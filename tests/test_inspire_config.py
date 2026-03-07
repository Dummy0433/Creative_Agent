"""Inspire 配置和模型测试。"""

from models import InspireSlots, InspireSession


def test_inspire_slots_defaults():
    slots = InspireSlots()
    assert slots.region is None
    assert slots.price is None
    assert slots.price_hint is None
    assert slots.subject is None


def test_inspire_slots_update():
    slots = InspireSlots(region="MENA")
    assert slots.region == "MENA"
    assert slots.price is None


def test_inspire_session_creation():
    session = InspireSession(user_id="ou_test")
    assert session.user_id == "ou_test"
    assert session.slots == InspireSlots()
    assert session.conversation_history == []
    assert session.table_context == ""


def test_inspire_slots_equality():
    a = InspireSlots(region="US")
    b = InspireSlots(region="US")
    c = InspireSlots(region="JP")
    assert a == b
    assert a != c


def test_inspire_config_loaded():
    from defaults import load_defaults
    d = load_defaults()
    assert d.inspire_extract_model
    assert d.inspire_chat_model
    assert d.inspire_session_ttl > 0
