"""EditProvider 接口和注册测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from models import EditResult
from providers.base import EditProvider


def test_edit_provider_is_abstract():
    """EditProvider 不能直接实例化。"""
    with pytest.raises(TypeError):
        EditProvider()


def test_gemini_edit_provider_exists():
    """GeminiEditProvider 已注册。"""
    from providers.registry import get_edit_provider
    provider = get_edit_provider("gemini", timeout=30)
    assert isinstance(provider, EditProvider)


def test_edit_provider_registry_unknown():
    """未知供应商抛 KeyError。"""
    from providers.registry import get_edit_provider
    with pytest.raises(KeyError, match="未知的编辑供应商"):
        get_edit_provider("nonexistent")
