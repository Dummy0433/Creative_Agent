"""Main pipeline orchestration: generate(region, subject, price) -> PipelineResult."""

import json

import feishu
from models import MediaType, PipelineResult
from providers import get_image_provider, get_text_provider
from settings import get_settings

from pipeline.context import ANALYZE_SYSTEM, PROMPT_GEN_SYSTEM, build_context, format_instances
from pipeline.data import query_instances, query_region_info, query_table0, query_tier_rules
from pipeline.postprocess import build_postprocess_chain
from pipeline.subject import detect_tier, validate_subject


def generate(region: str, subject: str, price: int) -> PipelineResult:
    s = get_settings()

    print("=" * 60)
    print("Gift Service Pipeline")
    print(f"  region={region}, subject={subject}, price={price}")
    print("=" * 60)

    # STEP 0: Authenticate
    print("\n[STEP 0] Loading credentials...")
    token = feishu.get_token()
    receive_id = s.feishu_receive_id
    print("  Feishu token acquired")
    print("  Gemini key loaded")

    # STEP 1: Detect tier
    tier = detect_tier(price)
    print(f"\n[STEP 1] Price={price} -> Tier={tier}")

    # STEP 2: Query TABLE0 (routing)
    route = query_table0(token, region)

    # STEP 3: Query TABLE1 (region info)
    region_info = query_region_info(
        token,
        route.get("archetype_app_token", ""),
        route.get("archetype_table_id", ""),
        region,
    )

    # STEP 4: Query TABLE2 (tier rules)
    tier_rules = query_tier_rules(token, region, tier)

    # STEP 5: Subject validation
    print(f"\n[STEP 5] Validating subject '{subject}'...")
    subject_final = validate_subject(subject, tier_rules, region_info)
    if subject_final == subject:
        print(f"  Subject '{subject}' is allowed at tier {tier}")

    # STEP 6: Query instances (few-shot)
    instances = query_instances(
        token,
        route.get("instance_app_token", ""),
        route.get("instance_table_id", ""),
        region, tier, limit=3,
    )

    # STEP 7: Gemini structured analysis
    print("\n[STEP 7] Structured analysis...")
    text_provider = get_text_provider()
    context = build_context(region_info, tier_rules)
    examples = format_instances(instances)
    user_input = (
        f"{context}\n\n{examples}\n\n"
        f"## 用户输入\nregion: {region}, subject: {subject_final}, price: {price} coins"
    )
    structured = text_provider.generate(s.text_model, ANALYZE_SYSTEM, user_input)
    print("  Structured JSON:")
    for k, v in structured.items():
        print(f"    {k}: {v}")

    # STEP 8: Prompt generation
    print("\n[STEP 8] Prompt generation...")
    prompt_input = f"请将以下结构化JSON转换为图片生成提示词：\n{json.dumps(structured, ensure_ascii=False)}"
    prompts = text_provider.generate(s.text_model, PROMPT_GEN_SYSTEM, prompt_input)
    print(f"  Chinese prompt: {prompts.get('prompt', '')[:80]}...")
    print(f"  English prompt: {prompts.get('english_prompt', '')[:80]}...")

    # STEP 9: Image generation
    print("\n[STEP 9] Generating image...")
    image_provider = get_image_provider()
    image_bytes = image_provider.generate(prompts["english_prompt"])
    print(f"  Image generated: {len(image_bytes)} bytes")

    # Build result
    result = PipelineResult(
        subject_final=subject_final,
        tier=tier,
        prompt=prompts["prompt"],
        english_prompt=prompts["english_prompt"],
        media_type=MediaType.IMAGE,
        status="generated",
        media_bytes=image_bytes,
    )

    # POST-PROCESS
    if s.enable_postprocess:
        for processor in build_postprocess_chain(tier):
            result = processor.process(result)

    # STEP 10: Send to Feishu
    print("\n[STEP 10] Sending to Feishu...")
    if result.media_type == MediaType.IMAGE and result.media_bytes:
        image_key = feishu.upload_image(token, result.media_bytes)
        print(f"  Image uploaded: {image_key}")
        result.image_key = image_key

        caption = (
            f"[Gift Generation] {region} | {subject_final} | {price} coins\n\n"
            f"Prompt: {prompts['prompt']}"
        )
        msg_id = feishu.send_image(token, receive_id, image_key)
        print(f"  Image message sent: {msg_id}")
        result.message_id = msg_id
        feishu.send_text(token, receive_id, caption)
        print("  Caption sent")

    result.status = "sent_to_feishu"

    print(f"\n{'=' * 60}")
    print("DONE!")
    print(result.model_dump_json(indent=2))
    print(f"{'=' * 60}")
    return result
