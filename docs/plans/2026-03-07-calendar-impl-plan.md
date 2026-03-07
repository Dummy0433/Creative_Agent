# Calendar (礼物项目看板) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bot 菜单点击 `calendar` 后，从飞书多维表格拉取当前季度的礼物项目数据，按 Deadline 排序展示最近 15 条，以只读卡片形式发送给用户。

**Architecture:** 在 `generation_defaults.yaml` 中配置季度表地址，运行时根据当前日期自动选择季度。新增 `pipeline/calendar.py` 处理数据拉取和排序，`cards.py` 新增卡片构建函数，`bot_ws.py` 接入菜单事件。

**Tech Stack:** Python, httpx, Feishu Bitable API, Feishu Card Schema 2.0, pytest

---

### Task 1: Calendar 配置模型 + YAML

**Files:**
- Modify: `models.py` (在 `GenerationDefaults` 中新增字段)
- Modify: `generation_defaults.yaml` (新增 calendar 配置段)
- Test: `tests/test_calendar_config.py`

**Step 1: Write the failing test**

```python
# tests/test_calendar_config.py
"""Calendar 配置测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_calendar_config_loads():
    """generation_defaults.yaml 中 calendar 配置可正常加载。"""
    from defaults import load_defaults
    load_defaults.cache_clear()
    d = load_defaults()
    assert d.calendar_app_token != ""
    assert "Q1" in d.calendar_quarters
    q1 = d.calendar_quarters["Q1"]
    assert q1.table_id != ""
    assert q1.view_id != ""


def test_calendar_quarter_selection():
    """根据月份自动选择正确的季度。"""
    from pipeline.calendar import _get_current_quarter
    # 这里用固定日期测试
    assert _get_current_quarter(month=1) == "Q1"
    assert _get_current_quarter(month=3) == "Q1"
    assert _get_current_quarter(month=4) == "Q2"
    assert _get_current_quarter(month=7) == "Q3"
    assert _get_current_quarter(month=12) == "Q4"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_calendar_config.py -v`
Expected: FAIL (fields don't exist yet)

**Step 3: Write minimal implementation**

Add to `models.py` after `TierProfile` class:

```python
class CalendarQuarterConfig(BaseModel):
    """季度表配置：table_id + view_id。"""
    table_id: str
    view_id: str
```

Add to `GenerationDefaults` class body:

```python
    # ── Calendar 配置 ──
    calendar_app_token: str = ""
    calendar_quarters: dict[str, CalendarQuarterConfig] = {}
```

Add to `generation_defaults.yaml` at the end:

```yaml
# ── Calendar 看板 ──────────────────────────────────────────────
calendar_app_token: "FJucbi5B0aCnpbsBDGelU0NFgug"
calendar_quarters:
  Q1:
    table_id: "tblQPUBfShTwkIxb"
    view_id: "vew6G1bwqT"
  Q2:
    table_id: ""
    view_id: ""
  Q3:
    table_id: ""
    view_id: ""
  Q4:
    table_id: ""
    view_id: ""
```

Create `pipeline/calendar.py`:

```python
"""Calendar 看板：数据拉取 + 季度路由。"""

import datetime


def _get_current_quarter(month: int | None = None) -> str:
    """根据月份返回季度标识（Q1-Q4）。"""
    if month is None:
        month = datetime.date.today().month
    return f"Q{(month - 1) // 3 + 1}"
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_calendar_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add models.py generation_defaults.yaml pipeline/calendar.py tests/test_calendar_config.py
git commit -m "feat(calendar): add config model + quarter selection"
```

---

### Task 2: view_id 支持 + Calendar 数据拉取

**Files:**
- Modify: `feishu.py` (`query_bitable_sync` 增加 `view_id` 参数)
- Modify: `pipeline/calendar.py` (新增 `fetch_calendar_records()`)
- Test: `tests/test_calendar_fetch.py`

**Step 1: Write the failing test**

```python
# tests/test_calendar_fetch.py
"""Calendar 数据拉取测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_fetch_sorts_by_deadline_and_limits(monkeypatch):
    """fetch_calendar_records 按 Deadline 排序并限制 15 条。"""
    import pipeline.calendar as cal

    # Mock records：乱序的 deadline
    mock_records = []
    for i in range(20):
        # 时间戳：2026-03-01 + i 天（毫秒）
        ts = (1740787200 + i * 86400) * 1000
        mock_records.append({
            "fields": {
                "Gift Name // 礼物名": f"Gift {i}",
                "Deadline // 截止日期": ts,
                "Progress // 进展": "in Design // 设计中",
            }
        })
    # 打乱顺序
    import random
    random.shuffle(mock_records)

    # Mock feishu 调用
    monkeypatch.setattr(cal, "_query_calendar_raw", lambda: mock_records)

    result = cal.fetch_calendar_records()
    assert len(result) == 15
    # 验证按 deadline 升序排列（最早的在前）
    deadlines = [r["deadline_ts"] for r in result]
    assert deadlines == sorted(deadlines)


def test_fetch_extracts_fields(monkeypatch):
    """fetch_calendar_records 正确提取核心字段。"""
    import pipeline.calendar as cal

    mock_records = [{
        "fields": {
            "Gift Name // 礼物名": "Test Gift",
            "Price // 价格": 500,
            "Gift Type // 礼物类型": "Animation",
            "Categories // 需求类型": "Campaign Gifts // 活动礼物",
            "Regions // 区域": ["MENA", "TR"],
            "POC // 需求方": [{"name": "张三", "id": "ou_xxx"}],
            "Doc // 需求文档": {"link": "https://example.com", "text": "PRD"},
            "Progress // 进展": "in Design // 设计中",
            "Designer // 设计师": [{"name": "李四", "id": "ou_yyy"}],
            "Deadline // 截止日期": 1741392000000,
        }
    }]
    monkeypatch.setattr(cal, "_query_calendar_raw", lambda: mock_records)

    result = cal.fetch_calendar_records()
    assert len(result) == 1
    r = result[0]
    assert r["name"] == "Test Gift"
    assert r["price"] == 500
    assert r["gift_type"] == "Animation"
    assert r["regions"] == ["MENA", "TR"]
    assert r["poc"] == "张三"
    assert r["doc_link"] == "https://example.com"
    assert r["doc_text"] == "PRD"
    assert r["progress"] == "in Design // 设计中"
    assert r["designer"] == "李四"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_calendar_fetch.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Modify `feishu.py` — add `view_id` param to `query_bitable_sync` (line ~270):

```python
def query_bitable_sync(token, app_token, table_id, filter_expr=None, view_id=None):
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    params = {"page_size": 100}
    if filter_expr:
        params["filter"] = filter_expr
    if view_id:
        params["view_id"] = view_id
    with _sync_client() as client:
        resp = client.get(url, headers=_headers(token), params=params)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("items", [])
```

Expand `pipeline/calendar.py`:

```python
"""Calendar 看板：数据拉取 + 季度路由。"""

import datetime
import logging

import feishu
from defaults import load_defaults

logger = logging.getLogger(__name__)

_CALENDAR_LIMIT = 15


def _get_current_quarter(month: int | None = None) -> str:
    """根据月份返回季度标识（Q1-Q4）。"""
    if month is None:
        month = datetime.date.today().month
    return f"Q{(month - 1) // 3 + 1}"


def _query_calendar_raw() -> list[dict]:
    """从飞书 Bitable 拉取当前季度的 Calendar 原始记录。"""
    d = load_defaults()
    quarter = _get_current_quarter()
    qc = d.calendar_quarters.get(quarter)
    if not qc or not qc.table_id:
        logger.warning("[Calendar] 季度 %s 未配置 table_id", quarter)
        return []
    token = feishu.get_token_sync()
    return feishu.query_bitable_sync(
        token, d.calendar_app_token, qc.table_id, view_id=qc.view_id,
    )


def _extract_record(fields: dict) -> dict:
    """从原始 fields 提取 Calendar 卡片所需字段。"""
    # 人员字段提取名字
    def _person_name(val):
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val[0].get("name", "")
        return ""

    # 超链接字段
    doc = fields.get("Doc // 需求文档") or {}
    if isinstance(doc, dict):
        doc_link = doc.get("link", "")
        doc_text = doc.get("text", "")
    else:
        doc_link, doc_text = "", ""

    # 区域（多选 — 可能是 list[str] 或 list[dict]）
    regions_raw = fields.get("Regions // 区域") or []
    if regions_raw and isinstance(regions_raw[0], dict):
        regions = [r.get("text", "") for r in regions_raw]
    else:
        regions = list(regions_raw)

    deadline_ts = fields.get("Deadline // 截止日期") or 0

    return {
        "name": fields.get("Gift Name // 礼物名", ""),
        "price": fields.get("Price // 价格"),
        "gift_type": fields.get("Gift Type // 礼物类型", ""),
        "categories": fields.get("Categories // 需求类型", ""),
        "regions": regions,
        "poc": _person_name(fields.get("POC // 需求方")),
        "doc_link": doc_link,
        "doc_text": doc_text,
        "progress": fields.get("Progress // 进展", ""),
        "designer": _person_name(fields.get("Designer // 设计师")),
        "deadline_ts": deadline_ts,
    }


def fetch_calendar_records() -> list[dict]:
    """拉取 Calendar 记录，按 Deadline 排序，返回最近 N 条。"""
    raw_records = _query_calendar_raw()
    records = [_extract_record(rec.get("fields", {})) for rec in raw_records]
    # 按 deadline 升序（最早的在前），无 deadline 的排最后
    records.sort(key=lambda r: r["deadline_ts"] if r["deadline_ts"] else float("inf"))
    return records[:_CALENDAR_LIMIT]
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_calendar_fetch.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add feishu.py pipeline/calendar.py tests/test_calendar_fetch.py
git commit -m "feat(calendar): data fetching with view_id + sort + limit"
```

---

### Task 3: Calendar 卡片构建

**Files:**
- Modify: `cards.py` (新增 `build_calendar_card()`)
- Test: `tests/test_calendar_card.py`

**Step 1: Write the failing test**

```python
# tests/test_calendar_card.py
"""Calendar 卡片构建测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_build_calendar_card_structure():
    """build_calendar_card 返回有效的 schema 2.0 卡片。"""
    from cards import build_calendar_card

    records = [
        {
            "name": "Test Gift",
            "price": 500,
            "gift_type": "Animation",
            "categories": "Campaign Gifts // 活动礼物",
            "regions": ["MENA"],
            "poc": "张三",
            "doc_link": "https://example.com",
            "doc_text": "PRD Doc",
            "progress": "in Design // 设计中",
            "designer": "李四",
            "deadline_ts": 1741392000000,
        },
    ]
    card = build_calendar_card(records)
    assert card["schema"] == "2.0"
    assert card["header"]["title"]["content"] == "Gift Calendar"
    # body 应有 elements
    elements = card["body"]["elements"]
    assert len(elements) > 0


def test_build_calendar_card_empty():
    """空记录时显示提示信息。"""
    from cards import build_calendar_card

    card = build_calendar_card([])
    elements = card["body"]["elements"]
    # 应有一个 markdown 提示"暂无数据"
    assert any("暂无" in str(e) or "No data" in str(e) for e in elements)


def test_build_calendar_card_contains_doc_link():
    """卡片中包含文档链接。"""
    from cards import build_calendar_card

    records = [{
        "name": "Linked Gift",
        "price": 100,
        "gift_type": "Banner",
        "categories": "",
        "regions": ["US"],
        "poc": "Alice",
        "doc_link": "https://example.com/doc",
        "doc_text": "My PRD",
        "progress": "Not Started// 未启动",
        "designer": "Bob",
        "deadline_ts": 1741392000000,
    }]
    card = build_calendar_card(records)
    card_str = str(card)
    assert "https://example.com/doc" in card_str
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_calendar_card.py -v`
Expected: FAIL (function doesn't exist)

**Step 3: Write minimal implementation**

Add to `cards.py`:

```python
def build_calendar_card(records: list[dict]) -> dict:
    """构建 Calendar 只读卡片：展示最近的礼物项目状态。

    每条记录用 markdown 行展示：名称、状态、区域、设计师、POC、截止日期、文档链接。
    """
    import datetime

    if not records:
        return {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "Gift Calendar"},
                "template": "blue",
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": [{"tag": "markdown", "content": "No data available for this quarter."}],
            },
        }

    # 状态 → emoji 映射
    status_icons = {
        "in Design": "🎨",
        "in Feedback": "💬",
        "Not Started": "⏳",
        "Not Scheduled": "📋",
        "Delivered": "✅",
        "Delayed": "🔴",
        "Pending": "⏸️",
        "Cancelled": "❌",
    }

    lines = []
    for r in records:
        # 格式化 deadline
        deadline_str = ""
        if r["deadline_ts"]:
            dt = datetime.datetime.fromtimestamp(r["deadline_ts"] / 1000)
            deadline_str = dt.strftime("%m/%d")

        # 状态 icon
        progress = r.get("progress", "")
        icon = "📦"
        for key, emoji in status_icons.items():
            if key in progress:
                icon = emoji
                break

        # 区域
        regions = ", ".join(r.get("regions", [])) or "—"

        # 文档链接
        doc_part = ""
        if r.get("doc_link"):
            doc_label = r.get("doc_text") or "Doc"
            # 截断过长的 label
            if len(doc_label) > 30:
                doc_label = doc_label[:27] + "..."
            doc_part = f" | [📄 {doc_label}]({r['doc_link']})"

        # 价格
        price_str = f"{r['price']}c" if r.get("price") else ""

        # 人员
        people = []
        if r.get("designer"):
            people.append(f"🎨{r['designer']}")
        if r.get("poc"):
            people.append(f"👤{r['poc']}")
        people_str = " ".join(people)

        line = f"{icon} **{r['name']}**"
        meta_parts = [x for x in [regions, price_str, deadline_str, people_str] if x]
        if meta_parts:
            line += f"\n      {' | '.join(meta_parts)}"
        if doc_part:
            line += f"\n      {doc_part}"

        lines.append(line)

    # 用 divider 分隔每条记录
    elements = []
    for i, line in enumerate(lines):
        elements.append({"tag": "markdown", "content": line})
        if i < len(lines) - 1:
            elements.append({"tag": "hr"})

    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "Gift Calendar"},
            "subtitle": {"tag": "plain_text", "content": f"Upcoming {len(records)} items"},
            "template": "blue",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": elements,
        },
    }
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_calendar_card.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add cards.py tests/test_calendar_card.py
git commit -m "feat(calendar): build_calendar_card read-only card"
```

---

### Task 4: Bot 菜单接入

**Files:**
- Modify: `bot_ws.py` (`on_menu` 新增 `calendar` 分支)

**Step 1: Add calendar handler to on_menu**

In `bot_ws.py`, modify `on_menu` function, replace the `inspire` placeholder and add `calendar`:

```python
        elif event_key == "calendar":
            from pipeline.calendar import fetch_calendar_records
            from cards import build_calendar_card
            token = feishu.get_token_sync()
            try:
                records = fetch_calendar_records()
                card = build_calendar_card(records)
                feishu.send_card_sync(token, open_id, card)
            except Exception as e:
                logger.error("[Calendar] 拉取失败: %s", e, exc_info=True)
                feishu.send_text_sync(token, open_id, f"Calendar 拉取失败: {e}")
```

**Step 2: Manual test**

Run: `python bot_ws.py --test card`

In Feishu bot, configure a `calendar` menu button, click it, verify card appears with correct data.

**Step 3: Commit**

```bash
git add bot_ws.py
git commit -m "feat(calendar): wire calendar menu to bot_ws"
```

---

### Task 5: 集成测试 — 实际效果验证

**No code changes — manual verification.**

**Step 1:** Start bot: `python bot_ws.py --test card`

**Step 2:** Click `calendar` menu in Feishu bot

**Step 3:** Verify:
- [ ] 卡片标题 "Gift Calendar"
- [ ] 展示 ≤ 15 条记录
- [ ] 按 Deadline 排序（最近的在前）
- [ ] 每条显示：名称、状态 icon、区域、价格、设计师、POC
- [ ] 文档链接可点击跳转
- [ ] 空季度（Q2/Q3/Q4 未配置）显示"No data"

**Step 4:** 如果卡片效果需要调整，在此轮迭代。
