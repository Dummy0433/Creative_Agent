"""Post-processing chain with extension point for video generation."""

from abc import ABC, abstractmethod
from pathlib import Path

from models import PipelineResult
from settings import get_settings


class PostProcessor(ABC):
    @abstractmethod
    def process(self, result: PipelineResult) -> PipelineResult:
        ...


class ImageSaveProcessor(PostProcessor):
    def process(self, result: PipelineResult) -> PipelineResult:
        if result.media_bytes is None:
            return result
        output_dir = Path(get_settings().output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "output.png"
        path.write_bytes(result.media_bytes)
        print(f"  Saved to {path}")
        return result


def build_postprocess_chain(tier: str | None = None) -> list[PostProcessor]:
    chain: list[PostProcessor] = [ImageSaveProcessor()]
    # Future: if tier in ("T3", "T4"):
    #     chain.append(MattingProcessor())
    #     chain.append(VideoGenerationProcessor())
    return chain
