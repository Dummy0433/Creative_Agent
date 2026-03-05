"""主编排器：generate(config) -> PipelineResult，串联整个生成流程。"""

import json
import logging

import feishu
from models import GenerationConfig, MediaType, PipelineResult
from providers import get_image_provider, get_text_provider
from settings import get_settings

from pipeline.context import get_analyze_system, get_prompt_gen_system, build_context, format_instances
from pipeline.data import download_instance_images, query_instances, query_region_info, query_tier_rules, resolve_routing
from pipeline.postprocess import build_postprocess_chain
from pipeline.subject import validate_subject

logger = logging.getLogger(__name__)

# 档位字段名（双语兼容），与 data.py 保持一致
_TIER_KEYS = ("价格层级", "tier", "Tier", "price_tier")


def _log_dict(label: str, data: dict, rid: str) -> None:
    """以可读格式打印字典内容到 INFO 日志，带 request_id 前缀。"""
    logger.info("[%s]   %s:", rid, label)
    for k, v in data.items():
        logger.info("[%s]     %s: %s", rid, k, v)


def generate(config: GenerationConfig) -> PipelineResult:
    """执行完整的礼物生成流程（顶层容错）。

    始终返回 PipelineResult，异常时 status="error" 并携带错误信息。
    """
    rid = config.request_id
    try:
        return _generate_inner(config)
    except Exception as e:
        logger.error("[%s] Pipeline 异常终止: %s", rid, e, exc_info=True)
        return PipelineResult(
            subject_final=config.subject,
            tier="?",
            prompt="",
            english_prompt="",
            status="error",
            error_message=str(e),
            request_id=rid,
        )


def _generate_inner(config: GenerationConfig) -> PipelineResult:
    """Pipeline 核心逻辑，允许异常上抛由 generate() 捕获。

    流程：解析配置 → 认证 → 查询区域信息 → 查询档位规则 → 主体校验
        → 查询参考案例 → 结构化分析 → 提示词生成 → 图片生成
        → 后处理 → 发送到飞书
    """
    s = get_settings()       # 仅读凭证/表格地址
    cfg = config.resolve()   # 生成参数从 cfg 读
    rid = cfg.request_id

    region = cfg.region
    subject = cfg.subject
    price = cfg.price

    logger.info("[%s] %s", rid, "=" * 56)
    logger.info("[%s] 礼物生成 Pipeline", rid)
    logger.info("[%s]   区域=%s, 主体=%s, 价格=%s", rid, region, subject, price)
    logger.info("[%s]   模型: analyze=%s, prompt=%s, image=%s",
                rid, cfg.analyze_model, cfg.prompt_model, cfg.image_models)
    logger.info("[%s]   图片: %s, %s", rid, cfg.image_aspect_ratio, cfg.image_size)
    logger.info("[%s] %s", rid, "=" * 56)

    # 步骤1: 飞书认证
    logger.info("[%s] [步骤1] 正在认证...", rid)
    token = feishu.get_token()
    receive_id = s.feishu_receive_id

    # 步骤1.5: TABLE0 路由解析（区域 → 各表格物理地址）
    logger.info("[%s] [步骤1.5] 正在解析路由...", rid)
    routing = resolve_routing(token, region)
    logger.info("[%s]   TABLE1: %s/%s", rid, routing.archetype_app_token, routing.archetype_table_id)
    logger.info("[%s]   TABLE2: %s/%s", rid, routing.rules_app_token, routing.rules_table_id)
    logger.info("[%s]   TABLE3: %s/%s", rid, routing.instance_app_token, routing.instance_table_id)

    # 步骤2: 查询 TABLE1（区域原型），获取设计风格、特色物件等
    region_info = query_region_info(token, region, routing=routing)
    logger.info("[%s] [步骤2] TABLE1(区域原型) 查询结果:", rid)
    _log_dict("区域信息", region_info, rid)

    # 步骤3: 查询 TABLE2（档位规则），根据价格匹配档位
    tier_rules = query_tier_rules(token, region, price, routing=routing)
    tier = next((tier_rules[k] for k in _TIER_KEYS if tier_rules.get(k)), "?")
    logger.info("[%s] [步骤3] TABLE2(档位规则) 价格=%d -> 档位=%s", rid, price, tier)
    _log_dict("档位规则", tier_rules, rid)

    # 步骤4: 主体校验（被禁止的主体会被容器包裹）
    logger.info("[%s] [步骤4] 正在校验主体 '%s'...", rid, subject)
    subject_final = validate_subject(subject, tier_rules, region_info)
    if subject_final == subject:
        logger.info("[%s]   主体 '%s' 在档位 %s 允许使用", rid, subject, tier)
    else:
        logger.info("[%s]   主体已变更: '%s' -> '%s'", rid, subject, subject_final)

    # 步骤5: 查询 TABLE3（参考案例），按同价格档位随机抽取
    instances = query_instances(token, region, price=price, limit=3, routing=routing)
    logger.info("[%s] [步骤5] TABLE3(参考案例) 查询结果:", rid)
    for i, inst in enumerate(instances, 1):
        _log_dict(f"案例{i}", inst, rid)

    # 步骤5.1: 下载参考图片
    ref_images = download_instance_images(token, instances)
    logger.info("[%s] [步骤5.1] 下载了 %d 张参考图片", rid, len(ref_images))
    for i, img in enumerate(ref_images, 1):
        logger.info("[%s]   参考图%d: %d 字节", rid, i, len(img))

    # 步骤5.5: 组装 LLM 上下文
    text_provider = get_text_provider(timeout=cfg.text_timeout)
    context = build_context(region_info, tier_rules)
    examples = format_instances(instances)
    user_input = (
        f"{context}\n\n{examples}\n\n"
        f"## 用户输入\nregion: {region}, subject: {subject_final}, price: {price} coins"
    )
    logger.info("[%s] [步骤5.5] 组装后的 LLM 上下文:", rid)
    logger.info("[%s] %s", rid, user_input)

    # 步骤6: LLM 结构化分析，输出设计要素 JSON
    logger.info("[%s] [步骤6] 正在结构化分析...", rid)
    analyze_system = get_analyze_system(cfg.analyze_system_prompt)
    logger.info("[%s]   analyze 系统提示词:\n%s", rid, analyze_system)
    try:
        structured = text_provider.generate(
            cfg.analyze_model,
            analyze_system,
            user_input,
        )
    except Exception as e:
        raise RuntimeError(f"结构化分析失败 (model={cfg.analyze_model}): {e}") from e
    logger.info("[%s] [步骤6] 结构化分析 JSON 结果:", rid)
    logger.info("[%s] %s", rid, json.dumps(structured, ensure_ascii=False, indent=2))

    # 步骤7: LLM 提示词生成，将结构化 JSON 转为中英文提示词
    logger.info("[%s] [步骤7] 正在生成提示词...", rid)
    prompt_gen_system = get_prompt_gen_system(cfg.prompt_gen_system_prompt)
    logger.info("[%s]   prompt_gen 系统提示词:\n%s", rid, prompt_gen_system)
    prompt_input = f"请将以下结构化JSON转换为图片生成提示词：\n{json.dumps(structured, ensure_ascii=False)}"
    logger.info("[%s]   prompt_gen 用户输入:\n%s", rid, prompt_input)
    try:
        prompts = text_provider.generate(
            cfg.prompt_model,
            prompt_gen_system,
            prompt_input,
        )
    except Exception as e:
        raise RuntimeError(f"提示词生成失败 (model={cfg.prompt_model}): {e}") from e
    logger.info("[%s] [步骤7] 提示词生成结果:", rid)
    logger.info("[%s]   中文提示词: %s", rid, prompts.get('prompt', ''))
    logger.info("[%s]   英文提示词: %s", rid, prompts.get('english_prompt', ''))

    # 步骤8: 调用图片生成模型
    logger.info("[%s] [步骤8] 正在生成图片...", rid)
    image_provider = get_image_provider(
        name=cfg.image_provider,
        models=cfg.image_models,
        aspect_ratio=cfg.image_aspect_ratio,
        image_size=cfg.image_size,
        timeout=cfg.image_timeout,
    )
    try:
        image_bytes = image_provider.generate(prompts["english_prompt"], reference_images=ref_images or None)
    except Exception as e:
        raise RuntimeError(f"图片生成失败 (models={cfg.image_models}): {e}") from e
    logger.info("[%s]   图片已生成: %d 字节", rid, len(image_bytes))

    # 组装结果对象
    result = PipelineResult(
        subject_final=subject_final,
        tier=tier,
        prompt=prompts["prompt"],
        english_prompt=prompts["english_prompt"],
        media_type=MediaType.IMAGE,
        status="generated",
        request_id=rid,
        media_bytes=image_bytes,
    )

    # 后处理（保存图片到本地等）
    if cfg.enable_postprocess:
        for processor in build_postprocess_chain(tier):
            result = processor.process(result)
    if result.local_path:
        logger.info("[%s] [步骤8] 图片已保存: %s", rid, result.local_path)

    # 步骤9: 上传图片并发送到飞书（单独 try/except，发送失败不丢弃已生成的图片）
    try:
        logger.info("[%s] [步骤9] 正在发送到飞书...", rid)
        if result.media_type == MediaType.IMAGE and result.media_bytes:
            image_key = feishu.upload_image(token, result.media_bytes)
            logger.info("[%s]   图片已上传: %s", rid, image_key)
            result.image_key = image_key

            # 构造描述文字
            caption = (
                f"[Gift Generation] {region} | {subject_final} | {price} coins\n\n"
                f"Prompt: {prompts['prompt']}"
            )
            msg_id = feishu.send_image(token, receive_id, image_key)
            logger.info("[%s]   图片消息已发送: %s", rid, msg_id)
            result.message_id = msg_id
            feishu.send_text(token, receive_id, caption)
            logger.info("[%s]   描述已发送", rid)

        result.status = "sent_to_feishu"
    except Exception as e:
        logger.error("[%s] 飞书发送失败（图片已生成）: %s", rid, e, exc_info=True)
        result.status = "generated_but_send_failed"
        result.error_message = f"飞书发送失败: {e}"

    # ── 最终汇总 ─────────────────────────────────────────────
    logger.info("[%s] %s", rid, "=" * 56)
    logger.info("[%s] Pipeline 完成! 汇总:", rid)
    logger.info("[%s]   主体: %s -> %s", rid, subject, subject_final)
    logger.info("[%s]   档位: %s", rid, tier)
    logger.info("[%s]   中文提示词: %s", rid, result.prompt)
    logger.info("[%s]   英文提示词: %s", rid, result.english_prompt)
    if result.local_path:
        logger.info("[%s]   本地图片: %s", rid, result.local_path)
    if result.image_key:
        logger.info("[%s]   飞书图片: %s", rid, result.image_key)
    if result.message_id:
        logger.info("[%s]   飞书消息: %s", rid, result.message_id)
    logger.info("[%s] %s", rid, "=" * 56)
    return result
