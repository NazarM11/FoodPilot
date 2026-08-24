# FoodPilot

**A production-style nutrition recommendation API built with FastAPI, SQLite, and LLM-based ranking — with a natural-language Telegram interface and a graceful, fully-local fallback when the LLM is unavailable.**

FoodPilot takes a user's macro goals (calories, protein, carbs, fats) and returns realistic, restaurant-accurate meal bundles — not generic "eat chicken and rice" suggestions, but combinations built from real menu items (main + side/add-on + drink) pulled from an ingested nutrition database covering six restaurants: A&W, Popeyes, Taco Bell, Wendy's, McDonald's, and Tim Hortons.

Live demo: message **[@fastmacros_bot](https://t.me/fastmacros_bot)** on Telegram and just describe what you want — e.g. *"something under 700 calories with plenty of protein and not too much fat."*

---

## Why this project is interesting

This isn't a CRUD wrapper around an LLM call. The core engineering problem is **reliability and correctness under uncertain conditions**:

- **Goals as hard upper limits, not fuzzy targets.** A recommendation never exceeds a stated calorie or macro ceiling. Instead of searching a symmetric tolerance band, the engine allows a controlled *shortfall* below the target — first up to 100 kcal / 5g protein / 10g carbs / 5g fat under, then relaxing to 150 kcal / 8g protein / 15g carbs / 8g fat under if nothing fits. This models how people actually think about limits ("under 700 calories") rather than treating goals as an approximate midpoint.
- **LLM ranking with a deterministic fallback.** The recommendation engine tries an OpenAI-compatible LLM to rank candidate bundles by quality/relevance. If the LLM is unreachable, times out, or returns malformed output, the system silently falls back to a local heuristic ranker — no degraded UX, no crash, no hallucinated data reaching the user.
- **Natural-language interface on top of a strict backend.** The Telegram bot parses free-form requests like *"not to much carbs"* (including common misspellings and wording variations) into structured constraints, applying sensible default ceilings (40g carbs, 20g fat) when the user gives a qualitative limit without a number.
- **Structured bundle generation, not random pairing.** The engine understands meal *roles* (main, side/add-on, drink) and prefers coherent, single-restaurant combinations. Drinks, sauces, spreads, and condiments are classified separately so they're never mislabeled as a main or side.
- **Same core logic across every interface.** The Telegram bot doesn't reimplement anything — it calls the same local API used by Swagger/curl, guaranteeing identical behavior (ranking, fallback, constraint logic) across all clients. Responses omit empty meal sections and label each item with its restaurant.
- **Idempotent data ingestion pipeline.** Menu data isn't hardcoded — nutrition labels are extracted from restaurant PDFs via an LLM-based parser and upserted into SQLite through an authenticated admin endpoint. Re-uploading the same restaurant/item updates the existing record instead of creating a duplicate.

---

## Architecture

```
main.py                    → FastAPI web layer, routes, request/response models
recommendation_engine.py   → scoring, meal-role logic, bundle generation, shortfall/limit checks, LLM ranking + fallback
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

Goals are treated as upper limits — a returned bundle will never exceed them, only fall modestly short. The LLM key in `.env` is optional — the API is fully functional on the local heuristic recommender without it.

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

Describe what you want in plain language:

```text
I want something under 700 calories with plenty of protein and not too much fat
```

The bot understands calorie/macro limits, qualitative preferences, and common wording variations, applying default ceilings (40g carbs, 20g fat) when a limit like "not too much carbs" is given without a number. It calls the same local API as curl/Swagger — same database, same ranking, same fallback logic.

Try it live: **[@fastmacros_bot](https://t.me/fastmacros_bot)**
---

## Admin: ingesting a menu PDF

```bash
curl -X POST http://localhost:8000/admin/nutrition-labels \
  -H "X-Admin-Key: YOUR_ADMIN_INGEST_KEY" \
  -F restaurant_name="Restaurant Name" \
  -F file=@path/to/menu.pdf
```

Extracted labels are upserted into SQLite and immediately available to the recommendation engine — no restart needed. Re-uploading the same restaurant and item updates the existing record rather than creating a duplicate.

---

## Security notes

- `.env`, `foodpilot.db`, database backups, and `env/` are gitignored.
- Only `.env.example` (placeholders only) is committed.
- API keys and Telegram tokens are never checked into source control.
- Admin ingestion is gated behind an `X-Admin-Key` header.

---

## What I'd build next

- Migrate persistence from SQLite to PostgreSQL with type-safe queries (sqlc) for production readiness
- Add JWT-based authentication (Argon2id hashing) to protect the admin ingestion endpoint properly
- Move background work (PDF ingestion, LLM ranking calls) onto RabbitMQ so user-facing requests stay responsive
- Containerize with Docker for reproducible deployment
- Caching for LLM ranking calls to reduce latency/cost on repeat queries
- Structured logging around the fallback path to track LLM reliability in production

---

## Author

**Nazar Marynich** — Backend Developer (Go, Python, REST APIs, PostgreSQL/SQLite, Clean Architecture)

- LinkedIn: [linkedin.com/in/nazar-marynich-a488473b7](https://linkedin.com/in/nazar-marynich-a488473b7)
- Email: marynich.nazar1@gmail.com
