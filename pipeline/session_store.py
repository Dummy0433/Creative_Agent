"""编辑 Session 暂存：用户级状态管理，TTL 自动过期。"""

import logging
import threading
import time

from defaults import load_defaults
from models import EditSession

logger = logging.getLogger(__name__)

_store: dict[str, tuple[EditSession, float]] = {}
_lock = threading.Lock()
_TTL = load_defaults().edit_session_ttl


def save(session: EditSession) -> None:
    """保存/覆盖用户的编辑 session。"""
    with _lock:
        _store[session.user_id] = (session, time.time())
    logger.info("[Session] 保存 user=%s, state=%s", session.user_id, session.state)


def get(user_id: str) -> EditSession | None:
    """获取用户的编辑 session，过期返回 None。"""
    with _lock:
        _cleanup_locked()
        entry = _store.get(user_id)
        if entry is None:
            return None
        session, ts = entry
        if time.time() - ts > _TTL:
            del _store[user_id]
            logger.info("[Session] user=%s 已过期", user_id)
            return None
        return session


def remove(user_id: str) -> None:
    """删除用户的编辑 session。"""
    with _lock:
        _store.pop(user_id, None)


def cleanup() -> None:
    """清理所有过期 session。"""
    with _lock:
        _cleanup_locked()


def _cleanup_locked() -> None:
    now = time.time()
    expired = [uid for uid, (_, ts) in _store.items() if now - ts > _TTL]
    for uid in expired:
        del _store[uid]
    if expired:
        logger.info("[Session] 清理 %d 条过期 session", len(expired))
