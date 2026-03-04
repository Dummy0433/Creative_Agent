"""Gemini implementations of ImageProvider and TextProvider."""

import base64
import json

import requests

from providers.base import ImageProvider, TextProvider
from settings import get_settings


def _parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


class GeminiTextProvider(TextProvider):
    def __init__(self):
        s = get_settings()
        self.api_key = s.gemini_api_key
        self.base_url = s.gemini_base_url
        self.timeout = s.text_timeout

    def generate(self, model: str, system_prompt: str, user_prompt: str) -> dict:
        url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        resp = requests.post(url, json=body, timeout=self.timeout)
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_json_response(text)


class GeminiImageProvider(ImageProvider):
    def __init__(self):
        s = get_settings()
        self.api_key = s.gemini_api_key
        self.base_url = s.gemini_base_url
        self.models = s.image_models
        self.timeout = s.image_timeout

    def generate(self, prompt: str) -> bytes:
        for model in self.models:
            try:
                print(f"  Trying model: {model}...")
                url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
                body = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
                }
                resp = requests.post(url, json=body, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                for part in data["candidates"][0]["content"]["parts"]:
                    if "inlineData" in part:
                        return base64.b64decode(part["inlineData"]["data"])
                print(f"  No image in response from {model}")
            except Exception as e:
                print(f"  {model} failed: {e}")
                continue
        raise RuntimeError("All image generation models failed")
