"""Calendar 配置测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_calendar_config_loads():
    """generation_defaults.yaml 中 calendar 配置可正常加载。"""
    from defaults import load_defaults
    load_defaults.cache_clear()
    d = load_defaults()
    assert d.calendar_app_token != ""
    assert "Q1" in d.calendar_quarters
    q1 = d.calendar_quarters["Q1"]
    assert q1.table_id != ""
    assert q1.view_id != ""


def test_calendar_quarter_selection():
    """根据月份自动选择正确的季度。"""
    from pipeline.calendar import _get_current_quarter
    assert _get_current_quarter(month=1) == "Q1"
    assert _get_current_quarter(month=3) == "Q1"
    assert _get_current_quarter(month=4) == "Q2"
    assert _get_current_quarter(month=7) == "Q3"
    assert _get_current_quarter(month=12) == "Q4"
