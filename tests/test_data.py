"""数据解析函数的单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.data import _parse_price_range


# ── _parse_price_range 测试 ────────────────────────────────────


def test_parse_range_normal():
    """标准范围格式：'1-19 coins' -> (1, 19)。"""
    assert _parse_price_range("1-19 coins") == (1, 19)


def test_parse_range_large():
    """大数字范围格式：'5000-20999 coins' -> (5000, 20999)。"""
    assert _parse_price_range("5000-20999 coins") == (5000, 20999)


def test_parse_range_plus():
    """无上限格式：'21000+ coins' -> (21000, 10^9)。"""
    assert _parse_price_range("21000+ coins") == (21000, 10**9)


def test_parse_range_with_comma():
    """包含千分位逗号：'5,000-20,999 coins' -> (5000, 20999)。"""
    assert _parse_price_range("5,000-20,999 coins") == (5000, 20999)


def test_parse_range_en_dash():
    """使用 en-dash (–) 分隔：'1–19' -> (1, 19)。"""
    assert _parse_price_range("1–19") == (1, 19)


def test_parse_range_invalid():
    """无法解析的格式返回 (-1, -1)。"""
    assert _parse_price_range("abc") == (-1, -1)
    assert _parse_price_range("") == (-1, -1)


def test_parse_range_whitespace():
    """带额外空白的格式也能解析。"""
    assert _parse_price_range("  1 - 19  ") == (1, 19)
