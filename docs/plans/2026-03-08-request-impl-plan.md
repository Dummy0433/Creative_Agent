# Request (需求提单) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 用户通过飞书 Bot 提交礼物需求，校验 15 工作日规则后写入 Calendar 多维表格。

**Architecture:** 在 `cards.py` 新增表单卡片，`feishu.py` 新增 Bitable 写入 API，`pipeline/request.py` 处理校验和提交逻辑，`bot_ws.py` 接入表单提交事件。

**Tech Stack:** Python, httpx, Feishu Bitable API (create record), pytest

---

### Task 1: Bitable 写入 API

**Files:**
- Modify: `feishu.py` (新增 `create_bitable_record` async + sync)
- Test: `tests/test_request.py`

**Step 1: Write the failing test**

```python
# tests/test_request.py
"""需求提单测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_working_days_enough():
    """15+ 工作日应通过校验。"""
    from pipeline.request import check_working_days
    import datetime
    # 25 个自然日 ≈ 17-18 个工作日
    target = datetime.date.today() + datetime.timedelta(days=25)
    assert check_working_days(target, min_days=15) is True


def test_working_days_insufficient():
    """< 15 工作日应不通过。"""
    from pipeline.request import check_working_days
    import datetime
    target = datetime.date.today() + datetime.timedelta(days=5)
    assert check_working_days(target, min_days=15) is False


def test_working_days_weekends_excluded():
    """工作日计算应排除周末。"""
    from pipeline.request import count_working_days
    import datetime
    # 2026-03-09 是周一，2026-03-13 是周五 → 5 个工作日
    start = datetime.date(2026, 3, 9)
    end = datetime.date(2026, 3, 13)
    assert count_working_days(start, end) == 5


def test_working_days_across_weekend():
    """跨周末：周五到下周一 = 2 个工作日（周五 + 周一）。"""
    from pipeline.request import count_working_days
    import datetime
    # 2026-03-13 是周五，2026-03-16 是周一
    start = datetime.date(2026, 3, 13)
    end = datetime.date(2026, 3, 16)
    assert count_working_days(start, end) == 2
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_request.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Write minimal implementation**

Create `pipeline/request.py`:

```python
"""需求提单：校验 + 写入 Calendar 表。"""

import datetime
import logging

logger = logging.getLogger(__name__)

_MIN_WORKING_DAYS = 15


def count_working_days(start: datetime.date, end: datetime.date) -> int:
    """计算 start 到 end（含）之间的工作日数（排除周六日）。"""
    if end < start:
        return 0
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:  # 0=Mon, 4=Fri
            days += 1
        current += datetime.timedelta(days=1)
    return days


def check_working_days(target_date: datetime.date, min_days: int = _MIN_WORKING_DAYS) -> bool:
    """检查 target_date 距今是否有足够的工作日。"""
    today = datetime.date.today()
    working = count_working_days(today, target_date)
    return working >= min_days
```

Add to `feishu.py` — async + sync Bitable record creation:

```python
async def create_bitable_record(token, app_token, table_id, fields: dict):
    """在多维表格中创建一条记录，返回 record_id。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    body = {"fields": fields}
    async with _new_async_client() as client:
        resp = await client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    record_id = data.get("record", {}).get("record_id", "")
    return record_id


def create_bitable_record_sync(token, app_token, table_id, fields: dict):
    """在多维表格中创建一条记录（sync），返回 record_id。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    body = {"fields": fields}
    with _sync_client() as client:
        resp = client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    record_id = data.get("record", {}).get("record_id", "")
    return record_id
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_request.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add pipeline/request.py feishu.py tests/test_request.py
git commit -m "feat(request): working day validation + bitable create API"
```

---

### Task 2: Request 表单卡片

**Files:**
- Modify: `cards.py` (新增 `REQUEST_FORM_CARD`)
- Test: `tests/test_request_card.py`

**Step 1: Write the failing test**

```python
# tests/test_request_card.py
"""需求提单表单卡片测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_request_form_card_exists():
    """REQUEST_FORM_CARD 存在且是 dict。"""
    from cards import REQUEST_FORM_CARD
    assert isinstance(REQUEST_FORM_CARD, dict)
    assert REQUEST_FORM_CARD["header"]["title"]["content"] == "Gift Request"


def test_request_form_has_required_fields():
    """表单包含所有必填字段。"""
    from cards import REQUEST_FORM_CARD
    form = REQUEST_FORM_CARD["elements"][0]
    assert form["tag"] == "form"
    field_names = [e.get("name", "") for e in form["elements"]]
    assert "gift_name" in field_names
    assert "price" in field_names
    assert "gift_type" in field_names
    assert "categories" in field_names
    assert "region" in field_names
    assert "deadline" in field_names
```

**Step 2: Run test to verify it fails**

**Step 3: Write minimal implementation**

Add `REQUEST_FORM_CARD` to `cards.py`. The form fields:
- gift_name: input (required)
- price: input (number)
- gift_type: select_static (Banner/Animation/Random/Face)
- categories: select_static (Regular Gifts/Campaign Gifts/IP Partnership/Non-Gifts/LIVE Effects/Stickers/Interactive Gift)
- region: select_static (top regions: US, MENA, EU, JP, KR, TW, VN, TH, ID, Global Gift, Cross-Region, TR, BR, LATAM, ANZ, SG, MY, PH, CCA, RO, KW, SA)
- prd: input (optional, placeholder "Activity name or PRD link")
- deadline: input (placeholder "YYYY-MM-DD", label "Expected Delivery Date")
- submit button

```python
REQUEST_FORM_CARD = {
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
                    "placeholder": {"tag": "plain_text", "content": "e.g. Ramadan Moon"},
                    "label": {"tag": "plain_text", "content": "Gift Name *"},
                },
                {
                    "tag": "input",
                    "name": "price",
                    "placeholder": {"tag": "plain_text", "content": "e.g. 500"},
                    "label": {"tag": "plain_text", "content": "Price (coins) *"},
                },
                {
                    "tag": "select_static",
                    "name": "gift_type",
                    "placeholder": {"tag": "plain_text", "content": "Select gift type"},
                    "options": [
                        {"text": {"tag": "plain_text", "content": "Banner"}, "value": "Banner"},
                        {"text": {"tag": "plain_text", "content": "Animation"}, "value": "Animation"},
                        {"text": {"tag": "plain_text", "content": "Random"}, "value": "Random"},
                        {"text": {"tag": "plain_text", "content": "Face"}, "value": "Face"},
                    ],
                },
                {
                    "tag": "select_static",
                    "name": "categories",
                    "placeholder": {"tag": "plain_text", "content": "Select request type"},
                    "options": [
                        {"text": {"tag": "plain_text", "content": "Regular Gifts"}, "value": "Regular Gifts // 常规礼物"},
                        {"text": {"tag": "plain_text", "content": "Campaign Gifts"}, "value": "Campaign Gifts // 活动礼物"},
                        {"text": {"tag": "plain_text", "content": "IP Partnership"}, "value": "IP Partnership // 知识产权合作伙伴关系"},
                        {"text": {"tag": "plain_text", "content": "Non-Gifts"}, "value": "Non-Gifts // 非礼物需求"},
                        {"text": {"tag": "plain_text", "content": "LIVE Effects"}, "value": "LIVE Effects // 开播特效"},
                        {"text": {"tag": "plain_text", "content": "Stickers"}, "value": "Stickers // 贴纸"},
                        {"text": {"tag": "plain_text", "content": "Interactive Gift"}, "value": "Interactive Gift // 互动礼物"},
                    ],
                },
                {
                    "tag": "select_static",
                    "name": "region",
                    "placeholder": {"tag": "plain_text", "content": "Select region"},
                    "options": [
                        {"text": {"tag": "plain_text", "content": r}, "value": r}
                        for r in [
                            "US", "MENA", "EU", "JP", "KR", "TW", "TR",
                            "ID", "VN", "TH", "BR", "LATAM",
                            "Global Gift", "Cross-Region",
                            "SG", "MY", "PH", "ANZ", "CCA", "RO", "KW", "SA",
                        ]
                    ],
                },
                {"tag": "hr"},
                {
                    "tag": "input",
                    "name": "prd",
                    "placeholder": {"tag": "plain_text", "content": "Activity name or PRD link (optional)"},
                    "label": {"tag": "plain_text", "content": "Activity PRD"},
                },
                {
                    "tag": "input",
                    "name": "deadline",
                    "placeholder": {"tag": "plain_text", "content": "YYYY-MM-DD"},
                    "label": {"tag": "plain_text", "content": "Expected Delivery Date *"},
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
```

**Step 4: Run test**

**Step 5: Commit**

```bash
git add cards.py tests/test_request_card.py
git commit -m "feat(request): add REQUEST_FORM_CARD"
```

---

### Task 3: Request 提交处理

**Files:**
- Modify: `pipeline/request.py` (新增 `submit_request()`)
- Modify: `generation_defaults.yaml` (新增 request 配置)
- Modify: `models.py` (新增 request 配置字段)
- Test: `tests/test_request.py` (追加测试)

**Step 1: Add config**

Add to `GenerationDefaults` in `models.py`:

```python
    # ── Request 提单 ──
    request_min_working_days: int = Field(default=15, ge=1, le=60)
    request_exception_contact: str = ""
```

Add to `generation_defaults.yaml`:

```yaml
# ── Request 提单 ──────────────────────────────────────────────
request_min_working_days: 15
request_exception_contact: "请联系 Gift Design 群"
```

**Step 2: Add submit_request() to pipeline/request.py**

```python
def submit_request(form_data: dict, submitter_open_id: str) -> str:
    """校验并提交需求到 Calendar 表。

    Returns:
        成功时返回 record_id，失败时抛出 ValueError。
    """
    import feishu
    from defaults import load_defaults

    d = load_defaults()

    # 解析 deadline
    deadline_str = form_data.get("deadline", "").strip()
    if not deadline_str:
        raise ValueError("请填写期望交付时间")
    try:
        target_date = datetime.datetime.strptime(deadline_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"日期格式错误，请使用 YYYY-MM-DD 格式，收到: {deadline_str}")

    # 15 工作日校验
    if not check_working_days(target_date, d.request_min_working_days):
        contact = d.request_exception_contact or "管理员"
        raise ValueError(
            f"期望交付时间距今不足 {d.request_min_working_days} 个工作日。"
            f"如需例外，{contact}。"
        )

    # 必填校验
    gift_name = form_data.get("gift_name", "").strip()
    if not gift_name:
        raise ValueError("请填写礼物名")
    price_str = form_data.get("price", "").strip()
    if not price_str:
        raise ValueError("请填写价格")
    try:
        price = int(price_str)
    except ValueError:
        raise ValueError(f"价格必须是数字，收到: {price_str}")

    gift_type = form_data.get("gift_type", "")
    categories = form_data.get("categories", "")
    region = form_data.get("region", "")
    prd = form_data.get("prd", "").strip()

    # 构建 Bitable record fields
    deadline_ts = int(datetime.datetime.combine(target_date, datetime.time()).timestamp() * 1000)
    fields = {
        "Gift Name // 礼物名": gift_name,
        "Price // 价格": price,
        "Progress // 进展": "Not Scheduled// 未排期",
        "Deadline // 截止日期": deadline_ts,
        "POC // 需求方": [{"id": submitter_open_id}],
    }
    if gift_type:
        fields["Gift Type // 礼物类型"] = gift_type
    if categories:
        fields["Categories // 需求类型"] = categories
    if region:
        fields["Regions // 区域"] = [region]
    if prd:
        fields["Doc // 需求文档"] = {"link": prd, "text": prd}

    # 确定当前季度的表
    quarter = _get_current_quarter()
    qc = d.calendar_quarters.get(quarter)
    if not qc or not qc.table_id:
        raise ValueError(f"当前季度 {quarter} 未配置 Calendar 表")

    token = feishu.get_token_sync()
    record_id = feishu.create_bitable_record_sync(
        token, d.calendar_app_token, qc.table_id, fields,
    )
    logger.info("[Request] 需求已提交: %s → record_id=%s", gift_name, record_id)
    return record_id
```

Remember to import `_get_current_quarter` from the same module (it's already defined in pipeline/request.py... wait, no, it's in pipeline/calendar.py). Import it:

```python
from pipeline.calendar import _get_current_quarter
```

**Step 3: Add test for submit validation**

Append to `tests/test_request.py`:

```python
def test_submit_missing_name():
    """缺少礼物名应失败。"""
    import pytest
    from pipeline.request import submit_request
    with pytest.raises(ValueError, match="礼物名"):
        submit_request({"gift_name": "", "price": "100", "deadline": "2099-12-31"}, "ou_test")


def test_submit_bad_date_format():
    """日期格式错误应失败。"""
    import pytest
    from pipeline.request import submit_request
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        submit_request({"gift_name": "Test", "price": "100", "deadline": "12/31/2099"}, "ou_test")


def test_submit_deadline_too_soon():
    """交付时间过近应失败。"""
    import pytest
    import datetime
    from pipeline.request import submit_request
    soon = (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    with pytest.raises(ValueError, match="工作日"):
        submit_request({"gift_name": "Test", "price": "100", "deadline": soon}, "ou_test")
```

**Step 4: Run tests + commit**

```bash
python3 -m pytest tests/test_request.py -v
python3 -m pytest tests/ -v
git add pipeline/request.py models.py generation_defaults.yaml tests/test_request.py
git commit -m "feat(request): submit_request with validation + bitable write"
```

---

### Task 4: Bot 接入 — 菜单 + 表单提交处理

**Files:**
- Modify: `bot_ws.py` (新增 `request` 菜单 + request_form 表单提交处理)
- Modify: `cards.py` (import REQUEST_FORM_CARD 到 bot_ws)

**Step 1: Add request menu handler**

In `bot_ws.py` `on_menu`, add after the `calendar` branch:

```python
        elif event_key == "request":
            from cards import REQUEST_FORM_CARD
            token = feishu.get_token_sync()
            feishu.send_card_sync(token, open_id, REQUEST_FORM_CARD)
```

**Step 2: Add request form submission handler**

In `bot_ws.py` `on_card_action`, in the form_value processing section (around line 376), add a check for the request form BEFORE the existing generate form logic:

```python
        form_value = action.form_value or {}
        if form_value:
            # ── Request 表单提交 ──
            if form_value.get("gift_name") is not None or "request_submit" in str(action.name or ""):
                from pipeline.request import submit_request
                logger.info("[卡片] Request 表单: user=%s, form=%s", open_id, form_value)
                try:
                    record_id = submit_request(form_data=form_value, submitter_open_id=open_id)
                    return _make_toast(f"需求已提交! (record: {record_id})", "success")
                except ValueError as e:
                    return _make_toast(str(e), "error")
                except Exception as e:
                    logger.error("[Request] 提交失败: %s", e, exc_info=True)
                    return _make_toast(f"提交失败: {e}", "error")

            # ── 生成表单提交（原有逻辑）──
            logger.info("[卡片] 用户=%s, 表单=%s", open_id, form_value)
            ...existing generate form code...
```

**Step 3: Run tests + commit**

```bash
python3 -m pytest tests/ -v
git add bot_ws.py
git commit -m "feat(request): wire request menu + form submit to bot_ws"
```

---

### Task 5: 集成测试

**No code changes — manual verification.**

1. Start bot: `python3 bot_ws.py --test card`
2. In Feishu bot backend, add `request` menu button (event_key = `request`)
3. Click request menu → verify form card appears
4. Submit with valid data (deadline > 15 working days) → verify record created in Calendar table
5. Submit with deadline too soon → verify error toast
6. Submit with missing fields → verify error toast
7. Check Calendar table in Feishu to confirm the record was written correctly
