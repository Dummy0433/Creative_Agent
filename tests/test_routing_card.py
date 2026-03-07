"""路由卡片构建测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cards import build_routing_card


def test_routing_card_structure():
    card = build_routing_card("req123")
    assert card["schema"] == "2.0"
    assert "header" in card
    assert "body" in card


def test_routing_card_has_two_buttons():
    card = build_routing_card("req123")
    elements = card["body"]["elements"]
    buttons = [e for e in _flatten(elements) if isinstance(e, dict) and e.get("tag") == "button"]
    assert len(buttons) == 2


def test_routing_card_action_values():
    card = build_routing_card("req123")
    elements = card["body"]["elements"]
    buttons = [e for e in _flatten(elements) if isinstance(e, dict) and e.get("tag") == "button"]
    actions = {b["value"]["action"] for b in buttons}
    assert actions == {"route_regen", "route_continue"}
    for b in buttons:
        assert b["value"]["request_id"] == "req123"


def _flatten(obj):
    """递归展开嵌套结构中的所有 dict。"""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _flatten(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _flatten(item)
