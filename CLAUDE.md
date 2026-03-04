# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TikTok gift image generation service. Takes a region, subject, and price as input, generates a themed gift image via a pluggable provider (default: Gemini), and sends it to a user via Feishu (Lark) messaging.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# One-time: migrate YAML secrets to .env
python migrate_secrets.py

# Phase 1: Create Bitable fields and insert mock data into TABLE0/1/2
python setup_tables.py

# Phase 2: Run the full generation pipeline (CLI mode, uses .env defaults)
python app.py

# Start FastAPI server
python app.py serve
# Then: curl -X POST http://localhost:8000/generate \
#   -H "Content-Type: application/json" \
#   -d '{"region": "MENA", "subject": "雄狮", "price": 1}'
```

## Architecture

### Module structure

- **`settings.py`** — `pydantic-settings` `BaseSettings`, all config from env vars / `.env`. Singleton via `get_settings()`.
- **`models.py`** — Shared Pydantic models: `MediaType`, `GenerateRequest`, `GenerateResponse`, `PipelineResult`.
- **`feishu.py`** — Feishu API: `get_token` (no-arg default from settings), `query_bitable`, `parse_record`, `upload_image`, `send_image`, `send_text`.
- **`providers/`** — Generation provider abstraction layer:
  - `base.py` — `ImageProvider` / `TextProvider` ABCs
  - `gemini.py` — Gemini implementations
  - `registry.py` — Provider name → class mapping, `get_image_provider()` / `get_text_provider()`
- **`pipeline/`** — Pipeline orchestration:
  - `subject.py` — Tier detection, subject classification/validation, constants
  - `data.py` — TABLE0-3 Bitable queries
  - `context.py` — System prompts, context/instance formatting
  - `postprocess.py` — `PostProcessor` ABC + chain (video extension point)
  - `orchestrator.py` — `generate(region, subject, price) -> PipelineResult`
- **`media/`** — Reserved for future video post-processing implementations
- **`app.py`** — FastAPI `POST /generate` + `POST /bot/callback` (Feishu bot stub) + CLI entry point
- **`setup_tables.py`** — Phase 1 table setup script
- **`migrate_secrets.py`** — One-time YAML → `.env` migration

### Pipeline (in `pipeline/orchestrator.py`)

1. Authenticate via `feishu.get_token()` (credentials from `.env`)
2. Detect price tier (T0-T4)
3. Query TABLE0 (routing) → TABLE1 (region info) → TABLE2 (tier rules)
4. Validate subject against tier rules (container wrapping if forbidden)
5. Query TABLE3 (few-shot examples)
6. Text provider: structured analysis → prompt generation
7. Image provider: generate image
8. Post-process chain (save to disk; future: matting + video)
9. Upload to Feishu → send image + caption

### External services

- **Feishu Bitable** — Data store for region configs and tier rules (TABLE0-3).
- **Gemini API** — Default provider for text + image generation (pluggable via `IMAGE_PROVIDER` env var).
- **Feishu Messaging** — Upload image, send to recipient via open_id.

### Key data model

- **Tier boundaries** (T0-T4): price thresholds determine allowed subjects/scenes/materials
- **Subject classification**: Chinese keyword matching against animal/plant/landscape categories
- **Container wrapping**: forbidden subjects at low tiers get wrapped in a container from `容器备选`
- **PostProcessor chain**: extensible post-processing (currently image save; future video generation for T3/T4)

## Credentials

All secrets loaded from `.env` file (or environment variables). Use `python migrate_secrets.py` to convert from the legacy YAML format. Required variables: `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_RECEIVE_ID`, `GEMINI_API_KEY`.
