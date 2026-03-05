#!/usr/bin/env python3
"""飞书多维表格初始化脚本：创建字段并插入种子数据到 TABLE0 / TABLE1 / TABLE2。

适用场景:
  1. 新环境部署 — 首次配置飞书 Bitable，需要建表 + 写入初始数据
  2. 表格重建   — 原表被误删或损坏，需要从零恢复
  3. 新区域上线 — 增加新区域（如 TR / SEA）时，可在种子数据中追加后重新运行

不适用场景:
  - 日常运维（表格已存在且数据正常时无需运行）
  - 数据修改（直接在飞书多维表格 UI 中编辑即可）

表格说明:
  TABLE0 (路由表)   — 每个区域一行，映射到 TABLE1/2/3 的物理表格地址
  TABLE1 (区域原型) — 每个区域一行，定义设计风格、特色物件、配色等
  TABLE2 (档位规则) — 每个区域×档位一行，定义价格区间、允许/禁止物象、容器等

注意:
  TABLE3 (参考案例) 由设计团队在飞书中手动维护，不在此脚本管理范围内。

用法:
  python3 setup_tables.py                       # 预览全部种子数据（只读）
  python3 setup_tables.py apply [table0|1|2]    # 写入种子数据（可指定表）
  python3 setup_tables.py route                 # 交互式：粘贴 URL 自动更新 TABLE0 路由
"""

import json
import logging
import re
import sys
from urllib.parse import urlparse, parse_qs

import requests

from feishu import get_token, _headers, extract_text
from settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 表格 Schema 定义
# Pipeline 实际读取的字段，与 pipeline/data.py 和 pipeline/context.py 保持一致
# ══════════════════════════════════════════════════════════════

# TABLE0 (路由表) 字段 — pipeline/data.py resolve_routing() 消费
# 注意："区域" 字段已存在于表中，无需创建
TABLE0_FIELDS = [
    "archetype_app_token",   # TABLE1 应用 token
    "archetype_table_id",    # TABLE1 表格 ID
    "rules_app_token",       # TABLE2 应用 token
    "rules_table_id",        # TABLE2 表格 ID
    "instance_app_token",    # TABLE3 应用 token
    "instance_table_id",     # TABLE3 表格 ID
]

# TABLE1 (区域原型) 字段 — pipeline/context.py build_context() 消费
TABLE1_FIELDS = [
    "文本",       # 区域名称，用于匹配（_REGION_KEYS 之一）
    "设计风格",   # context.py: build_context()
    "特色物件",   # context.py: build_context()
    "特色图案",   # context.py: build_context()
    "配色原则",   # context.py: build_context()
    "主材质",     # context.py: build_context()
    "禁忌",       # context.py: build_context()
]

# TABLE2 (档位规则) 字段 — pipeline/data.py + context.py + subject.py 消费
TABLE2_FIELDS = [
    "文本",       # 标签（如 MENA_T0），非 Pipeline 必需
    "region",     # 区域名称，用于匹配（_REGION_KEYS 之一）
    "tier",       # 档位标识（T0-T4），_TIER_KEYS 之一
    "价格区间",   # data.py: _parse_price_range() 匹配价格
    "允许物象",   # context.py: build_context()
    "禁止物象",   # subject.py: validate_subject() 判断是否被禁止
    "场景要求",   # context.py: build_context()
    "视觉质感",   # context.py: build_context()
    "容器备选",   # subject.py: validate_subject() 包裹被禁主体
]


# ══════════════════════════════════════════════════════════════
# 种子数据 — MENA 区域（可按需追加其他区域）
# ══════════════════════════════════════════════════════════════

TABLE0_SEED = [
    {
        "区域": "MENA",
        "archetype_app_token": "ZVpIbYAzXavJwPsIo7YlXBI2gJe",
        "archetype_table_id": "tblmBqweQeyO8Eis",
        "rules_app_token": "Weqqb5u5vaqVb6sX7lXlTJjxgdK",
        "rules_table_id": "tblyjwU9kHwQ8Yjk",
        "instance_app_token": "A4vIbpBaha7xr0soriylME5Lgke",
        "instance_table_id": "tblxocvuizuA2W3Y",
    },
]

TABLE1_SEED = [
    {
        "文本": "MENA",
        "设计风格": "写实为主，Pixar/Disney风格渲染，高度细节感、温润质感与叙事感",
        "特色物件": "骆驼/猎鹰/Dallah咖啡壶/阿拉伯咖啡/土耳其红茶/玻璃茶杯/椰枣/库纳法/"
                   "果仁蜜饼/阿拉伯长袍/头巾/香薰炉Mabkhara/项链/Darbuka鼓/"
                   "邪恶之眼/法蒂玛之手/棕榈树/沙漠玫瑰",
        "特色图案": "阿拉伯书法纹样(库法体/誊抄体)/几何马赛克(星形/菱形)/"
                   "植物缠枝纹(棕榈叶/无花果枝)",
        "配色原则": "以其他颜色为主，金色仅作点缀，比例约3:7；注意价效规范，低价档克制用金",
        "主材质": "丝绸质感为主基调",
        "禁忌": "清真寺不可直接出现(可虚拟化抽象化)/女性角色着装不可暴露/"
               "六芒星/显眼十字架/人物正面画像(宗教反偶像崇拜)/动物雕像可接受",
    },
]

TABLE2_SEED = [
    {
        "文本": "MENA_T0", "region": "MENA", "tier": "T0", "价格区间": "1-99",
        "允许物象": "文化手势/祈祷手势/邪恶之眼/法蒂玛之手/阿拉伯书法文字/"
                   "美食(椰枣/鹰嘴豆泥/库纳法/咖啡豆)/器具(Dallah/玻璃茶杯)/"
                   "足球/阿拉伯长袍/头巾/香薰炉/项链/配饰",
        "禁止物象": "动物整体/植物/自然地貌/大型场景/人物全身",
        "场景要求": "纯色背景居中，主体单独呈现，其他元素仅少量点缀",
        "视觉质感": "常规材质，弱质感，造型简单饱满不失细节",
        "容器备选": "贴纸/徽章/胸针/明信片/冰箱贴/珐琅别针/装饰补丁",
    },
    {
        "文本": "MENA_T1", "region": "MENA", "tier": "T1", "价格区间": "100-999",
        "允许物象": "T0全部/+乐器(Darbuka鼓)/+Shisha水烟壶/+Brass Tray",
        "禁止物象": "动物整体/植物/自然地貌",
        "场景要求": "物象单独出现或搭配简单场景(纯色背景/餐桌/盒子)",
        "视觉质感": "常规材质，遵循布料/玻璃等现实微质感，细节适度深入",
        "容器备选": "贴纸/徽章/胸针/明信片/冰箱贴/珐琅别针",
    },
    {
        "文本": "MENA_T2", "region": "MENA", "tier": "T2", "价格区间": "1000-2999",
        "允许物象": "T1全部/+植物(棕榈树/橄榄树/石榴树/沙漠玫瑰)",
        "禁止物象": "动物整体/自然地貌",
        "场景要求": "必须搭配简单场景(餐桌/盒子/室内陈设)",
        "视觉质感": "质感偏写实，材质种类适当增加，细节刻画深入",
        "容器备选": "装饰摆件/礼盒/装饰品",
    },
    {
        "文本": "MENA_T3", "region": "MENA", "tier": "T3", "价格区间": "3000-8999",
        "允许物象": "T2全部/+动物(骆驼/猎鹰)/+自然地貌(沙漠落日/绿洲)",
        "禁止物象": "无特殊限制",
        "场景要求": "必须搭配简单场景或复杂自然场景",
        "视觉质感": "质感写实，可增加贵金属/宝石/发光材质，细节刻画深入",
        "容器备选": "无需容器",
    },
    {
        "文本": "MENA_T4", "region": "MENA", "tier": "T4", "价格区间": "9000-29999",
        "允许物象": "T3全部/华丽场景/宫殿建筑/大型自然景观",
        "禁止物象": "无",
        "场景要求": "必须搭配华丽场景(宫殿/宏大自然)",
        "视觉质感": "质感高度写实，多材质结合，贵金属/宝石为主要表达",
        "容器备选": "无需容器",
    },
]


# ══════════════════════════════════════════════════════════════
# URL 解析 & 表格类型识别
# ══════════════════════════════════════════════════════════════

# 表格类型识别：TABLE1/TABLE2 各有独有字段，命中任一即认定；都不命中则为 TABLE3
_TABLE1_MARKERS = {"设计风格", "特色物件", "配色原则"}  # TABLE1 独有
_TABLE2_MARKERS = {"价格区间", "允许物象", "禁止物象"}  # TABLE2 独有

# 表格类型 → TABLE0 中对应的路由字段名
_TABLE_TYPE_FIELDS: dict[str, tuple[str, str]] = {
    "table1": ("archetype_app_token", "archetype_table_id"),
    "table2": ("rules_app_token", "rules_table_id"),
    "table3": ("instance_app_token", "instance_table_id"),
}

# 表格类型的中文名
_TABLE_TYPE_NAMES: dict[str, str] = {
    "table1": "TABLE1（区域原型）",
    "table2": "TABLE2（档位规则）",
    "table3": "TABLE3（参考案例）",
}


# wiki token → bitable app_token 缓存（同一文档只需解析一次）
_wiki_token_cache: dict[str, str] = {}


def _resolve_wiki_token(token: str, wiki_token: str) -> str:
    """将 wiki 节点 token 解析为真正的 bitable app_token。

    wiki URL 中的 token 是节点 ID，需要调用 wiki API 获取实际的 obj_token。
    结果会缓存，同一 wiki 文档下的多个表只需解析一次。
    """
    if wiki_token in _wiki_token_cache:
        return _wiki_token_cache[wiki_token]

    url = f"{_base()}/open-apis/wiki/v2/spaces/get_node"
    params = {"token": wiki_token, "obj_type": "wiki"}
    resp = requests.get(url, headers=_headers(token), params=params)
    body = resp.json()

    if resp.status_code != 200 or body.get("code", -1) != 0:
        code = body.get("code", "?")
        msg = body.get("msg", resp.text[:200])
        logger.error("  wiki API 失败 (HTTP %d, code=%s): %s", resp.status_code, code, msg)
        return ""

    node = body.get("data", {}).get("node", {})
    obj_token = node.get("obj_token", "")
    obj_type = node.get("obj_type", "")
    if obj_token:
        logger.info("  wiki 节点解析: %s -> app_token=%s (type=%s)", wiki_token, obj_token, obj_type)
        _wiki_token_cache[wiki_token] = obj_token
    return obj_token


def parse_feishu_url(auth_token: str, url: str) -> tuple[str, str]:
    """从飞书多维表格 URL 中提取 app_token 和 table_id。

    wiki 类型 URL 会自动调用 wiki API 解析出真正的 bitable app_token。

    支持格式：
      https://xxx.larkoffice.com/wiki/<wiki_token>?table=<table_id>&...
      https://xxx.larkoffice.com/base/<app_token>?table=<table_id>&...
      https://xxx.feishu.cn/wiki/...  或 /base/...

    Returns:
        (app_token, table_id)，解析失败时对应字段为空字符串
    """
    url = url.strip()
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]
    raw_token = path_parts[-1] if path_parts else ""
    # table_id 从 query param 提取
    params = parse_qs(parsed.query)
    table_id = params.get("table", [""])[0]

    # wiki 类型 URL 需要解析节点 token → bitable app_token
    is_wiki = "wiki" in path_parts
    if is_wiki and raw_token:
        app_token = _resolve_wiki_token(auth_token, raw_token)
        if not app_token:
            logger.error("  wiki 节点解析失败: %s", raw_token)
            return "", table_id
        return app_token, table_id

    return raw_token, table_id


def _get_field_names(token: str, app_token: str, table_id: str) -> set[str]:
    """获取表格字段名集合。优先用 fields API，为空时 fallback 到读记录提取。"""
    # 方式1：fields API
    try:
        fields = list_fields(token, app_token, table_id)
        if fields:
            return set(fields.keys())
    except Exception as e:
        logger.warning("  fields API 失败: %s", e)

    # 方式2：读记录，从 record.fields 的 key 中提取字段名
    logger.info("  fields API 返回空，尝试从记录中提取字段名...")
    try:
        records = read_records(token, app_token, table_id)
        names: set[str] = set()
        for item in records:
            names.update(item.get("fields", {}).keys())
        return names
    except Exception as e:
        logger.error("  读取记录也失败: %s", e)
        return set()


def detect_table_type(token: str, app_token: str, table_id: str) -> str:
    """读取表头字段名，自动识别表格类型。

    规则：包含任一 TABLE1 独有字段 → table1，包含任一 TABLE2 独有字段 → table2，
    都不命中 → table3（参考案例表结构多变，作为兜底）。

    Returns:
        "table1" / "table2" / "table3" / "unknown"（无法读取字段时）
    """
    field_names = _get_field_names(token, app_token, table_id)
    if not field_names:
        logger.error("  无法获取任何字段名")
        return "unknown"
    logger.info("  表头字段: %s", sorted(field_names))

    if field_names & _TABLE1_MARKERS:
        return "table1"
    if field_names & _TABLE2_MARKERS:
        return "table2"
    # 都不命中 → TABLE3（参考案例表结构多变，不硬编码特征）
    return "table3"


def update_record(token: str, app_token: str, table_id: str,
                  record_id: str, fields: dict) -> bool:
    """更新一条已有记录（PATCH），返回是否成功。"""
    url = f"{_base()}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    resp = requests.put(url, headers=_headers(token), json={"fields": fields})
    if resp.status_code == 200:
        return True
    detail = resp.json().get("msg", resp.text[:200])
    logger.error("  x 记录更新失败 (%d): %s", resp.status_code, detail)
    return False


def _find_table0_record(token: str, region: str) -> tuple[str, dict] | None:
    """在 TABLE0 中查找指定区域的记录，返回 (record_id, fields) 或 None。"""
    s = get_settings()
    records = read_records(token, s.table0_app_token, s.table0_table_id)
    for item in records:
        raw = item.get("fields", {})
        # 区域字段可能是纯文本或富文本数组
        region_val = extract_text(raw, "区域")
        if region_val == region:
            return item["record_id"], raw
    return None


def _detect_region(token: str, app_token: str, table_id: str) -> str:
    """通过表名获取区域名称。

    同一 wiki 文档下每个区域是一张独立的表，表名即区域名（如 TR、MENA）。
    调用 tables 列表 API，用 table_id 匹配拿到表名。
    """
    url = f"{_base()}/open-apis/bitable/v1/apps/{app_token}/tables"
    try:
        resp = requests.get(url, headers=_headers(token), params={"page_size": 100})
        resp.raise_for_status()
        tables = resp.json().get("data", {}).get("items", [])
    except Exception as e:
        logger.warning("  获取表列表失败: %s", e)
        return ""
    for tbl in tables:
        if tbl.get("table_id") == table_id:
            name = tbl.get("name", "")
            logger.info("  → 表名(区域): %s", name)
            return name
    logger.warning("  在表列表中未找到 table_id=%s", table_id)
    return ""


def _parse_urls_by_region(token: str, urls_text: str
                          ) -> dict[str, dict[str, tuple[str, str]]]:
    """解析 URL 列表，按区域分组，自动识别表类型。

    Returns:
        {region: {table_type: (app_token, table_id)}}
        如 {"TR": {"table2": ("xxx", "tblyyy"), "table3": ("xxx", "tblzzz")}}
    """
    urls = [u.strip() for u in urls_text.split(";") if u.strip()]
    if not urls:
        logger.error("未输入任何 URL")
        sys.exit(1)

    # 结果按区域分组
    by_region: dict[str, dict[str, tuple[str, str]]] = {}

    for url in urls:
        app_token, table_id = parse_feishu_url(token, url)
        if not app_token or not table_id:
            logger.error("  URL 解析失败（缺少 app_token 或 table 参数）: %s", url)
            sys.exit(1)
        logger.info("解析 URL: app_token=%s, table_id=%s", app_token, table_id)

        # 识别表类型
        ttype = detect_table_type(token, app_token, table_id)
        if ttype == "unknown":
            logger.error("  无法识别表格类型，请检查 URL: %s", url)
            sys.exit(1)
        logger.info("  → 识别为 %s", _TABLE_TYPE_NAMES.get(ttype, ttype))

        # 提取区域
        region = _detect_region(token, app_token, table_id)
        if not region:
            logger.error("  → 未能检测到区域，请检查 URL: %s", url)
            sys.exit(1)
        logger.info("  → 区域: %s", region)

        # 按区域归组，同区域同类型重复则报错
        group = by_region.setdefault(region, {})
        if ttype in group:
            logger.error("  区域 '%s' 存在重复的 %s，请检查 URL", region, _TABLE_TYPE_NAMES[ttype])
            sys.exit(1)
        group[ttype] = (app_token, table_id)

    logger.info("共解析 %d 个 URL，涉及 %d 个区域: %s",
                len(urls), len(by_region), list(by_region.keys()))
    return by_region


# ══════════════════════════════════════════════════════════════
# 飞书 Bitable 操作工具
# ══════════════════════════════════════════════════════════════

def _base():
    """获取飞书 API 基地址。"""
    return get_settings().feishu_base_url


def list_fields(token: str, app_token: str, table_id: str) -> dict[str, dict]:
    """列出表格已有字段，返回 {字段名: 字段信息} 字典。"""
    url = f"{_base()}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    resp = requests.get(url, headers=_headers(token))
    resp.raise_for_status()
    fields = resp.json().get("data", {}).get("items", [])
    return {f["field_name"]: f for f in fields}


def read_records(token: str, app_token: str, table_id: str) -> list[dict]:
    """读取表格全部记录。"""
    url = f"{_base()}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    resp = requests.get(url, headers=_headers(token), params={"page_size": 100})
    resp.raise_for_status()
    return resp.json().get("data", {}).get("items", [])


def create_field(token: str, app_token: str, table_id: str, field_name: str) -> bool:
    """创建文本类型字段，返回是否成功。"""
    url = f"{_base()}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    resp = requests.post(url, headers=_headers(token), json={"field_name": field_name, "type": 1})
    ok = resp.status_code == 200
    if ok:
        logger.info("  + 字段已创建: %s", field_name)
    else:
        detail = resp.json().get("msg", resp.text[:120])
        logger.warning("  x 字段创建失败 (%d): %s - %s", resp.status_code, field_name, detail)
    return ok


def create_record(token: str, app_token: str, table_id: str, fields: dict) -> bool:
    """插入一条记录，各字段独立写入。失败时自动降级为 JSON-in-文本 模式。"""
    url = f"{_base()}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    resp = requests.post(url, headers=_headers(token), json={"fields": fields})
    if resp.status_code == 200:
        return True
    # 降级：将全部字段序列化为 JSON 存入「文本」字段
    logger.warning("  正常插入失败，降级为 JSON-in-文本 模式")
    json_str = json.dumps(fields, ensure_ascii=False)
    resp2 = requests.post(url, headers=_headers(token), json={"fields": {"文本": json_str}})
    if resp2.status_code == 200:
        logger.info("  + 记录已插入（降级模式）")
        return True
    logger.error("  x 记录插入失败: %s", resp2.json().get("msg", resp2.text[:120]))
    return False


# ══════════════════════════════════════════════════════════════
# 单表初始化逻辑
# ══════════════════════════════════════════════════════════════

def setup_table(
    token: str,
    name: str,
    app_token: str,
    table_id: str,
    field_names: list[str],
    seed_data: list[dict],
    dry_run: bool = True,
) -> None:
    """初始化单张表格：检查现有状态 → 创建缺失字段 → 插入种子记录。

    Args:
        dry_run: True 时仅预览，不执行写入
    """
    logger.info("=" * 56)
    logger.info("[%s] app_token=%s, table_id=%s", name, app_token, table_id)

    # 1. 检查已有字段
    existing_fields = list_fields(token, app_token, table_id)
    logger.info("  已有字段: %s", list(existing_fields.keys()))
    missing_fields = [f for f in field_names if f not in existing_fields]
    if missing_fields:
        logger.info("  缺失字段: %s", missing_fields)
    else:
        logger.info("  所有字段已存在")

    # 2. 检查已有记录
    existing_records = read_records(token, app_token, table_id)
    logger.info("  已有记录: %d 条", len(existing_records))
    for item in existing_records:
        raw = item.get("fields", {})
        label = extract_text(raw, "文本")
        logger.info("    %s: %s", item["record_id"], label or "(空)")

    # 3. 预览或执行
    if dry_run:
        logger.info("  [预览] 将创建 %d 个字段, 插入 %d 条记录", len(missing_fields), len(seed_data))
        for rec in seed_data:
            logger.info("    待插入: %s", rec.get("文本", "(无标签)"))
        return

    # 创建缺失字段
    logger.info("  [1/2] 创建字段...")
    for fname in missing_fields:
        create_field(token, app_token, table_id, fname)

    # 插入种子记录
    logger.info("  [2/2] 插入 %d 条记录...", len(seed_data))
    for i, rec in enumerate(seed_data, 1):
        ok = create_record(token, app_token, table_id, rec)
        if ok:
            logger.info("    + 记录 %d/%d: %s", i, len(seed_data), rec.get("文本", ""))

    logger.info("  [%s] 初始化完成", name)


# ══════════════════════════════════════════════════════════════
# 交互式路由管理：route
# ══════════════════════════════════════════════════════════════

def _build_routing_fields(detected: dict[str, tuple[str, str]]) -> dict[str, str]:
    """将检测结果转换为 TABLE0 字段格式。"""
    fields: dict[str, str] = {}
    for ttype, (app_token, table_id) in detected.items():
        app_key, id_key = _TABLE_TYPE_FIELDS[ttype]
        fields[app_key] = app_token
        fields[id_key] = table_id
    return fields


def route_command():
    """交互式更新 TABLE0 路由。

    流程：
      1. 提示用户粘贴飞书表格 URL（; 分隔，支持多区域混合）
      2. 自动识别每个 URL 的表类型和区域，按区域分组
      3. 逐个区域查找 TABLE0 → 找到则更新，未找到则报错
    """
    token = get_token()
    s = get_settings()

    urls_text = input("请输入飞书表格 URL（多个用 ; 隔开）: ").strip()
    by_region = _parse_urls_by_region(token, urls_text)

    # 预查找所有区域的 TABLE0 记录
    errors = []
    region_records: dict[str, tuple[str, dict]] = {}  # {region: (record_id, fields)}
    for region in by_region:
        found = _find_table0_record(token, region)
        if not found:
            errors.append(region)
        else:
            region_records[region] = found
    if errors:
        logger.error("以下区域在 TABLE0 中不存在: %s，请先添加", errors)
        sys.exit(1)

    # 预览所有变更
    logger.info("=" * 56)
    for region, detected in by_region.items():
        record_id, existing_raw = region_records[region]
        logger.info("[%s] (record_id=%s)", region, record_id)
        for ttype in ("table1", "table2", "table3"):
            if ttype not in detected:
                continue
            app_key, id_key = _TABLE_TYPE_FIELDS[ttype]
            old_app = extract_text(existing_raw, app_key) or "(空)"
            old_id = extract_text(existing_raw, id_key) or "(空)"
            new_app, new_id = detected[ttype]
            logger.info("  %s:", _TABLE_TYPE_NAMES[ttype])
            logger.info("    app_token: %s → %s", old_app, new_app)
            logger.info("    table_id:  %s → %s", old_id, new_id)
    logger.info("=" * 56)

    confirm = input(f"确认更新以上 {len(by_region)} 个区域？[y/N]: ").strip().lower()
    if confirm != "y":
        logger.info("已取消")
        return

    # 逐个区域写入
    for region, detected in by_region.items():
        record_id, _ = region_records[region]
        update_fields = _build_routing_fields(detected)
        ok = update_record(token, s.table0_app_token, s.table0_table_id, record_id, update_fields)
        if ok:
            logger.info("  ✓ 区域 '%s' 路由已更新", region)
        else:
            logger.error("  ✗ 区域 '%s' 更新失败", region)


# ══════════════════════════════════════════════════════════════
# 种子数据初始化：apply / preview
# ══════════════════════════════════════════════════════════════

def setup_seed(args: list[str], dry_run: bool):
    """按种子数据初始化指定表格（原 apply/preview 逻辑）。"""
    # 如果参数以 table 开头，说明省略了模式
    table_filter = {a.lower() for a in args if a.lower().startswith("table")}

    s = get_settings()
    all_tables = {
        "table0": ("TABLE0 (路由表)",   s.table0_app_token, s.table0_table_id, TABLE0_FIELDS, TABLE0_SEED),
        "table1": ("TABLE1 (区域原型)", s.table1_app_token, s.table1_table_id, TABLE1_FIELDS, TABLE1_SEED),
        "table2": ("TABLE2 (档位规则)", s.table2_app_token, s.table2_table_id, TABLE2_FIELDS, TABLE2_SEED),
    }

    if table_filter:
        unknown = table_filter - all_tables.keys()
        if unknown:
            logger.error("未知的表名: %s（可选: %s）", unknown, list(all_tables.keys()))
            sys.exit(1)
        targets = {k: v for k, v in all_tables.items() if k in table_filter}
    else:
        targets = all_tables

    target_names = [v[0] for v in targets.values()]
    if dry_run:
        logger.info("预览模式（只读）。目标: %s", " + ".join(target_names))
        logger.info("执行写入请运行: python3 setup_tables.py apply %s",
                     " ".join(targets.keys()))
    else:
        logger.info("执行模式：将创建字段并插入数据。目标: %s", " + ".join(target_names))

    token = get_token()
    for key, (name, app_token, table_id, fields, seed) in targets.items():
        setup_table(token, name=name, app_token=app_token, table_id=table_id,
                    field_names=fields, seed_data=seed, dry_run=dry_run)

    logger.info("=" * 56)
    if dry_run:
        logger.info("预览完成。确认无误后运行: python3 setup_tables.py apply %s",
                     " ".join(targets.keys()))
    else:
        logger.info("初始化完成! %s 已配置。", " + ".join(target_names))


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

_USAGE = """
用法:
  python3 setup_tables.py                       预览全部种子数据（只读）
  python3 setup_tables.py apply [table0|1|2]    写入种子数据（可指定表）
  python3 setup_tables.py route                 交互式更新 TABLE0 路由（粘贴 URL 自动识别区域和表类型）
""".strip()


def main():
    """统一入口：根据子命令分发到对应逻辑。"""
    args = sys.argv[1:]
    cmd = args[0].lower() if args else "preview"

    if cmd == "route":
        route_command()
    elif cmd == "apply":
        setup_seed(args[1:], dry_run=False)
    elif cmd in ("preview", "help", "-h", "--help"):
        if cmd in ("help", "-h", "--help"):
            print(_USAGE)
            return
        setup_seed(args[1:], dry_run=True)
    elif cmd.startswith("table"):
        # 省略模式直接写表名，默认 preview
        setup_seed(args, dry_run=True)
    else:
        print(f"未知命令: {cmd}")
        print(_USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
