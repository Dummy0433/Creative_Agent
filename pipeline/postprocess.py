"""后处理链：可扩展的处理器模式，当前实现图片保存，预留视频生成扩展点。"""

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


def build_postprocess_chain(tier: str | None = None) -> list[PostProcessor]:
    """构建后处理链。

    当前仅包含图片保存。未来可根据档位添加抠图、视频生成等处理器。
    """
    chain: list[PostProcessor] = [ImageSaveProcessor()]
    # 未来扩展: if tier in ("T3", "T4"):
    #     chain.append(MattingProcessor())
    #     chain.append(VideoGenerationProcessor())
    return chain
