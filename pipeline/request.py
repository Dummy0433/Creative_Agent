"""需求提单：校验 + 写入 Calendar 表。"""

import datetime
import logging

logger = logging.getLogger(__name__)

_MIN_WORKING_DAYS = 15


def count_working_days(start: datetime.date, end: datetime.date) -> int:
    """计算 start 到 end（含）之间的工作日数（排除周六日）。"""
    if end < start:
        return 0
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:  # 0=Mon, 4=Fri
            days += 1
        current += datetime.timedelta(days=1)
    return days


def check_working_days(target_date: datetime.date, min_days: int = _MIN_WORKING_DAYS) -> bool:
    """检查 target_date 距今是否有足够的工作日。"""
    today = datetime.date.today()
    working = count_working_days(today, target_date)
    return working >= min_days
