"""飞书机器人长连接 (WebSocket) 客户端。

启动方式:
    python bot_ws.py                # 正常启动（INFO 级别日志）
    python bot_ws.py --card         # 先发送 mock 候选卡片，再启动 WS 监听
    python bot_ws.py --test         # 全部 DEBUG 日志
    python bot_ws.py --test card    # 仅卡片交互 DEBUG 日志
    python bot_ws.py --test route   # 仅路由/数据查询 DEBUG 日志
    python bot_ws.py --test generate # 仅生成流程 DEBUG 日志
    python bot_ws.py --test post    # 仅后处理 DEBUG 日志
    python bot_ws.py --test card route  # 多个子系统组合

接收飞书消息，处理菜单点击和卡片交互，触发生成 Pipeline 并回传结果。
"""

import asyncio
import json
import logging
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

import lark_oapi as lark
from lark_oapi.api.application.v6 import P2ApplicationBotMenuV6
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
    CallBackToast,
)

import feishu
from cards import GENERATE_FORM_CARD, build_candidate_card, build_mock_candidate
from defaults import load_defaults
from models import GenerationConfig, SessionState, EditSession
from pipeline import generate_candidates, finalize_selected
from pipeline.candidate_store import get as get_candidate
from pipeline.edit import handle_edit, handle_editing_text
from pipeline.session_store import get as get_session, save as save_session, remove as remove_session
from settings import get_settings

# 使用固定名称，避免 __main__ vs bot_ws 不一致
logger = logging.getLogger("bot_ws")


def _run_async(coro):
    """在同步上下文中安全运行协程（兼容已有 event loop 的环境）。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Lark SDK 内部有 event loop，用独立线程运行
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()

# 线程池：用于异步执行生成任务，避免阻塞事件循环
_generate_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gen")

# ── 日志子系统映射 ─────────────────────────────────────────────
# --test <subsystem> 时只显示对应模块的 DEBUG 日志，其余保持 WARNING
_LOG_SUBSYSTEMS = {
    "route":    ["pipeline.data"],                                        # 路由 + 数据查询
    "generate": ["pipeline.orchestrator", "pipeline.context",             # 生成流程
                 "pipeline.subject", "pipeline.tier_profile",
                 "providers", "providers.gemini"],
    "post":     ["pipeline.postprocess"],                                 # 后处理
    "card":     ["bot_ws", "cards"],                                      # 卡片交互
    "feishu":   ["feishu"],                                               # 飞书 API
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
    price = d.default_price
    region = d.default_region

    if len(parts) >= 2 and parts[1].isdigit():
        price = int(parts[1])
    if len(parts) >= 3:
        region = parts[2].upper()

    return {"subject": subject, "price": price, "region": region}


def handle_generate(sender_id: str, config: GenerationConfig) -> None:
    """Phase 1: 生成候选图并发送选择卡片。"""
    token = feishu.get_token_sync()

    feishu.send_text_sync(
        token, sender_id,
        f"正在生成: {config.subject} | {config.price} coins | {config.region}...",
    )

    try:
        candidate = _run_async(generate_candidates(config))
        card = build_candidate_card(candidate)
        feishu.send_card_sync(token, sender_id, card)
        logger.info("已发送 %d 张候选图卡片: %s", len(candidate.image_keys), candidate.request_id)
    except Exception as e:
        logger.error("Phase 1 失败: %s", e, exc_info=True)
        feishu.send_text_sync(token, sender_id, f"生成失败: {e}")


def _send_download(sender_id: str, session: EditSession) -> None:
    """发送透明 PNG 文件给用户（Download 按钮回调）。

    优先使用预上传的 file_key（秒发），否则现场上传。
    """
    token = feishu.get_token_sync()
    file_key = session.file_key
    if not file_key:
        file_key = feishu.upload_file_sync(token, session.current_image, "gift.png")
    feishu.send_file_sync(token, sender_id, file_key)


def handle_finalize(sender_id: str, request_id: str, selected_index: int) -> None:
    """Phase 2: 处理用户选择，执行后处理，创建编辑 session。"""
    token = feishu.get_token_sync()
    try:
        feishu.send_text_sync(token, sender_id, f"已选择方案 {selected_index + 1}，正在处理...")
        result = _run_async(finalize_selected(request_id, selected_index))
        logger.info("Phase 2 完成: %s -> %s", request_id, result.status)

        # 创建 EditSession
        candidate = get_candidate(request_id)
        if candidate and candidate.config and result.media_bytes and result.message_id:
            session = EditSession(
                user_id=sender_id,
                state=SessionState.EDITING,
                request_id=request_id,
                current_image=result.media_bytes,
                original_config=candidate.config,
                file_key=result.file_key,
            )
            session.message_id_map[result.message_id] = "final"
            session.image_map[result.message_id] = result.media_bytes
            if result.image_id:
                session.image_map[result.image_id] = result.media_bytes
            save_session(session)
            logger.info("[Session] 已创建 user=%s, request_id=%s", sender_id, request_id)
    except Exception as e:
        logger.error("Phase 2 失败: %s", e, exc_info=True)
        feishu.send_text_sync(token, sender_id, f"处理失败: {e}")


# ── 事件处理器 ───────────────────────────────────────────────

def on_message(data: P2ImMessageReceiveV1) -> None:
    """处理用户消息：根据 session 状态和 parent_id 路由到正确流程。"""
    event = data.event
    sender_id = event.sender.sender_id.open_id
    msg_type = event.message.message_type
    parent_id = event.message.parent_id
    content = json.loads(event.message.content)

    logger.info("[消息] %s: type=%s, parent_id=%s, content=%s",
                sender_id, msg_type, parent_id, content)

    if msg_type == "image":
        logger.info("[调试] 收到用户图片: image_key=%s", content.get("image_key", ""))
        return

    if msg_type != "text":
        return

    text = content.get("text", "").strip()
    if not text:
        return

    session = get_session(sender_id)

    # 路由1: 回复了 bot 发出的图片 → 编辑（传 parent_id 以定位具体图片）
    if parent_id and session and parent_id in session.message_id_map:
        logger.info("[路由] 回复图片编辑: user=%s, parent=%s", sender_id, parent_id)
        threading.Thread(
            target=handle_edit, args=(sender_id, session, text, parent_id), daemon=True,
        ).start()
        return

    # 路由2: 有活跃 EDITING/DELIVERED session + 纯文字
    if session and session.state in (SessionState.EDITING, SessionState.DELIVERED):
        if session.pending_edit:
            # Modify 按钮已点击 → 下一条文字作为编辑指令，image_id 锁定目标图片
            image_id = session.pending_edit_image_id
            logger.info("[路由] pending_edit 编辑: user=%s, image_id=%s", sender_id, image_id)
            session.pending_edit = False
            session.pending_edit_image_id = ""
            save_session(session)
            threading.Thread(
                target=handle_edit, args=(sender_id, session, text, image_id), daemon=True,
            ).start()
        else:
            logger.info("[路由] 编辑状态文字: user=%s, state=%s", sender_id, session.state)
            threading.Thread(
                target=handle_editing_text, args=(sender_id, session, text), daemon=True,
            ).start()
        return

    # 路由3: 默认 → 新生成
    params = parse_input(text)
    if not params:
        token = feishu.get_token_sync()
        feishu.send_text_sync(token, sender_id, "请输入: 物象 [价格] [区域]\n例: 雄狮 1 MENA")
        return

    config = GenerationConfig(**params)
    threading.Thread(
        target=handle_generate, args=(sender_id, config), daemon=True,
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
            token = feishu.get_token_sync()
            feishu.send_card_sync(token, open_id, GENERATE_FORM_CARD)
        elif event_key == "debug":
            token = feishu.get_token_sync()
            d = load_defaults()
            s = get_settings()
            debug_info = (
                f"image_provider: {d.image_provider}\n"
                f"analyze_model: {d.analyze_model}\n"
                f"image_models: {d.image_models}\n"
                f"log_level: {s.log_level}\n"
                f"default_region: {d.default_region}\n"
                f"default_price: {d.default_price}"
            )
            feishu.send_text_sync(token, open_id, debug_info)
        elif event_key == "inspire":
            token = feishu.get_token_sync()
            feishu.send_text_sync(token, open_id, "灵感模式即将上线!")
        else:
            print(f"[菜单] 未知事件: {event_key}")
    except Exception as e:
        print(f"[菜单] 错误: {e}")
        traceback.print_exc()


def _make_toast(content: str, toast_type: str = "info") -> P2CardActionTriggerResponse:
    """快速构造带 toast 的卡片回调响应。"""
    resp = P2CardActionTriggerResponse()
    resp.toast = CallBackToast()
    resp.toast.type = toast_type
    resp.toast.content = content
    return resp


def on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    """处理卡片交互事件。

    路由逻辑：
    - candidate_select → 选中候选图 → Phase 2 (finalize + 下载)
    - regenerate       → 用同样配置重新生成
    - modify_request   → 返回生成表单卡片
    - form_value 有值  → 生成表单提交 → Phase 1
    """
    try:
        event = data.event
        open_id = event.operator.open_id
        action = event.action
        action_value = action.value

        # 兼容处理：SDK 可能返回 dict 或 JSON 字符串或 None
        if action_value is None:
            action_value = {}
        if isinstance(action_value, str):
            try:
                action_value = json.loads(action_value)
            except (json.JSONDecodeError, TypeError):
                action_value = {}

        logger.info("[卡片] action_value=%s, type=%s", action_value, type(action_value))

        if isinstance(action_value, dict) and action_value.get("action"):
            act = action_value["action"]
            rid = action_value.get("request_id", "")

            # ── 选择候选图 (A/B/C/D) → Phase 2 ──
            if act == "candidate_select":
                idx = int(action_value["selected_index"])
                logger.info("[卡片] 用户=%s 选择候选图: request_id=%s, index=%d", open_id, rid, idx)
                _generate_pool.submit(handle_finalize, open_id, rid, idx)
                return _make_toast(f"已选择方案 {chr(65 + idx)}，正在处理...")

            # ── Regenerate → 用原始配置重新生成 ──
            if act == "regenerate":
                logger.info("[卡片] 用户=%s 请求重新生成: request_id=%s", open_id, rid)
                candidate = get_candidate(rid)
                if candidate and candidate.config:
                    logger.info("[卡片] 找到候选数据，原始配置: subject=%s, region=%s, price=%d",
                                candidate.config.subject, candidate.config.region, candidate.config.price)
                    _generate_pool.submit(handle_generate, open_id, candidate.config)
                    return _make_toast("正在重新生成，请稍候...")
                else:
                    logger.warning("[卡片] 候选数据不存在或无配置: candidate=%s", candidate is not None)
                    return _make_toast("候选图已过期，请重新提交请求", "warning")

            # ── Modify Request → 发回生成表单 ──
            if act == "modify_request":
                logger.info("[卡片] 用户=%s 修改请求: request_id=%s", open_id, rid)
                token = feishu.get_token_sync()
                feishu.send_card_sync(token, open_id, GENERATE_FORM_CARD)
                return _make_toast("请在新卡片中修改参数")

            # ── 结果卡片：Modify → 进入编辑模式（锁定目标图片）──
            if act == "start_edit":
                image_id = action_value.get("image_id", "")
                logger.info("[卡片] 用户=%s 点击 Modify, image_id=%s", open_id, image_id)
                session = get_session(open_id)
                if session:
                    session.pending_edit = True
                    session.pending_edit_image_id = image_id
                    session.state = SessionState.EDITING
                    save_session(session)
                    return _make_toast("请输入编辑指令")
                return _make_toast("Session 已过期，请重新生成", "warning")

            # ── 结果卡片：Download → 发送透明 PNG 文件 ──
            if act == "download_png":
                logger.info("[卡片] 用户=%s 点击 Download", open_id)
                session = get_session(open_id)
                if session and session.current_image:
                    _generate_pool.submit(_send_download, open_id, session)
                    return _make_toast("正在准备下载...")
                return _make_toast("Session 已过期，请重新生成", "warning")

            # ── 路由卡片：重新生成 ──
            if act == "route_regen":
                logger.info("[卡片] 用户=%s 选择重新生成", open_id)
                session = get_session(open_id)
                config = session.original_config if session else None
                remove_session(open_id)
                if config:
                    _generate_pool.submit(handle_generate, open_id, config)
                    return _make_toast("正在重新生成，请稍候...")
                return _make_toast("Session 已过期，请重新提交", "warning")

            # ── 路由卡片：继续编辑 ──
            if act == "route_continue":
                logger.info("[卡片] 用户=%s 选择继续编辑", open_id)
                session = get_session(open_id)
                if session:
                    session.state = SessionState.EDITING
                    save_session(session)
                return _make_toast("继续编辑，请回复图片并输入调整指令")

            # 未知 action
            logger.warning("[卡片] 未知 action: %s, action_value=%s", act, action_value)
            return P2CardActionTriggerResponse()

        # ── 生成表单提交 ──
        form_value = action.form_value or {}
        logger.info("[卡片] form_value=%s (action_value 未匹配到已知 action)", form_value)
        if form_value:
            logger.info("[卡片] 用户=%s, 表单=%s", open_id, form_value)

            d = load_defaults()
            region = form_value.get("region", d.default_region)
            price_str = form_value.get("price", str(d.default_price))
            subject = form_value.get("object", "").strip() or d.default_subject

            try:
                price = int(price_str)
            except (ValueError, TypeError):
                price = d.default_price

            config = GenerationConfig(
                region=region,
                subject=subject,
                price=price,
                image_aspect_ratio=form_value.get("aspect_ratio"),
                image_size=form_value.get("image_size"),
            )

            _generate_pool.submit(handle_generate, open_id, config)
            return _make_toast(f"正在生成: {subject} | {price} coins | {region}...")

        return P2CardActionTriggerResponse()
    except Exception as e:
        logger.error("[卡片] 错误: %s", e, exc_info=True)
        return P2CardActionTriggerResponse()


# ── 主入口 ───────────────────────────────────────────────────

def _configure_logging(test_subsystems: list[str] | None, base_level: str) -> None:
    """配置日志级别。

    test_subsystems=None:  正常模式，所有 logger 使用 base_level
    test_subsystems=[]:    --test 无参数，全部 DEBUG
    test_subsystems=[...]: --test route card，指定子系统 DEBUG，其余 WARNING
    """
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    if test_subsystems is None:
        # 正常模式
        logging.basicConfig(level=getattr(logging, base_level.upper(), logging.INFO), format=fmt)
        return

    if not test_subsystems:
        # --test 无参数：全部 DEBUG
        logging.basicConfig(level=logging.DEBUG, format=fmt)
        return

    # --test route card：指定子系统 DEBUG，其余 WARNING
    logging.basicConfig(level=logging.WARNING, format=fmt)
    # 静默 Lark SDK 的 ping/pong 等噪音日志
    logging.getLogger("Lark").setLevel(logging.WARNING)
    valid_subs = []
    for sub in test_subsystems:
        if sub not in _LOG_SUBSYSTEMS:
            print(f"  未知子系统: '{sub}'. 可选: {', '.join(_LOG_SUBSYSTEMS)}")
            continue
        valid_subs.append(sub)
        for logger_name in _LOG_SUBSYSTEMS[sub]:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)

    if valid_subs:
        print(f"  日志过滤: 仅显示 {', '.join(valid_subs)} 的 DEBUG 日志")


def main():
    """启动飞书 WebSocket 长连接机器人。"""
    import sys

    s = get_settings()

    # 解析 --test [subsystem...] 参数
    test_subsystems = None  # None = 未使用 --test
    if "--test" in sys.argv:
        test_idx = sys.argv.index("--test")
        # 收集 --test 后面的子系统名称（直到下一个 --xxx 参数或末尾）
        test_subsystems = []
        for arg in sys.argv[test_idx + 1:]:
            if arg.startswith("--"):
                break
            test_subsystems.append(arg)

    _configure_logging(test_subsystems, s.log_level)

    # --card: 发送 mock 候选卡片后继续启动 WS 监听回调
    if "--card" in sys.argv:
        token = feishu.get_token_sync()
        candidate = build_mock_candidate(token)
        card = build_candidate_card(candidate)
        msg_id = feishu.send_card_sync(token, s.feishu_receive_id, card)
        print(f"Mock 候选卡片已发送! message_id={msg_id}")
        print("启动 WebSocket 监听回调...")

    # --result: 发送 mock 结果卡片（用 output/ 目录图片），创建 EditSession 使按钮可用
    if "--result" in sys.argv:
        from pathlib import Path
        from cards import build_result_card

        token = feishu.get_token_sync()
        receive_id = s.feishu_receive_id

        # 找 output/ 下第一张 PNG
        output_dir = Path("output")
        pngs = sorted(output_dir.glob("*.png"))
        if not pngs:
            print("output/ 目录下没有 PNG 文件，跳过 --result")
        else:
            img_path = pngs[0]
            img_bytes = img_path.read_bytes()
            print(f"使用测试图片: {img_path} ({len(img_bytes)} bytes)")

            from uuid import uuid4
            image_key = feishu.upload_image_sync(token, img_bytes)
            file_key = feishu.upload_file_sync(token, img_bytes, "gift_mock.png")
            rid = "mock_result"
            mock_image_id = uuid4().hex[:8]
            card = build_result_card(image_key, rid, "Mock | Test | 1 coin", image_id=mock_image_id)
            msg_id = feishu.send_card_sync(token, receive_id, card)
            print(f"Mock 结果卡片已发送! message_id={msg_id}, image_id={mock_image_id}")

            # 创建 EditSession 使 Modify/Download 按钮可用
            mock_session = EditSession(
                user_id=receive_id,
                state=SessionState.EDITING,
                request_id=rid,
                current_image=img_bytes,
                original_config=GenerationConfig(region="MENA", subject="test", price=1),
                file_key=file_key,
            )
            mock_session.message_id_map[msg_id] = "final"
            mock_session.image_map[msg_id] = img_bytes
            mock_session.image_map[mock_image_id] = img_bytes
            save_session(mock_session)
            print(f"Mock EditSession 已创建: user={receive_id}")
        print("启动 WebSocket 监听回调...")

    # 注册事件处理器
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_application_bot_menu_v6(on_menu)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )

    # Lark SDK 日志级别：仅 --test（无参数）时显示 DEBUG，其余情况只显示 INFO
    # --test card route 等子系统过滤模式下也静默 SDK 噪音
    sdk_log_level = (lark.LogLevel.DEBUG
                     if test_subsystems is not None and len(test_subsystems) == 0
                     else lark.LogLevel.INFO)
    cli = lark.ws.Client(
        s.feishu_app_id,
        s.feishu_app_secret,
        event_handler=event_handler,
        log_level=sdk_log_level,
    )

    logger.info("飞书礼物机器人已就绪!")
    cli.start()


if __name__ == "__main__":
    main()
