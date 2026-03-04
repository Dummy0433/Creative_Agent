"""Tier detection, subject classification, and validation constants."""

import random

# ── Tier boundaries ──────────────────────────────────────────
TIER_BOUNDARIES = [
    (99, "T0"), (999, "T1"), (2999, "T2"), (8999, "T3"), (29999, "T4"),
]

# ── Subject classification keywords ─────────────────────────
ANIMAL_KW = [
    "狮", "虎", "豹", "熊", "猫", "狗", "马", "鹰", "猎鹰", "骆驼", "鹿",
    "兔", "蛇", "鸟", "鱼", "象", "猴", "牛", "羊", "鸡", "猪", "鲨",
]
PLANT_KW = [
    "树", "花", "草", "棕榈", "玫瑰", "橄榄", "石榴", "无花果", "叶", "枝", "竹", "兰",
]
LANDSCAPE_KW = [
    "沙漠", "绿洲", "山脉", "大海", "落日", "日出", "湖", "河流", "瀑布", "冰川",
]


def detect_tier(price: int) -> str:
    for boundary, tier in TIER_BOUNDARIES:
        if price <= boundary:
            return tier
    return "T4"


def classify_subject(subject: str) -> set[str]:
    cats: set[str] = set()
    for kw in ANIMAL_KW:
        if kw in subject:
            cats.add("动物")
            break
    for kw in PLANT_KW:
        if kw in subject:
            cats.add("植物")
            break
    for kw in LANDSCAPE_KW:
        if kw in subject:
            cats.add("地貌")
            break
    return cats


def validate_subject(subject: str, tier_rules: dict, region_info: dict) -> str:
    forbidden = tier_rules.get("禁止物象", "")
    containers_str = tier_rules.get("容器备选", "")
    if not forbidden or forbidden in ("无", "无特殊限制"):
        return subject
    cats = classify_subject(subject)
    is_forbidden = any(c in forbidden for c in cats)
    if is_forbidden and containers_str and containers_str != "无需容器":
        containers = [c.strip() for c in containers_str.split("/") if c.strip()]
        if containers:
            container = random.choice(containers)
            result = f"{subject}{container}"
            print(f"  >> Subject '{subject}' (categories: {cats}) is forbidden at this tier")
            print(f"  >> Converted to: '{result}' (container: {container})")
            return result
    return subject
