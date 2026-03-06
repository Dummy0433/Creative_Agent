"""后处理模块：抠图、拼图、保存。

Phase 1 调用 matting_and_composite() 对每张候选图做：rembg 抠图 → Gift Panel 拼图预览。
Phase 2 调用 build_postprocess_chain() 对选中图做：保存 → [P2+: 视频占位]。
"""

import io
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rembg import remove

from models import PipelineResult
from settings import get_settings

logger = logging.getLogger(__name__)

# ── 资源路径 ──────────────────────────────────────────────────
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_PANEL_TEMPLATE = _ASSETS_DIR / "gift_panel_template.png"
_BADGE_NEW = _ASSETS_DIR / "badge_new.png"            # 60×26 @2x "New" 角标
_COIN_ICON = _ASSETS_DIR / "coin_icon.png"            # 20×20 @2x 金币图标
_FONT_PATH = _ASSETS_DIR / "TikTokSans-Medium.ttf"   # TikTok 官方字体

# ── Gift Panel 拼图参数（全部 @2x，780x904 模板）──────────────
# Figma 1x: 容器 70×70, 距上 80px, 距左 23.5px
_GIFT_SLOT_CENTER = (117, 230)   # slot 中心 (x, y) @2x
_GIFT_ICON_SIZE = 112            # Mask 56×56 @1x → 112 @2x

# 文字 Y 定位：基于 mask 底部的固定偏移（从底图 Rose 实测校准）
# mask 底部 = slot_center_y + 56 = 286
# Rose 名字顶部 y=333, Rose 价格顶部 y=359
_MASK_BOTTOM_TO_NAME = 47        # mask 底 → 名字顶 (333-286=47)
_NAME_TO_PRICE_GAP = 14          # 名字底 → 价格顶 (359-345=14)

# Figma CSS 标注 @1x → Pillow 校准 @2x
# font-size: 9px @1x, 但 Pillow size=18 渲染 "Rose" 高度=13px 精确匹配底图
_FONT_SIZE = 18
_TEXT_COLOR = (255, 255, 255, 191)  # rgba(255,255,255,0.75)
_COIN_TEXT_GAP = 2               # coin 与价格文字间距


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """加载 TikTok 字体，找不到时回退系统字体。"""
    if _FONT_PATH.exists():
        return ImageFont.truetype(str(_FONT_PATH), size)
    for fallback in ["/System/Library/Fonts/SFNS.ttf",
                     "/System/Library/Fonts/Supplemental/Arial.ttf"]:
        if Path(fallback).exists():
            logger.warning("[拼图] TikTok 字体缺失，回退到 %s", fallback)
            return ImageFont.truetype(fallback, size)
    return ImageFont.load_default()


# ── Phase 1 用：单张图的抠图 + 拼图 ─────────────────────────

def matting(image_bytes: bytes) -> bytes:
    """使用 rembg 去除背景，返回透明 PNG bytes。"""
    return remove(image_bytes)


def composite(matted_bytes: bytes, gift_name: str = "",
              price: int = 0, show_badge: bool = False) -> bytes:
    """将抠图后的礼物叠加到 Gift Panel 底图上，动态渲染组件。

    文字定位基于 mask 固定边界（与底图已有文字对齐），不依赖 icon 内容大小。
    """
    if not _PANEL_TEMPLATE.exists():
        logger.warning("[拼图] 底图模板不存在: %s，跳过", _PANEL_TEMPLATE)
        return matted_bytes

    panel = Image.open(_PANEL_TEMPLATE).convert("RGBA")
    cx, cy = _GIFT_SLOT_CENTER
    mask_half = _GIFT_ICON_SIZE // 2
    mask_bottom = cy + mask_half  # 固定参考线，不随 icon 内容变化

    # ① 礼物图标：缩放到容器内，居中粘贴（允许出血溢出）
    gift = Image.open(io.BytesIO(matted_bytes)).convert("RGBA")
    gift.thumbnail((_GIFT_ICON_SIZE, _GIFT_ICON_SIZE), Image.LANCZOS)
    paste_x = cx - gift.width // 2
    paste_y = cy - gift.height // 2
    panel.paste(gift, (paste_x, paste_y), gift)

    # ② "New" 角标（图标左上角外侧）
    if show_badge and _BADGE_NEW.exists():
        badge = Image.open(_BADGE_NEW).convert("RGBA")
        icon_left = cx - mask_half
        badge_x = icon_left - 4
        badge_y = (cy - mask_half) - badge.height // 2
        panel.paste(badge, (badge_x, badge_y), badge)

    # ③ 文字渲染（透明图层，支持 alpha 颜色混合）
    if gift_name or price:
        text_layer = Image.new("RGBA", panel.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(text_layer)
        font = _load_font(_FONT_SIZE)

        # 名字：固定 Y 位置 = mask底 + 47px, 水平居中于 slot
        name_y = mask_bottom + _MASK_BOTTOM_TO_NAME
        if gift_name:
            name_bbox = font.getbbox(gift_name)
            name_w = name_bbox[2] - name_bbox[0]
            name_h = name_bbox[3] - name_bbox[1]
            name_x = cx - name_w // 2
            draw.text((name_x, name_y), gift_name, fill=_TEXT_COLOR, font=font)
            name_bottom = name_y + name_h
        else:
            name_bottom = name_y

        # 价格行：固定 Y = 名字底 + 14px, 文字居中, coin 吸附文字左侧
        if price > 0:
            price_str = str(price)
            price_bbox = font.getbbox(price_str)
            price_w = price_bbox[2] - price_bbox[0]
            price_h = price_bbox[3] - price_bbox[1]
            price_y = name_bottom + _NAME_TO_PRICE_GAP

            # 价格文字先居中
            price_x = cx - price_w // 2
            draw.text((price_x, price_y), price_str, fill=_TEXT_COLOR, font=font)

            # coin 吸附在文字最左边
            if _COIN_ICON.exists():
                coin = Image.open(_COIN_ICON).convert("RGBA")
                coin_w, coin_h = coin.size
                coin_x = price_x - _COIN_TEXT_GAP - coin_w
                coin_y = price_y + (price_h - coin_h) // 2
                text_layer.paste(coin, (coin_x, coin_y), coin)

        panel = Image.alpha_composite(panel, text_layer)

    buf = io.BytesIO()
    panel.save(buf, format="PNG")
    return buf.getvalue()


def matting_and_composite(image_bytes: bytes, gift_name: str = "",
                          price: int = 0) -> tuple[bytes, bytes]:
    """Phase 1 用：对单张图做抠图 + 拼图。

    返回 (matted_bytes, composite_bytes)：
    - matted_bytes: 透明背景 PNG（选中后交付物）
    - composite_bytes: Gift Panel 预览图（卡片展示用）
    """
    matted = matting(image_bytes)
    preview = composite(matted, gift_name=gift_name, price=price)
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
_VIDEO_TIERS = {"P2", "P3", "P4", "P5"}


def build_postprocess_chain(tier: str | None = None) -> list[PostProcessor]:
    """根据层级构建 Phase 2 后处理链。"""
    chain: list[PostProcessor] = [ImageSaveProcessor()]
    if tier and tier in _VIDEO_TIERS:
        chain.append(VideoGenerationProcessor())
    return chain
