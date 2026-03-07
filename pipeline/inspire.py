"""Inspire 灵感对话：意图提取 + 槽位填充 + 表查询 + 对话生成。"""

from __future__ import annotations

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
