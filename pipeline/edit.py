"""编辑流编排：handle_edit / handle_editing_text / matches_termination。"""

import logging
import time

import feishu
from models import EditSession, SessionState
from providers.registry import get_edit_provider

logger = logging.getLogger(__name__)

_TERMINATION_WORDS = {"好了", "不用了", "不需要了", "OK", "ok", "done", "Done", "算了", "结束"}


def matches_termination(text: str) -> bool:
    """判断用户输入是否表示结束编辑。"""
    return text.strip() in _TERMINATION_WORDS


def _run_async(coro):
    """在同步上下文中安全运行协程。"""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def handle_edit(sender_id: str, session: EditSession, text: str) -> None:
    """执行一轮图片编辑：调用 EditProvider → 发送结果 → 更新 session。"""
    from defaults import load_defaults
    from pipeline.session_store import save as save_session

    # 检查是否超过最大编辑次数
    round_num = len([v for v in session.message_id_map.values() if v.startswith("edit_")]) + 1
    d = load_defaults()
    if round_num > d.edit_max_rounds:
        from cards import build_routing_card
        session.state = SessionState.DELIVERED
        save_session(session)
        token = feishu.get_token_sync()
        feishu.send_text_sync(token, sender_id, f"已达到最大编辑次数 ({d.edit_max_rounds})，请选择下一步操作。")
        feishu.send_card_sync(token, sender_id, build_routing_card(session.request_id))
        return

    token = feishu.get_token_sync()
    feishu.send_text_sync(token, sender_id, "正在编辑图片...")

    try:
        provider = get_edit_provider()
        result = _run_async(provider.edit(
            image=session.current_image,
            instruction=text,
            conversation_history=session.conversation_history,
        ))

        # 上传编辑后图片
        image_key = feishu.upload_image_sync(token, result.image)
        msg_id = feishu.send_image_sync(token, sender_id, image_key)
        feishu.send_text_sync(token, sender_id, result.message)

        # 更新 session
        session.current_image = result.image
        session.conversation_history = result.updated_history
        session.message_id_map[msg_id] = f"edit_{round_num}"
        session.state = SessionState.EDITING
        session.last_active = time.time()
        save_session(session)

        logger.info("[Edit] user=%s round=%d 完成", sender_id, round_num)
    except Exception as e:
        logger.error("[Edit] 编辑失败: %s", e, exc_info=True)
        feishu.send_text_sync(token, sender_id, f"编辑失败: {e}")


def handle_editing_text(sender_id: str, session: EditSession, text: str) -> None:
    """EDITING/DELIVERED 状态下收到纯文字（非回复图片）的处理。"""
    from cards import build_routing_card
    from pipeline.session_store import save as save_session

    if matches_termination(text):
        session.state = SessionState.DELIVERED
        save_session(session)
        token = feishu.get_token_sync()
        feishu.send_card_sync(token, sender_id, build_routing_card(session.request_id))
        logger.info("[Edit] user=%s 结束编辑，发送路由卡片", sender_id)
    else:
        # 当作对 current_image 的编辑指令
        handle_edit(sender_id, session, text)
