"""共享的 Pydantic 数据模型：请求 / 响应 / Pipeline 结果 / 配置。"""

from __future__ import annotations

from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from defaults import load_defaults


class RoutingInfo(BaseModel):
    """TABLE0 路由结果：区域 → 各表格物理地址映射。"""
    region: str                  # 区域名称
    archetype_app_token: str     # TABLE1 应用 token
    archetype_table_id: str      # TABLE1 表格 ID
    rules_app_token: str         # TABLE2 应用 token
    rules_table_id: str          # TABLE2 表格 ID
    instance_app_token: str      # TABLE3 应用 token
    instance_table_id: str       # TABLE3 表格 ID


class MediaType(str, Enum):
    """媒体类型枚举：图片或视频。"""
    IMAGE = "image"
    VIDEO = "video"


# ── 层级配置 ──────────────────────────────────────────────────


class TierProfile(BaseModel):
    """层级配置：提示词文件路径 + 可选参数覆盖。

    未设置的可选字段在运行时继承全局默认值。
    """
    analyze_prompt_file: str                    # prompts/ 下的分析提示词文件名
    prompt_gen_prompt_file: str                 # prompts/ 下的生图提示词文件名
    image_models: list[str] | None = None       # 可选：覆盖图片模型列表
    image_size: str | None = None               # 可选：覆盖图片尺寸
    image_aspect_ratio: str | None = None       # 可选：覆盖图片宽高比


class CalendarQuarterConfig(BaseModel):
    """季度表配置：table_id + view_id。"""
    table_id: str
    view_id: str


# ── 管理员默认值（类型化 YAML）────────────────────────────────


class GenerationDefaults(BaseModel):
    """generation_defaults.yaml 的类型化模型。

    启动时校验，YAML 字段拼写错误会立即报错而非运行时 KeyError。
    """
    # 模型选择
    analyze_model: str
    prompt_model: str
    image_provider: str = "gemini"
    image_models: list[str]
    # 图片参数
    image_aspect_ratio: str = "1:1"
    image_size: str = "1K"
    candidate_count: int = Field(default=4, ge=1, le=10)
    # 超时（秒）
    text_timeout: int = Field(default=60, ge=1, le=600)
    image_timeout: int = Field(default=180, ge=1, le=600)
    # 后处理
    enable_postprocess: bool = True
    # CLI / 默认请求参数
    default_region: str = "MENA"
    default_subject: str = "雄狮"
    default_price: int = 1
    # 提示词覆盖（None = 使用 prompts/*.md 文件）
    analyze_system_prompt: str | None = None
    prompt_gen_system_prompt: str | None = None
    # 编辑流
    edit_provider: str = "gemini"
    edit_models: list[str] = Field(default_factory=lambda: ["gemini-3.1-flash-image-preview"])
    edit_timeout: int = Field(default=120, ge=1, le=600)
    edit_max_rounds: int = Field(default=10, ge=1, le=50)
    edit_session_ttl: int = Field(default=1800, ge=60, le=7200)
    # 层级配置（键=层级名 如 "P0"，值=TierProfile）
    tier_profiles: dict[str, TierProfile] = {}
    # ── Calendar 看板 ──
    calendar_app_token: str = ""
    calendar_quarters: dict[str, CalendarQuarterConfig] = {}

    @field_validator("image_models")
    @classmethod
    def image_models_not_empty(cls, v):
        if not v:
            raise ValueError("image_models 列表不能为空")
        return v


# ── 三层配置模型 ──────────────────────────────────────────────


class GenerationConfig(BaseModel):
    """用户请求配置（第三层）。

    必填字段：region / subject / price。
    可选字段未提供时，resolve() 会用管理员默认值（generation_defaults.yaml）填充。
    """
    region: str
    subject: str
    price: int = Field(ge=1, le=29999)
    # 请求追踪 ID（自动生成 8 位十六进制）
    request_id: str = Field(default_factory=lambda: uuid4().hex[:8])
    # 可选覆盖（None = 使用管理员默认值）
    image_aspect_ratio: str | None = None
    image_size: str | None = None
    analyze_model: str | None = None
    prompt_model: str | None = None
    image_models: list[str] | None = None
    image_provider: str | None = None
    text_timeout: int | None = None
    image_timeout: int | None = None
    enable_postprocess: bool | None = None
    analyze_system_prompt: str | None = None
    prompt_gen_system_prompt: str | None = None

    def resolve(self) -> ResolvedConfig:
        """合并用户请求与管理员默认值，返回所有字段已填充的 ResolvedConfig。"""
        d = load_defaults()
        return ResolvedConfig(
            region=self.region,
            subject=self.subject,
            price=self.price,
            request_id=self.request_id,
            image_aspect_ratio=self.image_aspect_ratio or d.image_aspect_ratio,
            image_size=self.image_size or d.image_size,
            analyze_model=self.analyze_model or d.analyze_model,
            prompt_model=self.prompt_model or d.prompt_model,
            image_models=self.image_models or d.image_models,
            image_provider=self.image_provider or d.image_provider,
            text_timeout=self.text_timeout if self.text_timeout is not None else d.text_timeout,
            image_timeout=self.image_timeout if self.image_timeout is not None else d.image_timeout,
            enable_postprocess=self.enable_postprocess if self.enable_postprocess is not None else d.enable_postprocess,
            candidate_count=d.candidate_count,
            analyze_system_prompt=self.analyze_system_prompt or d.analyze_system_prompt,
            prompt_gen_system_prompt=self.prompt_gen_system_prompt or d.prompt_gen_system_prompt,
        )


class ResolvedConfig(BaseModel):
    """完全解析后的配置，所有字段已填充。Pipeline 内部使用。"""
    region: str
    subject: str
    price: int
    request_id: str = ""
    image_aspect_ratio: str
    image_size: str
    analyze_model: str
    prompt_model: str
    image_models: list[str]
    image_provider: str
    text_timeout: int
    image_timeout: int
    enable_postprocess: bool
    candidate_count: int = 4
    analyze_system_prompt: str | None = None
    prompt_gen_system_prompt: str | None = None


# ── 请求 / 响应 模型 ─────────────────────────────────────────


class GenerateRequest(BaseModel):
    """生成请求参数（FastAPI 入参），向后兼容 + 高级可选参数。"""
    region: str = Field(..., min_length=1)            # 区域，如 MENA / TR / General
    subject: str = Field(..., min_length=1)           # 主体/物象，如 雄狮
    price: int = Field(..., ge=1, le=29999)           # 价格（coins），决定档位
    # 高级可选参数（API 向后兼容：不传即用默认值）
    image_aspect_ratio: str | None = None
    image_size: str | None = None
    analyze_model: str | None = None
    prompt_model: str | None = None
    image_models: list[str] | None = None

    def to_config(self) -> GenerationConfig:
        """转换为 GenerationConfig（透传所有非 None 字段）。"""
        return GenerationConfig(
            region=self.region,
            subject=self.subject,
            price=self.price,
            image_aspect_ratio=self.image_aspect_ratio,
            image_size=self.image_size,
            analyze_model=self.analyze_model,
            prompt_model=self.prompt_model,
            image_models=self.image_models,
        )


class GenerateResponse(BaseModel):
    """生成响应（FastAPI 返回值）。"""
    subject_final: str       # 最终使用的主体（可能被容器包裹）
    tier: str                # 匹配到的价格档位
    prompt: str              # 中文提示词
    english_prompt: str      # 英文提示词
    media_type: MediaType = MediaType.IMAGE  # 媒体类型
    status: str              # 状态：generated / sent_to_feishu


class PipelineResult(BaseModel):
    """Pipeline 完整结果，包含媒体数据和飞书消息 ID。"""
    subject_final: str       # 最终使用的主体
    tier: str                # 匹配到的价格档位
    prompt: str              # 中文提示词
    english_prompt: str      # 英文提示词
    media_type: MediaType = MediaType.IMAGE  # 媒体类型
    status: str              # 当前状态
    error_message: str = ""  # 错误信息（status="error" 或 "generated_but_send_failed" 时填充）
    request_id: str = ""     # 请求追踪 ID
    image_key: str = ""      # 飞书图片 key（上传后获得）
    file_key: str = ""       # 飞书文件 key（预上传，供 Download 使用）
    image_id: str = ""       # 图片唯一 ID（卡片按钮关联用）
    message_id: str = ""     # 飞书消息 ID（发送后获得）
    local_path: str = ""     # 本地保存路径（后处理后填充）
    media_bytes: bytes | None = Field(default=None, exclude=True)  # 原始媒体字节（不序列化）


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
    config: "GenerationConfig | None" = None  # 原始请求配置（用于 regenerate）


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
    image_map: dict[str, bytes] = Field(default_factory=dict, exclude=True)
    conversation_history: list[dict] = Field(default_factory=list)
    message_id_map: dict[str, str] = Field(default_factory=dict)
    original_config: GenerationConfig
    pending_edit: bool = False
    pending_edit_image_id: str = ""
    file_key: str = ""
    last_active: float = Field(default_factory=lambda: __import__('time').time())


class EditResult(BaseModel):
    """图片编辑结果：编辑后图片 + AI 引导文字 + 更新后对话历史。"""
    image: bytes = Field(exclude=True)
    message: str
    updated_history: list[dict] = Field(default_factory=list)
