"""后处理模块的单元测试。"""

import io
import sys
from pathlib import Path
from unittest.mock import patch

# 将项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from models import PipelineResult


def _make_result(**overrides) -> PipelineResult:
    """构造测试用的 PipelineResult 实例。"""
    defaults = dict(
        subject_final="雄狮", tier="P0", prompt="p", english_prompt="e",
        status="generated", media_bytes=b"fake_image",
    )
    defaults.update(overrides)
    return PipelineResult(**defaults)


def _make_png_bytes(size=(100, 100), color=(255, 0, 0)) -> bytes:
    """生成一张真实的 PNG 图片 bytes。"""
    img = Image.new("RGBA", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_matting_returns_bytes():
    """matting() 调用 rembg 并返回 bytes。"""
    from pipeline.postprocess import matting
    fake_matted = b"matted_data"
    with patch("pipeline.postprocess.remove", return_value=fake_matted):
        result = matting(b"input_image")
        assert result == fake_matted


def test_composite_creates_panel_image():
    """composite() 将礼物叠加到 Gift Panel 底图。"""
    from pipeline.postprocess import composite, _PANEL_TEMPLATE
    if not _PANEL_TEMPLATE.exists():
        return  # CI 环境无底图时跳过
    png = _make_png_bytes()
    result = composite(png)
    # 合成图应能正常解码且尺寸为模板尺寸
    img = Image.open(io.BytesIO(result))
    assert img.size == (780, 904)


def test_composite_fallback_without_template():
    """composite() 底图不存在时返回原图。"""
    from pipeline.postprocess import composite
    with patch("pipeline.postprocess._PANEL_TEMPLATE") as mock_path:
        mock_path.exists.return_value = False
        original = b"original_image"
        assert composite(original) == original


def test_matting_and_composite():
    """matting_and_composite() 返回 (matted, preview) 元组。"""
    from pipeline.postprocess import matting_and_composite
    fake_matted = _make_png_bytes(size=(50, 50), color=(0, 255, 0))
    with patch("pipeline.postprocess.remove", return_value=fake_matted):
        matted, preview = matting_and_composite(b"input")
        assert matted == fake_matted
        assert len(preview) > 0


def test_video_processor_passthrough():
    """视频处理器占位：不修改数据，直接透传。"""
    from pipeline.postprocess import VideoGenerationProcessor
    proc = VideoGenerationProcessor()
    result = proc.process(_make_result())
    assert result.status == "generated"


def test_build_chain_p0():
    """P0 后处理链 = 保存（抠图已在 Phase 1 完成）。"""
    from pipeline.postprocess import build_postprocess_chain, ImageSaveProcessor
    chain = build_postprocess_chain("P0")
    types = [type(p) for p in chain]
    assert ImageSaveProcessor in types
    assert len(chain) == 1


def test_build_chain_p2():
    """P2 后处理链 = 保存 + 视频。"""
    from pipeline.postprocess import (
        build_postprocess_chain, ImageSaveProcessor, VideoGenerationProcessor,
    )
    chain = build_postprocess_chain("P2")
    types = [type(p) for p in chain]
    assert ImageSaveProcessor in types
    assert VideoGenerationProcessor in types
    assert len(chain) == 2


def test_build_chain_no_tier():
    """未指定层级时只有保存。"""
    from pipeline.postprocess import build_postprocess_chain, ImageSaveProcessor
    chain = build_postprocess_chain()
    assert len(chain) == 1
    assert isinstance(chain[0], ImageSaveProcessor)
