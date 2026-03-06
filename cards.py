"""飞书卡片模板：统一管理所有交互卡片的构建逻辑。

包含：
- GENERATE_FORM_CARD  — 生成表单（用户填写 region/price/subject）
- build_candidate_card() — 候选图选择卡片（动态，接收 CandidateResult）
- build_mock_candidate() — 用纯色占位图构造 mock CandidateResult（测试用）
"""

import struct
import zlib

import feishu
from models import CandidateResult, GenerationConfig
from pipeline.candidate_store import save as store_candidate


# ── 生成表单卡片（静态）──────────────────────────────────────

GENERATE_FORM_CARD = {
    "header": {
        "title": {"tag": "plain_text", "content": "Gift Generator"},
        "template": "blue",
    },
    "elements": [
        {
            "tag": "form",
            "name": "generate_form",
            "elements": [
                {
                    "tag": "select_static",
                    "placeholder": {"tag": "plain_text", "content": "Select region"},
                    "name": "region",
                    "initial_option": "MENA",
                    "options": [
                        {"text": {"tag": "plain_text", "content": "MENA"}, "value": "MENA"},
                        {"text": {"tag": "plain_text", "content": "TR"}, "value": "TR"},
                        {"text": {"tag": "plain_text", "content": "General"}, "value": "General"},
                    ],
                },
                {
                    "tag": "input",
                    "name": "price",
                    "placeholder": {"tag": "plain_text", "content": "Price (coins)"},
                    "default_value": "1",
                    "label": {"tag": "plain_text", "content": "Price"},
                },
                {
                    "tag": "input",
                    "name": "object",
                    "placeholder": {"tag": "plain_text", "content": "e.g. 雄狮 (optional)"},
                    "label": {"tag": "plain_text", "content": "Object"},
                },
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": "**Advanced Options** (optional)",
                },
                {
                    "tag": "select_static",
                    "placeholder": {"tag": "plain_text", "content": "Aspect Ratio (default: 1:1)"},
                    "name": "aspect_ratio",
                    "options": [
                        {"text": {"tag": "plain_text", "content": "1:1"}, "value": "1:1"},
                        {"text": {"tag": "plain_text", "content": "16:9"}, "value": "16:9"},
                        {"text": {"tag": "plain_text", "content": "9:16"}, "value": "9:16"},
                        {"text": {"tag": "plain_text", "content": "3:4"}, "value": "3:4"},
                        {"text": {"tag": "plain_text", "content": "4:3"}, "value": "4:3"},
                    ],
                },
                {
                    "tag": "select_static",
                    "placeholder": {"tag": "plain_text", "content": "Resolution (default: 1K)"},
                    "name": "image_size",
                    "options": [
                        {"text": {"tag": "plain_text", "content": "512px"}, "value": "512px"},
                        {"text": {"tag": "plain_text", "content": "1K"}, "value": "1K"},
                        {"text": {"tag": "plain_text", "content": "2K"}, "value": "2K"},
                    ],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Start Generation"},
                    "type": "primary",
                    "action_type": "form_submit",
                    "name": "generate_submit",
                },
            ],
        },
    ],
}


# ── 候选图选择卡片（动态）────────────────────────────────────

def build_candidate_card(candidate: CandidateResult) -> dict:
    """构建候选图选择卡片 (schema 2.0)。

    横向展示所有候选图 + 每张图的选择按钮 (A/B/C/D)，
    底部有 Regenerate / Modify Request 操作按钮。
    """
    labels = "ABCDEFGH"

    # 每张候选图一列：图片 + 选择按钮
    image_columns = []
    for i, key in enumerate(candidate.image_keys):
        label = labels[i] if i < len(labels) else str(i + 1)
        image_columns.append({
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "vertical_spacing": "8px",
            "horizontal_align": "left",
            "vertical_align": "top",
            "elements": [
                {
                    "tag": "img",
                    "img_key": key,
                    "preview": True,
                    "transparent": False,
                    "scale_type": "fit_horizontal",
                    "margin": "0px 0px 0px 0px",
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": label},
                    "type": "primary_filled",
                    "width": "fill",
                    "size": "small",
                    "value": {
                        "action": "candidate_select",
                        "request_id": candidate.request_id,
                        "selected_index": i,
                    },
                },
            ],
        })

    # 底部操作按钮行
    action_columns = [
        {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "vertical_spacing": "8px",
            "horizontal_align": "left",
            "vertical_align": "top",
            "elements": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Regenerate"},
                "type": "default",
                "width": "fill",
                "size": "medium",
                "icon": {"tag": "standard_icon", "token": "replace_outlined"},
                "hover_tips": {"tag": "plain_text", "content": "Regenerate all candidates"},
                "value": {
                    "action": "regenerate",
                    "request_id": candidate.request_id,
                },
            }],
        },
        {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "vertical_spacing": "8px",
            "horizontal_align": "left",
            "vertical_align": "top",
            "elements": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Modify Request"},
                "type": "default",
                "width": "fill",
                "size": "medium",
                "icon": {"tag": "standard_icon", "token": "edit_outlined"},
                "hover_tips": {"tag": "plain_text", "content": "Change generation parameters"},
                "value": {
                    "action": "modify_request",
                    "request_id": candidate.request_id,
                },
            }],
        },
    ]

    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Generation Success"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"{candidate.subject_final} | {candidate.tier} | {candidate.region}",
            },
            "template": "green",
            "padding": "12px 12px 12px 12px",
        },
        "body": {
            "direction": "vertical",
            "horizontal_spacing": "8px",
            "vertical_spacing": "16px",
            "horizontal_align": "left",
            "vertical_align": "top",
            "padding": "12px 12px 12px 12px",
            "elements": [
                {
                    "tag": "column_set",
                    "horizontal_spacing": "8px",
                    "horizontal_align": "left",
                    "columns": image_columns,
                    "margin": "0px 0px 0px 0px",
                },
                {
                    "tag": "column_set",
                    "horizontal_spacing": "8px",
                    "horizontal_align": "left",
                    "columns": action_columns,
                    "margin": "0px 0px 0px 0px",
                },
            ],
        },
    }


# ── Mock 候选图（测试用）─────────────────────────────────────

_MOCK_COLORS = [
    (235, 87, 87),    # A — 红
    (47, 128, 237),   # B — 蓝
    (39, 174, 96),    # C — 绿
    (243, 156, 18),   # D — 橙
]


def _make_png(w: int, h: int, rgb: tuple[int, int, int]) -> bytes:
    """生成纯色 PNG (无需第三方库)。"""
    r, g, b = rgb
    raw_row = b"\x00" + bytes([r, g, b]) * w
    raw_data = raw_row * h

    def _chunk(ctype: bytes, data: bytes) -> bytes:
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw_data))
        + _chunk(b"IEND", b"")
    )


def build_mock_candidate(token: str, num: int = 4) -> CandidateResult:
    """上传纯色占位图并构造 mock CandidateResult，同时存入 candidate_store。"""
    colors = _MOCK_COLORS[:num]

    print("上传占位图...")
    image_keys = []
    image_bytes_list = []
    for i, color in enumerate(colors):
        png = _make_png(512, 512, color)
        key = feishu.upload_image(token, png)
        print(f"  [{chr(65 + i)}] {key}  ({color})")
        image_keys.append(key)
        image_bytes_list.append(png)

    mock_config = GenerationConfig(region="MENA", subject="雄狮", price=299)
    candidate = CandidateResult(
        request_id="mock0001",
        tier="P2",
        subject_final="雄狮",
        prompt="(mock prompt)",
        english_prompt="(mock english prompt)",
        image_keys=image_keys,
        image_bytes_list=image_bytes_list,
        region="MENA",
        price=299,
        config=mock_config,
    )
    store_candidate(candidate)
    return candidate
