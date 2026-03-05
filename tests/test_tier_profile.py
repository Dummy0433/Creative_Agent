"""层级配置加载的单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_tier_profile_model():
    """TierProfile 基础字段解析。"""
    from models import TierProfile
    p = TierProfile(analyze_prompt_file="analyze_P0.md", prompt_gen_prompt_file="prompt_gen_P0.md")
    assert p.analyze_prompt_file == "analyze_P0.md"
    assert p.image_models is None


def test_generation_defaults_has_tier_profiles():
    """GenerationDefaults 包含 tier_profiles 字段。"""
    from models import GenerationDefaults, TierProfile
    d = GenerationDefaults(
        analyze_model="m", prompt_model="m", image_models=["m"],
        tier_profiles={"P0": TierProfile(
            analyze_prompt_file="analyze_P0.md",
            prompt_gen_prompt_file="prompt_gen_P0.md",
        )},
    )
    assert "P0" in d.tier_profiles
    assert d.tier_profiles["P0"].analyze_prompt_file == "analyze_P0.md"


def test_generation_defaults_empty_tier_profiles():
    """tier_profiles 为空时默认空字典。"""
    from models import GenerationDefaults
    d = GenerationDefaults(analyze_model="m", prompt_model="m", image_models=["m"])
    assert d.tier_profiles == {}
