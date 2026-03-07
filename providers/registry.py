"""供应商注册表：名称 → 实现类的映射与查找。"""

from defaults import load_defaults

# 已注册的供应商字典
_image_providers: dict[str, type] = {}
_text_providers: dict[str, type] = {}


def register_image_provider(name: str, cls: type):
    """注册一个图片生成供应商。"""
    _image_providers[name] = cls


def register_text_provider(name: str, cls: type):
    """注册一个文本生成供应商。"""
    _text_providers[name] = cls


def get_image_provider(name: str | None = None, **kwargs):
    """根据名称获取图片供应商实例，透传 kwargs 到构造函数。"""
    name = name or load_defaults().image_provider
    cls = _image_providers.get(name)
    if cls is None:
        raise KeyError(f"未知的图片供应商: {name!r}，已注册: {list(_image_providers)}")
    return cls(**kwargs)


def get_text_provider(name: str | None = None, **kwargs):
    """根据名称获取文本供应商实例，透传 kwargs 到构造函数。"""
    name = name or load_defaults().image_provider  # 与 image_provider 保持一致使用默认值
    cls = _text_providers.get(name)
    if cls is None:
        raise KeyError(f"未知的文本供应商: {name!r}，已注册: {list(_text_providers)}")
    return cls(**kwargs)


_edit_providers: dict[str, type] = {}


def register_edit_provider(name: str, cls: type):
    """注册一个图片编辑供应商。"""
    _edit_providers[name] = cls


def get_edit_provider(name: str | None = None, **kwargs):
    """根据名称获取编辑供应商实例。"""
    name = name or load_defaults().edit_provider
    cls = _edit_providers.get(name)
    if cls is None:
        raise KeyError(f"未知的编辑供应商: {name!r}，已注册: {list(_edit_providers)}")
    return cls(**kwargs)


# ── 自动注册内置供应商 ────────────────────────────────────
from providers.gemini import GeminiEditProvider, GeminiImageProvider, GeminiTextProvider  # noqa: E402

register_image_provider("gemini", GeminiImageProvider)
register_text_provider("gemini", GeminiTextProvider)
register_edit_provider("gemini", GeminiEditProvider)
