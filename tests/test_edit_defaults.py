"""编辑流配置加载测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from defaults import load_defaults


def test_edit_defaults_loaded():
    d = load_defaults()
    assert d.edit_provider == "gemini"
    assert len(d.edit_models) >= 1
    assert d.edit_timeout > 0
    assert d.edit_max_rounds >= 1
    assert d.edit_session_ttl > 0
