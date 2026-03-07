"""EditSession / EditResult 数据模型测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import SessionState, EditSession, EditResult, GenerationConfig


def test_session_state_values():
    assert SessionState.SELECTING == "selecting"
    assert SessionState.EDITING == "editing"
    assert SessionState.DELIVERED == "delivered"


def test_edit_session_creation():
    config = GenerationConfig(region="MENA", subject="雄狮", price=1)
    session = EditSession(
        user_id="ou_123",
        state=SessionState.EDITING,
        request_id="abc123",
        current_image=b"fake_img",
        original_config=config,
    )
    assert session.user_id == "ou_123"
    assert session.state == SessionState.EDITING
    assert session.conversation_history == []
    assert session.message_id_map == {}
    assert session.last_active > 0


def test_edit_session_defaults():
    config = GenerationConfig(region="MENA", subject="雄狮", price=1)
    session = EditSession(
        user_id="ou_456",
        state=SessionState.SELECTING,
        request_id="def456",
        current_image=b"",
        original_config=config,
    )
    assert session.conversation_history == []
    assert session.message_id_map == {}


def test_edit_result_creation():
    result = EditResult(
        image=b"edited_img",
        message="已调整背景颜色",
        updated_history=[{"role": "user", "parts": [{"text": "test"}]}],
    )
    assert result.image == b"edited_img"
    assert result.message == "已调整背景颜色"
    assert len(result.updated_history) == 1
