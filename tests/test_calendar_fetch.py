"""Calendar 数据拉取测试。"""

import sys
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_fetch_sorts_by_deadline_and_limits(monkeypatch):
    """fetch_calendar_records 按 Deadline 排序并限制 15 条。"""
    import pipeline.calendar as cal

    mock_records = []
    for i in range(20):
        ts = (1740787200 + i * 86400) * 1000
        mock_records.append({
            "fields": {
                "Gift Name // 礼物名": f"Gift {i}",
                "Deadline // 截止日期": ts,
                "Progress // 进展": "in Design // 设计中",
            }
        })
    random.shuffle(mock_records)

    monkeypatch.setattr(cal, "_query_calendar_raw", lambda: mock_records)

    result = cal.fetch_calendar_records()
    assert len(result) == 15
    deadlines = [r["deadline_ts"] for r in result]
    assert deadlines == sorted(deadlines)


def test_fetch_extracts_fields(monkeypatch):
    """fetch_calendar_records 正确提取核心字段。"""
    import pipeline.calendar as cal

    mock_records = [{
        "fields": {
            "Gift Name // 礼物名": "Test Gift",
            "Price // 价格": 500,
            "Gift Type // 礼物类型": "Animation",
            "Categories // 需求类型": "Campaign Gifts // 活动礼物",
            "Regions // 区域": ["MENA", "TR"],
            "POC // 需求方": [{"name": "张三", "id": "ou_xxx"}],
            "Doc // 需求文档": {"link": "https://example.com", "text": "PRD"},
            "Progress // 进展": "in Design // 设计中",
            "Designer // 设计师": [{"name": "李四", "id": "ou_yyy"}],
            "Deadline // 截止日期": 1741392000000,
        }
    }]
    monkeypatch.setattr(cal, "_query_calendar_raw", lambda: mock_records)

    result = cal.fetch_calendar_records()
    assert len(result) == 1
    r = result[0]
    assert r["name"] == "Test Gift"
    assert r["price"] == 500
    assert r["gift_type"] == "Animation"
    assert r["regions"] == ["MENA", "TR"]
    assert r["poc"] == "张三"
    assert r["doc_link"] == "https://example.com"
    assert r["doc_text"] == "PRD"
    assert r["progress"] == "in Design // 设计中"
    assert r["designer"] == "李四"


def test_fetch_empty_raw(monkeypatch):
    """原始记录为空时返回空列表。"""
    import pipeline.calendar as cal
    monkeypatch.setattr(cal, "_query_calendar_raw", lambda: [])
    assert cal.fetch_calendar_records() == []


def test_no_deadline_sorted_last(monkeypatch):
    """无 deadline 的记录排在最后。"""
    import pipeline.calendar as cal

    mock_records = [
        {"fields": {"Gift Name // 礼物名": "No Deadline"}},
        {"fields": {"Gift Name // 礼物名": "Has Deadline", "Deadline // 截止日期": 1740787200000}},
    ]
    monkeypatch.setattr(cal, "_query_calendar_raw", lambda: mock_records)

    result = cal.fetch_calendar_records()
    assert result[0]["name"] == "Has Deadline"
    assert result[1]["name"] == "No Deadline"


def test_quarter_invalid_month():
    """无效月份抛出 ValueError。"""
    import pytest
    from pipeline.calendar import _get_current_quarter
    with pytest.raises(ValueError):
        _get_current_quarter(month=0)
    with pytest.raises(ValueError):
        _get_current_quarter(month=13)
