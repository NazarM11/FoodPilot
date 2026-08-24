# FoodPilot

FoodPilot is a FastAPI nutrition recommendation service. It reads menu items from SQLite, builds realistic meal bundles, and optionally uses an OpenAI-compatible LLM endpoint to rank valid bundles. If the LLM is unavailable or returns invalid output, the local heuristic ranking is used.

## Project layout

- `main.py` - FastAPI web layer and endpoints.
- `recommendation_engine.py` - nutrition scoring, meal roles, bundle generation, tolerance checks, and LLM ranking.
- `database.py` - SQLite schema, initialization, and menu retrieval.
- `llama_client.py` - PDF parsing and nutrition-label extraction for admin uploads.
- `foodpilot.db` - local menu database (ignored from GitHub; populate it through PDF ingestion).
- `tests/test_recommendations.py` - regression tests for recommendation behavior.
- `run.sh` - local launcher.
- `telegram_bot.py` - Telegram bot client for the existing API.
- `.env.example` - environment variable template.

## Setup

From the project directory:

```bash
python3 -m venv env
. env/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

The existing `env/` can be reused if it is already installed. Edit `.env` only when you want LLM ranking or PDF ingestion; the local heuristic recommender works without an LLM key.

## Run the API

```bash
./run.sh serve
```

The API is available at `http://localhost:8000`. Interactive API documentation is at `http://localhost:8000/docs`.

## Try a recommendation

```bash
curl -X POST http://localhost:8000/recommendations \
  -H 'Content-Type: application/json' \
  -d '{"goals":{"kcal":650,"protein":30,"carbs":35,"fats":20}}'
```

The engine first tries strict windows of +/-100 kcal, +/-5g protein, +/-10g carbs, and +/-5g fat. If no bundle fits, it retries with +/-150 kcal, +/-8g protein, +/-15g carbs, and +/-8g fat. It uses the complete menu database, prefers one restaurant, and prefers a main, side/add-on, and drink when the data supports that structure.

## Run tests

```bash
. env/bin/activate
PYTHONPATH=. pytest -q
```

## Use Telegram

Create a bot with `@BotFather` using `/newbot`, then put the token in `.env`:

```text
TELEGRAM_BOT_TOKEN=your-private-token
```

Start the API and bot in separate terminals:

```bash
./run.sh serve
./run.sh telegram
```

In Telegram, send `/recommend 650 30 35 20`. You can also send `650 30 35 20` directly. The bot calls the existing local API, so it uses exactly the same database, AI ranking, fallback logic, and response behavior as Swagger and curl. No public URL or tunnel is needed.

## Import a nutrition PDF

Set `ADMIN_INGEST_KEY` in `.env`, then send a PDF to the admin endpoint:

```bash
curl -X POST http://localhost:8000/admin/nutrition-labels \
  -H "X-Admin-Key: YOUR_ADMIN_INGEST_KEY" \
  -F restaurant_name="Restaurant Name" \
  -F file=@path/to/menu.pdf
```

The PDF parser requires the configured Llama Cloud key. Every extracted label is upserted into SQLite under the supplied restaurant name and is immediately available to recommendations.

## Publish safely

Before pushing to GitHub, confirm that `.env`, `foodpilot.db`, database backups, and `env/` are ignored. Publish `.env.example` instead of `.env`; it contains placeholders only. API keys and Telegram tokens must never be committed.
