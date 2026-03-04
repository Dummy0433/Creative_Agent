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

# Phase 2: Run the full generation pipeline (CLI mode, uses generation_defaults.yaml)
python app.py

# Start FastAPI server
python app.py serve
# Then: curl -X POST http://localhost:8000/generate \
#   -H "Content-Type: application/json" \
#   -d '{"region": "MENA", "subject": "雄狮", "price": 1}'
# With advanced options:
# curl -X POST http://localhost:8000/generate \
#   -H "Content-Type: application/json" \
#   -d '{"region":"MENA","subject":"雄狮","price":1,"image_aspect_ratio":"16:9","image_size":"2K"}'
```

## Architecture

### Three-layer configuration

| Layer | Content | Who edits | Storage |
|-------|---------|-----------|---------|
| **Credentials/Infra** | API keys, URLs, table addresses | Developer | `.env` |
| **Admin defaults** | Models, image params, timeouts, prompts | Design team | `generation_defaults.yaml` (git-managed) |
| **User request** | region, subject, price, aspect ratio, resolution | End user | Request params (bot card / API / future UI) |

Pipeline receives a `GenerationConfig` object, calls `resolve()` to merge all three layers into a `ResolvedConfig` (all fields populated).

### Module structure

- **`settings.py`** — `pydantic-settings` `BaseSettings`, credentials and infrastructure only. Singleton via `get_settings()`.
- **`generation_defaults.yaml`** — Admin-tunable defaults: models, image params, timeouts, prompt overrides.
- **`defaults.py`** — YAML loader for `generation_defaults.yaml`, cached via `load_defaults()`.
- **`models.py`** — Shared Pydantic models: `MediaType`, `GenerationConfig`, `ResolvedConfig`, `GenerateRequest`, `GenerateResponse`, `PipelineResult`.
- **`feishu.py`** — Feishu API: `get_token` (no-arg default from settings), `query_bitable`, `parse_record`, `upload_image`, `send_image`, `send_text`.
- **`providers/`** — Generation provider abstraction layer:
  - `base.py` — `ImageProvider` / `TextProvider` ABCs
  - `gemini.py` — Gemini implementations (constructor accepts model/image params)
  - `registry.py` — Provider name → class mapping, `get_image_provider(**kwargs)` / `get_text_provider(**kwargs)`
- **`pipeline/`** — Pipeline orchestration:
  - `subject.py` — Tier detection, subject classification/validation, constants
  - `data.py` — TABLE0-3 Bitable queries
  - `context.py` — System prompts (with override support), context/instance formatting
  - `postprocess.py` — `PostProcessor` ABC + chain (video extension point)
  - `orchestrator.py` — `generate(config: GenerationConfig) -> PipelineResult`
- **`media/`** — Reserved for future video post-processing implementations
- **`app.py`** — FastAPI `POST /generate` + `POST /bot/callback` (Feishu bot stub) + CLI entry point
- **`setup_tables.py`** — Phase 1 table setup script
- **`migrate_secrets.py`** — One-time YAML → `.env` migration

### Pipeline (in `pipeline/orchestrator.py`)

1. Resolve config: `config.resolve()` merges user request + admin defaults
2. Authenticate via `feishu.get_token()` (credentials from `.env`)
3. Detect price tier (T0-T4)
4. Query TABLE0 (routing) → TABLE1 (region info) → TABLE2 (tier rules)
5. Validate subject against tier rules (container wrapping if forbidden)
6. Query TABLE3 (few-shot examples)
7. Text provider: structured analysis → prompt generation (models from resolved config)
8. Image provider: generate image (models, aspect ratio, size from resolved config)
9. Post-process chain (save to disk; future: matting + video)
10. Upload to Feishu → send image + caption

### External services

- **Feishu Bitable** — Data store for region configs and tier rules (TABLE0-3).
- **Gemini API** — Default provider for text + image generation (pluggable via `image_provider` in defaults).
- **Feishu Messaging** — Upload image, send to recipient via open_id.

### Key data model

- **Tier boundaries** (T0-T4): price thresholds determine allowed subjects/scenes/materials
- **Subject classification**: Chinese keyword matching against animal/plant/landscape categories
- **Container wrapping**: forbidden subjects at low tiers get wrapped in a container from `容器备选`
- **PostProcessor chain**: extensible post-processing (currently image save; future video generation for T3/T4)

## Credentials

All secrets loaded from `.env` file (or environment variables). Use `python migrate_secrets.py` to convert from the legacy YAML format. Required variables: `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_RECEIVE_ID`, `GEMINI_API_KEY`.

Generation parameters (models, image settings, timeouts) are in `generation_defaults.yaml`, not `.env`.
