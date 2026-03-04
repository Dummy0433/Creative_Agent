"""共享的 Pydantic 数据模型：请求 / 响应 / Pipeline 结果。"""

from enum import Enum

from pydantic import BaseModel, Field


class MediaType(str, Enum):
    """媒体类型枚举：图片或视频。"""
    IMAGE = "image"
    VIDEO = "video"


class GenerateRequest(BaseModel):
    """生成请求参数（FastAPI 入参）。"""
    region: str = Field(..., min_length=1)            # 区域，如 MENA / TR / General
    subject: str = Field(..., min_length=1)           # 主体/物象，如 雄狮
    price: int = Field(..., ge=1, le=29999)           # 价格（coins），决定档位


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
    media_bytes: bytes | None = Field(default=None, exclude=True)  # 原始媒体字节（不序列化）
