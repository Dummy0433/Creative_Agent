"""集中化配置管理（第一层：密钥/基础设施），基于 pydantic-settings。

生成参数已迁移至 generation_defaults.yaml（第二层），由 defaults.py 加载。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """基础设施配置，仅包含凭证、API 地址、表格地址和运行时基础参数。"""

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
    # TABLE0（路由表）：区域 → 各表格物理地址映射
    table0_app_token: str = "OeumbrA5OaLEYpsurLBlVRDegde"   # TABLE0(路由表) 应用 token
    table0_table_id: str = "tbl3hLBeyvNUe91s"                # TABLE0 表格 ID
    # TABLE1/2/3 地址保留作为 TABLE0 不可用时的 fallback
    table1_app_token: str = "ZVpIbYAzXavJwPsIo7YlXBI2gJe"   # TABLE1(区域原型) 应用 token
    table1_table_id: str = "tblmBqweQeyO8Eis"                # TABLE1 表格 ID
    table2_app_token: str = "Weqqb5u5vaqVb6sX7lXlTJjxgdK"   # TABLE2(档位规则) 应用 token
    table2_table_id: str = "tblyjwU9kHwQ8Yjk"                # TABLE2 表格 ID
    table3_app_token: str = "A4vIbpBaha7xr0soriylME5Lgke"   # TABLE3(参考案例) 应用 token
    table3_table_id: str = "tblxocvuizuA2W3Y"                # TABLE3 表格 ID

    # ── 基础设施 ─────────────────────────────────────────────
    log_level: str = "INFO"              # 日志级别
    output_dir: str = "./output"         # 图片输出目录


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例（首次调用时从 .env 加载，后续使用缓存）。"""
    return Settings()
