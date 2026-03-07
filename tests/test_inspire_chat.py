"""Inspire 对话生成测试。"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_generate_response_basic():
    from pipeline.inspire import generate_response
    with patch("pipeline.inspire._call_chat_llm", new_callable=AsyncMock, return_value="狮子是很受欢迎的礼物主题。"):
        result = await generate_response(
            conversation_history=[],
            table_context="",
            user_message="我想做一个狮子礼物",
        )
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_generate_response_with_context():
    from pipeline.inspire import generate_response
    with patch("pipeline.inspire._call_chat_llm", new_callable=AsyncMock, return_value="MENA 区域偏好暖色调。"):
        result = await generate_response(
            conversation_history=[
                {"role": "user", "text": "MENA 区域有什么偏好？"},
                {"role": "model", "text": "MENA 区域喜欢暖色调和几何图案。"},
            ],
            table_context="MENA 区域风格：暖色调，几何图案，金色元素",
            user_message="具体说说",
        )
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_generate_response_fallback():
    from pipeline.inspire import generate_response
    with patch("pipeline.inspire._call_chat_llm", new_callable=AsyncMock, side_effect=Exception("timeout")):
        result = await generate_response(
            conversation_history=[],
            table_context="",
            user_message="hello",
        )
    assert "抱歉" in result
