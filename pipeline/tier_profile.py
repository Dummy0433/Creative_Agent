"""层级配置加载与合并：从 YAML 读取 TierProfile，覆盖 ResolvedConfig。"""

from __future__ import annotations

import logging

from defaults import load_defaults
from models import ResolvedConfig, TierProfile

logger = logging.getLogger(__name__)


def load_tier_profile(tier: str) -> TierProfile | None:
    """从 generation_defaults.yaml 加载指定层级的配置。

    未配置的层级返回 None。
    """
    d = load_defaults()
    profile = d.tier_profiles.get(tier)
    if profile:
        logger.info("[层级] 已加载 TierProfile: %s", tier)
    else:
        logger.info("[层级] 未找到 TierProfile: %s，使用全局默认", tier)
    return profile


def apply_tier_profile(cfg: ResolvedConfig, profile: TierProfile) -> ResolvedConfig:
    """用层级配置覆盖 ResolvedConfig 中的可选参数。

    TierProfile 中为 None 的字段保持 cfg 原值不变。
    返回新的 ResolvedConfig 实例（不修改原对象）。
    """
    overrides = {}
    if profile.image_models is not None:
        overrides["image_models"] = profile.image_models
    if profile.image_size is not None:
        overrides["image_size"] = profile.image_size
    if profile.image_aspect_ratio is not None:
        overrides["image_aspect_ratio"] = profile.image_aspect_ratio
    if overrides:
        logger.info("[层级] 参数覆盖: %s", overrides)
    return cfg.model_copy(update=overrides)
