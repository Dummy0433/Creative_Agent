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


def handle_edit(sender_id: str, session: EditSession, text: str,
                parent_id: str | None = None) -> None:
    """执行一轮图片编辑：调用 EditProvider → 发送结果 → 更新 session。

    parent_id 用于确定编辑哪张图片：
    - 有 parent_id 且在 image_map 中 → 编辑用户回复的那张图
    - 否则 → 编辑 current_image（最新图片）
    """
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

    # 按 parent_id 查找要编辑的图片
    if parent_id and parent_id in session.image_map:
        edit_image = session.image_map[parent_id]
        logger.info("[Edit] user=%s 编辑指定图片: parent=%s", sender_id, parent_id)
    else:
        edit_image = session.current_image
        logger.info("[Edit] user=%s 编辑最新图片", sender_id)

    token = feishu.get_token_sync()
    feishu.send_text_sync(token, sender_id, "正在编辑图片...")

    try:
        provider = get_edit_provider()
        result = _run_async(provider.edit(
            image=edit_image,
            instruction=text,
            conversation_history=session.conversation_history,
        ))

        # 结果卡片：内嵌预览 + Modify/Download 按钮（并行上传 image + file）
        from cards import build_result_card
        from uuid import uuid4
        image_key = feishu.upload_image_sync(token, result.image)
        file_key = feishu.upload_file_sync(token, result.image, "gift_edit.png")
        image_id = uuid4().hex[:8]
        card = build_result_card(image_key, session.request_id, result.message, image_id=image_id)
        msg_id = feishu.send_card_sync(token, sender_id, card)

        # 更新 session
        session.current_image = result.image
        session.file_key = file_key
        session.image_map[msg_id] = result.image
        session.image_map[image_id] = result.image
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
    """EDITING/DELIVERED 状态下收到纯文字（非回复图片）：始终发送路由卡片。

    纯文字（不是回复某张图片）意味着用户不在编辑图片，
    发送路由卡片让用户选择：重新生成 or 继续编辑。
    """
    from cards import build_routing_card
    from pipeline.session_store import save as save_session

    session.state = SessionState.DELIVERED
    save_session(session)
    token = feishu.get_token_sync()
    feishu.send_card_sync(token, sender_id, build_routing_card(session.request_id))
    logger.info("[Edit] user=%s 纯文字输入'%s'，发送路由卡片", sender_id, text[:20])
