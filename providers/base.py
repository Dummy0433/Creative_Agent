"""生成供应商抽象基类，定义图片和文本生成的统一接口。"""

from abc import ABC, abstractmethod


class ImageProvider(ABC):
    """图片生成供应商抽象基类。"""

    @abstractmethod
    def generate(self, prompt: str) -> bytes:
        """根据提示词生成图片，返回图片字节数据。"""
        ...


class TextProvider(ABC):
    """文本生成供应商抽象基类。"""

    @abstractmethod
    def generate(self, model: str, system_prompt: str, user_prompt: str) -> dict:
        """根据系统提示和用户输入生成结构化 JSON 响应。"""
        ...
