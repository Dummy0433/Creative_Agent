"""候选图暂存：Phase 1 结果等待用户选择，TTL 30 分钟自动过期。"""

import logging
import time

from models import CandidateResult

logger = logging.getLogger(__name__)

# 暂存结构：{request_id: (CandidateResult, timestamp)}
_store: dict[str, tuple[CandidateResult, float]] = {}
_TTL = 1800  # 30 分钟过期


def save(result: CandidateResult) -> None:
    """保存候选结果，等待用户选择。"""
    _store[result.request_id] = (result, time.time())
    logger.info("[暂存] 已保存 request_id=%s, %d 张候选图",
                result.request_id, len(result.image_keys))


def get(request_id: str) -> CandidateResult | None:
    """获取候选结果，过期返回 None。"""
    entry = _store.get(request_id)
    if entry is None:
        return None
    result, ts = entry
    if time.time() - ts > _TTL:
        del _store[request_id]
        logger.info("[暂存] request_id=%s 已过期，自动清理", request_id)
        return None
    return result


def remove(request_id: str) -> None:
    """删除候选结果（用户选择后调用）。"""
    _store.pop(request_id, None)


def cleanup() -> None:
    """清理所有过期条目。"""
    now = time.time()
    expired = [rid for rid, (_, ts) in _store.items() if now - ts > _TTL]
    for rid in expired:
        del _store[rid]
    if expired:
        logger.info("[暂存] 清理 %d 条过期记录", len(expired))
