"""Provider registry: name -> implementation class mapping."""

from settings import get_settings

_image_providers: dict[str, type] = {}
_text_providers: dict[str, type] = {}


def register_image_provider(name: str, cls: type):
    _image_providers[name] = cls


def register_text_provider(name: str, cls: type):
    _text_providers[name] = cls


def get_image_provider(name: str | None = None):
    name = name or get_settings().image_provider
    cls = _image_providers.get(name)
    if cls is None:
        raise KeyError(f"Unknown image provider: {name!r}. Registered: {list(_image_providers)}")
    return cls()


def get_text_provider(name: str = "gemini"):
    cls = _text_providers.get(name)
    if cls is None:
        raise KeyError(f"Unknown text provider: {name!r}. Registered: {list(_text_providers)}")
    return cls()


# ── Auto-register built-in providers ────────────────────────
from providers.gemini import GeminiImageProvider, GeminiTextProvider  # noqa: E402

register_image_provider("gemini", GeminiImageProvider)
register_text_provider("gemini", GeminiTextProvider)
