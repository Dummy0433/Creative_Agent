# Inspire (灵感对话) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a conversational AI gift creative advisor that extracts user intent/slots, queries Bitable tables for context, and generates creative suggestions with three exit paths (continue chat, generate, request).

**Architecture:** Two-step serial: (1) flash-lite extracts intent + slots from user message, (2) if slots changed, query TABLE0-3 for context, (3) main model generates response using domain knowledge + table context + conversation history. InspireSession stores per-user state with TTL auto-cleanup. Exit intents (generate/request) terminate session and route to existing features.

**Tech Stack:** Gemini API (flash-lite for extraction, flash for conversation), Feishu Bitable API (TABLE0-3 reuse from `pipeline/data.py`), Feishu messaging (text responses via `feishu.send_text_sync`)

---

### Task 1: Config + InspireSession Model

**Files:**
- Modify: `generation_defaults.yaml:71-73` (add inspire config section)
- Modify: `models.py` (add InspireSlots, InspireSession)
- Modify: `defaults.py` (add inspire fields to GenerationDefaults)
- Test: `tests/test_inspire_config.py`

**Step 1: Write the failing test**

Create `tests/test_inspire_config.py`:

```python
"""Inspire 配置和模型测试。"""

from models import InspireSlots, InspireSession


def test_inspire_slots_defaults():
    """InspireSlots 默认值全为 None。"""
    slots = InspireSlots()
    assert slots.region is None
    assert slots.price is None
    assert slots.price_hint is None
    assert slots.subject is None


def test_inspire_slots_update():
    """InspireSlots 可以部分更新。"""
    slots = InspireSlots(region="MENA")
    assert slots.region == "MENA"
    assert slots.price is None


def test_inspire_session_creation():
    """InspireSession 创建时有正确的默认值。"""
    session = InspireSession(user_id="ou_test")
    assert session.user_id == "ou_test"
    assert session.slots == InspireSlots()
    assert session.conversation_history == []
    assert session.table_context == ""


def test_inspire_session_has_new_slots():
    """has_new_slots 检测槽位是否有变化。"""
    session = InspireSession(user_id="ou_test")
    old = session.slots.model_copy()

    # 无变化
    assert not _slots_changed(old, session.slots)

    # 有变化
    session.slots.region = "US"
    assert _slots_changed(old, session.slots)


def _slots_changed(old: InspireSlots, new: InspireSlots) -> bool:
    """辅助函数：测试用，实际逻辑在 inspire.py 中。"""
    return old != new


def test_inspire_config_loaded():
    """generation_defaults.yaml 中的 inspire 配置可正常加载。"""
    from defaults import load_defaults
    d = load_defaults()
    assert d.inspire_extract_model
    assert d.inspire_chat_model
    assert d.inspire_session_ttl > 0
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_inspire_config.py -v`
Expected: FAIL (InspireSlots, InspireSession not defined)

**Step 3: Write minimal implementation**

Add to `generation_defaults.yaml` after the request section:

```yaml
# -- Inspire 灵感对话 --------------------------------------------------------
inspire_extract_model: "gemini-3.1-flash-lite-preview"
inspire_chat_model: "gemini-3.1-flash-lite-preview"
inspire_session_ttl: 1800
```

Add to `defaults.py` GenerationDefaults class (add 3 fields):

```python
inspire_extract_model: str = "gemini-3.1-flash-lite-preview"
inspire_chat_model: str = "gemini-3.1-flash-lite-preview"
inspire_session_ttl: int = 1800
```

Add to `models.py`:

```python
class InspireSlots(BaseModel):
    """Inspire 对话槽位。"""
    region: str | None = None
    price: int | None = None
    price_hint: str | None = None  # "low", "mid", "high"
    subject: str | None = None


class InspireSession(BaseModel):
    """Inspire 灵感对话 session。"""
    user_id: str
    slots: InspireSlots = Field(default_factory=InspireSlots)
    conversation_history: list[dict] = Field(default_factory=list)
    table_context: str = ""
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_inspire_config.py -v`
Expected: PASS (5 passed)

**Step 5: Commit**

```bash
git add generation_defaults.yaml defaults.py models.py tests/test_inspire_config.py
git commit -m "feat(inspire): add InspireSession model + config"
```

---

### Task 2: Inspire Session Store

**Files:**
- Create: `pipeline/inspire_store.py`
- Test: `tests/test_inspire_store.py`

**Step 1: Write the failing test**

Create `tests/test_inspire_store.py`:

```python
"""Inspire session store 测试。"""

import time
from unittest.mock import patch

from models import InspireSession, InspireSlots


def test_save_and_get():
    """保存后可以获取 session。"""
    from pipeline import inspire_store
    inspire_store._store.clear()

    session = InspireSession(user_id="ou_1")
    inspire_store.save(session)
    result = inspire_store.get("ou_1")
    assert result is not None
    assert result.user_id == "ou_1"


def test_get_nonexistent():
    """获取不存在的 session 返回 None。"""
    from pipeline import inspire_store
    inspire_store._store.clear()

    assert inspire_store.get("ou_nonexist") is None


def test_remove():
    """删除 session。"""
    from pipeline import inspire_store
    inspire_store._store.clear()

    session = InspireSession(user_id="ou_2")
    inspire_store.save(session)
    inspire_store.remove("ou_2")
    assert inspire_store.get("ou_2") is None


def test_ttl_expiry():
    """过期的 session 自动清理。"""
    from pipeline import inspire_store
    inspire_store._store.clear()

    session = InspireSession(user_id="ou_3")
    inspire_store.save(session)

    # 模拟过期
    with patch("time.time", return_value=time.time() + 9999):
        assert inspire_store.get("ou_3") is None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_inspire_store.py -v`
Expected: FAIL (module not found)

**Step 3: Write minimal implementation**

Create `pipeline/inspire_store.py`:

```python
"""Inspire Session 暂存：用户级状态管理，TTL 自动过期。"""

import logging
import threading
import time

from defaults import load_defaults
from models import InspireSession

logger = logging.getLogger(__name__)

_store: dict[str, tuple[InspireSession, float]] = {}
_lock = threading.Lock()
_TTL = load_defaults().inspire_session_ttl


def save(session: InspireSession) -> None:
    """保存/覆盖用户的 inspire session。"""
    with _lock:
        _store[session.user_id] = (session, time.time())
    logger.info("[Inspire] 保存 session user=%s", session.user_id)


def get(user_id: str) -> InspireSession | None:
    """获取用户的 inspire session，过期返回 None。"""
    with _lock:
        entry = _store.get(user_id)
        if entry is None:
            return None
        session, ts = entry
        if time.time() - ts > _TTL:
            del _store[user_id]
            logger.info("[Inspire] user=%s session 已过期", user_id)
            return None
        return session


def remove(user_id: str) -> None:
    """删除用户的 inspire session。"""
    with _lock:
        _store.pop(user_id, None)
    logger.info("[Inspire] 删除 session user=%s", user_id)
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_inspire_store.py -v`
Expected: PASS (4 passed)

**Step 5: Commit**

```bash
git add pipeline/inspire_store.py tests/test_inspire_store.py
git commit -m "feat(inspire): add inspire session store with TTL"
```

---

### Task 3: Slot Extraction (Prompt + LLM Call)

**Files:**
- Create: `prompts/inspire_extract.md`
- Create: `pipeline/inspire.py` (extraction function only)
- Test: `tests/test_inspire_extract.py`

**Step 1: Write the failing test**

Create `tests/test_inspire_extract.py`:

```python
"""Inspire 意图提取测试。"""

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_extract_region():
    """提取区域信息。"""
    from pipeline.inspire import extract_slots

    mock_response = {
        "region": "MENA",
        "price": None,
        "subject": None,
        "price_hint": None,
        "intent": "chat",
    }
    with patch("pipeline.inspire._call_extract_llm", new_callable=AsyncMock, return_value=mock_response):
        from models import InspireSlots
        result = await extract_slots("我想做一个中东风格的礼物", InspireSlots())
    assert result["region"] == "MENA"
    assert result["intent"] == "chat"


@pytest.mark.asyncio
async def test_extract_generate_intent():
    """提取生成意图。"""
    from pipeline.inspire import extract_slots

    mock_response = {
        "region": "US",
        "price": 100,
        "subject": "lion",
        "price_hint": None,
        "intent": "generate",
    }
    with patch("pipeline.inspire._call_extract_llm", new_callable=AsyncMock, return_value=mock_response):
        from models import InspireSlots
        result = await extract_slots("好的我想生成一个狮子主题的", InspireSlots(region="US", price=100))
    assert result["intent"] == "generate"
    assert result["subject"] == "lion"


@pytest.mark.asyncio
async def test_extract_fallback_on_error():
    """LLM 调用失败时返回空提取结果。"""
    from pipeline.inspire import extract_slots

    with patch("pipeline.inspire._call_extract_llm", new_callable=AsyncMock, side_effect=Exception("API error")):
        from models import InspireSlots
        result = await extract_slots("随便说点什么", InspireSlots())
    assert result["intent"] == "chat"
    assert result["region"] is None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_inspire_extract.py -v`
Expected: FAIL (module not found)

**Step 3: Write the extraction prompt**

Create `prompts/inspire_extract.md`:

```markdown
You are a slot-filling assistant for a gift design creative advisor.

Given the user's message and current slot values, extract any NEW information and determine the user's intent.

## Current Slots
- region: {region}
- price: {price}
- subject: {subject}

## Output Format (JSON)
{
  "region": "extracted region or null if not mentioned",
  "price": "extracted price as integer or null",
  "subject": "extracted subject/theme or null",
  "price_hint": "low/mid/high or null (if user says 'cheap', 'expensive', etc.)",
  "intent": "chat/generate/request/stop"
}

## Intent Rules
- "chat": user is discussing, asking questions, or exploring ideas
- "generate": user explicitly wants to try generating an image (keywords: 生成, generate, 试试, try, 做一个)
- "request": user wants to submit a formal request (keywords: 提需求, 提单, submit request, 下需求)
- "stop": user wants to end the conversation (keywords: 停, 结束, 再见, bye, stop, 谢谢)

## Region Mapping (fuzzy match)
- 中东/阿拉伯/Middle East → MENA
- 美国/美区 → US
- 欧洲 → EU
- 日本 → JP
- 韩国 → KR
- 台湾 → TW
- 土耳其 → TR
- 印尼 → ID
- 越南 → VN
- 泰国 → TH
- 巴西 → BR
- 拉美 → LATAM
- 新加坡 → SG
- 全球 → Global Gift

## Price Hint Mapping
- 便宜的/低价/cheap → low
- 中等/moderate → mid
- 贵的/高价/expensive/premium → high

Only extract values that are explicitly mentioned or strongly implied. Do not guess. Return null for anything not mentioned.
```

**Step 4: Write minimal implementation**

Create `pipeline/inspire.py` (extraction function only, more functions added in later tasks):

```python
"""Inspire 灵感对话：意图提取 + 槽位填充 + 表查询 + 对话生成。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from models import InspireSlots
from settings import get_settings
from defaults import load_defaults

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "inspire_extract.md"


def _load_extract_prompt(slots: InspireSlots) -> str:
    """加载并填充提取 prompt 模板。"""
    template = _EXTRACT_PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        region=slots.region or "null",
        price=slots.price or "null",
        subject=slots.subject or "null",
    )


async def _call_extract_llm(system_prompt: str, user_message: str) -> dict:
    """调用 flash-lite 模型提取意图和槽位。"""
    s = get_settings()
    d = load_defaults()
    model = d.inspire_extract_model
    url = f"{s.gemini_base_url}/models/{model}:generateContent"
    headers = {"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"}
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


async def extract_slots(user_message: str, current_slots: InspireSlots) -> dict:
    """从用户消息中提取意图和槽位，失败时优雅降级。"""
    try:
        system_prompt = _load_extract_prompt(current_slots)
        result = await _call_extract_llm(system_prompt, user_message)
        # 确保 intent 字段存在
        if "intent" not in result:
            result["intent"] = "chat"
        return result
    except Exception as e:
        logger.warning("[Inspire] 意图提取失败，降级为 chat: %s", e)
        return {
            "region": None,
            "price": None,
            "subject": None,
            "price_hint": None,
            "intent": "chat",
        }
```

**Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_inspire_extract.py -v`
Expected: PASS (3 passed)

**Step 6: Commit**

```bash
git add prompts/inspire_extract.md pipeline/inspire.py tests/test_inspire_extract.py
git commit -m "feat(inspire): slot extraction with flash-lite + graceful fallback"
```

---

### Task 4: System Prompt + Conversation Generation

**Files:**
- Create: `prompts/inspire_system.md`
- Modify: `pipeline/inspire.py` (add conversation generation function)
- Test: `tests/test_inspire_chat.py`

**Step 1: Write the failing test**

Create `tests/test_inspire_chat.py`:

```python
"""Inspire 对话生成测试。"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_generate_response_basic():
    """基本对话生成。"""
    from pipeline.inspire import generate_response

    with patch("pipeline.inspire._call_chat_llm", new_callable=AsyncMock, return_value="这是一个很好的想法！狮子是很受欢迎的礼物主题。"):
        result = await generate_response(
            conversation_history=[],
            table_context="",
            user_message="我想做一个狮子礼物",
        )
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_generate_response_with_context():
    """带表数据上下文的对话生成。"""
    from pipeline.inspire import generate_response

    with patch("pipeline.inspire._call_chat_llm", new_callable=AsyncMock, return_value="MENA 区域的用户偏好暖色调设计。"):
        result = await generate_response(
            conversation_history=[
                {"role": "user", "text": "MENA 区域有什么偏好？"},
            ],
            table_context="MENA 区域风格：暖色调，几何图案，金色元素",
            user_message="具体说说",
        )
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_generate_response_fallback():
    """LLM 失败时返回兜底文案。"""
    from pipeline.inspire import generate_response

    with patch("pipeline.inspire._call_chat_llm", new_callable=AsyncMock, side_effect=Exception("timeout")):
        result = await generate_response(
            conversation_history=[],
            table_context="",
            user_message="hello",
        )
    assert "抱歉" in result or "稍后" in result
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_inspire_chat.py -v`
Expected: FAIL (generate_response not defined)

**Step 3: Write the system prompt**

Create `prompts/inspire_system.md`:

```markdown
You are a creative gift design advisor for TikTok LIVE gifts. You help users discover "what's worth making" by combining your knowledge of gift design with real data about regions and pricing.

## Your Role
- Help users brainstorm gift ideas (subjects, themes, styles)
- Provide insights about what works in different regions
- Explain pricing tiers and design complexity trade-offs
- Suggest timely ideas based on upcoming events or cultural moments

## Gift Types
- **Banner**: Static decorative gift, simplest to produce
- **Animation**: Animated gift with motion effects
- **Random**: Randomized gift with surprise element
- **Face**: Face-tracking interactive gift, most complex

## Price Tiers & Design Complexity
- T0 (1-19 coins): Simple designs, limited subjects, often use containers
- T1 (20-199 coins): Moderate complexity, broader subject range
- T2 (200-4999 coins): Rich detail, custom scenes, multiple elements
- T3 (5000-20999 coins): Premium quality, complex animations
- T4 (21000+ coins): Top tier, maximum production value

## Today's Date
{today}

## Dynamic Context (from data tables)
{table_context}

## Guidelines
- Respond in the same language as the user (Chinese or English)
- Be concise but insightful (2-4 sentences per response)
- When you have enough context (region + price + subject idea), proactively suggest the user can:
  - Type "generate" or "生成" to try creating an image
  - Type "request" or "提需求" to submit a formal design request
- Do NOT generate images yourself — guide the user toward using the generate or request features
- If the user hasn't mentioned a region or price range, gently ask about it
```

**Step 4: Write implementation**

Add to `pipeline/inspire.py`:

```python
import datetime

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "inspire_system.md"


def _load_system_prompt(table_context: str) -> str:
    """加载并填充对话系统 prompt。"""
    template = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        today=datetime.date.today().isoformat(),
        table_context=table_context or "(No table data yet — ask the user about region and price)",
    )


async def _call_chat_llm(system_prompt: str, messages: list[dict]) -> str:
    """调用主模型生成对话回复（支持多轮历史）。"""
    s = get_settings()
    d = load_defaults()
    model = d.inspire_chat_model
    url = f"{s.gemini_base_url}/models/{model}:generateContent"
    headers = {"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"}

    # 构建 Gemini contents（多轮）
    contents = []
    for msg in messages:
        contents.append({
            "role": msg["role"],
            "parts": [{"text": msg["text"]}],
        })

    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def generate_response(
    conversation_history: list[dict],
    table_context: str,
    user_message: str,
) -> str:
    """生成 Inspire 对话回复。"""
    try:
        system_prompt = _load_system_prompt(table_context)
        # 构建消息列表：历史 + 当前消息
        messages = list(conversation_history) + [{"role": "user", "text": user_message}]
        return await _call_chat_llm(system_prompt, messages)
    except Exception as e:
        logger.error("[Inspire] 对话生成失败: %s", e, exc_info=True)
        return "抱歉，我遇到了一些问题，请稍后再试。你可以继续描述你的想法，或者输入 'stop' 结束对话。"
```

**Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_inspire_chat.py -v`
Expected: PASS (3 passed)

**Step 6: Commit**

```bash
git add prompts/inspire_system.md pipeline/inspire.py tests/test_inspire_chat.py
git commit -m "feat(inspire): conversation generation with system prompt + history"
```

---

### Task 5: Pipeline Orchestration (handle_message)

**Files:**
- Modify: `pipeline/inspire.py` (add handle_message, table query integration)
- Test: `tests/test_inspire_pipeline.py`

**Context:** This is the core orchestration function that ties extraction, table query, and response generation together. It takes a user message + InspireSession, returns a response string + updated session + optional exit action.

**Step 1: Write the failing test**

Create `tests/test_inspire_pipeline.py`:

```python
"""Inspire pipeline 编排测试。"""

from unittest.mock import AsyncMock, patch

import pytest

from models import InspireSession, InspireSlots


@pytest.mark.asyncio
async def test_handle_message_chat():
    """普通对话：提取 + 生成回复，session 更新。"""
    from pipeline.inspire import handle_inspire_message

    session = InspireSession(user_id="ou_test")
    extract_result = {
        "region": "MENA", "price": None, "subject": None,
        "price_hint": None, "intent": "chat",
    }
    with patch("pipeline.inspire.extract_slots", new_callable=AsyncMock, return_value=extract_result), \
         patch("pipeline.inspire._query_tables_for_context", new_callable=AsyncMock, return_value="MENA region data"), \
         patch("pipeline.inspire.generate_response", new_callable=AsyncMock, return_value="MENA is a great region!"):
        reply, action = await handle_inspire_message(session, "我想做中东的礼物")

    assert reply == "MENA is a great region!"
    assert action is None
    assert session.slots.region == "MENA"
    assert len(session.conversation_history) == 2  # user + model


@pytest.mark.asyncio
async def test_handle_message_generate_exit():
    """generate 意图：返回 exit action。"""
    from pipeline.inspire import handle_inspire_message

    session = InspireSession(user_id="ou_test", slots=InspireSlots(region="US", price=100))
    extract_result = {
        "region": "US", "price": 100, "subject": "lion",
        "price_hint": None, "intent": "generate",
    }
    with patch("pipeline.inspire.extract_slots", new_callable=AsyncMock, return_value=extract_result):
        reply, action = await handle_inspire_message(session, "帮我生成一个")

    assert action == "generate"
    assert "终止" in reply or "已终止" in reply


@pytest.mark.asyncio
async def test_handle_message_request_exit():
    """request 意图：返回 exit action。"""
    from pipeline.inspire import handle_inspire_message

    session = InspireSession(user_id="ou_test", slots=InspireSlots(region="JP"))
    extract_result = {
        "region": "JP", "price": None, "subject": None,
        "price_hint": None, "intent": "request",
    }
    with patch("pipeline.inspire.extract_slots", new_callable=AsyncMock, return_value=extract_result):
        reply, action = await handle_inspire_message(session, "我要提个需求")

    assert action == "request"
    assert "终止" in reply or "已终止" in reply


@pytest.mark.asyncio
async def test_handle_message_stop():
    """stop 意图：返回 stop action。"""
    from pipeline.inspire import handle_inspire_message

    session = InspireSession(user_id="ou_test")
    extract_result = {
        "region": None, "price": None, "subject": None,
        "price_hint": None, "intent": "stop",
    }
    with patch("pipeline.inspire.extract_slots", new_callable=AsyncMock, return_value=extract_result):
        reply, action = await handle_inspire_message(session, "谢谢，再见")

    assert action == "stop"


@pytest.mark.asyncio
async def test_handle_message_no_slot_change_skips_query():
    """槽位无变化时不查表。"""
    from pipeline.inspire import handle_inspire_message

    session = InspireSession(
        user_id="ou_test",
        slots=InspireSlots(region="MENA"),
        table_context="cached MENA data",
    )
    extract_result = {
        "region": "MENA", "price": None, "subject": None,
        "price_hint": None, "intent": "chat",
    }
    with patch("pipeline.inspire.extract_slots", new_callable=AsyncMock, return_value=extract_result), \
         patch("pipeline.inspire._query_tables_for_context", new_callable=AsyncMock) as mock_query, \
         patch("pipeline.inspire.generate_response", new_callable=AsyncMock, return_value="Ok"):
        await handle_inspire_message(session, "继续说说")

    mock_query.assert_not_called()  # 没有新槽位 → 不查表
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_inspire_pipeline.py -v`
Expected: FAIL (handle_inspire_message not defined)

**Step 3: Write implementation**

Add to `pipeline/inspire.py`:

```python
async def _query_tables_for_context(slots: InspireSlots) -> str:
    """根据槽位查询 TABLE0-3，返回拼接的上下文文本。"""
    from pipeline.data import query_routing, query_region_info, query_tier_rules, query_instances

    context_parts = []

    if slots.region:
        try:
            routing = await query_routing(slots.region)
            if routing:
                # 查 TABLE1 区域风格
                region_info = await query_region_info(routing)
                if region_info:
                    context_parts.append(f"Region Style ({slots.region}):\n{region_info}")

                # 查 TABLE2 档位规则（如果有价格）
                if slots.price is not None:
                    tier_rules = await query_tier_rules(routing, slots.price)
                    if tier_rules:
                        context_parts.append(f"Tier Rules (price={slots.price}):\n{tier_rules}")

                # 查 TABLE3 参考案例（如果有区域+价格）
                if slots.price is not None:
                    instances = await query_instances(routing, slots.price)
                    if instances:
                        context_parts.append(f"Reference Cases:\n{instances}")
        except Exception as e:
            logger.warning("[Inspire] 表查询失败: %s", e)

    return "\n\n".join(context_parts)


def _update_slots(session: InspireSession, extracted: dict) -> bool:
    """用提取结果更新 session 槽位，返回是否有变化。"""
    old = session.slots.model_copy()
    if extracted.get("region"):
        session.slots.region = extracted["region"]
    if extracted.get("price") is not None:
        session.slots.price = extracted["price"]
    if extracted.get("subject"):
        session.slots.subject = extracted["subject"]
    if extracted.get("price_hint"):
        session.slots.price_hint = extracted["price_hint"]
    return old != session.slots


async def handle_inspire_message(
    session: InspireSession, user_message: str
) -> tuple[str, str | None]:
    """处理一轮 Inspire 对话。

    Returns:
        (reply_text, action) — action 为 None/"generate"/"request"/"stop"
    """
    # Step 1: 提取意图和槽位
    extracted = await extract_slots(user_message, session.slots)
    intent = extracted.get("intent", "chat")

    # Exit intents: generate / request / stop
    if intent in ("generate", "request"):
        _update_slots(session, extracted)
        return "灵感对话已终止。正在为你准备...", intent
    if intent == "stop":
        return "感谢使用灵感对话，再见！", "stop"

    # Step 2: 更新槽位，有变化则查表
    slots_changed = _update_slots(session, extracted)
    if slots_changed:
        session.table_context = await _query_tables_for_context(session.slots)

    # Step 3: 生成回复
    reply = await generate_response(
        conversation_history=session.conversation_history,
        table_context=session.table_context,
        user_message=user_message,
    )

    # Step 4: 更新对话历史
    session.conversation_history.append({"role": "user", "text": user_message})
    session.conversation_history.append({"role": "model", "text": reply})

    return reply, None
```

**Note:** `_query_tables_for_context` reuses the existing async table query functions from `pipeline/data.py`. The `query_region_info`, `query_tier_rules`, `query_instances` function signatures may need adaptation — check `pipeline/data.py` for exact signatures and adjust the calls accordingly. If those functions return dicts, convert them to readable strings. If they don't exist with those exact names, wrap the existing functions.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_inspire_pipeline.py -v`
Expected: PASS (5 passed)

**Step 5: Commit**

```bash
git add pipeline/inspire.py tests/test_inspire_pipeline.py
git commit -m "feat(inspire): pipeline orchestration — extract + query + respond"
```

---

### Task 6: Bot Wiring (Menu + Message Routing + Exit Intents)

**Files:**
- Modify: `bot_ws.py:167-228` (add inspire session routing in on_message)
- Modify: `bot_ws.py:272-274` (update inspire menu handler)
- Test: `tests/test_inspire_routing.py`

**Context:** The `on_message` function routes text messages. We need to add a check for active InspireSession BEFORE the EditSession check (line ~189). The inspire menu creates a new session and sends a welcome message. Exit intents route to Generate form / Request form.

**Step 1: Write the failing test**

Create `tests/test_inspire_routing.py`:

```python
"""Inspire 路由测试（单元级别）。"""

from models import InspireSession, InspireSlots
from pipeline import inspire_store


def test_inspire_session_created_on_menu():
    """点击 inspire 菜单后创建 session。"""
    inspire_store._store.clear()
    inspire_store.save(InspireSession(user_id="ou_menu_test"))
    session = inspire_store.get("ou_menu_test")
    assert session is not None
    assert session.user_id == "ou_menu_test"


def test_inspire_session_removed_on_stop():
    """stop 意图清除 session。"""
    inspire_store._store.clear()
    inspire_store.save(InspireSession(user_id="ou_stop"))
    inspire_store.remove("ou_stop")
    assert inspire_store.get("ou_stop") is None


def test_inspire_session_removed_on_generate():
    """generate 意图清除 session。"""
    inspire_store._store.clear()
    inspire_store.save(InspireSession(user_id="ou_gen"))
    inspire_store.remove("ou_gen")
    assert inspire_store.get("ou_gen") is None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_inspire_routing.py -v`
Expected: PASS (these are store-level tests, should pass with existing store code)

**Step 3: Write implementation**

Modify `bot_ws.py` — update the inspire menu handler (around line 272):

```python
        elif event_key == "inspire":
            from pipeline import inspire_store
            from models import InspireSession
            # 如果已有 session，先终止
            inspire_store.remove(open_id)
            # 创建新 session
            session = InspireSession(user_id=open_id)
            inspire_store.save(session)
            token = feishu.get_token_sync()
            feishu.send_text_sync(
                token, open_id,
                "Hi! I'm your gift creative advisor. Tell me about what you're thinking:\n"
                "- Which region? (e.g., MENA, US, JP)\n"
                "- What price range?\n"
                "- Any subject or theme ideas?\n\n"
                "Type 'stop' to end the session anytime.",
            )
```

Modify `bot_ws.py` `on_message` — add inspire routing BEFORE the EditSession check (around line 189):

```python
    # 路由0: Inspire 对话中 → 转交 inspire 处理
    from pipeline import inspire_store
    inspire_session = inspire_store.get(sender_id)
    if inspire_session:
        threading.Thread(
            target=_handle_inspire_message,
            args=(sender_id, inspire_session, text),
            daemon=True,
        ).start()
        return
```

Add the `_handle_inspire_message` helper function in `bot_ws.py`:

```python
def _handle_inspire_message(sender_id: str, session, text: str) -> None:
    """处理 Inspire 对话消息（在后台线程中运行）。"""
    from pipeline.inspire import handle_inspire_message
    from pipeline import inspire_store

    try:
        reply, action = _run_async(handle_inspire_message(session, text))
        token = feishu.get_token_sync()

        if action == "generate":
            # 终止 session，发送 Generate 表单
            inspire_store.remove(sender_id)
            feishu.send_text_sync(token, sender_id, reply)
            feishu.send_card_sync(token, sender_id, GENERATE_FORM_CARD)
        elif action == "request":
            # 终止 session，发送 Request 表单
            from cards import REQUEST_FORM_CARD
            inspire_store.remove(sender_id)
            feishu.send_text_sync(token, sender_id, reply)
            feishu.send_card_sync(token, sender_id, REQUEST_FORM_CARD)
        elif action == "stop":
            # 终止 session
            inspire_store.remove(sender_id)
            feishu.send_text_sync(token, sender_id, reply)
        else:
            # 继续对话，保存 session
            inspire_store.save(session)
            feishu.send_text_sync(token, sender_id, reply)
    except Exception as e:
        logger.error("[Inspire] 消息处理失败: %s", e, exc_info=True)
        try:
            token = feishu.get_token_sync()
            feishu.send_text_sync(token, sender_id, f"Inspire 处理出错: {e}")
        except Exception:
            pass
```

**Step 4: Run all tests to verify nothing is broken**

Run: `python3 -m pytest --tb=short -q`
Expected: All tests pass

**Step 5: Commit**

```bash
git add bot_ws.py tests/test_inspire_routing.py
git commit -m "feat(inspire): wire inspire menu + message routing + exit intents"
```

---

### Task 7: Table Query Adaptation

**Files:**
- Modify: `pipeline/inspire.py` (adapt `_query_tables_for_context` to actual data.py API)
- Test: `tests/test_inspire_table_query.py`

**Context:** The existing `pipeline/data.py` has async functions for querying TABLE0-3, but their signatures and return types may not directly match what `_query_tables_for_context` expects. This task adapts the table query calls to work with the real API.

**Step 1: Read `pipeline/data.py` to understand available functions**

Check function signatures: `query_routing()`, `query_table1()`, `query_table2()`, `query_table3()`, etc. Note their exact parameter names and return types.

**Step 2: Write test**

Create `tests/test_inspire_table_query.py`:

```python
"""Inspire 表查询适配测试。"""

from unittest.mock import AsyncMock, patch

import pytest

from models import InspireSlots


@pytest.mark.asyncio
async def test_query_context_with_region():
    """有 region 时查 TABLE0 + TABLE1。"""
    from pipeline.inspire import _query_tables_for_context

    slots = InspireSlots(region="MENA")
    with patch("pipeline.inspire.query_routing", new_callable=AsyncMock) as mock_route:
        mock_route.return_value = None  # 无路由 → 返回空
        result = await _query_tables_for_context(slots)

    assert result == ""


@pytest.mark.asyncio
async def test_query_context_empty_slots():
    """无槽位时不查表。"""
    from pipeline.inspire import _query_tables_for_context

    slots = InspireSlots()
    result = await _query_tables_for_context(slots)
    assert result == ""
```

**Step 3: Adapt implementation**

Based on actual `pipeline/data.py` function signatures, update `_query_tables_for_context` in `pipeline/inspire.py`. Import the correct function names and adapt parameters. If the data functions return dicts/lists, format them into readable text strings for the system prompt context.

**Step 4: Run test**

Run: `python3 -m pytest tests/test_inspire_table_query.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add pipeline/inspire.py tests/test_inspire_table_query.py
git commit -m "feat(inspire): adapt table queries to actual data.py API"
```

---

### Task 8: Integration Test

**No code changes — manual verification.**

**Test scenarios:**

1. **Start inspire session**: Click `inspire` menu → bot sends welcome message
2. **Chat round 1**: Send "I'm thinking about a MENA gift" → bot responds with MENA context
3. **Chat round 2**: Send "around 100 coins, something with a lion" → bot responds with tier/subject context
4. **Exit via generate**: Send "generate" → bot says "已终止" + sends generate form card
5. **Exit via request**: Start new session, send "提需求" → bot says "已终止" + sends request form card
6. **Exit via stop**: Start new session, send "stop" → bot says goodbye, session cleared
7. **Session isolation**: While in inspire session, text messages go to inspire (not generate)
8. **Session expiry**: Wait for TTL or restart bot, verify expired session falls through to normal routing

Run: `python3 bot_ws.py`

Test each scenario in Feishu and verify correct behavior.
