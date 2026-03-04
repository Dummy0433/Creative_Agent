"""Gemini 供应商实现：图片生成和文本生成。"""

import base64
import json

import requests

from providers.base import ImageProvider, TextProvider
from settings import get_settings


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


class GeminiTextProvider(TextProvider):
    """基于 Gemini API 的文本生成供应商。"""

    def __init__(self, timeout: int | None = None):
        s = get_settings()
        self.api_key = s.gemini_api_key
        self.base_url = s.gemini_base_url
        self.timeout = timeout if timeout is not None else 60

    def generate(self, model: str, system_prompt: str, user_prompt: str) -> dict:
        """调用 Gemini generateContent 接口，返回结构化 JSON。"""
        url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        resp = requests.post(url, json=body, timeout=self.timeout)
        resp.raise_for_status()
        # 从响应中提取生成的文本
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
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
        self.models = models or d["image_models"]
        self.timeout = timeout if timeout is not None else d["image_timeout"]
        self.aspect_ratio = aspect_ratio or d["image_aspect_ratio"]
        self.image_size = image_size or d["image_size"]

    def generate(self, prompt: str, reference_images: list[bytes] | None = None) -> bytes:
        """依次尝试候选模型生成图片，返回图片字节数据。"""
        for model in self.models:
            try:
                print(f"  尝试模型: {model}...")
                url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
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
                        # 图片尺寸配置
                        "imageConfig": {
                            "aspectRatio": self.aspect_ratio,
                            "imageSize": self.image_size,
                        },
                        # 启用深度思考模式，模型会推理复杂 prompt 后再生成终稿
                        "thinkingConfig": {
                            "thinkingLevel": "High",
                        },
                    },
                }
                resp = requests.post(url, json=body, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                # 遍历响应各部分，查找内联图片数据
                for part in data["candidates"][0]["content"]["parts"]:
                    if "inlineData" in part:
                        return base64.b64decode(part["inlineData"]["data"])
                print(f"  {model} 响应中无图片")
            except Exception as e:
                print(f"  {model} 失败: {e}")
                continue
        raise RuntimeError("所有图片生成模型均失败")
