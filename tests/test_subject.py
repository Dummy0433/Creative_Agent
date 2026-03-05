"""主体分类与校验的单元测试。"""

import sys
from pathlib import Path

# 将项目根目录加入 sys.path，方便直接导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.subject import classify_subject, validate_subject


# ── classify_subject 测试 ──────────────────────────────────────


def test_classify_animal():
    """动物关键词应被识别为「动物」类别。"""
    assert "动物" in classify_subject("雄狮")
    assert "动物" in classify_subject("猎鹰展翅")


def test_classify_plant():
    """植物关键词应被识别为「植物」类别。"""
    assert "植物" in classify_subject("玫瑰")
    assert "植物" in classify_subject("棕榈树")


def test_classify_landscape():
    """地貌关键词应被识别为「地貌」类别。"""
    assert "地貌" in classify_subject("沙漠风光")
    assert "地貌" in classify_subject("绿洲")


def test_classify_mixed():
    """同时包含多个类别关键词时应返回多个类别。"""
    cats = classify_subject("沙漠中的雄狮")
    assert "动物" in cats
    assert "地貌" in cats


def test_classify_unknown():
    """不包含已知关键词时返回空集。"""
    assert classify_subject("钻石") == set()
    assert classify_subject("金冠") == set()


# ── validate_subject 测试 ──────────────────────────────────────


def test_validate_allowed():
    """无禁止规则时主体原样通过。"""
    rules = {"禁止物象": "无", "容器备选": ""}
    result = validate_subject("雄狮", rules, {})
    assert result == "雄狮"


def test_validate_no_forbidden_field():
    """无禁止字段时主体原样通过。"""
    result = validate_subject("雄狮", {}, {})
    assert result == "雄狮"


def test_validate_forbidden_wrapped():
    """被禁止的主体应被容器包裹。"""
    rules = {"禁止物象": "动物", "容器备选": "徽章/奖牌"}
    result = validate_subject("雄狮", rules, {})
    # 结果应以「雄狮」开头 + 容器后缀
    assert result.startswith("雄狮")
    assert result != "雄狮"
    assert any(c in result for c in ["徽章", "奖牌"])


def test_validate_forbidden_no_container():
    """被禁止但无容器可选时，主体原样通过。"""
    rules = {"禁止物象": "动物", "容器备选": "无需容器"}
    result = validate_subject("雄狮", rules, {})
    assert result == "雄狮"


def test_validate_not_forbidden():
    """主体类别不在禁止列表中时原样通过。"""
    rules = {"禁止物象": "地貌", "容器备选": "徽章/奖牌"}
    result = validate_subject("雄狮", rules, {})
    assert result == "雄狮"
