"""上下文构建与格式化的单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.context import build_context, format_instances


# ── build_context 测试 ─────────────────────────────────────────


def test_build_context_basic():
    """基础上下文应包含区域和档位信息。"""
    region = {"设计风格": "阿拉伯纹样", "特色物件": "新月"}
    tier = {"允许物象": "动物/植物", "视觉质感": "扁平化"}
    result = build_context(region, tier)
    assert "区域通用信息" in result
    assert "阿拉伯纹样" in result
    assert "新月" in result
    assert "档位规则" in result
    assert "动物/植物" in result
    assert "扁平化" in result


def test_build_context_missing_fields():
    """缺失字段时不应抛错，只输出有值的字段。"""
    result = build_context({"设计风格": "极简"}, {})
    assert "极简" in result
    assert "档位规则" in result


def test_build_context_empty():
    """空输入应返回包含标题的最小上下文。"""
    result = build_context({}, {})
    assert "区域通用信息" in result
    assert "档位规则" in result


# ── format_instances 测试 ──────────────────────────────────────


def test_format_instances_basic():
    """格式化单个参考案例。"""
    instances = [{"Resource Name": "Golden Lion", "设计理念": "力量与荣耀", "风格": "写实", "材质": "金属", "物象 II": "雄狮"}]
    result = format_instances(instances)
    assert "参考案例" in result
    assert "Golden Lion" in result
    assert "力量与荣耀" in result


def test_format_instances_empty():
    """空列表应返回提示文字。"""
    result = format_instances([])
    assert "暂无参考案例" in result


def test_format_instances_chinese_name():
    """使用中文字段名「名称」的案例也能正确格式化。"""
    instances = [{"名称": "金色雄狮", "风格": "写实", "材质": "金属", "物象II": "狮"}]
    result = format_instances(instances)
    assert "金色雄狮" in result


# ── get_analyze_system / get_prompt_gen_system tier_file 测试 ───────


def test_get_analyze_system_tier_file(tmp_path, monkeypatch):
    """指定 tier_file 时从对应文件加载。"""
    from pipeline import context
    tier_file = tmp_path / "analyze_P0.md"
    tier_file.write_text("P0 专用分析提示词", encoding="utf-8")
    monkeypatch.setattr(context, "_PROMPTS_DIR", tmp_path)
    context._load_prompt.cache_clear()
    result = context.get_analyze_system(tier_file="analyze_P0.md")
    assert result == "P0 专用分析提示词"


def test_get_analyze_system_override_beats_tier_file():
    """override 参数优先级高于 tier_file。"""
    from pipeline.context import get_analyze_system
    result = get_analyze_system(override="直接覆盖", tier_file="analyze_P0.md")
    assert result == "直接覆盖"


def test_get_prompt_gen_system_tier_file(tmp_path, monkeypatch):
    """prompt_gen 也支持 tier_file。"""
    from pipeline import context
    tier_file = tmp_path / "prompt_gen_P0.md"
    tier_file.write_text("P0 专用提示词生成", encoding="utf-8")
    monkeypatch.setattr(context, "_PROMPTS_DIR", tmp_path)
    context._load_prompt.cache_clear()
    result = context.get_prompt_gen_system(tier_file="prompt_gen_P0.md")
    assert result == "P0 专用提示词生成"
