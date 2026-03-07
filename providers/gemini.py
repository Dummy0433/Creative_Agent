"""Gemini 供应商实现：图片生成和文本生成（async）。"""

import base64
import json
import logging

import httpx

from providers.base import EditProvider, ImageProvider, TextProvider
from settings import get_settings

logger = logging.getLogger(__name__)


def _parse_json_response(text):
    """解析 LLM 返回的 JSON 文本。

    处理可能被 markdown 代码块包裹的情况（```json ... ```）。
    """
    text = text.strip()
    if text.startswith("```"):
        # 去掉 ``` 开头和结尾的行
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


def _extract_text_from_response(data: dict) -> str:
    """从 Gemini 响应中安全提取文本内容。

    校验响应结构完整性，缺失时抛出明确异常。
    """
    candidates = data.get("candidates")
    if not candidates:
        raise RuntimeError(f"Gemini 响应中无 candidates 字段: {json.dumps(data, ensure_ascii=False)[:300]}")
    content = candidates[0].get("content")
    if not content or not content.get("parts"):
        raise RuntimeError(f"Gemini 响应中无 content/parts: {json.dumps(candidates[0], ensure_ascii=False)[:300]}")
    text = content["parts"][0].get("text")
    if text is None:
        raise RuntimeError("Gemini 响应的 parts[0] 中无 text 字段")
    return text


class GeminiTextProvider(TextProvider):
    """基于 Gemini API 的文本生成供应商。"""

    def __init__(self, timeout: int | None = None):
        s = get_settings()
        self.api_key = s.gemini_api_key
        self.base_url = s.gemini_base_url
        self.timeout = timeout if timeout is not None else 60

    async def generate(self, model: str, system_prompt: str, user_prompt: str) -> dict:
        """调用 Gemini generateContent 接口，返回结构化 JSON。"""
        url = f"{self.base_url}/models/{model}:generateContent"
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        text = _extract_text_from_response(resp.json())
        return _parse_json_response(text)


class GeminiImageProvider(ImageProvider):
    """基于 Gemini API 的图片生成供应商。

    按 image_models 列表顺序尝试多个模型，首个成功即返回。
    """

    def __init__(self, models: list[str] | None = None, aspect_ratio: str | None = None,
                 image_size: str | None = None, timeout: int | None = None):
        s = get_settings()
        self.api_key = s.gemini_api_key
        self.base_url = s.gemini_base_url
        # 生成参数由 orchestrator 从 ResolvedConfig 传入
        from defaults import load_defaults
        d = load_defaults()
        self.models = models or d.image_models
        self.timeout = timeout if timeout is not None else d.image_timeout
        self.aspect_ratio = aspect_ratio or d.image_aspect_ratio
        self.image_size = image_size or d.image_size

    async def generate(self, prompt: str, reference_images: list[bytes] | None = None) -> bytes:
        """依次尝试候选模型生成图片，返回图片字节数据。"""
        errors: list[str] = []  # 记录每个模型的失败原因
        for model in self.models:
            try:
                logger.info("  尝试模型: %s...", model)
                url = f"{self.base_url}/models/{model}:generateContent"
                headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
                # 构建 parts：有参考图时使用多模态输入
                parts = []
                if reference_images:
                    parts.append({"text": "Reference images for style and quality guidance:"})
                    for img in reference_images:
                        parts.append({
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(img).decode(),
                            }
                        })
                    parts.append({"text": f"Generate a new image in similar style:\n{prompt}"})
                else:
                    parts.append({"text": prompt})
                body = {
                    "contents": [{"parts": parts}],
                    "generationConfig": {
                        "responseModalities": ["TEXT", "IMAGE"],
                        "imageConfig": {
                            "aspectRatio": self.aspect_ratio,
                            "imageSize": self.image_size,
                        },
                        "thinkingConfig": {
                            "thinkingLevel": "High",
                        },
                    },
                }
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                # 安全遍历响应各部分，查找内联图片数据
                candidates = data.get("candidates", [])
                if not candidates:
                    logger.warning("  %s 响应中无 candidates", model)
                    errors.append(f"{model}: 响应中无 candidates")
                    continue
                content_parts = candidates[0].get("content", {}).get("parts", [])
                for part in content_parts:
                    if "inlineData" in part:
                        return base64.b64decode(part["inlineData"]["data"])
                logger.warning("  %s 响应中无图片", model)
                errors.append(f"{model}: 响应中无图片数据")
            except Exception as e:
                logger.warning("  %s 失败: %s", model, e)
                errors.append(f"{model}: {e}")
                continue
        raise RuntimeError(f"所有图片生成模型均失败: {'; '.join(errors)}")


class GeminiEditProvider(EditProvider):
    """基于 Gemini generateContent 的图片编辑供应商。

    利用 responseModalities: ["TEXT", "IMAGE"] 一次调用
    同时返回编辑后图片和 AI 引导文字。
    """

    def __init__(self, models: list[str] | None = None, timeout: int | None = None):
        s = get_settings()
        self.api_key = s.gemini_api_key
        self.base_url = s.gemini_base_url
        from defaults import load_defaults
        d = load_defaults()
        self.models = models or d.edit_models
        self.timeout = timeout if timeout is not None else d.edit_timeout

    async def edit(self, image, instruction, conversation_history=None):
        from models import EditResult

        history = list(conversation_history or [])
        current_turn = {
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(image).decode()}},
                {"text": instruction},
            ],
        }
        contents = history + [current_turn]

        errors = []
        for model in self.models:
            try:
                logger.info("  [Edit] 尝试模型: %s", model)
                url = f"{self.base_url}/models/{model}:generateContent"
                headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
                body = {
                    "contents": contents,
                    "generationConfig": {
                        "responseModalities": ["TEXT", "IMAGE"],
                    },
                }
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()

                candidates = data.get("candidates", [])
                if not candidates:
                    errors.append(f"{model}: 无 candidates")
                    continue

                parts = candidates[0].get("content", {}).get("parts", [])
                edited_image = None
                message_text = ""
                for part in parts:
                    if "inlineData" in part:
                        edited_image = base64.b64decode(part["inlineData"]["data"])
                    if "text" in part:
                        message_text += part["text"]

                if edited_image is None:
                    errors.append(f"{model}: 响应中无图片")
                    continue

                updated = contents + [{"role": "model", "parts": parts}]

                return EditResult(
                    image=edited_image,
                    message=message_text or "编辑完成，还需要调整什么吗？",
                    updated_history=updated,
                )
            except Exception as e:
                logger.warning("  [Edit] %s 失败: %s", model, e)
                errors.append(f"{model}: {e}")
                continue

        raise RuntimeError(f"所有编辑模型均失败: {'; '.join(errors)}")
