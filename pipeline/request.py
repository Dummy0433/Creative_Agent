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


def submit_request(form_data: dict, submitter_open_id: str) -> str:
    """校验并提交需求到 Calendar 表。

    Returns:
        成功时返回 record_id。
    Raises:
        ValueError: 校验失败时。
    """
    import feishu
    from defaults import load_defaults
    from pipeline.calendar import _get_current_quarter

    d = load_defaults()

    # 必填校验
    gift_name = form_data.get("gift_name", "").strip()
    if not gift_name:
        raise ValueError("请填写礼物名")

    price_str = form_data.get("price", "").strip()
    if not price_str:
        raise ValueError("请填写价格")
    try:
        price = int(price_str)
    except (ValueError, TypeError):
        raise ValueError(f"价格必须是数字，收到: {price_str}")

    # 解析 deadline
    deadline_str = form_data.get("deadline", "").strip()
    if not deadline_str:
        raise ValueError("请填写期望交付时间")
    try:
        # date_picker 返回 "YYYY-MM-DD +0800" 格式，取前10字符
        target_date = datetime.datetime.strptime(deadline_str[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"日期格式错误，收到: {deadline_str}")

    # 15 工作日校验
    if not check_working_days(target_date, d.request_min_working_days):
        contact = d.request_exception_contact or "管理员"
        raise ValueError(
            f"期望交付时间距今不足 {d.request_min_working_days} 个工作日。"
            f"如需例外，{contact}。"
        )

    gift_type = form_data.get("gift_type", "")
    categories = form_data.get("categories", "")
    region = form_data.get("region", "")
    prd = form_data.get("prd", "").strip()

    # 构建 Bitable record fields
    deadline_ts = int(datetime.datetime.combine(target_date, datetime.time()).timestamp() * 1000)
    fields = {
        "Gift Name // 礼物名": gift_name,
        "Price // 价格": price,
        "Progress // 进展": "Not Scheduled// 未排期",
        "Deadline // 截止日期": deadline_ts,
        "POC // 需求方": [{"id": submitter_open_id}],
    }
    if gift_type:
        fields["Gift Type // 礼物类型"] = gift_type
    if categories:
        fields["Categories // 需求类型"] = categories
    if region:
        fields["Regions // 区域"] = [region]
    if prd:
        fields["Doc // 需求文档"] = {"link": prd, "text": prd}

    # 确定当前季度的表
    quarter = _get_current_quarter()
    qc = d.calendar_quarters.get(quarter)
    if not qc or not qc.table_id:
        raise ValueError(f"当前季度 {quarter} 未配置 Calendar 表")

    token = feishu.get_token_sync()
    record_id = feishu.create_bitable_record_sync(
        token, d.calendar_app_token, qc.table_id, fields,
    )
    logger.info("[Request] 需求已提交: %s → record_id=%s", gift_name, record_id)
    return record_id
