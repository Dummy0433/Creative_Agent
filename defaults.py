"""管理员默认值加载器：从 generation_defaults.yaml 读取生成参数默认值。"""

from functools import lru_cache
from pathlib import Path

import yaml

_DEFAULTS_PATH = Path(__file__).resolve().parent / "generation_defaults.yaml"


@lru_cache
def load_defaults() -> dict:
    """加载 generation_defaults.yaml（进程启动时缓存）。"""
    return yaml.safe_load(_DEFAULTS_PATH.read_text(encoding="utf-8"))
