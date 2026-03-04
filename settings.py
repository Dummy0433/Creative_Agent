"""Centralized configuration via pydantic-settings. All values from env vars / .env."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # ── Feishu credentials ──────────────────────────────────────
    feishu_app_id: str
    feishu_app_secret: str
    feishu_receive_id: str
    feishu_base_url: str = "https://open.feishu.cn"

    # ── Gemini credentials ──────────────────────────────────────
    gemini_api_key: str
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    # ── Bitable routing ─────────────────────────────────────────
    table0_app_token: str = "OeumbrA5OaLEYpsurLBlVRDegde"
    table0_table_id: str = "tbl3hLBeyvNUe91s"
    table2_app_token: str = "Weqqb5u5vaqVb6sX7lXlTJjxgdK"
    table2_table_id: str = "tblyjwU9kHwQ8Yjk"

    # ── Model selection ─────────────────────────────────────────
    text_model: str = "gemini-2.5-flash"
    image_provider: str = "gemini"
    image_models: list[str] = Field(default=[
        "gemini-2.0-flash-exp-image-generation",
        "gemini-2.5-flash-image",
        "imagen-4.0-generate-001",
    ])

    # ── CLI defaults ────────────────────────────────────────────
    default_region: str = "MENA"
    default_subject: str = "雄狮"
    default_price: int = 1

    # ── Runtime ─────────────────────────────────────────────────
    output_dir: str = "./output"
    text_timeout: int = 60
    image_timeout: int = 180
    enable_postprocess: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
