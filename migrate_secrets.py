#!/usr/bin/env python3
"""One-time migration: read ~/.openclaw/secrets/agents/intelligence.yaml and write .env."""

from pathlib import Path

import yaml

SECRETS_PATH = Path.home() / ".openclaw/secrets/agents/intelligence.yaml"
ENV_PATH = Path(__file__).parent / ".env"


def main():
    if not SECRETS_PATH.exists():
        print(f"Secrets file not found: {SECRETS_PATH}")
        return

    with open(SECRETS_PATH) as f:
        secrets = yaml.safe_load(f)

    feishu = secrets.get("feishu", {})
    gemini = secrets.get("gemini", {})

    lines = [
        f"FEISHU_APP_ID={feishu.get('app_id', '')}",
        f"FEISHU_APP_SECRET={feishu.get('app_secret', '')}",
        f"FEISHU_RECEIVE_ID={feishu.get('receive_id', '')}",
        f"GEMINI_API_KEY={gemini.get('api_key', '')}",
    ]

    ENV_PATH.write_text("\n".join(lines) + "\n")
    print(f"Written {ENV_PATH}")
    print("You can now delete the YAML secrets file if desired.")


if __name__ == "__main__":
    main()
