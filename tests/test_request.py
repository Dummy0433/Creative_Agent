"""需求提单测试。"""

import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_working_days_enough():
    """15+ 工作日应通过校验。"""
    from pipeline.request import check_working_days
    target = datetime.date.today() + datetime.timedelta(days=25)
    assert check_working_days(target, min_days=15) is True


def test_working_days_insufficient():
    """< 15 工作日应不通过。"""
    from pipeline.request import check_working_days
    target = datetime.date.today() + datetime.timedelta(days=5)
    assert check_working_days(target, min_days=15) is False


def test_working_days_weekends_excluded():
    """工作日计算应排除周末。"""
    from pipeline.request import count_working_days
    # 2026-03-09 is Monday, 2026-03-13 is Friday → 5 working days
    start = datetime.date(2026, 3, 9)
    end = datetime.date(2026, 3, 13)
    assert count_working_days(start, end) == 5


def test_working_days_across_weekend():
    """跨周末：周五到下周一 = 2 个工作日。"""
    from pipeline.request import count_working_days
    # 2026-03-13 is Friday, 2026-03-16 is Monday
    start = datetime.date(2026, 3, 13)
    end = datetime.date(2026, 3, 16)
    assert count_working_days(start, end) == 2


def test_working_days_end_before_start():
    """end < start 返回 0。"""
    from pipeline.request import count_working_days
    start = datetime.date(2026, 3, 16)
    end = datetime.date(2026, 3, 13)
    assert count_working_days(start, end) == 0


def test_working_days_same_day_weekday():
    """同一天（工作日）= 1。"""
    from pipeline.request import count_working_days
    day = datetime.date(2026, 3, 9)  # Monday
    assert count_working_days(day, day) == 1


def test_working_days_same_day_weekend():
    """同一天（周末）= 0。"""
    from pipeline.request import count_working_days
    day = datetime.date(2026, 3, 14)  # Saturday
    assert count_working_days(day, day) == 0
