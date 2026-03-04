"""Shared Pydantic models for request / response / pipeline result."""

from enum import Enum

from pydantic import BaseModel, Field


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class GenerateRequest(BaseModel):
    region: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    price: int = Field(..., ge=1, le=29999)


class GenerateResponse(BaseModel):
    subject_final: str
    tier: str
    prompt: str
    english_prompt: str
    media_type: MediaType = MediaType.IMAGE
    status: str


class PipelineResult(BaseModel):
    subject_final: str
    tier: str
    prompt: str
    english_prompt: str
    media_type: MediaType = MediaType.IMAGE
    status: str
    image_key: str = ""
    message_id: str = ""
    media_bytes: bytes | None = Field(default=None, exclude=True)
