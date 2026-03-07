"""Calendar 看板：数据拉取 + 季度路由。"""

import datetime


def _get_current_quarter(month: int | None = None) -> str:
    """根据月份返回季度标识（Q1-Q4）。"""
    if month is None:
        month = datetime.date.today().month
    return f"Q{(month - 1) // 3 + 1}"
