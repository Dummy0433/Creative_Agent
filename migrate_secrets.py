#!/usr/bin/env python3
"""一次性迁移脚本：读取 YAML 格式的密钥文件并生成 .env 文件。"""

from pathlib import Path

import yaml

# 源文件路径（旧版 YAML 密钥）
SECRETS_PATH = Path.home() / ".openclaw/secrets/agents/intelligence.yaml"
# 目标文件路径
ENV_PATH = Path(__file__).parent / ".env"


def main():
    """读取 YAML 密钥文件，提取飞书和 Gemini 凭证，写入 .env 文件。"""
    if not SECRETS_PATH.exists():
        print(f"密钥文件不存在: {SECRETS_PATH}")
        return

    with open(SECRETS_PATH) as f:
        secrets = yaml.safe_load(f)

    # 提取各服务的凭证
    feishu = secrets.get("feishu", {})
    gemini = secrets.get("gemini", {})

    # 组装 .env 内容
    lines = [
        f"FEISHU_APP_ID={feishu.get('app_id', '')}",
        f"FEISHU_APP_SECRET={feishu.get('app_secret', '')}",
        f"FEISHU_RECEIVE_ID={feishu.get('receive_id', '')}",
        f"GEMINI_API_KEY={gemini.get('api_key', '')}",
    ]

    ENV_PATH.write_text("\n".join(lines) + "\n")
    print(f"已写入 {ENV_PATH}")
    print("如不再需要，可删除原 YAML 密钥文件。")


if __name__ == "__main__":
    main()
