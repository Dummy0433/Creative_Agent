"""集中化配置管理，基于 pydantic-settings，所有配置项从环境变量 / .env 文件加载。"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用全局配置，自动从 .env 文件或环境变量读取。"""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # ── 飞书凭证 ─────────────────────────────────────────────
    feishu_app_id: str          # 飞书应用 ID
    feishu_app_secret: str      # 飞书应用密钥
    feishu_receive_id: str      # 默认消息接收者 open_id
    feishu_base_url: str = "https://open.feishu.cn"  # 飞书 API 基地址

    # ── Gemini 凭证 ──────────────────────────────────────────
    gemini_api_key: str         # Gemini API 密钥
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"  # Gemini API 基地址

    # ── 多维表格地址 ─────────────────────────────────────────
    table1_app_token: str = "ZVpIbYAzXavJwPsIo7YlXBI2gJe"   # TABLE1(区域原型) 应用 token
    table1_table_id: str = "tblmBqweQeyO8Eis"                # TABLE1 表格 ID
    table2_app_token: str = "Weqqb5u5vaqVb6sX7lXlTJjxgdK"   # TABLE2(档位规则) 应用 token
    table2_table_id: str = "tblyjwU9kHwQ8Yjk"                # TABLE2 表格 ID
    table3_app_token: str = "A4vIbpBaha7xr0soriylME5Lgke"   # TABLE3(参考案例) 应用 token
    table3_table_id: str = "tblxocvuizuA2W3Y"                # TABLE3 表格 ID

    # ── 模型选择 ─────────────────────────────────────────────
    text_model: str = "gemini-2.5-flash"       # 文本生成模型
    image_provider: str = "gemini"             # 图片生成供应商名称
    image_models: list[str] = Field(default=[  # 图片生成模型候选列表（按顺序尝试）
        "gemini-2.0-flash-exp-image-generation",
        "gemini-2.5-flash-image",
        "imagen-4.0-generate-001",
    ])

    # ── CLI 默认值 ───────────────────────────────────────────
    default_region: str = "MENA"    # 默认区域
    default_subject: str = "雄狮"   # 默认主体
    default_price: int = 1          # 默认价格（coins）

    # ── 运行时参数 ───────────────────────────────────────────
    log_level: str = "INFO"              # 日志级别
    output_dir: str = "./output"         # 图片输出目录
    text_timeout: int = 60               # 文本生成超时（秒）
    image_timeout: int = 180             # 图片生成超时（秒）
    enable_postprocess: bool = True      # 是否启用后处理链


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例（首次调用时从 .env 加载，后续使用缓存）。"""
    return Settings()
