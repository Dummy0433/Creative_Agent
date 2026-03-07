"""Inspire Session 暂存：用户级状态管理，TTL 自动过期。"""

import logging
import threading
import time

from defaults import load_defaults
from models import InspireSession

logger = logging.getLogger(__name__)

_store: dict[str, tuple[InspireSession, float]] = {}
_lock = threading.Lock()
_TTL = load_defaults().inspire_session_ttl


def save(session: InspireSession) -> None:
    """保存/覆盖用户的 inspire session。"""
    with _lock:
        _store[session.user_id] = (session, time.time())
    logger.info("[Inspire] 保存 session user=%s", session.user_id)


def get(user_id: str) -> InspireSession | None:
    """获取用户的 inspire session，过期返回 None。"""
    with _lock:
        entry = _store.get(user_id)
        if entry is None:
            return None
        session, ts = entry
        if time.time() - ts > _TTL:
            del _store[user_id]
            logger.info("[Inspire] user=%s session 已过期", user_id)
            return None
        return session


def remove(user_id: str) -> None:
    """删除用户的 inspire session。"""
    with _lock:
        _store.pop(user_id, None)
    logger.info("[Inspire] 删除 session user=%s", user_id)
