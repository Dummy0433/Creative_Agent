"""主编排器：两阶段生成流程（async）。

Phase 1 — generate_candidates(): 数据查询 → LLM 分析 → 4x 并行生图 → 暂存候选
Phase 2 — finalize_selected():   取回选中图 → 后处理 → 发飞书
兼容入口 — generate():            Phase 1 → auto-select #0 → Phase 2
"""

import asyncio
import json
import logging
import time
from uuid import uuid4
from functools import partial

import feishu
from models import CandidateResult, GenerationConfig, MediaType, PipelineResult
from providers import get_image_provider, get_text_provider
from settings import get_settings

from pipeline.candidate_store import save as store_candidate, get as get_candidate
from pipeline.context import get_analyze_system, get_prompt_gen_system, build_context, format_instances
from pipeline.data import download_instance_images, query_instances, query_region_info, query_tier_rules, resolve_routing
from pipeline.postprocess import build_postprocess_chain, matting_and_composite
from pipeline.subject import validate_subject
from pipeline.tier_profile import load_tier_profile, apply_tier_profile

logger = logging.getLogger(__name__)

# 档位字段名（双语兼容），与 data.py 保持一致
_TIER_KEYS = ("价格层级", "tier", "Tier", "price_tier")


def _log_dict(label: str, data: dict, rid: str) -> None:
    """以可读格式打印字典内容到 DEBUG 日志，带 request_id 前缀。"""
    logger.debug("[%s]   %s:", rid, label)
    for k, v in data.items():
        logger.debug("[%s]     %s: %s", rid, k, v)


# ── Phase 1 ────────────────────────────────────────────────


async def generate_candidates(config: GenerationConfig) -> CandidateResult:
    """Phase 1: 数据查询 → LLM 分析 → 4x 并行生图 → 暂存候选。

    异常时向上抛出，由调用方处理。
    """
    s = get_settings()
    cfg = config.resolve()
    rid = cfg.request_id
    region, subject, price = cfg.region, cfg.subject, cfg.price

    logger.info("[%s] Phase 1 开始: 区域=%s, 主体=%s, 价格=%d", rid, region, subject, price)
    _t0 = time.monotonic()

    # 步骤1: 飞书认证
    token = await feishu.get_token()

    # 步骤1.5: TABLE0 路由解析（区域 → 各表格物理地址）
    routing = await resolve_routing(token, region)
    logger.debug("[%s] 路由: T1=%s/%s, T2=%s/%s, T3=%s/%s", rid,
                 routing.archetype_app_token, routing.archetype_table_id,
                 routing.rules_app_token, routing.rules_table_id,
                 routing.instance_app_token, routing.instance_table_id)

    # 步骤2+3: 并行查询 TABLE1(区域原型) + TABLE2(档位规则)
    region_info, tier_rules = await asyncio.gather(
        query_region_info(token, region, routing=routing),
        query_tier_rules(token, region, price, routing=routing),
    )
    _log_dict("TABLE1 区域信息", region_info, rid)
    tier = next((tier_rules[k] for k in _TIER_KEYS if tier_rules.get(k)), "?")
    logger.info("[%s] 档位匹配: 价格=%d → %s", rid, price, tier)
    _log_dict("TABLE2 档位规则", tier_rules, rid)
    _t1 = time.monotonic()
    logger.info("[PERF-TEST] [%s] 飞书认证+路由+TABLE1/2 查询: %.2fs", rid, _t1 - _t0)

    # 步骤3.5: 加载 TierProfile 并覆盖配置
    profile = load_tier_profile(tier)
    if profile:
        cfg = apply_tier_profile(cfg, profile)
        logger.debug("[%s] 已应用 TierProfile: %s", rid, tier)

    # 步骤4: 主体校验（被禁止的主体会被容器包裹）
    subject_final = validate_subject(subject, tier_rules, region_info)
    if subject_final != subject:
        logger.info("[%s] 主体变更: '%s' → '%s'", rid, subject, subject_final)

    # 步骤5+5.1: 并行查询 TABLE3 + 下载参考图
    # TABLE3 查询和参考图下载串行依赖，但与后续 LLM 上下文组装无关
    _t2 = time.monotonic()
    instances = await query_instances(token, region, price=price, limit=3, routing=routing)
    logger.debug("[%s] TABLE3 参考案例: %d 条", rid, len(instances))
    for i, inst in enumerate(instances, 1):
        _log_dict(f"案例{i}", inst, rid)
    _t3 = time.monotonic()
    logger.info("[PERF-TEST] [%s] TABLE3 查询: %.2fs", rid, _t3 - _t2)

    # 步骤5.1: 并行下载参考图片
    ref_images = await download_instance_images(token, instances)
    _t4 = time.monotonic()
    logger.info("[PERF-TEST] [%s] 参考图下载 (%d张): %.2fs", rid, len(ref_images), _t4 - _t3)
    logger.debug("[%s] 参考图片: %d 张", rid, len(ref_images))

    # 步骤5.5: 组装 LLM 上下文
    text_provider = get_text_provider(timeout=cfg.text_timeout)
    context = build_context(region_info, tier_rules)
    examples = format_instances(instances)
    user_input = (
        f"{context}\n\n{examples}\n\n"
        f"## 用户输入\nregion: {region}, subject: {subject_final}, price: {price} coins"
    )
    logger.debug("[%s] LLM 上下文:\n%s", rid, user_input)

    # 步骤6: LLM 结构化分析（使用层级提示词）
    analyze_tier_file = profile.analyze_prompt_file if profile else None
    analyze_system = get_analyze_system(cfg.analyze_system_prompt, tier_file=analyze_tier_file)
    logger.debug("[%s] analyze 系统提示词:\n%s", rid, analyze_system)
    _t5 = time.monotonic()
    try:
        structured = await text_provider.generate(cfg.analyze_model, analyze_system, user_input)
    except Exception as e:
        raise RuntimeError(f"结构化分析失败 (model={cfg.analyze_model}): {e}") from e
    _t6 = time.monotonic()
    logger.info("[PERF-TEST] [%s] LLM 结构化分析 (%s): %.2fs", rid, cfg.analyze_model, _t6 - _t5)
    logger.debug("[%s] 结构化分析 JSON:\n%s", rid, json.dumps(structured, ensure_ascii=False, indent=2))

    # 提取 gift_name（Gemini 生成的简短展示名），回退到 subject_final
    gift_name = structured.get("gift_name") or subject_final
    logger.info("[%s] 礼物展示名: '%s'", rid, gift_name)

    # 步骤7: LLM 提示词生成（使用层级提示词）
    prompt_gen_tier_file = profile.prompt_gen_prompt_file if profile else None
    prompt_gen_system = get_prompt_gen_system(cfg.prompt_gen_system_prompt, tier_file=prompt_gen_tier_file)
    prompt_input = f"请将以下结构化JSON转换为图片生成提示词：\n{json.dumps(structured, ensure_ascii=False)}"
    _t7 = time.monotonic()
    try:
        prompts = await text_provider.generate(cfg.prompt_model, prompt_gen_system, prompt_input)
    except Exception as e:
        raise RuntimeError(f"提示词生成失败 (model={cfg.prompt_model}): {e}") from e
    _t8 = time.monotonic()
    logger.info("[PERF-TEST] [%s] LLM 提示词生成 (%s): %.2fs", rid, cfg.prompt_model, _t8 - _t7)
    logger.info("[%s] 提示词: %s", rid, prompts.get('english_prompt', '')[:120])
    logger.debug("[%s] 完整提示词: %s", rid, prompts)

    # 步骤8: 并行生图（asyncio.gather 替代 ThreadPoolExecutor）
    _t9 = time.monotonic()
    logger.info("[%s] 生成 %d 张候选图...", rid, cfg.candidate_count)
    image_provider = get_image_provider(
        name=cfg.image_provider, models=cfg.image_models,
        aspect_ratio=cfg.image_aspect_ratio, image_size=cfg.image_size,
        timeout=cfg.image_timeout,
    )

    async def _gen_one(idx: int) -> bytes | None:
        try:
            img = await image_provider.generate(
                prompts["english_prompt"],
                reference_images=ref_images or None,
            )
            logger.debug("[%s]   候选图 %d: %d 字节", rid, idx + 1, len(img))
            return img
        except Exception as e:
            logger.warning("[%s]   候选图 %d 生成失败: %s", rid, idx + 1, e)
            return None

    gen_results = await asyncio.gather(*[_gen_one(i) for i in range(cfg.candidate_count)])
    image_list: list[bytes] = [img for img in gen_results if img is not None]

    failed_count = cfg.candidate_count - len(image_list)
    if failed_count > 0:
        logger.warning("[%s] %d/%d 张候选图生成失败", rid, failed_count, cfg.candidate_count)
    _t10 = time.monotonic()
    logger.info("[PERF-TEST] [%s] 4x 并行生图: %.2fs (%d张成功)", rid, _t10 - _t9, len(image_list))

    if not image_list:
        raise RuntimeError("所有候选图生成均失败")

    # 步骤8.5: 并行抠图 + 拼图预览（CPU 密集型，用 executor）
    loop = asyncio.get_running_loop()

    async def _mat_one(idx: int, img: bytes) -> tuple[bytes, bytes]:
        try:
            matted, preview = await loop.run_in_executor(
                None, partial(matting_and_composite, img, gift_name=gift_name, price=price),
            )
            logger.debug("[%s]   候选图 %d: 抠图 %d 字节, 预览 %d 字节",
                         rid, idx + 1, len(matted), len(preview))
            return matted, preview
        except Exception as e:
            logger.warning("[%s]   候选图 %d 抠图/拼图失败: %s，使用原图", rid, idx + 1, e)
            return img, img

    mat_results = await asyncio.gather(*[_mat_one(i, img) for i, img in enumerate(image_list)])
    matted_list = [r[0] for r in mat_results]
    preview_list = [r[1] for r in mat_results]
    _t11 = time.monotonic()
    logger.info("[PERF-TEST] [%s] 4x 抠图+拼图: %.2fs", rid, _t11 - _t10)
    logger.info("[%s] 抠图+拼图完成: %d 张", rid, len(matted_list))

    # 步骤9: 并行上传预览图（composite）到飞书
    async def _upload_one(idx: int, preview: bytes) -> str | None:
        try:
            key = await feishu.upload_image(token, preview)
            logger.debug("[%s]   预览图 %d: %s", rid, idx + 1, key)
            return key
        except Exception as e:
            logger.warning("[%s]   预览图 %d 上传失败: %s", rid, idx + 1, e)
            return None

    upload_results = await asyncio.gather(*[_upload_one(i, p) for i, p in enumerate(preview_list)])
    image_keys: list[str] = [k for k in upload_results if k is not None]
    _t12 = time.monotonic()
    logger.info("[PERF-TEST] [%s] 4x 预览上传飞书: %.2fs", rid, _t12 - _t11)

    # 组装 CandidateResult 并暂存（image_bytes_list 存的是 matted 透明图）
    candidate = CandidateResult(
        request_id=rid, tier=tier, subject_final=subject_final,
        prompt=prompts["prompt"], english_prompt=prompts["english_prompt"],
        image_keys=image_keys, image_bytes_list=matted_list,
        region=region, price=price, config=config,
    )
    store_candidate(candidate)

    _t13 = time.monotonic()
    logger.info("[PERF-TEST] [%s] ══ Phase 1 总耗时: %.2fs ══", rid, _t13 - _t0)
    logger.info("[%s] Phase 1 完成: %d 张候选图已暂存", rid, len(image_list))
    return candidate


# ── Phase 2 ────────────────────────────────────────────────


async def finalize_selected(request_id: str, selected_index: int) -> PipelineResult:
    """Phase 2: 取回选中候选图 → 层级后处理 → 发飞书。"""
    candidate = get_candidate(request_id)
    if candidate is None:
        raise RuntimeError(f"候选结果已过期或不存在: request_id={request_id}")

    if selected_index < 0 or selected_index >= len(candidate.image_bytes_list):
        raise ValueError(
            f"无效的选择索引: {selected_index}, "
            f"可选范围 0-{len(candidate.image_bytes_list) - 1}"
        )

    rid = request_id
    logger.info("[%s] Phase 2: 用户选择了候选图 #%d", rid, selected_index + 1)

    selected_bytes = candidate.image_bytes_list[selected_index]

    # 验证图片格式
    is_png = selected_bytes[:4] == b'\x89PNG'
    logger.info("[%s] Phase 2: 图片格式=%s, 大小=%d bytes, 有alpha=%s",
                rid, "PNG" if is_png else "非PNG(前4字节: {})".format(selected_bytes[:4]),
                len(selected_bytes), is_png)

    # 组装 PipelineResult
    result = PipelineResult(
        subject_final=candidate.subject_final,
        tier=candidate.tier,
        prompt=candidate.prompt,
        english_prompt=candidate.english_prompt,
        media_type=MediaType.IMAGE,
        status="selected",
        request_id=rid,
        media_bytes=selected_bytes,
    )

    # 层级后处理链（保存 + 抠图 + 视频占位）
    for processor in build_postprocess_chain(candidate.tier):
        result = processor.process(result)
    if result.local_path:
        logger.debug("[%s]   图片已保存: %s", rid, result.local_path)

    # 发送到飞书
    try:
        logger.debug("[%s] 正在发送最终结果到飞书...", rid)
        s = get_settings()
        token = await feishu.get_token()
        receive_id = s.feishu_receive_id

        if result.media_bytes:
            # 并行上传 image（卡片预览）+ file（Download 预备）
            image_key, file_key = await asyncio.gather(
                feishu.upload_image(token, result.media_bytes),
                feishu.upload_file(token, result.media_bytes, "gift_final.png"),
            )
            result.image_key = image_key
            result.file_key = file_key
            result.image_id = uuid4().hex[:8]

            from cards import build_result_card
            caption = (
                f"{candidate.region} | {candidate.subject_final} "
                f"| {candidate.price} coins | {candidate.tier}"
            )
            card = build_result_card(image_key, rid, caption, image_id=result.image_id)
            msg_id_result = await feishu.send_card(token, receive_id, card)
            result.message_id = msg_id_result
            logger.debug("[%s]   结果卡片已发送 (image_id=%s)", rid, result.image_id)

        result.status = "sent_to_feishu"
    except Exception as e:
        logger.error("[%s] Phase 2 飞书发送失败: %s", rid, e, exc_info=True)
        result.status = "generated_but_send_failed"
        result.error_message = f"飞书发送失败: {e}"

    logger.info("[%s] Phase 2 完成: %s", rid, result.status)
    return result


# ── 兼容入口 ──────────────────────────────────────────────


async def generate_async(config: GenerationConfig) -> PipelineResult:
    """异步入口：Phase 1 → auto-select 第 0 张 → Phase 2。"""
    rid = config.request_id
    try:
        candidate = await generate_candidates(config)
        return await finalize_selected(candidate.request_id, 0)
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


def generate(config: GenerationConfig) -> PipelineResult:
    """同步兼容入口：CLI 和 bot_ws 使用。"""
    return asyncio.run(generate_async(config))
