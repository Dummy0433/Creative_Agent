"""飞书卡片模板：统一管理所有交互卡片的构建逻辑。

包含：
- GENERATE_FORM_CARD  — 生成表单（用户填写 region/price/subject）
- build_candidate_card() — 候选图选择卡片（动态，接收 CandidateResult）
- build_result_card()    — 结果交付卡片（图片预览 + Modify/Download 按钮）
- build_routing_card()   — 路由引导卡片（重新生成 or 继续编辑）
- build_calendar_card()  — Calendar 看板卡片（只读，展示 upcoming items）
- build_mock_candidate() — 用纯色占位图构造 mock CandidateResult（测试用）
"""

import copy
import datetime
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


# ── 需求提单表单卡片（静态）──────────────────────────────────────

REQUEST_FORM_CARD = {
    "config": {"update_multi": True},
    "header": {
        "title": {"tag": "plain_text", "content": "Gift Request"},
        "template": "purple",
    },
    "elements": [
        {
            "tag": "form",
            "name": "request_form",
            "elements": [
                {
                    "tag": "input",
                    "name": "gift_name",
                    "placeholder": {"tag": "plain_text", "content": "Gift name"},
                    "label": {"tag": "plain_text", "content": "Gift Name *"},
                },
                {
                    "tag": "input",
                    "name": "price",
                    "placeholder": {"tag": "plain_text", "content": "Enter number only"},
                    "label": {"tag": "plain_text", "content": "Price (coins) *"},
                },
                {
                    "tag": "select_static",
                    "placeholder": {"tag": "plain_text", "content": "Select gift type"},
                    "name": "gift_type",
                    "options": [
                        {"text": {"tag": "plain_text", "content": "Banner"}, "value": "Banner"},
                        {"text": {"tag": "plain_text", "content": "Animation"}, "value": "Animation"},
                        {"text": {"tag": "plain_text", "content": "Random"}, "value": "Random"},
                        {"text": {"tag": "plain_text", "content": "Face"}, "value": "Face"},
                    ],
                },
                {
                    "tag": "select_static",
                    "placeholder": {"tag": "plain_text", "content": "Select category"},
                    "name": "categories",
                    "options": [
                        {"text": {"tag": "plain_text", "content": "Regular Gifts"}, "value": "Regular Gifts // \u5e38\u89c4\u793c\u7269"},
                        {"text": {"tag": "plain_text", "content": "Campaign Gifts"}, "value": "Campaign Gifts // \u6d3b\u52a8\u793c\u7269"},
                        {"text": {"tag": "plain_text", "content": "IP Partnership"}, "value": "IP Partnership // \u77e5\u8bc6\u4ea7\u6743\u5408\u4f5c\u4f19\u4f34\u5173\u7cfb"},
                        {"text": {"tag": "plain_text", "content": "Non-Gifts"}, "value": "Non-Gifts // \u975e\u793c\u7269\u9700\u6c42"},
                        {"text": {"tag": "plain_text", "content": "LIVE Effects"}, "value": "LIVE Effects // \u5f00\u64ad\u7279\u6548"},
                        {"text": {"tag": "plain_text", "content": "Stickers"}, "value": "Stickers // \u8d34\u7eb8"},
                        {"text": {"tag": "plain_text", "content": "Interactive Gift"}, "value": "Interactive Gift // \u4e92\u52a8\u793c\u7269"},
                    ],
                },
                {
                    "tag": "select_static",
                    "placeholder": {"tag": "plain_text", "content": "Select region"},
                    "name": "region",
                    "options": [
                        {"text": {"tag": "plain_text", "content": "US"}, "value": "US"},
                        {"text": {"tag": "plain_text", "content": "MENA"}, "value": "MENA"},
                        {"text": {"tag": "plain_text", "content": "EU"}, "value": "EU"},
                        {"text": {"tag": "plain_text", "content": "JP"}, "value": "JP"},
                        {"text": {"tag": "plain_text", "content": "KR"}, "value": "KR"},
                        {"text": {"tag": "plain_text", "content": "TW"}, "value": "TW"},
                        {"text": {"tag": "plain_text", "content": "TR"}, "value": "TR"},
                        {"text": {"tag": "plain_text", "content": "ID"}, "value": "ID"},
                        {"text": {"tag": "plain_text", "content": "VN"}, "value": "VN"},
                        {"text": {"tag": "plain_text", "content": "TH"}, "value": "TH"},
                        {"text": {"tag": "plain_text", "content": "BR"}, "value": "BR"},
                        {"text": {"tag": "plain_text", "content": "LATAM"}, "value": "LATAM"},
                        {"text": {"tag": "plain_text", "content": "Global Gift"}, "value": "Global Gift"},
                        {"text": {"tag": "plain_text", "content": "Cross-Region"}, "value": "Cross-Region"},
                        {"text": {"tag": "plain_text", "content": "SG"}, "value": "SG"},
                        {"text": {"tag": "plain_text", "content": "MY"}, "value": "MY"},
                        {"text": {"tag": "plain_text", "content": "PH"}, "value": "PH"},
                        {"text": {"tag": "plain_text", "content": "ANZ"}, "value": "ANZ"},
                        {"text": {"tag": "plain_text", "content": "CCA"}, "value": "CCA"},
                        {"text": {"tag": "plain_text", "content": "RO"}, "value": "RO"},
                        {"text": {"tag": "plain_text", "content": "KW"}, "value": "KW"},
                        {"text": {"tag": "plain_text", "content": "SA"}, "value": "SA"},
                    ],
                },
                {
                    "tag": "date_picker",
                    "name": "deadline",
                    "placeholder": {"tag": "plain_text", "content": "Select date"},
                    "label": {"tag": "plain_text", "content": "Expected Delivery Date *"},
                },
                {"tag": "hr"},
                {
                    "tag": "input",
                    "name": "prd",
                    "placeholder": {"tag": "plain_text", "content": "Link to PRD (optional)"},
                    "label": {"tag": "plain_text", "content": "Activity PRD"},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Submit Request"},
                    "type": "primary",
                    "action_type": "form_submit",
                    "name": "request_submit",
                },
            ],
        },
    ],
}


# ── 预填表单（Inspire exit 时使用）────────────────────────────


def _find_form_element(card: dict, field_name: str) -> dict | None:
    """在卡片 form 中按 name 查找元素。"""
    for el in card.get("elements", []):
        if el.get("tag") == "form":
            for sub in el.get("elements", []):
                if sub.get("name") == field_name:
                    return sub
    return None


def build_prefilled_generate_form(
    region: str | None = None,
    price: int | None = None,
    subject: str | None = None,
) -> dict:
    """基于 GENERATE_FORM_CARD 模板构建预填值的生成表单。"""
    card = copy.deepcopy(GENERATE_FORM_CARD)
    if region:
        el = _find_form_element(card, "region")
        if el:
            # 只有 region 在 options 中存在时才预选
            valid = {opt["value"] for opt in el.get("options", [])}
            if region in valid:
                el["initial_option"] = region
    if price is not None:
        el = _find_form_element(card, "price")
        if el:
            el["default_value"] = str(price)
    if subject:
        el = _find_form_element(card, "object")
        if el:
            el["default_value"] = subject
    return card


def build_prefilled_request_form(
    region: str | None = None,
    price: int | None = None,
    subject: str | None = None,
) -> dict:
    """基于 REQUEST_FORM_CARD 模板构建预填值的需求表单。"""
    card = copy.deepcopy(REQUEST_FORM_CARD)
    if region:
        el = _find_form_element(card, "region")
        if el:
            valid = {opt["value"] for opt in el.get("options", [])}
            if region in valid:
                el["initial_option"] = region
    if price is not None:
        el = _find_form_element(card, "price")
        if el:
            el["default_value"] = str(price)
    if subject:
        el = _find_form_element(card, "gift_name")
        if el:
            el["default_value"] = subject
    return card


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


# ── 结果交付卡片（图片预览 + Modify/Download）──────────────

def build_result_card(image_key: str, request_id: str,
                      caption: str = "", image_id: str = "") -> dict:
    """构建结果交付卡片：内嵌图片预览 + Modify/Download 按钮。

    image_id 唯一标识本卡片对应的图片，Modify 按钮靠它锁定编辑目标。
    """
    elements = [
        {
            "tag": "img",
            "img_key": image_key,
            "preview": True,
            "scale_type": "fit_horizontal",
        },
    ]

    if caption:
        elements.append({
            "tag": "markdown",
            "content": caption,
        })

    elements.append({
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Modify"},
                    "type": "primary",
                    "width": "fill",
                    "icon": {"tag": "standard_icon", "token": "edit_outlined"},
                    "value": {
                        "action": "start_edit",
                        "request_id": request_id,
                        "image_id": image_id,
                    },
                }],
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Download PNG"},
                    "type": "default",
                    "width": "fill",
                    "icon": {"tag": "standard_icon", "token": "download_outlined"},
                    "value": {
                        "action": "download_png",
                        "request_id": request_id,
                        "image_id": image_id,
                    },
                }],
            },
        ],
    })

    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Gift Result"},
            "template": "green",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": elements,
        },
    }


# ── 路由卡片（编辑完成后引导）─────────────────────────────

def build_routing_card(request_id: str) -> dict:
    """构建"是否重新生成"路由卡片。"""
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "What's next?"},
            "template": "blue",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": [
                {
                    "tag": "markdown",
                    "content": "Would you like to regenerate the gift?",
                },
                {
                    "tag": "column_set",
                    "horizontal_spacing": "8px",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [{
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "Yes"},
                                "type": "primary",
                                "width": "fill",
                                "value": {
                                    "action": "route_regen",
                                    "request_id": request_id,
                                },
                            }],
                        },
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [{
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "No"},
                                "type": "default",
                                "width": "fill",
                                "value": {
                                    "action": "route_continue",
                                    "request_id": request_id,
                                },
                            }],
                        },
                    ],
                },
            ],
        },
    }


# ── Calendar 看板卡片（只读）─────────────────────────────────

_STATUS_ICONS = {
    "in Design": "\U0001f3a8",       # 🎨
    "in Feedback": "\U0001f4ac",     # 💬
    "Not Started": "\u231b",         # ⏳
    "Not Scheduled": "\U0001f4cb",   # 📋
    "Delivered": "\u2705",           # ✅
    "Delayed": "\U0001f534",         # 🔴
    "Pending": "\u23f8\ufe0f",       # ⏸️
    "Cancelled": "\u274c",           # ❌
}

_DEFAULT_STATUS_ICON = "\U0001f4e6"  # 📦


def _resolve_status_icon(progress: str) -> str:
    """从 progress 字段提取英文状态关键字并映射 icon。"""
    key = progress.split("//")[0].strip() if progress else ""
    return _STATUS_ICONS.get(key, _DEFAULT_STATUS_ICON)


def _format_deadline(ts_ms: int | float) -> str:
    """毫秒时间戳 → MM/DD，无效时返回空字符串。"""
    if not ts_ms:
        return ""
    try:
        dt = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.timezone.utc)
        return dt.strftime("%m/%d")
    except (OSError, ValueError, OverflowError):
        return ""


def build_calendar_card(records: list[dict]) -> dict:
    """构建 Calendar 看板卡片 (schema 2.0, read-only)。

    展示 upcoming gift calendar 记录，每条包含名称、状态、区域、
    价格、截止日期、设计师/POC 和文档链接。
    """
    header = {
        "title": {"tag": "plain_text", "content": "Gift Calendar"},
        "subtitle": {
            "tag": "plain_text",
            "content": f"Upcoming {len(records)} items",
        },
        "template": "blue",
    }

    elements: list[dict] = []

    if not records:
        elements.append({
            "tag": "markdown",
            "content": "No data available for this quarter.",
        })
        return {
            "schema": "2.0",
            "header": header,
            "body": {"elements": elements},
        }

    for idx, rec in enumerate(records):
        if idx > 0:
            elements.append({"tag": "hr"})

        name = rec.get("name") or "Untitled"
        progress = rec.get("progress") or ""
        icon = _resolve_status_icon(progress)
        regions = rec.get("regions") or []
        price = rec.get("price")
        deadline_ts = rec.get("deadline_ts") or 0
        designer = rec.get("designer") or ""
        poc = rec.get("poc") or ""
        doc_link = rec.get("doc_link") or ""
        doc_text = rec.get("doc_text") or ""

        # Line 1: icon + bold name
        lines = [f"{icon} **{name}**"]

        # Line 2: regions | price | deadline
        info_parts = []
        if regions:
            info_parts.append(", ".join(regions))
        if price:
            info_parts.append(f"{price}c")
        deadline_str = _format_deadline(deadline_ts)
        if deadline_str:
            info_parts.append(deadline_str)
        if info_parts:
            lines.append("      " + " | ".join(info_parts))

        # Line 3: designer + poc
        people_parts = []
        if designer:
            people_parts.append(f"\U0001f3a8{designer}")
        if poc:
            people_parts.append(f"\U0001f464{poc}")
        if people_parts:
            lines.append("      " + " | ".join(people_parts))

        # Line 4: doc link
        if doc_link:
            display_text = doc_text if doc_text else "Link"
            if len(display_text) > 30:
                display_text = display_text[:30] + "..."
            lines.append(f"      [\U0001f4c4 {display_text}]({doc_link})")

        elements.append({
            "tag": "markdown",
            "content": "\n".join(lines),
        })

    return {
        "schema": "2.0",
        "header": header,
        "body": {"elements": elements},
    }
