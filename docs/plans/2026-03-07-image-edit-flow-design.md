# Image Edit Flow 设计文档

## 背景

用户选择候选图（Phase 2）后，当前流程即结束。用户如果想微调（换背景、加元素等），只能重新走完整生成链路。
需要一个轻量的"图片编辑"后续流程，让用户通过飞书回复图片 + 输入文字的方式，利用 Gemini image edit 能力进行多轮迭代调整。

## 目标

- 用户选完候选图后可多轮编辑，无需触发完整生成
- 利用 Gemini `generateContent` 的多模态能力，一次调用同时返回编辑图 + AI 引导文字
- 编辑流可被中断，通过路由卡片引导回重新生成或继续编辑
- EditProvider 可插拔，先用 Gemini，未来可接其他供应商
- 架构可扩展，为未来意图编排（新需求/灵感模式等）预留空间
- 目标并发：100 人量级

## 用户旅程状态机

```
新对话 ─→ 新生成 ─→ 填生成表 ─→ Gift Hub (TABLE0/1/2) ─→ 生图
                      ↑ 选了重新生成                       ↑ 选了重新生成
                      │                                    │
          ─→ 后处理和呈现 ─→ 用户选择 ─→ 进入编辑流 ─→ 多轮对话 ─→ 完成交付
                              ↑                                      │
                              └──────────── loop ────────────────────┘
                                                                     │
                                                            引导回重新生成
```

### Session 状态

| 状态 | 含义 | 进入条件 |
|------|------|----------|
| `IDLE` | 无活跃 session | 初始 / TTL 超时 / 用户重新生成 |
| `SELECTING` | Phase 1 已出候选图，等用户选择 | `generate_candidates` 完成 |
| `EDITING` | 编辑流中，接受编辑指令 | 用户选了 A/B/C/D |
| `DELIVERED` | 本轮编辑完成，等待用户决策 | 用户说"好了" / 不活跃 |

### 状态转换

```
IDLE ──(generate)──→ SELECTING
SELECTING ──(pick A/B/C/D)──→ EDITING
SELECTING ──(regenerate)──→ SELECTING
SELECTING ──(modify)──→ SELECTING

EDITING ──(回复bot图+文字)──→ EDITING  (多轮循环)
EDITING ──(纯文字,看起来是编辑指令)──→ EDITING  (对 current_image 编辑)
EDITING ──("好了"/"不用了"/不活跃)──→ DELIVERED

DELIVERED ──(卡片"是",重新生成)──→ IDLE → SELECTING
DELIVERED ──(卡片"否"/回复编辑)──→ EDITING
DELIVERED ──(TTL 超时)──→ IDLE
```

## 数据模型

### EditSession

```python
class SessionState(str, Enum):
    SELECTING = "selecting"
    EDITING   = "editing"
    DELIVERED = "delivered"

class EditSession:
    user_id: str                       # 用户 open_id (key)
    state: SessionState
    request_id: str                    # 关联的 candidate request_id
    current_image: bytes               # 当前最新图片（matted）
    conversation_history: list[dict]   # Gemini contents 数组
    message_id_map: dict[str, str]     # {bot_msg_id → "final"/"edit_N"}
    original_config: GenerationConfig  # 原始配置（用于 regen）
    last_active: float                 # 最后活跃时间戳
```

每个用户同一时间只有一个活跃 session（key = `user_id`）。

### EditResult

```python
class EditResult(BaseModel):
    image: bytes              # 编辑后图片
    message: str              # AI 引导文字
    updated_history: list[dict]  # 更新后对话历史
```

### 对话历史大小控制

每轮编辑追加 user message + model response（含图片 base64），约 1-2MB/轮。
上限 10 轮，超过后保留首轮图片 + 最近 N 轮。

## 消息路由

### `on_message` 路由逻辑

```python
def on_message(data):
    sender_id = event.sender.sender_id.open_id
    parent_id = event.message.parent_id
    text = parse_text(event.message)
    session = session_store.get(sender_id)

    # 1. 回复了 bot 发出的图片 → 编辑
    if parent_id and session and parent_id in session.message_id_map:
        handle_edit(sender_id, session, text, parent_id)
        return

    # 2. 有活跃 EDITING/DELIVERED session + 纯文字
    if session and session.state in (EDITING, DELIVERED):
        handle_editing_text(sender_id, session, text)
        return

    # 3. 其他情况 → 现有 generate 逻辑
    params = parse_input(text)
    config = GenerationConfig(**params)
    handle_generate(sender_id, config)
```

### message_id 跟踪

bot 每次发图片时记录 `{message_id → 标签}` 到 session.message_id_map。
这样用户回复时通过 `parent_id` 直接匹配，零额外 API 调用。

注册时机：
- `handle_finalize` 发送最终图后 → `"final"`
- `handle_edit` 发送编辑结果后 → `"edit_N"`

### 纯文字处理（EDITING 状态）

```python
def handle_editing_text(sender_id, session, text):
    if matches_termination(text):  # "好了"/"不用了"/"OK"/"done"
        session.state = DELIVERED
        send_routing_card(sender_id)
    else:
        # 当作对 current_image 的编辑指令
        handle_edit(sender_id, session, text, parent_id=None)
```

## EditProvider 抽象

### 接口定义 — `providers/base.py`

```python
class EditProvider(ABC):
    @abstractmethod
    async def edit(
        self,
        image: bytes,
        instruction: str,
        conversation_history: list[dict] | None = None,
    ) -> EditResult:
        """编辑图片，返回编辑后图片 + AI 引导文字。"""
        ...
```

### GeminiEditProvider — `providers/gemini.py`

利用 `generateContent` + `responseModalities: ["TEXT", "IMAGE"]`，一次调用同时返回编辑图 + 引导文字。

对话历史直接作为 `contents` 数组传入（Gemini 原生多轮支持）：
```python
body = {
    "system_instruction": {"parts": [{"text": EDIT_SYSTEM_PROMPT}]},
    "contents": history + [current_turn],
    "generationConfig": {
        "responseModalities": ["TEXT", "IMAGE"],
    },
}
```

### 注册

`providers/registry.py` 新增 `_edit_providers` 注册表 + `get_edit_provider()`。

## 卡片交互

### 新增：路由卡片 `build_routing_card(request_id)`

完成交付时发送，内容："你希望重新生成礼物吗？"
- 按钮 [是] → `{"action": "route_regen", "request_id": "..."}`
- 按钮 [否] → `{"action": "route_continue", "request_id": "..."}`

### `on_card_action` 新增路由

```python
if act == "route_regen":
    session_store.remove(open_id)
    config = ...  # 从 session 的 original_config
    _generate_pool.submit(handle_generate, open_id, config)

if act == "route_continue":
    session.state = SessionState.EDITING
    # toast: "继续编辑，请回复图片并输入调整指令"
```

### 编辑结果呈现

每轮编辑后发送：
1. 编辑后图片（直接发原图，快速迭代）
2. AI 引导文字（如"已把背景改成红色，还想调什么？"）
3. 可选：用户可点"预览 Panel"按钮触发抠图+拼图后处理

## 存储 — `session_store.py`

与 `candidate_store.py` 同模式：
- 内存 dict，key = `user_id`
- TTL 30 分钟不活跃自动清理
- `threading.Lock` 线程安全
- 100 人并发 × 5MB/session ≈ 500MB 峰值内存，可接受

## 配置扩展 — `generation_defaults.yaml`

```yaml
# 编辑流配置
edit_provider: "gemini"
edit_models:
  - "gemini-3.1-flash-image-preview"
edit_timeout: 120
edit_max_rounds: 10
edit_session_ttl: 1800  # 30分钟
```

## 改动清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `pipeline/session_store.py` | **新增** | EditSession 存储（内存 dict + TTL） |
| `pipeline/edit.py` | **新增** | handle_edit / handle_editing_text 编排逻辑 |
| `prompts/edit_system.md` | **新增** | 编辑模式系统提示词 |
| `providers/base.py` | 修改 | 新增 EditProvider ABC + EditResult |
| `providers/gemini.py` | 修改 | 新增 GeminiEditProvider |
| `providers/registry.py` | 修改 | 新增 edit provider 注册表 |
| `models.py` | 修改 | 新增 SessionState, EditSession 模型 |
| `bot_ws.py` | 修改 | on_message 路由改造 + on_card_action 新增路由 |
| `cards.py` | 修改 | 新增 build_routing_card() |
| `pipeline/orchestrator.py` | 修改 | handle_finalize 末尾创建 EditSession |
| `generation_defaults.yaml` | 修改 | 新增 edit_* 配置项 |
| `defaults.py` / `models.py` | 修改 | GenerationDefaults 新增 edit 相关字段 |

### 不动的部分

- `pipeline/candidate_store.py` — Phase 1 暂存独立工作
- `pipeline/data.py`, `context.py`, `subject.py` — 编辑流不涉及数据查询
- `pipeline/postprocess.py` — 编辑流中作为可选调用
- `app.py` — FastAPI 路由暂不改
- `feishu.py` — 可能备用新增 get_message()，但 message_id_map 方案下不需要

## 未来扩展点

- **意图编排层**：on_message 路由可演进为意图分类器（LLM/规则），路由到 generate / edit / inspire / request 等不同 handler
- **用户自传图编辑**：EDITING 状态下检测用户上传图片，作为 reference image
- **图片首发模式**：新对话中用户直接传图，作为需求输入（新需求 → Request Hub）
- **灵感模式**：新灵感 → 灵感 Hub（旅程图中标注为尚未实现）
