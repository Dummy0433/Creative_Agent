"""Inspire 路由测试（单元级别）。"""

from models import InspireSession, InspireSlots
from pipeline import inspire_store


def test_inspire_session_created_on_menu():
    """点击 inspire 菜单后创建 session。"""
    inspire_store._store.clear()
    inspire_store.save(InspireSession(user_id="ou_menu_test"))
    session = inspire_store.get("ou_menu_test")
    assert session is not None
    assert session.user_id == "ou_menu_test"


def test_inspire_session_removed_on_stop():
    """stop 意图清除 session。"""
    inspire_store._store.clear()
    inspire_store.save(InspireSession(user_id="ou_stop"))
    inspire_store.remove("ou_stop")
    assert inspire_store.get("ou_stop") is None


def test_inspire_session_removed_on_generate():
    """generate 意图清除 session。"""
    inspire_store._store.clear()
    inspire_store.save(InspireSession(user_id="ou_gen"))
    inspire_store.remove("ou_gen")
    assert inspire_store.get("ou_gen") is None
