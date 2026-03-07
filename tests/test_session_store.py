"""Session 存储模块测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import SessionState, EditSession, GenerationConfig


def _make_session(uid="ou_test", state=SessionState.EDITING) -> EditSession:
    config = GenerationConfig(region="MENA", subject="雄狮", price=1)
    return EditSession(
        user_id=uid, state=state, request_id="req123",
        current_image=b"img", original_config=config,
    )


def test_save_and_get():
    from pipeline.session_store import save, get, _store
    _store.clear()
    s = _make_session()
    save(s)
    assert get("ou_test") is not None
    assert get("ou_test").state == SessionState.EDITING


def test_get_nonexistent():
    from pipeline.session_store import get, _store
    _store.clear()
    assert get("no_such_user") is None


def test_remove():
    from pipeline.session_store import save, get, remove, _store
    _store.clear()
    save(_make_session())
    remove("ou_test")
    assert get("ou_test") is None


def test_cleanup_expired(monkeypatch):
    from pipeline import session_store
    from pipeline.session_store import save, cleanup, get, _store
    _store.clear()
    save(_make_session())
    monkeypatch.setattr(session_store, "_TTL", 0)
    cleanup()
    assert get("ou_test") is None


def test_overwrite_existing():
    """同一用户保存新 session 覆盖旧的。"""
    from pipeline.session_store import save, get, _store
    _store.clear()
    s1 = _make_session(state=SessionState.SELECTING)
    save(s1)
    s2 = _make_session(state=SessionState.DELIVERED)
    save(s2)
    assert get("ou_test").state == SessionState.DELIVERED
