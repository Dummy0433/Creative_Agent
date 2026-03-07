"""Calendar 卡片构建测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_build_calendar_card_structure():
    """build_calendar_card 返回有效的 schema 2.0 卡片。"""
    from cards import build_calendar_card

    records = [
        {
            "name": "Test Gift",
            "price": 500,
            "gift_type": "Animation",
            "categories": "Campaign Gifts // 活动礼物",
            "regions": ["MENA"],
            "poc": "张三",
            "doc_link": "https://example.com",
            "doc_text": "PRD Doc",
            "progress": "in Design // 设计中",
            "designer": "李四",
            "deadline_ts": 1741392000000,
        },
    ]
    card = build_calendar_card(records)
    assert card["schema"] == "2.0"
    assert card["header"]["title"]["content"] == "Gift Calendar"
    elements = card["body"]["elements"]
    assert len(elements) > 0


def test_build_calendar_card_empty():
    """空记录时显示提示信息。"""
    from cards import build_calendar_card

    card = build_calendar_card([])
    elements = card["body"]["elements"]
    assert any("No data" in str(e) for e in elements)


def test_build_calendar_card_contains_doc_link():
    """卡片中包含文档链接。"""
    from cards import build_calendar_card

    records = [{
        "name": "Linked Gift",
        "price": 100,
        "gift_type": "Banner",
        "categories": "",
        "regions": ["US"],
        "poc": "Alice",
        "doc_link": "https://example.com/doc",
        "doc_text": "My PRD",
        "progress": "Not Started// 未启动",
        "designer": "Bob",
        "deadline_ts": 1741392000000,
    }]
    card = build_calendar_card(records)
    card_str = str(card)
    assert "https://example.com/doc" in card_str


def test_build_calendar_card_no_doc():
    """无文档链接时不崩溃。"""
    from cards import build_calendar_card

    records = [{
        "name": "No Doc Gift",
        "price": None,
        "gift_type": "",
        "categories": "",
        "regions": [],
        "poc": "",
        "doc_link": "",
        "doc_text": "",
        "progress": "",
        "designer": "",
        "deadline_ts": 0,
    }]
    card = build_calendar_card(records)
    assert card["schema"] == "2.0"
    elements = card["body"]["elements"]
    assert len(elements) > 0


def test_build_calendar_card_status_icon():
    """状态 icon 正确映射。"""
    from cards import build_calendar_card

    records = [{
        "name": "Design Gift",
        "price": 100,
        "gift_type": "",
        "categories": "",
        "regions": ["MENA"],
        "poc": "",
        "doc_link": "",
        "doc_text": "",
        "progress": "in Design // 设计中",
        "designer": "",
        "deadline_ts": 1741392000000,
    }]
    card = build_calendar_card(records)
    card_str = str(card)
    assert "\U0001f3a8" in card_str  # in Design icon
