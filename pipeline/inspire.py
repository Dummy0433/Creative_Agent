"""Inspire 灵感对话：意图提取 + 槽位填充 + 表查询 + 对话生成。"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

import httpx

from models import InspireSlots
from settings import get_settings
from defaults import load_defaults

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "inspire_extract.md"


def _load_extract_prompt(slots: InspireSlots) -> str:
    """加载并填充提取 prompt 模板。"""
    template = _EXTRACT_PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        region=slots.region or "null",
        price=slots.price or "null",
        subject=slots.subject or "null",
    )


async def _call_extract_llm(system_prompt: str, user_message: str) -> dict:
    """调用 flash-lite 模型提取意图和槽位。"""
    s = get_settings()
    d = load_defaults()
    model = d.inspire_extract_model
    url = f"{s.gemini_base_url}/models/{model}:generateContent"
    headers = {"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"}
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


async def extract_slots(user_message: str, current_slots: InspireSlots) -> dict:
    """从用户消息中提取意图和槽位，失败时优雅降级。"""
    try:
        system_prompt = _load_extract_prompt(current_slots)
        result = await _call_extract_llm(system_prompt, user_message)
        if "intent" not in result:
            result["intent"] = "chat"
        return result
    except Exception as e:
        logger.warning("[Inspire] 意图提取失败，降级为 chat: %s", e)
        return {
            "region": None,
            "price": None,
            "subject": None,
            "price_hint": None,
            "intent": "chat",
        }


# ── 对话生成 ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "inspire_system.md"


def _load_system_prompt(table_context: str) -> str:
    """加载并填充对话系统 prompt。"""
    template = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        today=datetime.date.today().isoformat(),
        table_context=table_context or "(No table data yet — ask the user about region and price)",
    )


async def _call_chat_llm(system_prompt: str, messages: list[dict]) -> str:
    """调用主模型生成对话回复（支持多轮历史）。"""
    s = get_settings()
    d = load_defaults()
    model = d.inspire_chat_model
    url = f"{s.gemini_base_url}/models/{model}:generateContent"
    headers = {"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"}

    contents = []
    for msg in messages:
        contents.append({
            "role": msg["role"],
            "parts": [{"text": msg["text"]}],
        })

    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def generate_response(
    conversation_history: list[dict],
    table_context: str,
    user_message: str,
) -> str:
    """生成 Inspire 对话回复。"""
    try:
        system_prompt = _load_system_prompt(table_context)
        messages = list(conversation_history) + [{"role": "user", "text": user_message}]
        return await _call_chat_llm(system_prompt, messages)
    except Exception as e:
        logger.error("[Inspire] 对话生成失败: %s", e, exc_info=True)
        return "抱歉，我遇到了一些问题，请稍后再试。你可以继续描述你的想法，或者输入 'stop' 结束对话。"


# ── Pipeline 编排 ─────────────────────────────────────────────────────


async def _query_tables_for_context(slots: InspireSlots) -> str:
    """根据槽位查询 TABLE0-3，返回拼接的上下文文本。

    Note: This is a stub. Task 7 will adapt to the real pipeline/data.py API.
    """
    # TODO(T7): Integrate with real pipeline/data.py queries
    context_parts = []
    if slots.region:
        context_parts.append(f"Region: {slots.region}")
    if slots.price is not None:
        context_parts.append(f"Price: {slots.price} coins")
    if slots.price_hint:
        context_parts.append(f"Price hint: {slots.price_hint}")
    return " | ".join(context_parts)


def _update_slots(session, extracted: dict) -> bool:
    """用提取结果更新 session 槽位，返回是否有变化。"""
    old = session.slots.model_copy()
    if extracted.get("region"):
        session.slots.region = extracted["region"]
    if extracted.get("price") is not None:
        session.slots.price = extracted["price"]
    if extracted.get("subject"):
        session.slots.subject = extracted["subject"]
    if extracted.get("price_hint"):
        session.slots.price_hint = extracted["price_hint"]
    return old != session.slots


async def handle_inspire_message(
    session, user_message: str
) -> tuple[str, str | None]:
    """处理一轮 Inspire 对话。

    Returns:
        (reply_text, action) — action is None/"generate"/"request"/"stop"
    """
    # Step 1: 提取意图和槽位
    extracted = await extract_slots(user_message, session.slots)
    intent = extracted.get("intent", "chat")

    # Exit intents
    if intent in ("generate", "request"):
        _update_slots(session, extracted)
        return "灵感对话已终止。正在为你准备...", intent
    if intent == "stop":
        return "感谢使用灵感对话，再见！", "stop"

    # Step 2: 更新槽位，有变化则查表
    slots_changed = _update_slots(session, extracted)
    if slots_changed:
        session.table_context = await _query_tables_for_context(session.slots)

    # Step 3: 生成回复
    reply = await generate_response(
        conversation_history=session.conversation_history,
        table_context=session.table_context,
        user_message=user_message,
    )

    # Step 4: 更新对话历史
    session.conversation_history.append({"role": "user", "text": user_message})
    session.conversation_history.append({"role": "model", "text": reply})

    return reply, None
