# Async Pipeline 设计文档

## 背景

Pipeline 单次执行 85-118s，生图占 46%，LLM 占 34%。
当前同步架构并发上限 1-2 请求，无法支撑多 provider / 批量 / 高并发 / 埋点等未来需求。

## 目标

- 架构可扩展性优先（多 provider、批量生成、埋点信号）
- 单次延迟适度降低（~10-15%）
- 当前单机部署，未来可平滑上云
- 飞书表格查询不加缓存，保持实时性

## PERF-TEST 基线（3 次实测）

| 阶段 | 耗时 | 占比 |
|------|------|------|
| 飞书认证+路由+TABLE1/2 | ~4.4s | 5% |
| TABLE3 查询 | ~1.3s | 1.5% |
| 参考图下载 | ~0.6s (权限失败) | 0.6% |
| LLM 结构化分析 (Pro) | 13-16s | 17% |
| LLM 提示词生成 (Flash) | 10-14s | 13% |
| 4x 并行生图 | 39-78s | 46% |
| 4x 抠图+拼图 | ~7s | 9% |
| 4x 预览上传 | ~3.4s | 4% |
| Phase 2 | ~2.6s | 3% |

## 方案：Async Pipeline + Event Bus

### 改造范围

| 模块 | 改动 |
|------|------|
| `pipeline/orchestrator.py` | sync → async，阶段并行化 |
| `feishu.py` | requests → httpx.AsyncClient |
| `providers/gemini.py` | requests → httpx.AsyncClient |
| `pipeline/data.py` | 函数签名 async |
| `pipeline/postprocess.py` | 抠图用 executor 并行 |
| `app.py` | endpoint 改 async def |

### 不变

- `pipeline/context.py` — 纯内存
- `pipeline/subject.py` — 纯 CPU
- `pipeline/tier_profile.py` — 缓存 YAML
- `pipeline/candidate_store.py` — 内存 dict
- `models.py` / `settings.py` / `defaults.py`
- 飞书表格查询不缓存

### 并行化策略

```
Phase 1（现在 ~85-118s）:
  ┌ TABLE1+TABLE2 (并行) ──────┐
  └ TABLE3 + 参考图下载 (并行) ┘ → LLM分析 → LLM提示词 → 4x生图(已并行)
                                                            ↓
                                                   4x抠图(并行) → 4x上传(并行)

预估: 省 ~12s (抠图5s + 上传2.4s + 查询重叠4s)
```

### Event Bus（预留）

轻量级 in-process 事件总线，用于：
- 阶段耗时埋点
- 未来 A/B 测试信号采集
- 监控告警钩子

### 兼容性

- `generate()` 兼容入口保留，内部调 `asyncio.run()`
- CLI 模式不受影响
- bot_ws.py 可逐步迁移
