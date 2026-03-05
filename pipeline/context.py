"""系统提示词与上下文构建器：为 LLM 调用组装输入。"""

from functools import lru_cache
from pathlib import Path

# ── 提示词文件目录 ────────────────────────────────────────
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache
def _load_prompt(filename: str) -> str:
    """从 prompts/ 目录加载提示词文件，结果缓存避免重复读取。"""
    path = _PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8").strip()


def get_analyze_system(override: str | None = None, tier_file: str | None = None) -> str:
    """获取结构化分析的系统提示词。优先级：override > tier_file > 默认文件。"""
    if override:
        return override
    if tier_file:
        return _load_prompt(tier_file)
    return _load_prompt("analyze_system.md")


def get_prompt_gen_system(override: str | None = None, tier_file: str | None = None) -> str:
    """获取提示词扩写的系统提示词。优先级：override > tier_file > 默认文件。"""
    if override:
        return override
    if tier_file:
        return _load_prompt(tier_file)
    return _load_prompt("prompt_gen_system.md")


def build_context(region_info: dict, tier_rules: dict) -> str:
    """将区域信息和档位规则组装为 LLM 可读的上下文文本。"""
    # 区域通用信息部分
    parts = ["## 区域通用信息"]
    for k in ["设计风格", "特色物件", "特色图案", "配色原则", "主材质", "禁忌"]:
        if region_info.get(k):
            parts.append(f"- {k}: {region_info[k]}")

    # 档位规则部分
    parts.append("\n## 档位规则")
    for k in ["允许物象", "禁止物象", "场景要求", "视觉质感", "容器备选", "价格区间"]:
        if tier_rules.get(k):
            parts.append(f"- {k}: {tier_rules[k]}")

    return "\n".join(parts)


def format_instances(instances: list[dict]) -> str:
    """将参考案例格式化为 LLM 可读的 few-shot 示例文本。"""
    if not instances:
        return "暂无参考案例。"

    lines = ["## 参考案例"]
    for i, inst in enumerate(instances, 1):
        # 兼容中英文字段名
        name = inst.get("Resource Name", inst.get("名称", f"案例{i}"))
        desc = inst.get("设计理念", "")
        style = inst.get("风格", "")
        mat = inst.get("材质", "")
        obj = inst.get("物象 II", inst.get("物象II", ""))
        lines.append(f"{i}. {name} (风格:{style}, 材质:{mat}, 物象:{obj}): {desc}")

    return "\n".join(lines)
