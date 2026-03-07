"""编辑编排逻辑测试（mock provider）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.edit import matches_termination


def test_termination_positive():
    for word in ["好了", "不用了", "OK", "ok", "done", "Done", "不需要了"]:
        assert matches_termination(word), f"should match: {word}"


def test_termination_negative():
    for word in ["把背景改成红色", "加个皇冠", "雄狮 100", ""]:
        assert not matches_termination(word), f"should not match: {word}"
