"""Inspire 意图提取测试。"""

from unittest.mock import AsyncMock, patch

import pytest

from models import InspireSlots


@pytest.mark.asyncio
async def test_extract_region():
    from pipeline.inspire import extract_slots
    mock_response = {
        "region": "MENA", "price": None, "subject": None,
        "price_hint": None, "intent": "chat",
    }
    with patch("pipeline.inspire._call_extract_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await extract_slots("我想做一个中东风格的礼物", InspireSlots())
    assert result["region"] == "MENA"
    assert result["intent"] == "chat"


@pytest.mark.asyncio
async def test_extract_generate_intent():
    from pipeline.inspire import extract_slots
    mock_response = {
        "region": "US", "price": 100, "subject": "lion",
        "price_hint": None, "intent": "generate",
    }
    with patch("pipeline.inspire._call_extract_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await extract_slots("好的我想生成一个狮子主题的", InspireSlots(region="US", price=100))
    assert result["intent"] == "generate"
    assert result["subject"] == "lion"


@pytest.mark.asyncio
async def test_extract_fallback_on_error():
    from pipeline.inspire import extract_slots
    with patch("pipeline.inspire._call_extract_llm", new_callable=AsyncMock, side_effect=Exception("API error")):
        result = await extract_slots("随便说点什么", InspireSlots())
    assert result["intent"] == "chat"
    assert result["region"] is None


@pytest.mark.asyncio
async def test_extract_missing_intent_defaults_to_chat():
    from pipeline.inspire import extract_slots
    mock_response = {"region": "JP", "price": None, "subject": None, "price_hint": None}
    with patch("pipeline.inspire._call_extract_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await extract_slots("日本市场怎么样", InspireSlots())
    assert result["intent"] == "chat"
