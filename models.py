"""共享的 Pydantic 数据模型：请求 / 响应 / Pipeline 结果 / 配置。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from defaults import load_defaults


class MediaType(str, Enum):
    """媒体类型枚举：图片或视频。"""
    IMAGE = "image"
    VIDEO = "video"


# ── 三层配置模型 ──────────────────────────────────────────────


class GenerationConfig(BaseModel):
    """用户请求配置（第三层）。

    必填字段：region / subject / price。
    可选字段未提供时，resolve() 会用管理员默认值（generation_defaults.yaml）填充。
    """
    region: str
    subject: str
    price: int = Field(ge=1, le=29999)
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
            image_aspect_ratio=self.image_aspect_ratio or d["image_aspect_ratio"],
            image_size=self.image_size or d["image_size"],
            analyze_model=self.analyze_model or d["analyze_model"],
            prompt_model=self.prompt_model or d["prompt_model"],
            image_models=self.image_models or d["image_models"],
            image_provider=self.image_provider or d["image_provider"],
            text_timeout=self.text_timeout if self.text_timeout is not None else d["text_timeout"],
            image_timeout=self.image_timeout if self.image_timeout is not None else d["image_timeout"],
            enable_postprocess=self.enable_postprocess if self.enable_postprocess is not None else d["enable_postprocess"],
            analyze_system_prompt=self.analyze_system_prompt or d.get("analyze_system_prompt"),
            prompt_gen_system_prompt=self.prompt_gen_system_prompt or d.get("prompt_gen_system_prompt"),
        )


class ResolvedConfig(BaseModel):
    """完全解析后的配置，所有字段已填充。Pipeline 内部使用。"""
    region: str
    subject: str
    price: int
    image_aspect_ratio: str
    image_size: str
    analyze_model: str
    prompt_model: str
    image_models: list[str]
    image_provider: str
    text_timeout: int
    image_timeout: int
    enable_postprocess: bool
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
    image_key: str = ""      # 飞书图片 key（上传后获得）
    message_id: str = ""     # 飞书消息 ID（发送后获得）
    local_path: str = ""     # 本地保存路径（后处理后填充）
    media_bytes: bytes | None = Field(default=None, exclude=True)  # 原始媒体字节（不序列化）
