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


def test_candidate_result_model():
    """CandidateResult 基础字段。"""
    from models import CandidateResult
    cr = CandidateResult(
        request_id="abc123", tier="P0", subject_final="雄狮徽章",
        prompt="中文提示词", english_prompt="english prompt",
        image_keys=["key1", "key2", "key3", "key4"],
        image_bytes_list=[b"img1", b"img2", b"img3", b"img4"],
        region="MENA", price=1,
    )
    assert len(cr.image_keys) == 4
    assert cr.tier == "P0"


def test_candidate_result_excludes_bytes():
    """image_bytes_list 不应出现在序列化输出中。"""
    from models import CandidateResult
    cr = CandidateResult(
        request_id="x", tier="P0", subject_final="s", prompt="p",
        english_prompt="e", image_keys=["k"], image_bytes_list=[b"b"],
        region="MENA", price=1,
    )
    d = cr.model_dump()
    assert "image_bytes_list" not in d
