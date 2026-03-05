"""后处理链：可扩展的处理器模式。

当前实现：图片保存 + 抠图占位 + 视频占位。
"""

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

from models import PipelineResult
from settings import get_settings

logger = logging.getLogger(__name__)


class PostProcessor(ABC):
    """后处理器抽象基类。"""

    @abstractmethod
    def process(self, result: PipelineResult) -> PipelineResult:
        """处理 Pipeline 结果并返回（可修改结果内容）。"""
        ...


class ImageSaveProcessor(PostProcessor):
    """图片保存处理器：将生成的图片写入本地文件。"""

    def process(self, result: PipelineResult) -> PipelineResult:
        if result.media_bytes is None:
            return result
        # 确保输出目录存在
        output_dir = Path(get_settings().output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        # 用主体+档位+时间戳生成有意义的文件名
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{result.subject_final}_{result.tier}_{ts}.png"
        path = output_dir / filename
        path.write_bytes(result.media_bytes)
        result.local_path = str(path)
        logger.info("  已保存到 %s", path)
        return result


class MattingProcessor(PostProcessor):
    """抠图处理器（占位，接入实际抠图服务后实现）。"""

    def process(self, result: PipelineResult) -> PipelineResult:
        # TODO: 调用抠图 API，替换 result.media_bytes 为抠图后的图片
        logger.info("  [抠图] 占位 — 待接入抠图服务")
        return result


class VideoGenerationProcessor(PostProcessor):
    """视频生成处理器（占位）。"""

    def process(self, result: PipelineResult) -> PipelineResult:
        # TODO: 调用视频生成服务
        logger.info("  [视频] 占位 — 待接入视频生成服务")
        return result


# ── 层级 → 后处理链 ────────────────────────────────────────
# P0/P1: 图片保存 + 抠图
# P2+:   图片保存 + 抠图 + 视频
_VIDEO_TIERS = {"P2", "P3", "P4", "P5"}


def build_postprocess_chain(tier: str | None = None) -> list[PostProcessor]:
    """根据层级构建后处理链。"""
    chain: list[PostProcessor] = [ImageSaveProcessor()]
    if tier:
        # 所有层级都做抠图
        chain.append(MattingProcessor())
        # P2+ 追加视频生成
        if tier in _VIDEO_TIERS:
            chain.append(VideoGenerationProcessor())
    return chain
