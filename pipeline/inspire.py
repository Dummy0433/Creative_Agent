"""Inspire 灵感对话：意图提取 + 槽位填充 + 表查询 + 对话生成。"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

import httpx

import feishu
from models import InspireSlots
from settings import get_settings
from defaults import load_defaults

logger = logging.getLogger(__name__)

# ── 表查询依赖（便于测试 mock）──────────────────────────────────


async def _feishu_get_token() -> str:
    return await feishu.get_token()


async def _resolve_routing(token: str, region: str):
    from pipeline.data import resolve_routing
    return await resolve_routing(token, region)


async def _query_region_info(token: str, region: str, routing):
    from pipeline.data import query_region_info
    return await query_region_info(token, region, routing)


async def _query_tier_rules(token: str, region: str, price: int, routing):
    from pipeline.data import query_tier_rules
    return await query_tier_rules(token, region, price, routing)


async def _query_instances(token: str, region: str, price: int, limit: int, routing):
    from pipeline.data import query_instances
    return await query_instances(token, region, price, limit=limit, routing=routing)

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
    """根据槽位查询 TABLE0-3，返回拼接的上下文文本供对话模型参考。"""
    if not slots.region:
        return ""

    context_parts = []
    try:
        token = await _feishu_get_token()
        routing = await _resolve_routing(token, slots.region)

        # TABLE1: 区域风格
        try:
            region_data = await _query_region_info(token, slots.region, routing)
            style_keys = ["设计风格", "配色", "特色物件", "主体画法", "场景", "氛围"]
            style_parts = [f"{k}: {region_data[k]}" for k in style_keys if region_data.get(k)]
            if style_parts:
                context_parts.append(f"Region Style ({slots.region}):\n" + "\n".join(style_parts))
        except Exception as e:
            logger.warning("[Inspire] TABLE1 查询失败: %s", e)

        # TABLE2: 档位规则（需要价格）
        if slots.price is not None:
            try:
                tier_data = await _query_tier_rules(token, slots.region, slots.price, routing)
                tier_keys = ["价格层级", "价格区间", "允许主体", "禁止主体", "容器备选", "材质"]
                tier_parts = [f"{k}: {tier_data[k]}" for k in tier_keys if tier_data.get(k)]
                if tier_parts:
                    context_parts.append(f"Tier Rules (price={slots.price}):\n" + "\n".join(tier_parts))
            except Exception as e:
                logger.warning("[Inspire] TABLE2 查询失败: %s", e)

        # TABLE3: 参考案例（需要区域，价格可选）
        try:
            instances = await _query_instances(token, slots.region, slots.price or 0, limit=3, routing=routing)
            if instances:
                instance_lines = []
                for inst in instances:
                    name = inst.get("名称", inst.get("name", "unnamed"))
                    desc_parts = [f"{k}: {inst[k]}" for k in ["主体", "场景", "价格层级"] if inst.get(k)]
                    instance_lines.append(f"- {name} ({', '.join(desc_parts)})")
                context_parts.append("Reference Cases:\n" + "\n".join(instance_lines))
        except Exception as e:
            logger.warning("[Inspire] TABLE3 查询失败: %s", e)

    except Exception as e:
        logger.warning("[Inspire] 表查询初始化失败: %s", e)

    return "\n\n".join(context_parts)


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
