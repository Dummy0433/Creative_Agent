"""后处理链的单元测试。"""

import sys
from pathlib import Path

# 将项目根目录加入 sys.path，方便直接导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import PipelineResult


def _make_result() -> PipelineResult:
    """构造测试用的 PipelineResult 实例。"""
    return PipelineResult(
        subject_final="雄狮", tier="P0", prompt="p", english_prompt="e",
        status="generated", media_bytes=b"fake_image",
    )


def test_matting_processor_passthrough():
    """抠图处理器占位：不修改数据，直接透传。"""
    from pipeline.postprocess import MattingProcessor
    proc = MattingProcessor()
    result = proc.process(_make_result())
    assert result.media_bytes == b"fake_image"


def test_video_processor_passthrough():
    """视频处理器占位：不修改数据，直接透传。"""
    from pipeline.postprocess import VideoGenerationProcessor
    proc = VideoGenerationProcessor()
    result = proc.process(_make_result())
    assert result.status == "generated"


def test_build_chain_p0():
    """P0 后处理链 = 保存 + 抠图。"""
    from pipeline.postprocess import build_postprocess_chain, ImageSaveProcessor, MattingProcessor
    chain = build_postprocess_chain("P0")
    types = [type(p) for p in chain]
    assert ImageSaveProcessor in types
    assert MattingProcessor in types


def test_build_chain_p2():
    """P2 后处理链 = 保存 + 抠图 + 视频。"""
    from pipeline.postprocess import build_postprocess_chain, ImageSaveProcessor, MattingProcessor, VideoGenerationProcessor
    chain = build_postprocess_chain("P2")
    types = [type(p) for p in chain]
    assert ImageSaveProcessor in types
    assert MattingProcessor in types
    assert VideoGenerationProcessor in types


def test_build_chain_no_tier():
    """未指定层级时只有保存。"""
    from pipeline.postprocess import build_postprocess_chain, ImageSaveProcessor
    chain = build_postprocess_chain()
    assert len(chain) == 1
    assert isinstance(chain[0], ImageSaveProcessor)
