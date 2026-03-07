"""Calendar 看板：数据拉取 + 季度路由。"""

import datetime
import logging

import feishu
from defaults import load_defaults

logger = logging.getLogger(__name__)

_CALENDAR_LIMIT = 15


def _get_current_quarter(month: int | None = None) -> str:
    """根据月份返回季度标识（Q1-Q4）。"""
    if month is None:
        month = datetime.date.today().month
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    return f"Q{(month - 1) // 3 + 1}"


def _query_calendar_raw() -> list[dict]:
    """从飞书 Bitable 拉取当前季度的 Calendar 原始记录。"""
    d = load_defaults()
    quarter = _get_current_quarter()
    qc = d.calendar_quarters.get(quarter)
    if not qc or not qc.table_id:
        logger.warning("[Calendar] 季度 %s 未配置 table_id", quarter)
        return []
    token = feishu.get_token_sync()
    return feishu.query_bitable_sync(
        token, d.calendar_app_token, qc.table_id, view_id=qc.view_id,
    )


def _extract_record(fields: dict) -> dict:
    """从原始 fields 提取 Calendar 卡片所需字段。"""
    def _person_name(val):
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val[0].get("name", "")
        return ""

    # 超链接字段
    doc = fields.get("Doc // 需求文档") or {}
    if isinstance(doc, dict):
        doc_link = doc.get("link", "")
        doc_text = doc.get("text", "")
    else:
        doc_link, doc_text = "", ""

    # 区域（多选 — 可能是 list[str] 或 list[dict]）
    regions_raw = fields.get("Regions // 区域") or []
    if regions_raw and isinstance(regions_raw[0], dict):
        regions = [r.get("text", "") for r in regions_raw]
    else:
        regions = list(regions_raw)

    deadline_ts = fields.get("Deadline // 截止日期") or 0

    return {
        "name": fields.get("Gift Name // 礼物名", ""),
        "price": fields.get("Price // 价格"),
        "gift_type": fields.get("Gift Type // 礼物类型", ""),
        "categories": fields.get("Categories // 需求类型", ""),
        "regions": regions,
        "poc": _person_name(fields.get("POC // 需求方")),
        "doc_link": doc_link,
        "doc_text": doc_text,
        "progress": fields.get("Progress // 进展", ""),
        "designer": _person_name(fields.get("Designer // 设计师")),
        "deadline_ts": deadline_ts,
    }


def fetch_calendar_records() -> list[dict]:
    """拉取 Calendar 记录，按 Deadline 排序，返回最近 N 条。"""
    raw_records = _query_calendar_raw()
    records = [_extract_record(rec.get("fields", {})) for rec in raw_records]
    # 按 deadline 升序（最早的在前），无 deadline 的排最后
    records.sort(key=lambda r: r["deadline_ts"] if r["deadline_ts"] else float("inf"))
    return records[:_CALENDAR_LIMIT]
