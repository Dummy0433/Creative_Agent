"""主体分类与校验：根据关键词判断类别，结合档位规则决定是否需要容器包裹。"""

import logging
import random

logger = logging.getLogger(__name__)

# ── 主体分类关键词 ───────────────────────────────────────────
# 用于将用户输入的主体归类为「动物」「植物」「地貌」

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


def classify_subject(subject: str) -> set[str]:
    """根据关键词匹配，返回主体所属类别集合（可能同时属于多个类别）。"""
    cats: set[str] = set()
    # 检查是否包含动物关键词
    for kw in ANIMAL_KW:
        if kw in subject:
            cats.add("动物")
            break
    # 检查是否包含植物关键词
    for kw in PLANT_KW:
        if kw in subject:
            cats.add("植物")
            break
    # 检查是否包含地貌关键词
    for kw in LANDSCAPE_KW:
        if kw in subject:
            cats.add("地貌")
            break
    return cats


def validate_subject(subject: str, tier_rules: dict, region_info: dict) -> str:
    """校验主体是否在当前档位被禁止，若被禁止则用容器包裹。

    Args:
        subject: 用户输入的主体名称
        tier_rules: 当前档位规则（包含「禁止物象」「容器备选」等字段）
        region_info: 区域信息（预留扩展用）

    Returns:
        校验后的主体名称（可能被容器包裹，如「雄狮徽章」）
    """
    forbidden = tier_rules.get("禁止物象", "")
    containers_str = tier_rules.get("容器备选", "")

    # 无禁止规则时直接放行
    if not forbidden or forbidden in ("无", "无特殊限制"):
        return subject

    # 判断主体类别是否在禁止列表中
    cats = classify_subject(subject)
    is_forbidden = any(c in forbidden for c in cats)

    # 被禁止且有容器可选时，随机选一个容器包裹
    if is_forbidden and containers_str and containers_str != "无需容器":
        containers = [c.strip() for c in containers_str.split("/") if c.strip()]
        if containers:
            container = random.choice(containers)
            result = f"{subject}{container}"
            logger.info("  >> 主体 '%s' (分类: %s) 在该档位被禁止", subject, cats)
            logger.info("  >> 已转换为: '%s' (容器: %s)", result, container)
            return result

    return subject
