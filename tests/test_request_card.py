"""需求提单表单卡片测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_request_form_card_exists():
    """REQUEST_FORM_CARD 存在且是 dict。"""
    from cards import REQUEST_FORM_CARD
    assert isinstance(REQUEST_FORM_CARD, dict)
    assert REQUEST_FORM_CARD["header"]["title"]["content"] == "Gift Request"


def test_request_form_has_required_fields():
    """表单包含所有必填字段。"""
    from cards import REQUEST_FORM_CARD
    form = REQUEST_FORM_CARD["elements"][0]
    assert form["tag"] == "form"
    field_names = [e.get("name", "") for e in form["elements"]]
    assert "gift_name" in field_names
    assert "price" in field_names
    assert "gift_type" in field_names
    assert "categories" in field_names
    assert "region" in field_names
    assert "deadline" in field_names


def test_request_form_has_submit_button():
    """表单有提交按钮。"""
    from cards import REQUEST_FORM_CARD
    form = REQUEST_FORM_CARD["elements"][0]
    buttons = [e for e in form["elements"] if e.get("tag") == "button"]
    assert len(buttons) == 1
    assert buttons[0]["name"] == "request_submit"
    assert buttons[0]["action_type"] == "form_submit"
