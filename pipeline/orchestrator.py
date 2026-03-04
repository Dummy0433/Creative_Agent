"""主编排器：generate(region, subject, price) -> PipelineResult，串联整个生成流程。"""

import json
import logging

import feishu
from models import MediaType, PipelineResult
from providers import get_image_provider, get_text_provider
from settings import get_settings

from pipeline.context import ANALYZE_SYSTEM, PROMPT_GEN_SYSTEM, build_context, format_instances
from pipeline.data import query_instances, query_region_info, query_tier_rules
from pipeline.postprocess import build_postprocess_chain
from pipeline.subject import validate_subject

logger = logging.getLogger(__name__)

# 档位字段名（双语兼容），与 data.py 保持一致
_TIER_KEYS = ("价格层级", "tier", "Tier", "price_tier")


def generate(region: str, subject: str, price: int) -> PipelineResult:
    """执行完整的礼物生成流程。

    流程：认证 → 查询区域信息 → 查询档位规则 → 主体校验
        → 查询参考案例 → 结构化分析 → 提示词生成 → 图片生成
        → 后处理 → 发送到飞书
    """
    s = get_settings()

    logger.info("=" * 60)
    logger.info("礼物生成 Pipeline")
    logger.info("  区域=%s, 主体=%s, 价格=%s", region, subject, price)
    logger.info("=" * 60)

    # 步骤1: 飞书认证
    logger.info("[步骤1] 正在认证...")
    token = feishu.get_token()
    receive_id = s.feishu_receive_id

    # 步骤2: 查询 TABLE1（区域原型），获取设计风格、特色物件等
    region_info = query_region_info(token, region)
    logger.debug("  区域信息: %s", region_info)

    # 步骤3: 查询 TABLE2（档位规则），根据价格匹配档位
    tier_rules = query_tier_rules(token, region, price)
    tier = next((tier_rules[k] for k in _TIER_KEYS if tier_rules.get(k)), "?")
    logger.info("[步骤3] 价格=%d -> 档位=%s", price, tier)
    logger.debug("  档位规则: %s", tier_rules)

    # 步骤4: 主体校验（被禁止的主体会被容器包裹）
    logger.info("[步骤4] 正在校验主体 '%s'...", subject)
    subject_final = validate_subject(subject, tier_rules, region_info)
    if subject_final == subject:
        logger.info("  主体 '%s' 在档位 %s 允许使用", subject, tier)

    # 步骤5: 查询 TABLE3（参考案例），用作 few-shot 示例
    instances = query_instances(token, region, limit=3)
    logger.debug("  参考案例: %s", instances)

    # 步骤6: LLM 结构化分析，输出设计要素 JSON
    logger.info("[步骤6] 正在结构化分析...")
    text_provider = get_text_provider()
    context = build_context(region_info, tier_rules)
    examples = format_instances(instances)
    user_input = (
        f"{context}\n\n{examples}\n\n"
        f"## 用户输入\nregion: {region}, subject: {subject_final}, price: {price} coins"
    )
    logger.debug("  用户输入:\n%s", user_input)
    structured = text_provider.generate(s.text_model, ANALYZE_SYSTEM, user_input)
    logger.info("  结构化 JSON:")
    for k, v in structured.items():
        logger.info("    %s: %s", k, v)

    # 步骤7: LLM 提示词生成，将结构化 JSON 转为中英文提示词
    logger.info("[步骤7] 正在生成提示词...")
    prompt_input = f"请将以下结构化JSON转换为图片生成提示词：\n{json.dumps(structured, ensure_ascii=False)}"
    logger.debug("  提示词输入:\n%s", prompt_input)
    prompts = text_provider.generate(s.text_model, PROMPT_GEN_SYSTEM, prompt_input)
    logger.info("  中文提示词: %s...", prompts.get('prompt', '')[:80])
    logger.info("  英文提示词: %s...", prompts.get('english_prompt', '')[:80])

    # 步骤8: 调用图片生成模型
    logger.info("[步骤8] 正在生成图片...")
    image_provider = get_image_provider()
    image_bytes = image_provider.generate(prompts["english_prompt"])
    logger.info("  图片已生成: %d 字节", len(image_bytes))

    # 组装结果对象
    result = PipelineResult(
        subject_final=subject_final,
        tier=tier,
        prompt=prompts["prompt"],
        english_prompt=prompts["english_prompt"],
        media_type=MediaType.IMAGE,
        status="generated",
        media_bytes=image_bytes,
    )

    # 后处理（保存图片到本地等）
    if s.enable_postprocess:
        for processor in build_postprocess_chain(tier):
            result = processor.process(result)

    # 步骤9: 上传图片并发送到飞书
    logger.info("[步骤9] 正在发送到飞书...")
    if result.media_type == MediaType.IMAGE and result.media_bytes:
        image_key = feishu.upload_image(token, result.media_bytes)
        logger.info("  图片已上传: %s", image_key)
        result.image_key = image_key

        # 构造描述文字
        caption = (
            f"[Gift Generation] {region} | {subject_final} | {price} coins\n\n"
            f"Prompt: {prompts['prompt']}"
        )
        msg_id = feishu.send_image(token, receive_id, image_key)
        logger.info("  图片消息已发送: %s", msg_id)
        result.message_id = msg_id
        feishu.send_text(token, receive_id, caption)
        logger.info("  描述已发送")

    result.status = "sent_to_feishu"

    logger.info("=" * 60)
    logger.info("完成!")
    logger.debug(result.model_dump_json(indent=2))
    logger.info("=" * 60)
    return result
