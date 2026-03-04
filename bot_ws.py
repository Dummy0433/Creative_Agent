"""飞书机器人长连接 (WebSocket) 客户端。

启动方式:  python bot_ws.py
接收飞书消息，处理菜单点击和卡片表单提交，触发生成 Pipeline 并回传结果。

文本模式消息格式示例（仍然支持）：
    雄狮 1 MENA
    玫瑰 100
    雪山
"""

import json
import logging
import threading
import traceback

import lark_oapi as lark
from lark_oapi.api.application.v6 import P2ApplicationBotMenuV6
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
    CallBackToast,
)

import feishu
from defaults import load_defaults
from models import GenerationConfig
from pipeline import generate
from settings import get_settings

logger = logging.getLogger(__name__)

# ── 生成表单卡片 JSON ────────────────────────────────────────
# 用户点击 Generate 菜单后发送此交互卡片

GENERATE_CARD = {
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
                    # 区域下拉选择
                    "tag": "select_static",
                    "placeholder": {"tag": "plain_text", "content": "Select region"},
                    "name": "region",
                    "initial_option": "General",
                    "options": [
                        {"text": {"tag": "plain_text", "content": "MENA"}, "value": "MENA"},
                        {"text": {"tag": "plain_text", "content": "TR"}, "value": "TR"},
                        {"text": {"tag": "plain_text", "content": "General"}, "value": "General"},
                    ],
                },
                {
                    # 价格输入框
                    "tag": "input",
                    "name": "price",
                    "placeholder": {"tag": "plain_text", "content": "Price (coins)"},
                    "default_value": "1",
                    "label": {"tag": "plain_text", "content": "Price"},
                },
                {
                    # 物象输入框（可选）
                    "tag": "input",
                    "name": "object",
                    "placeholder": {"tag": "plain_text", "content": "e.g. 雄狮 (optional)"},
                    "label": {"tag": "plain_text", "content": "Object"},
                },
                # ── 高级选项分隔线 ──────────────────────────
                {
                    "tag": "hr",
                },
                {
                    "tag": "markdown",
                    "content": "**Advanced Options** (optional)",
                },
                {
                    # 宽高比下拉
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
                    # 分辨率下拉
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
                    # 提交按钮
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


# ── 辅助函数 ─────────────────────────────────────────────────

def parse_input(text: str) -> dict:
    """解析用户文本输入为 subject / price / region 参数。

    支持格式：
        主体 价格 区域   (如 "雄狮 1 MENA")
        主体 价格         (如 "玫瑰 100"，使用默认区域)
        主体              (如 "雪山"，使用默认价格和区域)
    """
    d = load_defaults()
    parts = text.strip().split()

    if not parts:
        return {}

    subject = parts[0]
    price = d["default_price"]
    region = d["default_region"]

    # 第二个参数为价格（纯数字）
    if len(parts) >= 2 and parts[1].isdigit():
        price = int(parts[1])
    # 第三个参数为区域
    if len(parts) >= 3:
        region = parts[2].upper()

    return {"subject": subject, "price": price, "region": region}


def handle_generate(sender_id: str, config: GenerationConfig) -> None:
    """在新线程中运行生成 Pipeline 并将结果发回给用户。"""
    token = feishu.get_token()

    # 先发送一条提示消息
    feishu.send_text(
        token, sender_id,
        f"正在生成: {config.subject} | {config.price} coins | {config.region}...",
    )

    try:
        result = generate(config)
        logger.info("生成完成: %s", result.status)
    except Exception as e:
        traceback.print_exc()
        feishu.send_text(token, sender_id, f"生成失败: {e}")


# ── 事件处理器 ───────────────────────────────────────────────

def on_message(data: P2ImMessageReceiveV1) -> None:
    """处理用户直接发送的文本消息（旧版文本模式）。"""
    event = data.event
    sender_id = event.sender.sender_id.open_id
    msg_type = event.message.message_type
    content = json.loads(event.message.content)

    logger.info("[消息] %s: %s", sender_id, content)

    # 只处理文本消息
    if msg_type != "text":
        return

    text = content.get("text", "").strip()
    if not text:
        return

    # 解析输入参数
    params = parse_input(text)
    if not params:
        token = feishu.get_token()
        feishu.send_text(token, sender_id, "请输入: 物象 [价格] [区域]\n例: 雄狮 1 MENA")
        return

    config = GenerationConfig(**params)

    # 在新线程中执行生成，避免阻塞事件循环
    threading.Thread(
        target=handle_generate,
        args=(sender_id, config),
        daemon=True,
    ).start()


def on_menu(data: P2ApplicationBotMenuV6) -> None:
    """处理 bot 底部菜单按钮点击事件。"""
    try:
        event = data.event
        event_key = event.event_key
        operator = event.operator
        open_id = operator.operator_id.open_id

        print(f"[菜单] 用户={open_id}, 事件={event_key}")

        if event_key == "generate":
            # 发送生成表单卡片
            token = feishu.get_token()
            feishu.send_card(token, open_id, GENERATE_CARD)
        elif event_key == "debug":
            # 发送调试信息
            token = feishu.get_token()
            d = load_defaults()
            s = get_settings()
            debug_info = (
                f"image_provider: {d.get('image_provider', 'gemini')}\n"
                f"analyze_model: {d['analyze_model']}\n"
                f"image_models: {d['image_models']}\n"
                f"log_level: {s.log_level}\n"
                f"default_region: {d['default_region']}\n"
                f"default_price: {d['default_price']}"
            )
            feishu.send_text(token, open_id, debug_info)
        elif event_key == "inspire":
            # 灵感模式（预留）
            token = feishu.get_token()
            feishu.send_text(token, open_id, "灵感模式即将上线!")
        else:
            print(f"[菜单] 未知事件: {event_key}")
    except Exception as e:
        print(f"[菜单] 错误: {e}")
        traceback.print_exc()


def on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    """处理卡片表单提交事件。

    从 form_value 中提取 region / price / object + 高级选项，构造 GenerationConfig。
    返回 toast 提示告知用户已开始生成。
    """
    try:
        event = data.event
        open_id = event.operator.open_id
        action = event.action
        form_value = action.form_value or {}

        print(f"[卡片] 用户={open_id}, 表单={form_value}")

        d = load_defaults()
        region = form_value.get("region", d["default_region"])
        price_str = form_value.get("price", str(d["default_price"]))
        subject = form_value.get("object", "").strip() or d["default_subject"]

        # 安全解析价格
        try:
            price = int(price_str)
        except (ValueError, TypeError):
            price = d["default_price"]

        # 构造 GenerationConfig，高级选项为 None 时使用默认值
        config = GenerationConfig(
            region=region,
            subject=subject,
            price=price,
            image_aspect_ratio=form_value.get("aspect_ratio"),
            image_size=form_value.get("image_size"),
        )

        # 在新线程中执行生成
        threading.Thread(
            target=handle_generate,
            args=(open_id, config),
            daemon=True,
        ).start()

        # 返回 toast 提示
        resp = P2CardActionTriggerResponse()
        resp.toast = CallBackToast()
        resp.toast.type = "info"
        resp.toast.content = f"正在生成: {subject} | {price} coins | {region}..."
        return resp
    except Exception as e:
        print(f"[卡片] 错误: {e}")
        traceback.print_exc()
        return P2CardActionTriggerResponse()


# ── 主入口 ───────────────────────────────────────────────────

def main():
    """启动飞书 WebSocket 长连接机器人。"""
    s = get_settings()

    # 配置日志格式和级别
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 注册事件处理器
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)       # 文本消息
        .register_p2_application_bot_menu_v6(on_menu)         # 菜单点击
        .register_p2_card_action_trigger(on_card_action)      # 卡片表单提交
        .build()
    )

    # 创建 WebSocket 客户端并启动
    cli = lark.ws.Client(
        s.feishu_app_id,
        s.feishu_app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.DEBUG,
    )

    logger.info("飞书礼物机器人已就绪!")
    logger.info("支持: 文本消息、Generate 菜单、卡片表单提交")
    cli.start()


if __name__ == "__main__":
    main()
