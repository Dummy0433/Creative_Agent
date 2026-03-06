"""多维表格查询：路由表、区域信息、档位规则、参考案例（async）。"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time

import feishu
from models import RoutingInfo
from settings import get_settings

logger = logging.getLogger(__name__)

# ── TABLE0 路由缓存 ──────────────────────────────────────
# 结构：{region: (RoutingInfo, timestamp)}，TTL 600秒（10分钟）
_routing_cache: dict[str, tuple[RoutingInfo, float]] = {}
_ROUTING_TTL = 600  # 缓存过期时间（秒）

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

async def query_routing(token: str, region: str) -> RoutingInfo | None:
    """查询 TABLE0（路由表），返回该区域对应的各表格物理地址。

    结果缓存 10 分钟。查询失败或未找到区域时返回 None。
    """
    # 检查缓存
    now = time.time()
    if region in _routing_cache:
        cached, ts = _routing_cache[region]
        if now - ts < _ROUTING_TTL:
            logger.debug("[路由] 缓存命中: 区域=%s", region)
            return cached

    s = get_settings()
    # TABLE0 地址为空时跳过查询
    if not s.table0_app_token or not s.table0_table_id:
        logger.debug("[路由] TABLE0 地址未配置，跳过路由查询")
        return None

    try:
        logger.debug("[路由] 正在查询 TABLE0(路由表) 区域=%s", region)
        records = await feishu.query_bitable(token, s.table0_app_token, s.table0_table_id)
    except Exception as e:
        logger.warning("[路由] TABLE0 查询失败: %s，将使用 settings 默认地址", e)
        return None

    # TABLE0 字段名列表
    routing_fields = [
        "archetype_app_token", "archetype_table_id",
        "rules_app_token", "rules_table_id",
        "instance_app_token", "instance_table_id",
    ]

    # 遍历记录，匹配区域
    for rec in records:
        data = feishu.parse_record(rec)
        if not _match_region(data, region):
            continue
        # 提取 6 个地址字段
        routing_data = {"region": region}
        for field_name in routing_fields:
            routing_data[field_name] = data.get(field_name, "")
        # 校验完整性：6 个地址字段必须非空
        missing = [k for k in routing_fields if not routing_data.get(k)]
        if missing:
            logger.warning("[路由] TABLE0 区域=%s 数据不完整，缺失: %s，将使用 settings 默认地址",
                           region, missing)
            return None
        routing = RoutingInfo(**routing_data)
        # 写入缓存
        _routing_cache[region] = (routing, now)
        logger.debug("[路由] TABLE0 解析成功: 区域=%s", region)
        return routing

    logger.warning("[路由] TABLE0 中未找到区域 '%s'，将使用 settings 默认地址", region)
    return None


async def resolve_routing(token: str, region: str) -> RoutingInfo:
    """解析路由信息：TABLE0 查询 + settings fallback，保证始终返回有效值。"""
    routing = await query_routing(token, region)
    if routing:
        return routing
    # Fallback：从 settings 构建默认路由
    s = get_settings()
    logger.debug("[路由] 使用 settings 默认地址作为 fallback")
    return RoutingInfo(
        region=region,
        archetype_app_token=s.table1_app_token,
        archetype_table_id=s.table1_table_id,
        rules_app_token=s.table2_app_token,
        rules_table_id=s.table2_table_id,
        instance_app_token=s.table3_app_token,
        instance_table_id=s.table3_table_id,
    )


# ── 查询函数 ────────────────────────────────────────────────

async def query_region_info(token: str, region: str, routing: RoutingInfo | None = None) -> dict:
    """查询 TABLE1（区域原型），返回该区域的设计风格、特色物件等信息。"""
    if routing:
        app_token, table_id = routing.archetype_app_token, routing.archetype_table_id
    else:
        s = get_settings()
        app_token, table_id = s.table1_app_token, s.table1_table_id
    logger.debug("[数据] 正在查询 TABLE1(区域原型) 区域=%s", region)
    records = await feishu.query_bitable(token, app_token, table_id)
    if not records:
        raise RuntimeError("TABLE1 为空")
    # 遍历记录，匹配区域
    for rec in records:
        data = feishu.parse_record(rec)
        if _match_region(data, region):
            logger.debug("  已找到区域信息: %s", region)
            return data
    raise RuntimeError(
        f"在 TABLE1 中未找到区域 '{region}' (已搜索字段: {_REGION_KEYS})"
    )


async def query_tier_rules(token: str, region: str, price: int, routing: RoutingInfo | None = None) -> dict:
    """查询 TABLE2（档位规则），根据区域和价格匹配对应档位。"""
    if routing:
        app_token, table_id = routing.rules_app_token, routing.rules_table_id
    else:
        s = get_settings()
        app_token, table_id = s.table2_app_token, s.table2_table_id
    logger.debug("[数据] 正在查询 TABLE2(档位规则) 区域=%s, 价格=%d", region, price)
    records = await feishu.query_bitable(token, app_token, table_id)

    candidates = []
    for rec in records:
        data = feishu.parse_record(rec)
        if not _match_region(data, region):
            continue
        range_text = ""
        for k in _PRICE_RANGE_KEYS:
            if data.get(k):
                range_text = data[k]
                break
        lo, hi = _parse_price_range(range_text)
        if lo <= price <= hi:
            tier = ""
            for k in _TIER_KEYS:
                if data.get(k):
                    tier = data[k]
                    break
            logger.debug("  匹配到档位 %s (%s), 价格 %d", tier, range_text, price)
            return data
        candidates.append((data.get("价格层级", "?"), range_text))

    available = ", ".join(f"{t}({r})" for t, r in candidates)
    raise RuntimeError(
        f"未找到匹配的档位规则: 区域='{region}' 价格={price}. "
        f"可用档位: [{available}]"
    )


def _match_price_tier_instance(data: dict, price: int) -> bool:
    """检查参考案例记录的价格档位是否与给定价格匹配。"""
    for k in (*_PRICE_RANGE_KEYS, *_TIER_KEYS):
        range_text = data.get(k, "")
        if isinstance(range_text, str) and range_text:
            lo, hi = _parse_price_range(range_text)
            if lo >= 0 and lo <= price <= hi:
                return True
    return False


async def query_instances(token: str, region: str, price: int = 0, limit: int = 3,
                          routing: RoutingInfo | None = None) -> list[dict]:
    """查询 TABLE3（参考案例），按区域和价格档位筛选后随机返回指定数量的案例。"""
    if routing:
        app_token, table_id = routing.instance_app_token, routing.instance_table_id
    else:
        s = get_settings()
        app_token, table_id = s.table3_app_token, s.table3_table_id
    logger.debug("[数据] 正在查询 TABLE3(参考案例) 区域=%s, 价格=%d", region, price)
    records = await feishu.query_bitable(token, app_token, table_id)
    all_parsed = [feishu.parse_record(rec) for rec in records]

    has_region_field = any(
        any(data.get(k) for k in _REGION_KEYS) for data in all_parsed
    )

    if has_region_field:
        matched = [d for d in all_parsed if _match_region(d, region)]
        logger.debug("  按区域筛选: %d/%d 条记录", len(matched), len(all_parsed))
    else:
        matched = all_parsed
        logger.debug("  TABLE3 无区域字段, 使用全部 %d 条记录", len(matched))

    if price > 0:
        price_matched = [d for d in matched if _match_price_tier_instance(d, price)]
        if price_matched:
            logger.debug("  按价格档位筛选: %d/%d 条记录", len(price_matched), len(matched))
            matched = price_matched
        else:
            logger.debug("  无价格档位匹配, fallback 到全部 %d 条记录", len(matched))

    random.shuffle(matched)
    instances = matched[:limit]
    logger.debug("  返回 %d 条案例", len(instances))
    return instances


async def download_instance_images(token: str, instances: list[dict]) -> list[bytes]:
    """并行下载实例的图标附件图片，返回图片字节列表。"""
    async def _download_one(inst: dict) -> bytes | None:
        attachments = inst.get("图标")
        if not isinstance(attachments, list) or not attachments:
            return None
        download_url = attachments[0].get("url", "")
        if not download_url:
            return None
        try:
            return await feishu.download_media(token, download_url)
        except Exception as e:
            logger.warning("  下载实例图片失败 (%s): %s", download_url, e)
            return None

    results = await asyncio.gather(*[_download_one(inst) for inst in instances])
    return [img for img in results if img is not None]
