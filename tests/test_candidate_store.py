"""候选图暂存模块的单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import CandidateResult


def _make_candidate(rid="test123") -> CandidateResult:
    """构造测试用 CandidateResult。"""
    return CandidateResult(
        request_id=rid, tier="P0", subject_final="雄狮",
        prompt="p", english_prompt="e",
        image_keys=["k1", "k2"], image_bytes_list=[b"a", b"b"],
        region="MENA", price=1,
    )


def test_save_and_get():
    """保存后能取回。"""
    from pipeline.candidate_store import save, get, _store
    _store.clear()
    cr = _make_candidate()
    save(cr)
    assert get("test123") is not None
    assert get("test123").tier == "P0"


def test_get_nonexistent():
    """不存在的 request_id 返回 None。"""
    from pipeline.candidate_store import get, _store
    _store.clear()
    assert get("no_such_id") is None


def test_remove():
    """取回后可删除。"""
    from pipeline.candidate_store import save, get, remove, _store
    _store.clear()
    save(_make_candidate())
    remove("test123")
    assert get("test123") is None


def test_cleanup_expired(monkeypatch):
    """过期条目被清理。"""
    from pipeline import candidate_store
    from pipeline.candidate_store import save, cleanup, _store
    _store.clear()
    save(_make_candidate())
    monkeypatch.setattr(candidate_store, "_TTL", 0)
    cleanup()
    from pipeline.candidate_store import get
    assert get("test123") is None
