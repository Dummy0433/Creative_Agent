"""Inspire pipeline 编排测试。"""

from unittest.mock import AsyncMock, patch

import pytest

from models import InspireSession, InspireSlots


@pytest.mark.asyncio
async def test_handle_message_chat():
    """普通对话：提取 + 生成回复，session 更新。"""
    from pipeline.inspire import handle_inspire_message

    session = InspireSession(user_id="ou_test")
    extract_result = {
        "region": "MENA", "price": None, "subject": None,
        "price_hint": None, "intent": "chat",
    }
    with patch("pipeline.inspire.extract_slots", new_callable=AsyncMock, return_value=extract_result), \
         patch("pipeline.inspire._query_tables_for_context", new_callable=AsyncMock, return_value="MENA region data"), \
         patch("pipeline.inspire.generate_response", new_callable=AsyncMock, return_value="MENA is great!"):
        reply, action = await handle_inspire_message(session, "我想做中东的礼物")

    assert reply == "MENA is great!"
    assert action is None
    assert session.slots.region == "MENA"
    assert len(session.conversation_history) == 2


@pytest.mark.asyncio
async def test_handle_message_generate_exit():
    """generate 意图：返回 exit action。"""
    from pipeline.inspire import handle_inspire_message

    session = InspireSession(user_id="ou_test", slots=InspireSlots(region="US", price=100))
    extract_result = {
        "region": "US", "price": 100, "subject": "lion",
        "price_hint": None, "intent": "generate",
    }
    with patch("pipeline.inspire.extract_slots", new_callable=AsyncMock, return_value=extract_result):
        reply, action = await handle_inspire_message(session, "帮我生成一个")

    assert action == "generate"
    assert "终止" in reply


@pytest.mark.asyncio
async def test_handle_message_request_exit():
    """request 意图：返回 exit action。"""
    from pipeline.inspire import handle_inspire_message

    session = InspireSession(user_id="ou_test", slots=InspireSlots(region="JP"))
    extract_result = {
        "region": "JP", "price": None, "subject": None,
        "price_hint": None, "intent": "request",
    }
    with patch("pipeline.inspire.extract_slots", new_callable=AsyncMock, return_value=extract_result):
        reply, action = await handle_inspire_message(session, "我要提个需求")

    assert action == "request"
    assert "终止" in reply


@pytest.mark.asyncio
async def test_handle_message_stop():
    """stop 意图。"""
    from pipeline.inspire import handle_inspire_message

    session = InspireSession(user_id="ou_test")
    extract_result = {
        "region": None, "price": None, "subject": None,
        "price_hint": None, "intent": "stop",
    }
    with patch("pipeline.inspire.extract_slots", new_callable=AsyncMock, return_value=extract_result):
        reply, action = await handle_inspire_message(session, "谢谢再见")

    assert action == "stop"
    assert "再见" in reply


@pytest.mark.asyncio
async def test_handle_message_no_slot_change_skips_query():
    """槽位无变化时不查表。"""
    from pipeline.inspire import handle_inspire_message

    session = InspireSession(
        user_id="ou_test",
        slots=InspireSlots(region="MENA"),
        table_context="cached MENA data",
    )
    extract_result = {
        "region": "MENA", "price": None, "subject": None,
        "price_hint": None, "intent": "chat",
    }
    with patch("pipeline.inspire.extract_slots", new_callable=AsyncMock, return_value=extract_result), \
         patch("pipeline.inspire._query_tables_for_context", new_callable=AsyncMock) as mock_query, \
         patch("pipeline.inspire.generate_response", new_callable=AsyncMock, return_value="Ok"):
        await handle_inspire_message(session, "继续说说")

    mock_query.assert_not_called()
    assert session.table_context == "cached MENA data"
