# Calendar + Inspire + Request 设计文档

## 概述

为飞书 Bot 新增三个功能：礼物项目看板（Calendar）、灵感对话（Inspire）、需求提单（Request）。

## Feature 1: Calendar — 礼物项目看板

### 定位
运营视角：展示近期礼物项目状态，纯阅读卡片。

### 触发方式
Bot 菜单新增 `calendar` 按钮。

### 数据源
- 飞书多维表格，按季度分表（Q1/Q2/Q3/Q4），共用同一 `app_token`
- `app_token`: `FJucbi5B0aCnpbsBDGelU0NFgug`
- Q1: `table_id=tblQPUBfShTwkIxb`, `view_id=vew6G1bwqT`
- Q2/Q3/Q4: 待补充
- 运行时根据当前日期自动选季度（1-3月=Q1, 4-6月=Q2, 7-9月=Q3, 10-12月=Q4）
- 配置在 `generation_defaults.yaml` 中维护

### 展示规则
- 按 Deadline 排序，展示距今最近的 **15 条**
- 每次点击按钮重新 fetch，不缓存

### 卡片展示字段
- Gift Name // 礼物名
- Price // 价格
- Gift Type // 礼物类型
- Regions // 区域（多选）
- Progress // 进展（状态标签）
- Designer // 设计师
- POC // 需求方
- Deadline // 截止日期
- Doc // 需求文档（可点击链接，卡片提示"细节在这里看"）

### 表格字段结构（实测确认）
| 字段名 | 类型 | 说明 |
|--------|------|------|
| Gift Name // 礼物名 | 文本 | 主键 |
| Price // 价格 | 数字 | |
| Gift Type // 礼物类型 | 单选 | Banner/Animation/Random/Face |
| Categories // 需求类型 | 单选 | Regular/Campaign/IP Partnership/... |
| Regions // 区域 | 多选 | 23个区域 |
| POC // 需求方 | 人员 | |
| Doc // 需求文档 | 超链接 | `{link, text}` 结构 |
| Progress // 进展 | 单选 | Not Scheduled/Not Started/in Design/in Feedback/Delivered/... |
| Designer // 设计师 | 人员 | |
| Deadline // 截止日期 | 日期 | 毫秒时间戳 |
| Production Pipeline // 生产流程 | 多选 | In House/Vendor/AIGC/The Agent/Giftopia |

---

## Feature 2: Inspire — 灵感对话

### 定位
创意视角：AI 礼物创意顾问，对话式交互，帮用户发现"什么值得做"。

### 触发方式
Bot 菜单 `inspire` 按钮（已预留，当前返回占位文案）。

### 对话流程

```
用户点击 inspire
    ↓
创建 InspireSession（槽位: region=null, price=null, subject=null）
    ↓
发送欢迎消息
    ↓
┌─ 多轮对话循环 ──────────────────────────────┐
│  用户消息 → 意图提取(flash-lite) → 更新槽位  │
│       ↓                                      │
│  槽位有变化? → 查 TABLE0/1/2/3 → 更新上下文  │
│  槽位没变化? → 跳过查表                      │
│       ↓                                      │
│  主模型生成回复（system prompt + 表数据上下文）│
│       ↓                                      │
│  三种出口:                                    │
│  1. 继续聊/停止 → 留在 session               │
│  2. Generate → 预填表单 → 终止 session       │
│  3. Request → 弹出提单表单 → 终止 session    │
└──────────────────────────────────────────────┘
```

### 意图提取 + 槽位填充（方案 A：两步串行）

**Step 1 — 提取（轻量模型 flash-lite）：**
- 输入：用户当前消息 + 已有槽位
- 输出：结构化 JSON `{region, price, subject, intent}`
- intent: `chat` / `generate` / `request` / `stop`
- 模糊匹配："中东" → MENA，"便宜的" → price_hint=low

**Step 2 — 查表（仅槽位有新信息时）：**
- 有 region → TABLE0 路由 → TABLE1 区域风格
- 有 price → TABLE2 档位规则
- 两者都有 → 额外查 TABLE3 参考案例

**Step 3 — 生成回复（主模型）：**
- System prompt = 静态领域知识 + 动态表数据上下文
- 对话历史保持在 session 中

### 提取失败的优雅降级
- 未提取到参数 → 不查表，用基础领域知识回复 + 引导用户补充
- 多轮天然容错：本轮没提取到，下轮用户补充后再提取

### Session 管理
- `InspireSession`：复用 `session_store` 模式
- 字段：user_id, slots(region/price/subject), conversation_history, table_context_cache
- TTL 超时自动清理（复用 `edit_session_ttl` 或独立配置）
- Generate/Request 触发时主动终止，发送"灵感对话已终止"

### LLM System Prompt 包含
- 礼物类型说明（Banner/Animation/Random/Face）
- 价格档位与设计复杂度关系
- 区域文化差异概述
- 当前日期（用于时令事件推荐）
- "什么样的 subject 适合做礼物"的设计准则

---

## Feature 3: Request — 需求提单

### 定位
用户通过飞书向团队下需求，写入 Calendar 多维表格。

### 触发方式
- Inspire 对话出口（intent=request 时触发）
- 未来可加独立菜单按钮

### 表单字段
| 字段 | 必填 | 对应表字段 |
|------|------|-----------|
| 礼物名 | 是 | Gift Name // 礼物名 |
| 价格 | 是 | Price // 价格 |
| 礼物类型 | 是 | Gift Type // 礼物类型 (Banner/Animation/Random/Face) |
| 需求类型 | 是 | Categories // 需求类型 |
| 区域 | 是 | Regions // 区域（多选） |
| 活动PRD | 否 | Doc // 需求文档（可用活动名占位） |
| 期望交付时间 | 是 | Deadline // 截止日期 |

### 系统自动填充
- `POC // 需求方` = 提交人（从飞书事件获取）
- `Progress // 进展` = "Not Scheduled// 未排期"

### 校验规则
- **15 工作日规则**：期望交付时间距今 < 15 个工作日 → 提交失败
- 失败提示："需求至少需要提前 15 个工作日提交。如需例外请联系 [例外审批群]"
- 例外审批群链接：待配置

### 写入目标
- 和 Calendar 同一张表（同 app_token / table_id）
- 通过飞书 Bitable API `POST /records` 创建记录

---

## 架构变动

| 模块 | 变动 |
|------|------|
| `generation_defaults.yaml` | 新增 calendar 季度配置、inspire 相关配置 |
| `models.py` | 新增 `InspireSession`、`CalendarConfig` |
| `cards.py` | 新增 `build_calendar_card()`、`build_request_form_card()` |
| `bot_ws.py` | 新增 `calendar` 菜单处理 + inspire 对话路由 + request 表单提交处理 |
| `feishu.py` | 新增 `create_bitable_record()` / `create_bitable_record_sync()` |
| `pipeline/inspire.py` | 新模块：灵感对话编排（意图提取 + 槽位管理 + 表查询 + 回复生成） |
| `prompts/inspire_system.md` | 新文件：灵感对话 system prompt |
| `prompts/inspire_extract.md` | 新文件：意图/槽位提取 prompt |

### Bot 菜单结构（更新后）
- `generate` — 生成表单
- `calendar` — 项目看板（新）
- `inspire` — 灵感对话（更新）
- `debug` — 调试信息

---

## 技术决策记录

1. **Calendar 数据不缓存**：每次 fetch，保证实时性
2. **季度切换用 YAML 配置**：未来迁移到管理后台
3. **灵感对话用方案 A（两步串行）**：简单、不慢、失败时优雅降级
4. **不用 RAG**：数据是结构化表格且量小，参数化查询比向量检索更合适
5. **Inspire session 终止策略**：Generate/Request 触发即终止，发消息通知用户
