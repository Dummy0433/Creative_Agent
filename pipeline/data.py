"""多维表格查询：区域信息、档位规则、参考案例。"""

import logging
import random
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


def _match_price_tier_instance(data: dict, price: int) -> bool:
    """检查参考案例记录的价格档位是否与给定价格匹配。

    尝试从价格区间字段和档位字段中提取区间文本，判断 price 是否落入。
    TABLE3 的「价格层级」字段值可能是 "1-19 coins" 这样的区间文本。
    """
    for k in (*_PRICE_RANGE_KEYS, *_TIER_KEYS):
        range_text = data.get(k, "")
        if isinstance(range_text, str) and range_text:
            lo, hi = _parse_price_range(range_text)
            if lo >= 0 and lo <= price <= hi:
                return True
    return False


def query_instances(token: str, region: str, price: int = 0, limit: int = 3) -> list[dict]:
    """查询 TABLE3（参考案例），按区域和价格档位筛选后随机返回指定数量的案例。

    筛选逻辑：
    1. 按区域筛选（如有区域字段）
    2. 按价格档位筛选（如 price > 0）
    3. 无价格匹配时 fallback 到区域匹配结果
    4. 随机 shuffle 后取前 limit 条
    """
    s = get_settings()
    logger.info("[数据] 正在查询 TABLE3(参考案例) 区域=%s, 价格=%d", region, price)
    records = feishu.query_bitable(token, s.table3_app_token, s.table3_table_id)
    all_parsed = [feishu.parse_record(rec) for rec in records]

    # 检查是否有任何记录包含区域字段
    has_region_field = any(
        any(data.get(k) for k in _REGION_KEYS) for data in all_parsed
    )

    if has_region_field:
        matched = [d for d in all_parsed if _match_region(d, region)]
        logger.info("  按区域筛选: %d/%d 条记录", len(matched), len(all_parsed))
    else:
        matched = all_parsed
        logger.info("  TABLE3 无区域字段, 使用全部 %d 条记录", len(matched))

    # 按价格档位筛选
    if price > 0:
        price_matched = [d for d in matched if _match_price_tier_instance(d, price)]
        if price_matched:
            logger.info("  按价格档位筛选: %d/%d 条记录", len(price_matched), len(matched))
            matched = price_matched
        else:
            logger.info("  无价格档位匹配, fallback 到全部 %d 条记录", len(matched))

    random.shuffle(matched)
    instances = matched[:limit]
    logger.info("  返回 %d 条案例", len(instances))
    return instances


def download_instance_images(token: str, instances: list[dict]) -> list[bytes]:
    """下载实例的图标附件图片，返回图片字节列表。

    直接使用附件元数据中的 url 字段下载，下载失败的跳过。
    """
    images = []
    for inst in instances:
        attachments = inst.get("图标")
        if not isinstance(attachments, list) or not attachments:
            continue
        download_url = attachments[0].get("url", "")
        if not download_url:
            continue
        try:
            img_bytes = feishu.download_media(token, download_url)
            images.append(img_bytes)
        except Exception as e:
            logger.warning("  下载实例图片失败 (%s): %s", download_url, e)
    return images
