"""多维表格查询：区域信息、档位规则、参考案例。"""

import logging
import re

import feishu
from settings import get_settings

logger = logging.getLogger(__name__)

# ── 双语搜索键（兼容中英文字段名） ──────────────────────────

_REGION_KEYS = ("区域", "产品线", "region", "Region", "文本")       # 区域匹配字段
_TIER_KEYS = ("价格层级", "tier", "Tier", "price_tier")             # 档位匹配字段
_PRICE_RANGE_KEYS = ("价格区间", "price_range", "Price Range")      # 价格区间匹配字段


def _match(data: dict, keys: tuple[str, ...], value: str) -> bool:
    """检查 data 中是否有任一 key 的值等于 value（多字段名兼容匹配）。"""
    return any(data.get(k, "") == value for k in keys)


def _match_region(data: dict, region: str) -> bool:
    """检查记录是否匹配指定区域。"""
    return _match(data, _REGION_KEYS, region)


def _parse_price_range(text: str) -> tuple[int, int]:
    """解析价格区间文本，返回 (下限, 上限)。

    支持格式：
        "1-19 coins"    -> (1, 19)
        "21000+ coins"  -> (21000, 10^9)
        无法解析        -> (-1, -1)
    """
    text = text.replace(",", "").strip()
    # 匹配 "数字+" 格式（无上限）
    m = re.match(r"(\d+)\s*\+", text)
    if m:
        return int(m.group(1)), 10**9
    # 匹配 "数字-数字" 格式
    m = re.match(r"(\d+)\s*[-–]\s*(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return -1, -1


# ── 查询函数 ────────────────────────────────────────────────

def query_region_info(token: str, region: str) -> dict:
    """查询 TABLE1（区域原型），返回该区域的设计风格、特色物件等信息。"""
    s = get_settings()
    logger.info("[数据] 正在查询 TABLE1(区域原型) 区域=%s", region)
    records = feishu.query_bitable(token, s.table1_app_token, s.table1_table_id)
    if not records:
        raise RuntimeError("TABLE1 为空")
    # 遍历记录，匹配区域
    for rec in records:
        data = feishu.parse_record(rec)
        if _match_region(data, region):
            logger.info("  已找到区域信息: %s", region)
            return data
    raise RuntimeError(
        f"在 TABLE1 中未找到区域 '{region}' (已搜索字段: {_REGION_KEYS})"
    )


def query_tier_rules(token: str, region: str, price: int) -> dict:
    """查询 TABLE2（档位规则），根据区域和价格匹配对应档位。

    匹配逻辑：先按区域筛选，再判断价格是否落在「价格区间」内。
    """
    s = get_settings()
    logger.info("[数据] 正在查询 TABLE2(档位规则) 区域=%s, 价格=%d", region, price)
    records = feishu.query_bitable(token, s.table2_app_token, s.table2_table_id)

    candidates = []  # 收集同区域的候选档位（用于错误提示）
    for rec in records:
        data = feishu.parse_record(rec)
        # 先匹配区域
        if not _match_region(data, region):
            continue
        # 从多个可能的字段名中提取价格区间文本
        range_text = ""
        for k in _PRICE_RANGE_KEYS:
            if data.get(k):
                range_text = data[k]
                break
        # 解析价格区间并判断是否匹配
        lo, hi = _parse_price_range(range_text)
        if lo <= price <= hi:
            tier = ""
            for k in _TIER_KEYS:
                if data.get(k):
                    tier = data[k]
                    break
            logger.info("  匹配到档位 %s (%s), 价格 %d", tier, range_text, price)
            return data
        candidates.append((data.get("价格层级", "?"), range_text))

    # 未匹配到任何档位，抛出错误并列出可用档位
    available = ", ".join(f"{t}({r})" for t, r in candidates)
    raise RuntimeError(
        f"未找到匹配的档位规则: 区域='{region}' 价格={price}. "
        f"可用档位: [{available}]"
    )


def query_instances(token: str, region: str, limit: int = 3) -> list[dict]:
    """查询 TABLE3（参考案例），按区域筛选后返回指定数量的案例。

    如果 TABLE3 中不存在区域字段，则使用全部记录。
    """
    s = get_settings()
    logger.info("[数据] 正在查询 TABLE3(参考案例) 区域=%s", region)
    records = feishu.query_bitable(token, s.table3_app_token, s.table3_table_id)
    all_parsed = [feishu.parse_record(rec) for rec in records]

    # 检查是否有任何记录包含区域字段
    has_region_field = any(
        any(data.get(k) for k in _REGION_KEYS) for data in all_parsed
    )

    if has_region_field:
        # 有区域字段时按区域筛选
        matched = [d for d in all_parsed if _match_region(d, region)]
        logger.info("  按区域筛选: %d/%d 条记录", len(matched), len(all_parsed))
    else:
        # 无区域字段时使用全部记录
        matched = all_parsed
        logger.info("  TABLE3 无区域字段, 使用全部 %d 条记录", len(matched))

    instances = matched[:limit]
    logger.info("  返回 %d 条案例", len(instances))
    return instances
