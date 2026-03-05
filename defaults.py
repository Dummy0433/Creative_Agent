"""管理员默认值加载器：从 generation_defaults.yaml 读取生成参数默认值。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_DEFAULTS_PATH = Path(__file__).resolve().parent / "generation_defaults.yaml"


@lru_cache
def load_defaults() -> "GenerationDefaults":
    """加载 generation_defaults.yaml 并解析为 GenerationDefaults 模型（进程启动时缓存）。"""
    from models import GenerationDefaults  # 延迟导入，避免循环引用
    raw = yaml.safe_load(_DEFAULTS_PATH.read_text(encoding="utf-8"))
    return GenerationDefaults(**raw)
