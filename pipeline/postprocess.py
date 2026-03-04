"""后处理链：可扩展的处理器模式，当前实现图片保存，预留视频生成扩展点。"""

from abc import ABC, abstractmethod
from pathlib import Path

from models import PipelineResult
from settings import get_settings


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
        # 保存图片
        path = output_dir / "output.png"
        path.write_bytes(result.media_bytes)
        print(f"  已保存到 {path}")
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
