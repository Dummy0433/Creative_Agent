"""Inspire 表查询适配测试。"""

from unittest.mock import AsyncMock, patch

import pytest

from models import InspireSlots


@pytest.mark.asyncio
async def test_query_context_empty_slots():
    """无 region 时直接返回空。"""
    from pipeline.inspire import _query_tables_for_context

    result = await _query_tables_for_context(InspireSlots())
    assert result == ""


@pytest.mark.asyncio
async def test_query_context_with_region():
    """有 region 时查 TABLE0 + TABLE1，返回区域风格信息。"""
    from pipeline.inspire import _query_tables_for_context

    mock_region_data = {"设计风格": "几何图案", "配色": "金色+深蓝", "特色物件": "新月"}

    with patch("pipeline.inspire._feishu_get_token", new_callable=AsyncMock, return_value="fake_token"), \
         patch("pipeline.inspire._resolve_routing", new_callable=AsyncMock, return_value="fake_routing"), \
         patch("pipeline.inspire._query_region_info", new_callable=AsyncMock, return_value=mock_region_data), \
         patch("pipeline.inspire._query_instances", new_callable=AsyncMock, return_value=[]):
        result = await _query_tables_for_context(InspireSlots(region="MENA"))

    assert "MENA" in result
    assert "几何图案" in result


@pytest.mark.asyncio
async def test_query_context_with_price():
    """有 region + price 时查 TABLE2 档位规则。"""
    from pipeline.inspire import _query_tables_for_context

    mock_region_data = {"设计风格": "简约"}
    mock_tier_data = {"价格层级": "T0", "价格区间": "1-19 coins", "允许主体": "花卉,动物"}

    with patch("pipeline.inspire._feishu_get_token", new_callable=AsyncMock, return_value="fake_token"), \
         patch("pipeline.inspire._resolve_routing", new_callable=AsyncMock, return_value="fake_routing"), \
         patch("pipeline.inspire._query_region_info", new_callable=AsyncMock, return_value=mock_region_data), \
         patch("pipeline.inspire._query_tier_rules", new_callable=AsyncMock, return_value=mock_tier_data), \
         patch("pipeline.inspire._query_instances", new_callable=AsyncMock, return_value=[]):
        result = await _query_tables_for_context(InspireSlots(region="MENA", price=10))

    assert "T0" in result
    assert "允许主体" in result


@pytest.mark.asyncio
async def test_query_context_table_failure_graceful():
    """表查询失败时优雅降级返回空。"""
    from pipeline.inspire import _query_tables_for_context

    with patch("pipeline.inspire._feishu_get_token", new_callable=AsyncMock, side_effect=Exception("no token")):
        result = await _query_tables_for_context(InspireSlots(region="US"))

    assert result == ""


@pytest.mark.asyncio
async def test_query_context_region_info_failure_continues():
    """TABLE1 查询失败时继续查 TABLE3。"""
    from pipeline.inspire import _query_tables_for_context

    mock_instances = [{"名称": "Golden Lion", "主体": "狮子", "场景": "沙漠"}]

    with patch("pipeline.inspire._feishu_get_token", new_callable=AsyncMock, return_value="fake_token"), \
         patch("pipeline.inspire._resolve_routing", new_callable=AsyncMock, return_value="fake_routing"), \
         patch("pipeline.inspire._query_region_info", new_callable=AsyncMock, side_effect=RuntimeError("TABLE1 not found")), \
         patch("pipeline.inspire._query_instances", new_callable=AsyncMock, return_value=mock_instances):
        result = await _query_tables_for_context(InspireSlots(region="MENA"))

    assert "Golden Lion" in result
    assert "狮子" in result


@pytest.mark.asyncio
async def test_query_context_instances_formatted():
    """参考案例格式化包含名称和描述字段。"""
    from pipeline.inspire import _query_tables_for_context

    mock_instances = [
        {"名称": "Crystal Rose", "主体": "玫瑰", "场景": "花园", "价格层级": "T2"},
        {"name": "Dragon", "主体": "龙"},
    ]

    with patch("pipeline.inspire._feishu_get_token", new_callable=AsyncMock, return_value="fake_token"), \
         patch("pipeline.inspire._resolve_routing", new_callable=AsyncMock, return_value="fake_routing"), \
         patch("pipeline.inspire._query_region_info", new_callable=AsyncMock, return_value={}), \
         patch("pipeline.inspire._query_instances", new_callable=AsyncMock, return_value=mock_instances):
        result = await _query_tables_for_context(InspireSlots(region="US"))

    assert "Crystal Rose" in result
    assert "Dragon" in result
    assert "Reference Cases" in result
