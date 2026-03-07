# Image Edit Flow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a multi-turn image editing flow after candidate selection, using a pluggable EditProvider and session state machine.

**Architecture:** User-level session state machine (IDLE → SELECTING → EDITING → DELIVERED) with message router in bot_ws.py. EditProvider ABC enables pluggable backends (Gemini first). Session store uses same in-memory dict+TTL pattern as candidate_store.

**Tech Stack:** Python 3.12, httpx (async), Pydantic, lark_oapi (Feishu SDK), Gemini generateContent API with multi-modal response

**Design doc:** `docs/plans/2026-03-07-image-edit-flow-design.md`

**Test runner:** `pytest` (install first: `pip install pytest`). Existing test pattern: `tests/test_<module>.py`, uses `monkeypatch` fixture, `sys.path.insert` for imports.

---

### Task 1: Data Models — SessionState, EditSession, EditResult

**Files:**
- Modify: `models.py` (append after `CandidateResult` class, ~line 222)
- Test: `tests/test_session_models.py`

**Step 1: Write the failing test**

Create `tests/test_session_models.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'SessionState' from 'models'`

**Step 3: Write minimal implementation**

Append to `models.py` after `CandidateResult` (after line 222):

```python
# ── 编辑 Session 模型 ─────────────────────────────────────


class SessionState(str, Enum):
    """编辑 Session 状态枚举。"""
    SELECTING = "selecting"
    EDITING   = "editing"
    DELIVERED = "delivered"


class EditSession(BaseModel):
    """用户级编辑 Session，存储编辑流状态和对话历史。"""
    user_id: str
    state: SessionState
    request_id: str
    current_image: bytes = Field(exclude=True)
    conversation_history: list[dict] = Field(default_factory=list)
    message_id_map: dict[str, str] = Field(default_factory=dict)
    original_config: GenerationConfig
    last_active: float = Field(default_factory=lambda: __import__('time').time())


class EditResult(BaseModel):
    """图片编辑结果：编辑后图片 + AI 引导文字 + 更新后对话历史。"""
    image: bytes = Field(exclude=True)
    message: str
    updated_history: list[dict] = Field(default_factory=list)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_models.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add models.py tests/test_session_models.py
git commit -m "feat(models): add SessionState, EditSession, EditResult"
```

---

### Task 2: Session Store

**Files:**
- Create: `pipeline/session_store.py`
- Test: `tests/test_session_store.py`

**Step 1: Write the failing test**

Create `tests/test_session_store.py`:

```python
"""Session 存储模块测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import SessionState, EditSession, GenerationConfig


def _make_session(uid="ou_test", state=SessionState.EDITING) -> EditSession:
    config = GenerationConfig(region="MENA", subject="雄狮", price=1)
    return EditSession(
        user_id=uid, state=state, request_id="req123",
        current_image=b"img", original_config=config,
    )


def test_save_and_get():
    from pipeline.session_store import save, get, _store
    _store.clear()
    s = _make_session()
    save(s)
    assert get("ou_test") is not None
    assert get("ou_test").state == SessionState.EDITING


def test_get_nonexistent():
    from pipeline.session_store import get, _store
    _store.clear()
    assert get("no_such_user") is None


def test_remove():
    from pipeline.session_store import save, get, remove, _store
    _store.clear()
    save(_make_session())
    remove("ou_test")
    assert get("ou_test") is None


def test_cleanup_expired(monkeypatch):
    from pipeline import session_store
    from pipeline.session_store import save, cleanup, get, _store
    _store.clear()
    save(_make_session())
    monkeypatch.setattr(session_store, "_TTL", 0)
    cleanup()
    assert get("ou_test") is None


def test_overwrite_existing():
    """同一用户保存新 session 覆盖旧的。"""
    from pipeline.session_store import save, get, _store
    _store.clear()
    s1 = _make_session(state=SessionState.SELECTING)
    save(s1)
    s2 = _make_session(state=SessionState.DELIVERED)
    save(s2)
    assert get("ou_test").state == SessionState.DELIVERED
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.session_store'`

**Step 3: Write implementation**

Create `pipeline/session_store.py`:

```python
"""编辑 Session 暂存：用户级状态管理，TTL 自动过期。"""

import logging
import threading
import time

from models import EditSession

logger = logging.getLogger(__name__)

_store: dict[str, tuple[EditSession, float]] = {}
_lock = threading.Lock()
_TTL = 1800  # 30 分钟


def save(session: EditSession) -> None:
    """保存/覆盖用户的编辑 session。"""
    with _lock:
        _store[session.user_id] = (session, time.time())
    logger.info("[Session] 保存 user=%s, state=%s", session.user_id, session.state)


def get(user_id: str) -> EditSession | None:
    """获取用户的编辑 session，过期返回 None。"""
    with _lock:
        _cleanup_locked()
        entry = _store.get(user_id)
        if entry is None:
            return None
        session, ts = entry
        if time.time() - ts > _TTL:
            del _store[user_id]
            logger.info("[Session] user=%s 已过期", user_id)
            return None
        return session


def remove(user_id: str) -> None:
    """删除用户的编辑 session。"""
    with _lock:
        _store.pop(user_id, None)


def cleanup() -> None:
    """清理所有过期 session。"""
    with _lock:
        _cleanup_locked()


def _cleanup_locked() -> None:
    now = time.time()
    expired = [uid for uid, (_, ts) in _store.items() if now - ts > _TTL]
    for uid in expired:
        del _store[uid]
    if expired:
        logger.info("[Session] 清理 %d 条过期 session", len(expired))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_store.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add pipeline/session_store.py tests/test_session_store.py
git commit -m "feat(session): add session_store with TTL expiration"
```

---

### Task 3: EditProvider ABC + GeminiEditProvider

**Files:**
- Modify: `providers/base.py` (append after `TextProvider` class, ~line 27)
- Modify: `providers/gemini.py` (append new class at end)
- Modify: `providers/registry.py` (add edit provider registry)
- Test: `tests/test_edit_provider.py`

**Step 1: Write the failing test**

Create `tests/test_edit_provider.py`:

```python
"""EditProvider 接口和注册测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import EditResult
from providers.base import EditProvider


def test_edit_provider_is_abstract():
    """EditProvider 不能直接实例化。"""
    import pytest
    with pytest.raises(TypeError):
        EditProvider()


def test_gemini_edit_provider_exists():
    """GeminiEditProvider 已注册。"""
    from providers.registry import get_edit_provider
    provider = get_edit_provider("gemini", timeout=30)
    assert isinstance(provider, EditProvider)


def test_edit_provider_registry_unknown():
    """未知供应商抛 KeyError。"""
    import pytest
    from providers.registry import get_edit_provider
    with pytest.raises(KeyError, match="未知的编辑供应商"):
        get_edit_provider("nonexistent")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_edit_provider.py -v`
Expected: FAIL — `ImportError: cannot import name 'EditProvider' from 'providers.base'`

**Step 3a: Add EditProvider ABC to `providers/base.py`**

Append after `TextProvider` class:

```python
class EditProvider(ABC):
    """图片编辑供应商抽象基类。"""

    @abstractmethod
    async def edit(
        self,
        image: bytes,
        instruction: str,
        conversation_history: list[dict] | None = None,
    ) -> "EditResult":
        """编辑图片，返回 EditResult（编辑后图片 + AI 引导文字 + 更新后历史）。"""
        ...
```

**Step 3b: Add GeminiEditProvider to `providers/gemini.py`**

Append at end of file:

```python
class GeminiEditProvider:
    """基于 Gemini generateContent 的图片编辑供应商。

    利用 responseModalities: ["TEXT", "IMAGE"] 一次调用
    同时返回编辑后图片和 AI 引导文字。
    """

    def __init__(self, models: list[str] | None = None, timeout: int | None = None):
        s = get_settings()
        self.api_key = s.gemini_api_key
        self.base_url = s.gemini_base_url
        from defaults import load_defaults
        d = load_defaults()
        self.models = models or d.edit_models
        self.timeout = timeout if timeout is not None else d.edit_timeout

    async def edit(self, image, instruction, conversation_history=None):
        from models import EditResult

        history = list(conversation_history or [])
        current_turn = {
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(image).decode()}},
                {"text": instruction},
            ],
        }
        contents = history + [current_turn]

        errors = []
        for model in self.models:
            try:
                logger.info("  [Edit] 尝试模型: %s", model)
                url = f"{self.base_url}/models/{model}:generateContent"
                headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
                body = {
                    "contents": contents,
                    "generationConfig": {
                        "responseModalities": ["TEXT", "IMAGE"],
                    },
                }
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()

                candidates = data.get("candidates", [])
                if not candidates:
                    errors.append(f"{model}: 无 candidates")
                    continue

                parts = candidates[0].get("content", {}).get("parts", [])
                edited_image = None
                message_text = ""
                for part in parts:
                    if "inlineData" in part:
                        edited_image = base64.b64decode(part["inlineData"]["data"])
                    if "text" in part:
                        message_text += part["text"]

                if edited_image is None:
                    errors.append(f"{model}: 响应中无图片")
                    continue

                # 更新对话历史
                updated = contents + [{"role": "model", "parts": parts}]

                return EditResult(
                    image=edited_image,
                    message=message_text or "编辑完成，还需要调整什么吗？",
                    updated_history=updated,
                )
            except Exception as e:
                logger.warning("  [Edit] %s 失败: %s", model, e)
                errors.append(f"{model}: {e}")
                continue

        raise RuntimeError(f"所有编辑模型均失败: {'; '.join(errors)}")
```

**Step 3c: Add edit provider registry to `providers/registry.py`**

Add after existing `_text_providers` dict and register functions:

```python
_edit_providers: dict[str, type] = {}


def register_edit_provider(name: str, cls: type):
    """注册一个图片编辑供应商。"""
    _edit_providers[name] = cls


def get_edit_provider(name: str | None = None, **kwargs):
    """根据名称获取编辑供应商实例。"""
    name = name or load_defaults().edit_provider
    cls = _edit_providers.get(name)
    if cls is None:
        raise KeyError(f"未知的编辑供应商: {name!r}，已注册: {list(_edit_providers)}")
    return cls(**kwargs)
```

At the bottom, add registration:

```python
from providers.gemini import GeminiEditProvider  # noqa: E402
register_edit_provider("gemini", GeminiEditProvider)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_edit_provider.py -v`
Expected: All 3 tests PASS

Note: `test_gemini_edit_provider_exists` will need `edit_models` and `edit_timeout` in defaults. Proceed to Task 4 before running, or temporarily add them first.

**Step 5: Commit**

```bash
git add providers/base.py providers/gemini.py providers/registry.py tests/test_edit_provider.py
git commit -m "feat(providers): add EditProvider ABC + GeminiEditProvider"
```

---

### Task 4: Configuration — generation_defaults.yaml + models

**Files:**
- Modify: `generation_defaults.yaml` (append edit config section)
- Modify: `models.py` — `GenerationDefaults` class (~line 48-76)
- Test: `tests/test_edit_defaults.py`

**Step 1: Write the failing test**

Create `tests/test_edit_defaults.py`:

```python
"""编辑流配置加载测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from defaults import load_defaults


def test_edit_defaults_loaded():
    d = load_defaults()
    assert d.edit_provider == "gemini"
    assert len(d.edit_models) >= 1
    assert d.edit_timeout > 0
    assert d.edit_max_rounds >= 1
    assert d.edit_session_ttl > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_edit_defaults.py -v`
Expected: FAIL — `AttributeError: 'GenerationDefaults' object has no attribute 'edit_provider'`

**Step 3a: Add to `generation_defaults.yaml`**

Append before `# ── 层级配置` section:

```yaml
# ── 编辑流 ────────────────────────────────────────────────
edit_provider: "gemini"
edit_models:
  - "gemini-3.1-flash-image-preview"
edit_timeout: 120
edit_max_rounds: 10
edit_session_ttl: 1800
```

**Step 3b: Add fields to `GenerationDefaults` in `models.py`**

Inside the `GenerationDefaults` class, after `prompt_gen_system_prompt`, add:

```python
    # 编辑流
    edit_provider: str = "gemini"
    edit_models: list[str] = Field(default_factory=lambda: ["gemini-3.1-flash-image-preview"])
    edit_timeout: int = Field(default=120, ge=1, le=600)
    edit_max_rounds: int = Field(default=10, ge=1, le=50)
    edit_session_ttl: int = Field(default=1800, ge=60, le=7200)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_edit_defaults.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add generation_defaults.yaml models.py tests/test_edit_defaults.py
git commit -m "feat(config): add edit flow settings to defaults"
```

---

### Task 5: Routing Card

**Files:**
- Modify: `cards.py` (append new function after `build_mock_candidate`)
- Test: `tests/test_routing_card.py`

**Step 1: Write the failing test**

Create `tests/test_routing_card.py`:

```python
"""路由卡片构建测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cards import build_routing_card


def test_routing_card_structure():
    card = build_routing_card("req123")
    assert card["schema"] == "2.0"
    assert "header" in card
    assert "body" in card


def test_routing_card_has_two_buttons():
    card = build_routing_card("req123")
    elements = card["body"]["elements"]
    buttons = [e for e in _flatten(elements) if isinstance(e, dict) and e.get("tag") == "button"]
    assert len(buttons) == 2


def test_routing_card_action_values():
    card = build_routing_card("req123")
    elements = card["body"]["elements"]
    buttons = [e for e in _flatten(elements) if isinstance(e, dict) and e.get("tag") == "button"]
    actions = {b["value"]["action"] for b in buttons}
    assert actions == {"route_regen", "route_continue"}
    for b in buttons:
        assert b["value"]["request_id"] == "req123"


def _flatten(obj):
    """递归展开嵌套结构中的所有 dict。"""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _flatten(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _flatten(item)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_routing_card.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_routing_card' from 'cards'`

**Step 3: Implement `build_routing_card` in `cards.py`**

Append after `build_mock_candidate` function:

```python
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_routing_card.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add cards.py tests/test_routing_card.py
git commit -m "feat(cards): add routing card for post-edit navigation"
```

---

### Task 6: Edit Orchestrator — `pipeline/edit.py`

**Files:**
- Create: `pipeline/edit.py`
- Create: `prompts/edit_system.md`
- Test: `tests/test_edit_orchestrator.py`

**Step 1: Write the failing test**

Create `tests/test_edit_orchestrator.py`:

```python
"""编辑编排逻辑测试（mock provider）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.edit import matches_termination


def test_termination_positive():
    for word in ["好了", "不用了", "OK", "ok", "done", "Done", "不需要了"]:
        assert matches_termination(word), f"should match: {word}"


def test_termination_negative():
    for word in ["把背景改成红色", "加个皇冠", "雄狮 100", ""]:
        assert not matches_termination(word), f"should not match: {word}"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_edit_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.edit'`

**Step 3a: Create `prompts/edit_system.md`**

```markdown
You are a gift image editor. The user will provide an image and an editing instruction.

Your job:
1. Edit the image according to the instruction
2. Respond with BOTH the edited image AND a brief, helpful message in Chinese

Message guidelines:
- Describe what you changed (1 sentence)
- Suggest 1-2 possible next adjustments the user might want
- Keep it friendly and concise
- Example: "已将背景改为红色。你还可以试试加一些金色装饰，或者调整主体的大小。"

If the instruction is unclear, do your best and ask for clarification in your message.
```

**Step 3b: Create `pipeline/edit.py`**

```python
"""编辑流编排：handle_edit / handle_editing_text / matches_termination。"""

import logging
import time
from pathlib import Path

import feishu
from models import EditSession, SessionState
from providers.registry import get_edit_provider

logger = logging.getLogger(__name__)

_EDIT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "edit_system.md"

_TERMINATION_WORDS = {"好了", "不用了", "不需要了", "OK", "ok", "done", "Done", "算了", "结束"}


def _load_edit_system_prompt() -> str:
    return _EDIT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


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
    from pipeline.session_store import save as save_session

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
        round_num = len([k for k in session.message_id_map if k.startswith("edit_")]) + 1
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_edit_orchestrator.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add pipeline/edit.py prompts/edit_system.md tests/test_edit_orchestrator.py
git commit -m "feat(edit): add edit orchestrator + system prompt"
```

---

### Task 7: Bot Message Router — `bot_ws.py`

**Files:**
- Modify: `bot_ws.py` — rewrite `on_message` function (~line 131-159), add imports, modify `handle_finalize` (~line 117-127), add new card actions to `on_card_action` (~line 207-298)

**Step 1: Add imports at top of `bot_ws.py`**

After existing imports (~line 36-38), add:

```python
from pipeline.edit import handle_edit, handle_editing_text
from pipeline.session_store import get as get_session, save as save_session, remove as remove_session
from models import SessionState, EditSession
```

**Step 2: Rewrite `on_message` function**

Replace the existing `on_message` (~line 131-159) with:

```python
def on_message(data: P2ImMessageReceiveV1) -> None:
    """处理用户消息：根据 session 状态和 parent_id 路由到正确流程。"""
    event = data.event
    sender_id = event.sender.sender_id.open_id
    msg_type = event.message.message_type
    parent_id = event.message.parent_id
    content = json.loads(event.message.content)

    logger.info("[消息] %s: type=%s, parent_id=%s, content=%s",
                sender_id, msg_type, parent_id, content)

    if msg_type != "text":
        return

    text = content.get("text", "").strip()
    if not text:
        return

    session = get_session(sender_id)

    # 路由1: 回复了 bot 发出的图片 → 编辑
    if parent_id and session and parent_id in session.message_id_map:
        logger.info("[路由] 回复图片编辑: user=%s, parent=%s", sender_id, parent_id)
        threading.Thread(
            target=handle_edit, args=(sender_id, session, text), daemon=True,
        ).start()
        return

    # 路由2: 有活跃 EDITING/DELIVERED session + 纯文字
    if session and session.state in (SessionState.EDITING, SessionState.DELIVERED):
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
```

**Step 3: Modify `handle_finalize` to create EditSession**

Replace `handle_finalize` (~line 117-127) with:

```python
def handle_finalize(sender_id: str, request_id: str, selected_index: int) -> None:
    """Phase 2: 处理用户选择，执行后处理，创建编辑 session。"""
    token = feishu.get_token_sync()
    try:
        feishu.send_text_sync(token, sender_id, f"已选择方案 {selected_index + 1}，正在处理...")
        result = _run_async(finalize_selected(request_id, selected_index))
        logger.info("Phase 2 完成: %s -> %s", request_id, result.status)

        # 创建 EditSession
        candidate = get_candidate(request_id)
        if candidate and result.media_bytes and result.message_id:
            session = EditSession(
                user_id=sender_id,
                state=SessionState.EDITING,
                request_id=request_id,
                current_image=result.media_bytes,
                original_config=candidate.config,
            )
            session.message_id_map[result.message_id] = "final"
            save_session(session)
            logger.info("[Session] 已创建 user=%s, request_id=%s", sender_id, request_id)
    except Exception as e:
        logger.error("Phase 2 失败: %s", e, exc_info=True)
        feishu.send_text_sync(token, sender_id, f"处理失败: {e}")
```

**Step 4: Add routing card actions to `on_card_action`**

Inside `on_card_action`, in the `if isinstance(action_value, dict) and action_value.get("action"):` block, add before the "未知 action" warning:

```python
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
```

**Step 5: Run manual smoke test**

```bash
python3 bot_ws.py --test card
# 在飞书中发送消息，观察日志中的 [路由] 前缀输出
```

**Step 6: Commit**

```bash
git add bot_ws.py
git commit -m "feat(bot): message router + edit session lifecycle"
```

---

### Task 8: Integration Smoke Test + Cleanup

**Files:**
- Modify: `pipeline/__init__.py` (export edit functions if needed)
- Run full integration test

**Step 1: Verify all unit tests pass**

```bash
pip install pytest  # if not already
pytest tests/ -v
```
Expected: All tests PASS

**Step 2: Manual integration test**

```bash
python3 bot_ws.py --test card
```

Test sequence in Feishu:
1. Send "雄狮 100" → should trigger generate (existing flow)
2. Select candidate A → should see "正在处理" + final image + session created (check logs for `[Session]`)
3. Reply to the final image with "把背景改成红色" → should trigger edit (check logs for `[路由] 回复图片编辑`)
4. Send "好了" → should get routing card
5. Click "No" → should get toast "继续编辑"
6. Send "加个皇冠" (without replying) → should trigger edit on current image
7. Send "好了" → routing card again
8. Click "Yes" → should regenerate

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: integration adjustments for edit flow"
```

---

## Task Dependency Graph

```
Task 1 (models) ──→ Task 2 (session_store) ──→ Task 6 (edit orchestrator) ──→ Task 7 (bot router)
                                                      ↑                              ↑
Task 4 (config) ──→ Task 3 (EditProvider) ────────────┘                              │
                                                                                     │
Task 5 (routing card) ──────────────────────────────────────────────────────────────┘

Task 8 (integration) depends on all above
```

**Parallelizable:** Tasks 1+4+5 can run in parallel. Tasks 2+3 depend on 1 and 4 respectively. Task 6 depends on 2+3. Task 7 depends on 5+6.
