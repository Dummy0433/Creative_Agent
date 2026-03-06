"""后处理模块：抠图、拼图、保存。

Phase 1 调用 matting_and_composite() 对每张候选图做：rembg 抠图 → Gift Panel 拼图预览。
Phase 2 调用 build_postprocess_chain() 对选中图做：保存 → [P2+: 视频占位]。
"""

import io
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image
from rembg import remove

from models import PipelineResult
from settings import get_settings

logger = logging.getLogger(__name__)

# ── 资源路径 ──────────────────────────────────────────────────
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_PANEL_TEMPLATE = _ASSETS_DIR / "gift_panel_template.png"

# ── Gift Panel 拼图参数 ──────────────────────────────────────
# 基于 Gift Panel.png (780x904) 和带礼物版的像素差异分析得出
# 礼物图标放置区域：第一个 slot 中央，适配约 130x130px
_GIFT_SLOT_CENTER = (111, 225)   # slot 中心坐标 (x, y)
_GIFT_SLOT_SIZE = 130            # 礼物图标最大边长（像素）


# ── Phase 1 用：单张图的抠图 + 拼图 ─────────────────────────

def matting(image_bytes: bytes) -> bytes:
    """使用 rembg 去除背景，返回透明 PNG bytes。"""
    return remove(image_bytes)


def composite(matted_bytes: bytes) -> bytes:
    """将抠图后的礼物叠加到 Gift Panel 底图上，返回合成图 bytes。

    底图模板不存在时返回原始 matted_bytes。
    """
    if not _PANEL_TEMPLATE.exists():
        logger.warning("[拼图] 底图模板不存在: %s，跳过", _PANEL_TEMPLATE)
        return matted_bytes
    panel = Image.open(_PANEL_TEMPLATE).convert("RGBA")
    gift = Image.open(io.BytesIO(matted_bytes)).convert("RGBA")
    # 等比缩放礼物到 slot 大小
    gift.thumbnail((_GIFT_SLOT_SIZE, _GIFT_SLOT_SIZE), Image.LANCZOS)
    # 居中对齐到 slot 中心
    paste_x = _GIFT_SLOT_CENTER[0] - gift.width // 2
    paste_y = _GIFT_SLOT_CENTER[1] - gift.height // 2
    # 用 alpha 通道做蒙版粘贴
    panel.paste(gift, (paste_x, paste_y), gift)
    buf = io.BytesIO()
    panel.save(buf, format="PNG")
    return buf.getvalue()


def matting_and_composite(image_bytes: bytes) -> tuple[bytes, bytes]:
    """Phase 1 用：对单张图做抠图 + 拼图。

    返回 (matted_bytes, composite_bytes)：
    - matted_bytes: 透明背景 PNG（选中后交付物）
    - composite_bytes: Gift Panel 预览图（卡片展示用）
    """
    matted = matting(image_bytes)
    preview = composite(matted)
    return matted, preview


# ── Phase 2 用：后处理链 ──────────────────────────────────────


class PostProcessor(ABC):
    """后处理器抽象基类。"""

    @abstractmethod
    def process(self, result: PipelineResult) -> PipelineResult:
        """处理 Pipeline 结果并返回（可修改结果内容）。"""
        ...


class ImageSaveProcessor(PostProcessor):
    """图片保存处理器：将 media_bytes（已抠图）写入本地文件。"""

    def process(self, result: PipelineResult) -> PipelineResult:
        if result.media_bytes is None:
            return result
        output_dir = Path(get_settings().output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{result.subject_final}_{result.tier}_{ts}_matted.png"
        path = output_dir / filename
        path.write_bytes(result.media_bytes)
        result.local_path = str(path)
        logger.info("  已保存到 %s", path)
        return result


class VideoGenerationProcessor(PostProcessor):
    """视频生成处理器（占位）。"""

    def process(self, result: PipelineResult) -> PipelineResult:
        # TODO: 调用视频生成服务
        logger.info("  [视频] 占位 — 待接入视频生成服务")
        return result


# ── 层级 → Phase 2 后处理链 ────────────────────────────────
# 抠图已在 Phase 1 完成，Phase 2 只做：保存 + [P2+: 视频]
_VIDEO_TIERS = {"P2", "P3", "P4", "P5"}


def build_postprocess_chain(tier: str | None = None) -> list[PostProcessor]:
    """根据层级构建 Phase 2 后处理链。"""
    chain: list[PostProcessor] = [ImageSaveProcessor()]
    if tier and tier in _VIDEO_TIERS:
        chain.append(VideoGenerationProcessor())
    return chain
