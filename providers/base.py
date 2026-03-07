"""生成供应商抽象基类，定义图片和文本生成的统一接口。"""

from abc import ABC, abstractmethod


class ImageProvider(ABC):
    """图片生成供应商抽象基类。"""

    @abstractmethod
    async def generate(self, prompt: str, reference_images: list[bytes] | None = None) -> bytes:
        """根据提示词生成图片，返回图片字节数据。

        Args:
            prompt: 生成提示词
            reference_images: 可选的参考图片列表，用于风格引导
        """
        ...


class TextProvider(ABC):
    """文本生成供应商抽象基类。"""

    @abstractmethod
    async def generate(self, model: str, system_prompt: str, user_prompt: str) -> dict:
        """根据系统提示和用户输入生成结构化 JSON 响应。"""
        ...


class EditProvider(ABC):
    """图片编辑供应商抽象基类。"""

    @abstractmethod
    async def edit(
        self,
        image: bytes,
        instruction: str,
        conversation_history: list[dict] | None = None,
    ) -> "EditResult":
        """编辑图片，返回 EditResult（编辑后图片 + AI 引导文字 + 更新后历史）。"""
        ...
