# 层级工作流实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将单阶段线性 pipeline 拆分为两阶段交互流（4x 并行生图 → 用户选择 → 层级后处理），支持 P0/P1/P2 层级独立提示词和后处理链。

**Architecture:** Phase 1 (`generate_candidates`) 执行数据查询 + LLM 分析 + 4x 并行生图，结果暂存在进程内 candidate_store（TTL 30 分钟）。飞书卡片展示 4 张候选图，用户点击选择按钮触发 Phase 2 (`finalize_selected`)，执行抠图（占位）+ 视频（占位）后处理。TierProfile 从 YAML 加载，按层级覆盖提示词文件和可选模型参数。

**Tech Stack:** Python 3.14, Pydantic, FastAPI, concurrent.futures, lark_oapi, pytest

---

### Task 1: TierProfile 数据模型 + YAML 配置

**Files:**
- Modify: `models.py` (新增 TierProfile 类, ~L58 GenerationDefaults 之前)
- Modify: `models.py:33-57` (GenerationDefaults 新增 tier_profiles 字段)
- Modify: `generation_defaults.yaml` (新增 tier_profiles section)
- Test: `tests/test_tier_profile.py` (新建)

**Step 1: 写失败测试**

```python
# tests/test_tier_profile.py
"""层级配置加载的单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_tier_profile_model():
    """TierProfile 基础字段解析。"""
    from models import TierProfile
    p = TierProfile(analyze_prompt_file="analyze_P0.md", prompt_gen_prompt_file="prompt_gen_P0.md")
    assert p.analyze_prompt_file == "analyze_P0.md"
    assert p.image_models is None  # 可选字段默认 None


def test_generation_defaults_has_tier_profiles():
    """GenerationDefaults 包含 tier_profiles 字段。"""
    from models import GenerationDefaults, TierProfile
    d = GenerationDefaults(
        analyze_model="m", prompt_model="m", image_models=["m"],
        tier_profiles={"P0": TierProfile(
            analyze_prompt_file="analyze_P0.md",
            prompt_gen_prompt_file="prompt_gen_P0.md",
        )},
    )
    assert "P0" in d.tier_profiles
    assert d.tier_profiles["P0"].analyze_prompt_file == "analyze_P0.md"


def test_generation_defaults_empty_tier_profiles():
    """tier_profiles 为空时默认空字典。"""
    from models import GenerationDefaults
    d = GenerationDefaults(analyze_model="m", prompt_model="m", image_models=["m"])
    assert d.tier_profiles == {}
```

**Step 2: 运行测试确认失败**

Run: `cd /Users/bytedance/Documents/Projects/Creative_Micro_Tool/Creative_Agent && python -m pytest tests/test_tier_profile.py -v`
Expected: ImportError — TierProfile 不存在

**Step 3: 实现 TierProfile + 修改 GenerationDefaults**

在 `models.py` 的 `GenerationDefaults` 类之前新增:
```python
class TierProfile(BaseModel):
    """层级配置：提示词文件路径 + 可选参数覆盖。

    未设置的可选字段在运行时继承全局默认值。
    """
    analyze_prompt_file: str                    # prompts/ 下的分析提示词文件名
    prompt_gen_prompt_file: str                 # prompts/ 下的生图提示词文件名
    image_models: list[str] | None = None       # 可选：覆盖图片模型列表
    image_size: str | None = None               # 可选：覆盖图片尺寸
    image_aspect_ratio: str | None = None       # 可选：覆盖图片宽高比
```

在 `GenerationDefaults` 类新增字段:
```python
    # 层级配置（键=层级名 如 "P0"，值=TierProfile）
    tier_profiles: dict[str, TierProfile] = {}
```

**Step 4: 更新 generation_defaults.yaml**

在文件末尾追加:
```yaml
# ── 层级配置 ──────────────────────────────────────────────
# 每个层级可独立配置提示词文件和可选的模型/图片参数覆盖
# 未配置的层级使用全局默认提示词 (analyze_system.md / prompt_gen_system.md)
tier_profiles:
  P0:
    analyze_prompt_file: "analyze_P0.md"
    prompt_gen_prompt_file: "prompt_gen_P0.md"
  P1:
    analyze_prompt_file: "analyze_P1.md"
    prompt_gen_prompt_file: "prompt_gen_P1.md"
  P2:
    analyze_prompt_file: "analyze_P2.md"
    prompt_gen_prompt_file: "prompt_gen_P2.md"
```

**Step 5: 运行测试确认通过**

Run: `cd /Users/bytedance/Documents/Projects/Creative_Micro_Tool/Creative_Agent && python -m pytest tests/test_tier_profile.py -v`
Expected: 3 passed

**Step 6: 提交**

```bash
git add models.py generation_defaults.yaml tests/test_tier_profile.py
git commit -m "feat: TierProfile 数据模型 + YAML 层级配置"
```

---

### Task 2: CandidateResult 数据模型

**Files:**
- Modify: `models.py` (PipelineResult 之后新增 CandidateResult)
- Test: `tests/test_tier_profile.py` (追加测试)

**Step 1: 写失败测试**

追加到 `tests/test_tier_profile.py`:
```python
def test_candidate_result_model():
    """CandidateResult 基础字段。"""
    from models import CandidateResult
    cr = CandidateResult(
        request_id="abc123",
        tier="P0",
        subject_final="雄狮徽章",
        prompt="中文提示词",
        english_prompt="english prompt",
        image_keys=["key1", "key2", "key3", "key4"],
        image_bytes_list=[b"img1", b"img2", b"img3", b"img4"],
        region="MENA",
        price=1,
    )
    assert len(cr.image_keys) == 4
    assert cr.tier == "P0"


def test_candidate_result_excludes_bytes():
    """image_bytes_list 不应出现在序列化输出中。"""
    from models import CandidateResult
    cr = CandidateResult(
        request_id="x", tier="P0", subject_final="s", prompt="p",
        english_prompt="e", image_keys=["k"], image_bytes_list=[b"b"],
        region="MENA", price=1,
    )
    d = cr.model_dump()
    assert "image_bytes_list" not in d
```

**Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_tier_profile.py::test_candidate_result_model -v`
Expected: ImportError

**Step 3: 实现 CandidateResult**

在 `models.py` 的 `PipelineResult` 之后新增:
```python
class CandidateResult(BaseModel):
    """Phase 1 输出：多张候选图 + 元数据，等待用户选择。"""
    request_id: str                  # 请求追踪 ID
    tier: str                        # 匹配到的价格层级
    subject_final: str               # 最终主体（可能已被容器包裹）
    prompt: str                      # 中文提示词
    english_prompt: str              # 英文提示词
    image_keys: list[str]            # 飞书 image_key 列表
    image_bytes_list: list[bytes] = Field(default_factory=list, exclude=True)  # 原始图片字节（不序列化）
    region: str                      # 区域
    price: int                       # 价格
```

**Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_tier_profile.py -v`
Expected: 5 passed

**Step 5: 提交**

```bash
git add models.py tests/test_tier_profile.py
git commit -m "feat: CandidateResult 数据模型"
```

---

### Task 3: candidate_store 候选暂存模块

**Files:**
- Create: `pipeline/candidate_store.py`
- Test: `tests/test_candidate_store.py` (新建)

**Step 1: 写失败测试**

```python
# tests/test_candidate_store.py
"""候选图暂存模块的单元测试。"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import CandidateResult


def _make_candidate(rid="test123") -> CandidateResult:
    """构造测试用 CandidateResult。"""
    return CandidateResult(
        request_id=rid, tier="P0", subject_final="雄狮",
        prompt="p", english_prompt="e",
        image_keys=["k1", "k2"], image_bytes_list=[b"a", b"b"],
        region="MENA", price=1,
    )


def test_save_and_get():
    """保存后能取回。"""
    from pipeline.candidate_store import save, get, _store
    _store.clear()
    cr = _make_candidate()
    save(cr)
    assert get("test123") is not None
    assert get("test123").tier == "P0"


def test_get_nonexistent():
    """不存在的 request_id 返回 None。"""
    from pipeline.candidate_store import get, _store
    _store.clear()
    assert get("no_such_id") is None


def test_remove():
    """取回后可删除。"""
    from pipeline.candidate_store import save, get, remove, _store
    _store.clear()
    save(_make_candidate())
    remove("test123")
    assert get("test123") is None


def test_cleanup_expired(monkeypatch):
    """过期条目被清理。"""
    from pipeline import candidate_store
    from pipeline.candidate_store import save, cleanup, _store
    _store.clear()
    save(_make_candidate())
    # 模拟 TTL 过期
    monkeypatch.setattr(candidate_store, "_TTL", 0)
    cleanup()
    from pipeline.candidate_store import get
    assert get("test123") is None
```

**Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_candidate_store.py -v`
Expected: ModuleNotFoundError

**Step 3: 实现 candidate_store**

```python
# pipeline/candidate_store.py
"""候选图暂存：Phase 1 结果等待用户选择，TTL 30 分钟自动过期。"""

import logging
import time

from models import CandidateResult

logger = logging.getLogger(__name__)

# 暂存结构：{request_id: (CandidateResult, timestamp)}
_store: dict[str, tuple[CandidateResult, float]] = {}
_TTL = 1800  # 30 分钟过期


def save(result: CandidateResult) -> None:
    """保存候选结果，等待用户选择。"""
    _store[result.request_id] = (result, time.time())
    logger.info("[暂存] 已保存 request_id=%s, %d 张候选图",
                result.request_id, len(result.image_keys))


def get(request_id: str) -> CandidateResult | None:
    """获取候选结果，过期返回 None。"""
    entry = _store.get(request_id)
    if entry is None:
        return None
    result, ts = entry
    if time.time() - ts > _TTL:
        del _store[request_id]
        logger.info("[暂存] request_id=%s 已过期，自动清理", request_id)
        return None
    return result


def remove(request_id: str) -> None:
    """删除候选结果（用户选择后调用）。"""
    _store.pop(request_id, None)


def cleanup() -> None:
    """清理所有过期条目。"""
    now = time.time()
    expired = [rid for rid, (_, ts) in _store.items() if now - ts > _TTL]
    for rid in expired:
        del _store[rid]
    if expired:
        logger.info("[暂存] 清理 %d 条过期记录", len(expired))
```

**Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_candidate_store.py -v`
Expected: 4 passed

**Step 5: 提交**

```bash
git add pipeline/candidate_store.py tests/test_candidate_store.py
git commit -m "feat: candidate_store 候选图暂存模块"
```

---

### Task 4: context.py 支持层级提示词

**Files:**
- Modify: `pipeline/context.py:10-24` (get_analyze_system / get_prompt_gen_system 新增 tier_file 参数)
- Modify: `tests/test_context.py` (追加测试)

**Step 1: 写失败测试**

追加到 `tests/test_context.py`:
```python
def test_get_analyze_system_tier_file(tmp_path, monkeypatch):
    """指定 tier_file 时从对应文件加载。"""
    from pipeline import context
    # 创建临时提示词文件
    tier_file = tmp_path / "analyze_P0.md"
    tier_file.write_text("P0 专用分析提示词", encoding="utf-8")
    monkeypatch.setattr(context, "_PROMPTS_DIR", tmp_path)
    # 清除 lru_cache
    context._load_prompt.cache_clear()

    result = context.get_analyze_system(tier_file="analyze_P0.md")
    assert result == "P0 专用分析提示词"


def test_get_analyze_system_override_beats_tier_file():
    """override 参数优先级高于 tier_file。"""
    from pipeline.context import get_analyze_system
    result = get_analyze_system(override="直接覆盖", tier_file="analyze_P0.md")
    assert result == "直接覆盖"


def test_get_prompt_gen_system_tier_file(tmp_path, monkeypatch):
    """prompt_gen 也支持 tier_file。"""
    from pipeline import context
    tier_file = tmp_path / "prompt_gen_P0.md"
    tier_file.write_text("P0 专用提示词生成", encoding="utf-8")
    monkeypatch.setattr(context, "_PROMPTS_DIR", tmp_path)
    context._load_prompt.cache_clear()

    result = context.get_prompt_gen_system(tier_file="prompt_gen_P0.md")
    assert result == "P0 专用提示词生成"
```

**Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_context.py::test_get_analyze_system_tier_file -v`
Expected: TypeError — get_analyze_system() got unexpected keyword argument 'tier_file'

**Step 3: 修改 context.py**

```python
def get_analyze_system(override: str | None = None, tier_file: str | None = None) -> str:
    """获取结构化分析的系统提示词。优先级：override > tier_file > 默认文件。"""
    if override:
        return override
    if tier_file:
        return _load_prompt(tier_file)
    return _load_prompt("analyze_system.md")


def get_prompt_gen_system(override: str | None = None, tier_file: str | None = None) -> str:
    """获取提示词扩写的系统提示词。优先级：override > tier_file > 默认文件。"""
    if override:
        return override
    if tier_file:
        return _load_prompt(tier_file)
    return _load_prompt("prompt_gen_system.md")
```

**Step 4: 运行全量 context 测试**

Run: `python -m pytest tests/test_context.py -v`
Expected: ALL passed (新旧测试都通过)

**Step 5: 提交**

```bash
git add pipeline/context.py tests/test_context.py
git commit -m "feat: context.py 支持层级提示词文件 (tier_file)"
```

---

### Task 5: 层级提示词占位文件

**Files:**
- Create: `prompts/analyze_P0.md`
- Create: `prompts/analyze_P1.md`
- Create: `prompts/analyze_P2.md`
- Create: `prompts/prompt_gen_P0.md`
- Create: `prompts/prompt_gen_P1.md`
- Create: `prompts/prompt_gen_P2.md`

**Step 1: 创建占位文件**

每个文件先从对应的默认文件复制内容，头部加层级标识注释。例如:

`prompts/analyze_P0.md`:
```
<!-- P0 层级专用分析提示词 -->
<!-- TODO: 设计团队填写 P0 特定指令 -->
```
然后追加 `prompts/analyze_system.md` 的现有内容。

对 P1/P2、prompt_gen 系列同理。

**Step 2: 提交**

```bash
git add prompts/analyze_P0.md prompts/analyze_P1.md prompts/analyze_P2.md \
        prompts/prompt_gen_P0.md prompts/prompt_gen_P1.md prompts/prompt_gen_P2.md
git commit -m "feat: 层级提示词占位文件 (P0/P1/P2)"
```

---

### Task 6: pipeline/tier_profile.py — 加载与合并逻辑

**Files:**
- Create: `pipeline/tier_profile.py`
- Test: `tests/test_tier_profile.py` (追加测试)

**Step 1: 写失败测试**

追加到 `tests/test_tier_profile.py`:
```python
def test_load_tier_profile_known():
    """已配置的层级能正确加载。"""
    from pipeline.tier_profile import load_tier_profile
    p = load_tier_profile("P0")
    assert p.analyze_prompt_file == "analyze_P0.md"


def test_load_tier_profile_unknown():
    """未配置的层级返回 None。"""
    from pipeline.tier_profile import load_tier_profile
    p = load_tier_profile("P99")
    assert p is None


def test_apply_tier_profile_overrides():
    """TierProfile 的非 None 字段覆盖 ResolvedConfig。"""
    from models import ResolvedConfig, TierProfile
    from pipeline.tier_profile import apply_tier_profile
    cfg = ResolvedConfig(
        region="MENA", subject="雄狮", price=1,
        image_aspect_ratio="1:1", image_size="1K",
        analyze_model="m", prompt_model="m",
        image_models=["m1"], image_provider="gemini",
        text_timeout=60, image_timeout=180, enable_postprocess=True,
    )
    profile = TierProfile(
        analyze_prompt_file="analyze_P0.md",
        prompt_gen_prompt_file="prompt_gen_P0.md",
        image_size="2K",  # 覆盖
    )
    new_cfg = apply_tier_profile(cfg, profile)
    assert new_cfg.image_size == "2K"
    assert new_cfg.image_aspect_ratio == "1:1"  # 未覆盖，保持原值


def test_apply_tier_profile_no_override():
    """TierProfile 全部 None 时 ResolvedConfig 不变。"""
    from models import ResolvedConfig, TierProfile
    from pipeline.tier_profile import apply_tier_profile
    cfg = ResolvedConfig(
        region="MENA", subject="雄狮", price=1,
        image_aspect_ratio="1:1", image_size="1K",
        analyze_model="m", prompt_model="m",
        image_models=["m1"], image_provider="gemini",
        text_timeout=60, image_timeout=180, enable_postprocess=True,
    )
    profile = TierProfile(
        analyze_prompt_file="a.md", prompt_gen_prompt_file="p.md",
    )
    new_cfg = apply_tier_profile(cfg, profile)
    assert new_cfg.image_size == "1K"
    assert new_cfg.image_models == ["m1"]
```

**Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_tier_profile.py::test_load_tier_profile_known -v`
Expected: ModuleNotFoundError

**Step 3: 实现 tier_profile.py**

```python
# pipeline/tier_profile.py
"""层级配置加载与合并：从 YAML 读取 TierProfile，覆盖 ResolvedConfig。"""

from __future__ import annotations

import logging

from defaults import load_defaults
from models import ResolvedConfig, TierProfile

logger = logging.getLogger(__name__)


def load_tier_profile(tier: str) -> TierProfile | None:
    """从 generation_defaults.yaml 加载指定层级的配置。

    未配置的层级返回 None。
    """
    d = load_defaults()
    profile = d.tier_profiles.get(tier)
    if profile:
        logger.info("[层级] 已加载 TierProfile: %s", tier)
    else:
        logger.info("[层级] 未找到 TierProfile: %s，使用全局默认", tier)
    return profile


def apply_tier_profile(cfg: ResolvedConfig, profile: TierProfile) -> ResolvedConfig:
    """用层级配置覆盖 ResolvedConfig 中的可选参数。

    TierProfile 中为 None 的字段保持 cfg 原值不变。
    返回新的 ResolvedConfig 实例（不修改原对象）。
    """
    overrides = {}
    if profile.image_models is not None:
        overrides["image_models"] = profile.image_models
    if profile.image_size is not None:
        overrides["image_size"] = profile.image_size
    if profile.image_aspect_ratio is not None:
        overrides["image_aspect_ratio"] = profile.image_aspect_ratio
    if overrides:
        logger.info("[层级] 参数覆盖: %s", overrides)
    return cfg.model_copy(update=overrides)
```

**Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_tier_profile.py -v`
Expected: ALL passed (9 tests)

**Step 5: 提交**

```bash
git add pipeline/tier_profile.py tests/test_tier_profile.py
git commit -m "feat: tier_profile 层级配置加载与合并"
```

---

### Task 7: postprocess.py — 抠图 + 视频处理器占位

**Files:**
- Modify: `pipeline/postprocess.py` (新增 MattingProcessor, VideoGenerationProcessor, 修改 build_postprocess_chain)
- Test: `tests/test_postprocess.py` (新建)

**Step 1: 写失败测试**

```python
# tests/test_postprocess.py
"""后处理链的单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import PipelineResult


def _make_result() -> PipelineResult:
    return PipelineResult(
        subject_final="雄狮", tier="P0", prompt="p", english_prompt="e",
        status="generated", media_bytes=b"fake_image",
    )


def test_matting_processor_passthrough():
    """抠图处理器占位：不修改数据，直接透传。"""
    from pipeline.postprocess import MattingProcessor
    proc = MattingProcessor()
    result = proc.process(_make_result())
    assert result.media_bytes == b"fake_image"


def test_video_processor_passthrough():
    """视频处理器占位：不修改数据，直接透传。"""
    from pipeline.postprocess import VideoGenerationProcessor
    proc = VideoGenerationProcessor()
    result = proc.process(_make_result())
    assert result.status == "generated"


def test_build_chain_p0():
    """P0 后处理链 = 保存 + 抠图。"""
    from pipeline.postprocess import build_postprocess_chain, ImageSaveProcessor, MattingProcessor
    chain = build_postprocess_chain("P0")
    types = [type(p) for p in chain]
    assert ImageSaveProcessor in types
    assert MattingProcessor in types


def test_build_chain_p2():
    """P2 后处理链 = 保存 + 抠图 + 视频。"""
    from pipeline.postprocess import build_postprocess_chain, ImageSaveProcessor, MattingProcessor, VideoGenerationProcessor
    chain = build_postprocess_chain("P2")
    types = [type(p) for p in chain]
    assert ImageSaveProcessor in types
    assert MattingProcessor in types
    assert VideoGenerationProcessor in types
```

**Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_postprocess.py -v`
Expected: ImportError — MattingProcessor 不存在

**Step 3: 实现**

修改 `pipeline/postprocess.py`:
```python
"""后处理链：可扩展的处理器模式。

当前实现：图片保存 + 抠图占位 + 视频占位。
"""

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

from models import PipelineResult
from settings import get_settings

logger = logging.getLogger(__name__)


class PostProcessor(ABC):
    """后处理器抽象基类。"""

    @abstractmethod
    def process(self, result: PipelineResult) -> PipelineResult:
        """处理 Pipeline 结果并返回（可修改结果内容）。"""
        ...


class ImageSaveProcessor(PostProcessor):
    """图片保存处理器：将生成的图片写入本地文件。"""

    def process(self, result: PipelineResult) -> PipelineResult:
        if result.media_bytes is None:
            return result
        output_dir = Path(get_settings().output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{result.subject_final}_{result.tier}_{ts}.png"
        path = output_dir / filename
        path.write_bytes(result.media_bytes)
        result.local_path = str(path)
        logger.info("  已保存到 %s", path)
        return result


class MattingProcessor(PostProcessor):
    """抠图处理器（占位，接入实际抠图服务后实现）。"""

    def process(self, result: PipelineResult) -> PipelineResult:
        # TODO: 调用抠图 API，替换 result.media_bytes 为抠图后的图片
        logger.info("  [抠图] 占位 — 待接入抠图服务")
        return result


class VideoGenerationProcessor(PostProcessor):
    """视频生成处理器（占位）。"""

    def process(self, result: PipelineResult) -> PipelineResult:
        # TODO: 调用视频生成服务
        logger.info("  [视频] 占位 — 待接入视频生成服务")
        return result


# ── 层级 → 后处理链编号 ────────────────────────────────────
# P0/P1: 图片保存 + 抠图
# P2+:   图片保存 + 抠图 + 视频
_VIDEO_TIERS = {"P2", "P3", "P4", "P5"}


def build_postprocess_chain(tier: str | None = None) -> list[PostProcessor]:
    """根据层级构建后处理链。"""
    chain: list[PostProcessor] = [ImageSaveProcessor()]
    if tier:
        # 所有层级都做抠图
        chain.append(MattingProcessor())
        # P2+ 追加视频生成
        if tier in _VIDEO_TIERS:
            chain.append(VideoGenerationProcessor())
    return chain
```

**Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_postprocess.py -v`
Expected: 4 passed

**Step 5: 提交**

```bash
git add pipeline/postprocess.py tests/test_postprocess.py
git commit -m "feat: 抠图/视频后处理器占位 + 层级后处理链"
```

---

### Task 8: orchestrator.py 拆分为两阶段

**Files:**
- Modify: `pipeline/orchestrator.py` (拆分为 generate_candidates + finalize_selected，保留 generate 兼容)
- Modify: `pipeline/__init__.py` (导出新函数)

这是最核心的改动。orchestrator.py 拆分为:

1. `generate_candidates(config) -> CandidateResult` — Phase 1
2. `finalize_selected(request_id, selected_index) -> PipelineResult` — Phase 2
3. `generate(config) -> PipelineResult` — 兼容入口（内部调 Phase 1 → auto-select 第 0 张 → Phase 2）

**Step 1: 实现 generate_candidates**

核心改动点 (基于现有 `_generate_inner`):

```python
# 新增导入
from concurrent.futures import ThreadPoolExecutor, as_completed
from models import CandidateResult
from pipeline.candidate_store import save as store_candidate
from pipeline.tier_profile import load_tier_profile, apply_tier_profile

# 并行生图数量
_NUM_CANDIDATES = 4


def generate_candidates(config: GenerationConfig) -> CandidateResult:
    """Phase 1: 数据查询 → LLM 分析 → 4x 并行生图 → 暂存候选。"""
    rid = config.request_id
    try:
        return _generate_candidates_inner(config)
    except Exception as e:
        logger.error("[%s] Phase 1 异常终止: %s", rid, e, exc_info=True)
        raise


def _generate_candidates_inner(config: GenerationConfig) -> CandidateResult:
    """Phase 1 核心逻辑。"""
    s = get_settings()
    cfg = config.resolve()
    rid = cfg.request_id
    region, subject, price = cfg.region, cfg.subject, cfg.price

    # 步骤1-5.5: 与现有逻辑相同 (认证 → 路由 → TABLE1/2/3 → 主体校验 → 上下文)
    # ...（保持不变）

    # 步骤3 之后: 加载 TierProfile 并覆盖配置
    tier = next((tier_rules[k] for k in _TIER_KEYS if tier_rules.get(k)), "?")
    profile = load_tier_profile(tier)

    # 用层级配置覆盖模型/图片参数
    if profile:
        cfg = apply_tier_profile(cfg, profile)

    # 步骤5.5 中使用层级提示词
    analyze_tier_file = profile.analyze_prompt_file if profile else None
    prompt_gen_tier_file = profile.prompt_gen_prompt_file if profile else None

    # 步骤6: 结构化分析 (传入 tier_file)
    analyze_system = get_analyze_system(cfg.analyze_system_prompt, tier_file=analyze_tier_file)
    # ...

    # 步骤7: 提示词生成 (传入 tier_file)
    prompt_gen_system = get_prompt_gen_system(cfg.prompt_gen_system_prompt, tier_file=prompt_gen_tier_file)
    # ...

    # 步骤8: 4x 并行生图
    image_provider = get_image_provider(
        name=cfg.image_provider, models=cfg.image_models,
        aspect_ratio=cfg.image_aspect_ratio, image_size=cfg.image_size,
        timeout=cfg.image_timeout,
    )
    logger.info("[%s] [步骤8] 正在并行生成 %d 张候选图...", rid, _NUM_CANDIDATES)
    with ThreadPoolExecutor(max_workers=_NUM_CANDIDATES) as pool:
        futures = [
            pool.submit(image_provider.generate, prompts["english_prompt"],
                        reference_images=ref_images or None)
            for _ in range(_NUM_CANDIDATES)
        ]
        image_list = []
        for i, f in enumerate(futures):
            try:
                img = f.result()
                image_list.append(img)
                logger.info("[%s]   候选图 %d: %d 字节", rid, i + 1, len(img))
            except Exception as e:
                logger.warning("[%s]   候选图 %d 生成失败: %s", rid, i + 1, e)

    if not image_list:
        raise RuntimeError("所有候选图生成均失败")

    # 上传到飞书获取 image_key
    token = feishu.get_token()
    image_keys = []
    for i, img in enumerate(image_list):
        try:
            key = feishu.upload_image(token, img)
            image_keys.append(key)
        except Exception as e:
            logger.warning("[%s]   候选图 %d 上传失败: %s", rid, i + 1, e)

    # 组装 CandidateResult
    candidate = CandidateResult(
        request_id=rid, tier=tier, subject_final=subject_final,
        prompt=prompts["prompt"], english_prompt=prompts["english_prompt"],
        image_keys=image_keys, image_bytes_list=image_list,
        region=region, price=price,
    )

    # 暂存等待用户选择
    store_candidate(candidate)
    return candidate
```

**Step 2: 实现 finalize_selected**

```python
def finalize_selected(request_id: str, selected_index: int) -> PipelineResult:
    """Phase 2: 取回选中候选图 → 层级后处理 → 发飞书。"""
    from pipeline.candidate_store import get as get_candidate, remove as remove_candidate

    candidate = get_candidate(request_id)
    if candidate is None:
        raise RuntimeError(f"候选结果已过期或不存在: request_id={request_id}")

    if selected_index < 0 or selected_index >= len(candidate.image_bytes_list):
        raise ValueError(f"无效的选择索引: {selected_index}, 可选范围 0-{len(candidate.image_bytes_list)-1}")

    rid = request_id
    logger.info("[%s] Phase 2: 用户选择了候选图 #%d", rid, selected_index + 1)

    selected_bytes = candidate.image_bytes_list[selected_index]

    # 组装 PipelineResult
    result = PipelineResult(
        subject_final=candidate.subject_final,
        tier=candidate.tier,
        prompt=candidate.prompt,
        english_prompt=candidate.english_prompt,
        media_type=MediaType.IMAGE,
        status="selected",
        request_id=rid,
        media_bytes=selected_bytes,
    )

    # 层级后处理链 (抠图 + 视频占位)
    for processor in build_postprocess_chain(candidate.tier):
        result = processor.process(result)

    # 发送到飞书
    try:
        token = feishu.get_token()
        s = get_settings()
        receive_id = s.feishu_receive_id

        if result.media_bytes:
            image_key = feishu.upload_image(token, result.media_bytes)
            result.image_key = image_key
            msg_id = feishu.send_image(token, receive_id, image_key)
            result.message_id = msg_id

            caption = (
                f"[Gift Final] {candidate.region} | {candidate.subject_final} "
                f"| {candidate.price} coins | {candidate.tier}\n\n"
                f"Prompt: {candidate.prompt}"
            )
            feishu.send_text(token, receive_id, caption)

        result.status = "sent_to_feishu"
    except Exception as e:
        logger.error("[%s] Phase 2 飞书发送失败: %s", rid, e, exc_info=True)
        result.status = "generated_but_send_failed"
        result.error_message = f"飞书发送失败: {e}"

    # 清理暂存
    remove_candidate(request_id)
    return result
```

**Step 3: 保留 generate() 兼容入口**

```python
def generate(config: GenerationConfig) -> PipelineResult:
    """兼容入口：Phase 1 → auto-select 第 0 张 → Phase 2。

    CLI 和 API 模式使用此入口，自动选择第一张候选图。
    """
    rid = config.request_id
    try:
        candidate = generate_candidates(config)
        return finalize_selected(candidate.request_id, 0)
    except Exception as e:
        logger.error("[%s] Pipeline 异常终止: %s", rid, e, exc_info=True)
        return PipelineResult(
            subject_final=config.subject,
            tier="?",
            prompt="",
            english_prompt="",
            status="error",
            error_message=str(e),
            request_id=rid,
        )
```

**Step 4: 更新 pipeline/__init__.py**

```python
"""Pipeline 编排包，对外暴露入口函数。"""

from pipeline.orchestrator import generate, generate_candidates, finalize_selected

__all__ = ["generate", "generate_candidates", "finalize_selected"]
```

**Step 5: 运行现有测试确认不破坏**

Run: `python -m pytest tests/ -v`
Expected: ALL existing tests pass

**Step 6: 提交**

```bash
git add pipeline/orchestrator.py pipeline/__init__.py
git commit -m "feat: orchestrator 拆分为两阶段 (generate_candidates + finalize_selected)"
```

---

### Task 9: bot_ws.py — 卡片回调路由 + Phase 2 触发

**Files:**
- Modify: `bot_ws.py` (on_card_action 新增候选选择分支, handle_generate 改用 generate_candidates, 新增 handle_finalize)

**Step 1: 修改 handle_generate 使用 Phase 1**

```python
from pipeline import generate_candidates, finalize_selected


def handle_generate(sender_id: str, config: GenerationConfig) -> None:
    """Phase 1: 生成候选图并发送选择卡片。"""
    token = feishu.get_token()

    feishu.send_text(
        token, sender_id,
        f"正在生成: {config.subject} | {config.price} coins | {config.region}...",
    )

    try:
        candidate = generate_candidates(config)
        # 发送候选图选择卡片
        card = build_candidate_card(candidate)
        feishu.send_card(token, sender_id, card)
        logger.info("已发送 %d 张候选图卡片: %s", len(candidate.image_keys), candidate.request_id)
    except Exception as e:
        logger.error("Phase 1 失败: %s", e, exc_info=True)
        feishu.send_text(token, sender_id, f"生成失败: {e}")


def handle_finalize(sender_id: str, request_id: str, selected_index: int) -> None:
    """Phase 2: 处理用户选择，执行后处理并发送结果。"""
    token = feishu.get_token()
    try:
        result = finalize_selected(request_id, selected_index)
        logger.info("Phase 2 完成: %s -> %s", request_id, result.status)
    except Exception as e:
        logger.error("Phase 2 失败: %s", e, exc_info=True)
        feishu.send_text(token, sender_id, f"处理失败: {e}")
```

**Step 2: 新增 build_candidate_card**

```python
def build_candidate_card(candidate) -> dict:
    """构建候选图选择卡片（占位模板，后续由用户提供正式卡片 JSON）。"""
    elements = []
    for i, key in enumerate(candidate.image_keys):
        # 图片展示
        elements.append({
            "tag": "img",
            "img_key": key,
            "alt": {"tag": "plain_text", "content": f"候选图 {i + 1}"},
        })
        # 选择按钮
        elements.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": f"选择方案 {i + 1}"},
            "type": "primary" if i == 0 else "default",
            "value": {
                "action": "candidate_select",
                "request_id": candidate.request_id,
                "selected_index": i,
            },
        })

    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"候选图 | {candidate.subject_final} | {candidate.tier}"},
            "template": "blue",
        },
        "elements": elements,
    }
```

**Step 3: 修改 on_card_action 路由**

```python
def on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    """处理卡片交互事件。

    路由逻辑：
    - form_value 有值 → 生成表单提交 → Phase 1
    - action.value 含 candidate_select → 候选选择 → Phase 2
    """
    try:
        event = data.event
        open_id = event.operator.open_id
        action = event.action

        # 路由1: 候选图选择按钮
        action_value = action.value
        if isinstance(action_value, dict) and action_value.get("action") == "candidate_select":
            rid = action_value["request_id"]
            idx = action_value["selected_index"]
            logger.info("[卡片] 用户=%s 选择候选图: request_id=%s, index=%d", open_id, rid, idx)
            _generate_pool.submit(handle_finalize, open_id, rid, idx)

            resp = P2CardActionTriggerResponse()
            resp.toast = CallBackToast()
            resp.toast.type = "info"
            resp.toast.content = f"已选择方案 {idx + 1}，正在处理..."
            return resp

        # 路由2: 生成表单提交 (现有逻辑)
        form_value = action.form_value or {}
        if form_value:
            # ... 现有表单解析逻辑不变 ...
            pass

        return P2CardActionTriggerResponse()
    except Exception as e:
        logger.error("[卡片] 错误: %s", e, exc_info=True)
        return P2CardActionTriggerResponse()
```

**Step 4: 运行完整测试**

Run: `python -m pytest tests/ -v`
Expected: ALL passed

**Step 5: 提交**

```bash
git add bot_ws.py
git commit -m "feat: bot_ws 两阶段交互 (候选卡片 + 选择回调)"
```

---

### Task 10: 更新 test_context.py 修复旧测试

**Files:**
- Modify: `tests/test_context.py` (test_build_context_basic 中 "允许物象" → "特色物象")

注意：之前的重命名改动可能导致旧测试中仍引用 "允许物象"。

**Step 1: 检查并修复**

```python
def test_build_context_basic():
    """基础上下文应包含区域和档位信息。"""
    region = {"设计风格": "阿拉伯纹样", "特色物件": "新月"}
    tier = {"特色物象": "动物/植物", "视觉质感": "扁平化"}  # 允许物象 → 特色物象
    result = build_context(region, tier)
    assert "动物/植物" in result
```

**Step 2: 运行测试确认通过**

Run: `python -m pytest tests/test_context.py -v`
Expected: ALL passed

**Step 3: 提交**

```bash
git add tests/test_context.py
git commit -m "fix: 测试中 允许物象 → 特色物象 重命名同步"
```

---

### Task 11: 端到端验证

**Step 1: 运行全量测试**

Run: `python -m pytest tests/ -v`
Expected: ALL passed

**Step 2: CLI 冒烟测试 (dry-run)**

Run: `python app.py` (如果有 .env 配置)
验证: generate() 兼容入口正常工作（auto-select 第 0 张）

**Step 3: 提交整体验证通过标记**

如有任何修复，单独提交。
