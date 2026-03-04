"""生成供应商抽象层，对外暴露获取供应商的统一接口。"""

from providers.registry import get_image_provider, get_text_provider

__all__ = ["get_image_provider", "get_text_provider"]
