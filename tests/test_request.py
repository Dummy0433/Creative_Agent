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


def test_submit_missing_name():
    """缺少礼物名应失败。"""
    import pytest
    from pipeline.request import submit_request
    with pytest.raises(ValueError, match="礼物名"):
        submit_request({"gift_name": "", "price": "100", "deadline": "2099-12-31"}, "ou_test")


def test_submit_bad_date_format():
    """日期格式错误应失败。"""
    import pytest
    from pipeline.request import submit_request
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        submit_request({"gift_name": "Test", "price": "100", "deadline": "12/31/2099"}, "ou_test")


def test_submit_deadline_too_soon():
    """交付时间过近应失败。"""
    import pytest
    import datetime
    from pipeline.request import submit_request
    soon = (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    with pytest.raises(ValueError, match="工作日"):
        submit_request({"gift_name": "Test", "price": "100", "deadline": soon}, "ou_test")


def test_submit_missing_price():
    """缺少价格应失败。"""
    import pytest
    from pipeline.request import submit_request
    with pytest.raises(ValueError, match="价格"):
        submit_request({"gift_name": "Test", "price": "", "deadline": "2099-12-31"}, "ou_test")


def test_submit_non_numeric_price():
    """非数字价格应失败。"""
    import pytest
    from pipeline.request import submit_request
    with pytest.raises(ValueError, match="数字"):
        submit_request({"gift_name": "Test", "price": "abc", "deadline": "2099-12-31"}, "ou_test")


def test_submit_missing_deadline():
    """缺少交付时间应失败。"""
    import pytest
    from pipeline.request import submit_request
    with pytest.raises(ValueError, match="交付时间"):
        submit_request({"gift_name": "Test", "price": "100", "deadline": ""}, "ou_test")
