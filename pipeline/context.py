"""System prompts and context builders."""

# ── System prompts (domain logic, not configuration) ────────
ANALYZE_SYSTEM = """你是专业的TikTok礼物设计 Prompt 工程师。
根据用户输入和设计规范，输出结构化 JSON。

## 通用禁忌（所有区域）
- 严禁：政治/宗教娱乐化/丧葬/色情/血腥暴力/歧视
- 严禁：未经授权的IP与品牌
- 禁止：王冠/奖杯/龙/私人飞机等"尊贵"锚点
- 禁止：低幼元素（婴儿/校车/棒棒糖）
- 不得遮挡主播面部

## 输出格式（严格JSON）
{
  "subject_final": "最终主体描述",
  "color_palette": "配色自然语言描述",
  "material": "材质描述",
  "background": "背景描述",
  "region_style": "区域风格描述",
  "pattern": "yes/none"
}"""

PROMPT_GEN_SYSTEM = """你是专业图片提示词生成师。
将结构化JSON转换为适合图片生成模型的单行提示词。

固定开头：保证高质量 C4D OCTANE 卡通渲染的风格，视觉重心指向右方，
整体呈三分之二正面视角（约30°-40°俯视），主体占比整体画面的95%，
主体居中且呈现完整造型非局部造型，画面背景为纯黑色的纯色块背景便于抠图。

输出严格JSON：
{
  "prompt": "完整中文提示词",
  "english_prompt": "Complete English prompt"
}"""


def build_context(region_info: dict, tier_rules: dict) -> str:
    parts = ["## 区域通用信息"]
    for k in ["设计风格", "特色物件", "特色图案", "配色原则", "主材质", "禁忌"]:
        if region_info.get(k):
            parts.append(f"- {k}: {region_info[k]}")
    parts.append("\n## 档位规则")
    for k in ["允许物象", "禁止物象", "场景要求", "视觉质感", "容器备选", "价格区间"]:
        if tier_rules.get(k):
            parts.append(f"- {k}: {tier_rules[k]}")
    return "\n".join(parts)


def format_instances(instances: list[dict]) -> str:
    if not instances:
        return "暂无参考案例。"
    lines = ["## 参考案例"]
    for i, inst in enumerate(instances, 1):
        name = inst.get("Resource Name", inst.get("名称", f"案例{i}"))
        desc = inst.get("设计理念", "")
        style = inst.get("风格", "")
        mat = inst.get("材质", "")
        obj = inst.get("物象 II", inst.get("物象II", ""))
        lines.append(f"{i}. {name} (风格:{style}, 材质:{mat}, 物象:{obj}): {desc}")
    return "\n".join(lines)
