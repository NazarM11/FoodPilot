# FoodPilot

**A production-style nutrition recommendation API built with FastAPI, SQLite, and LLM-based ranking — with a graceful, fully-local fallback when the LLM is unavailable.**

FoodPilot takes a user's macro goals (calories, protein, carbs, fats) and returns realistic, restaurant-accurate meal bundles — not generic "eat chicken and rice" suggestions, but combinations built from real menu items (main + side/add-on + drink) pulled from an ingested nutrition database.

Live demo: message **[@fastmacros_bot](https://t.me/fastmacros_bot)** on Telegram and send `650 30 35 20` (kcal, protein, carbs, fats).

---

## Why this project is interesting

This isn't a CRUD wrapper around an LLM call. The core engineering problem is **reliability under uncertain conditions**:

- **LLM ranking with a deterministic fallback.** The recommendation engine tries an OpenAI-compatible LLM to rank candidate bundles by quality/relevance. If the LLM is unreachable, times out, or returns malformed output, the system silently falls back to a local heuristic ranker — no degraded UX, no crash, no hallucinated data reaching the user.
- **Two-tier tolerance matching.** Bundles are first matched within strict macro windows (±100 kcal, ±5g protein, ±10g carbs, ±5g fat). If nothing fits, the search automatically relaxes to wider windows (±150 kcal, ±8g protein, ±15g carbs, ±8g fat) rather than returning an empty result.
- **Structured bundle generation, not random pairing.** The engine understands meal *roles* (main, side/add-on, drink) and prefers coherent, single-restaurant combinations over mixing items arbitrarily.
- **Same core logic across every interface.** The Telegram bot doesn't reimplement anything — it calls the same local API used by Swagger/curl, guaranteeing identical behavior (ranking, fallback, tolerance logic) across all clients.
- **Real data ingestion pipeline.** Menu data isn't hardcoded — nutrition labels are extracted from restaurant PDFs via an LLM-based parser and upserted into SQLite through an authenticated admin endpoint.

---

## Architecture

```
main.py                    → FastAPI web layer, routes, request/response models
recommendation_engine.py   → scoring, meal-role logic, bundle generation, tolerance checks, LLM ranking + fallback
database.py                → SQLite schema, initialization, menu retrieval
llama_client.py            → PDF parsing and nutrition-label extraction (admin ingestion)
telegram_bot.py            → Telegram client, calls the existing API (no duplicated logic)
tests/test_recommendations.py → regression tests for recommendation behavior
```

**Stack:** Python, FastAPI, SQLite, OpenAI-compatible LLM API, Llama Cloud (PDF parsing), python-telegram-bot, pytest.

---

## Quickstart

```bash
python3 -m venv env
. env/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
./run.sh serve
```

API docs: `http://localhost:8000/docs`

```bash
curl -X POST http://localhost:8000/recommendations \
  -H 'Content-Type: application/json' \
  -d '{"goals":{"kcal":650,"protein":30,"carbs":35,"fats":20}}'
```

The LLM key in `.env` is optional — the API is fully functional on the local heuristic recommender without it.

---

## Testing

```bash
. env/bin/activate
PYTHONPATH=. pytest -q
```

Regression tests cover recommendation correctness, including fallback behavior when the LLM path is unavailable.

---

## Telegram bot

```bash
./run.sh serve
./run.sh telegram
```

Send `/recommend 650 30 35 20` or just `650 30 35 20` — same database, same ranking, same fallback logic as the raw API.

Try it live: **[@fastmacros_bot](https://t.me/fastmacros_bot)**

---

## Admin: ingesting a menu PDF

```bash
curl -X POST http://localhost:8000/admin/nutrition-labels \
  -H "X-Admin-Key: YOUR_ADMIN_INGEST_KEY" \
  -F restaurant_name="Restaurant Name" \
  -F file=@path/to/menu.pdf
```

Extracted labels are upserted into SQLite and immediately available to the recommendation engine — no restart needed.

---

## Security notes

- `.env`, `foodpilot.db`, database backups, and `env/` are gitignored.
- Only `.env.example` (placeholders only) is committed.
- API keys and Telegram tokens are never checked into source control.
- Admin ingestion is gated behind an `X-Admin-Key` header.

---

## What I'd build next

- Caching for LLM ranking calls to reduce latency/cost on repeat queries
- Structured logging around the fallback path to track LLM reliability in production
- Multi-restaurant bundle support with configurable weighting
