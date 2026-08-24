import logging
import os

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
API_URL = os.getenv("FOODPILOT_API_URL", "http://127.0.0.1:8000").rstrip("/")


async def recommendation_for(goals: dict) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{API_URL}/recommendations", json={"goals": goals})
        response.raise_for_status()
        return response.json()


def parse_goals(text: str) -> dict:
    values = text.replace(",", " ").split()
    if len(values) != 4:
        raise ValueError("Enter four numbers: kcal protein carbs fats")
    try:
        kcal, protein, carbs, fats = (float(value) for value in values)
    except ValueError as exc:
        raise ValueError("All four goals must be numbers") from exc
    return {"kcal": kcal, "protein": protein, "carbs": carbs, "fats": fats}


def format_response(result: dict) -> str:
    meal = result["meal"]
    if not meal["main"]:
        return meal["why_this_combo_fits"]
    items_by_name = {item["name"]: item for item in result.get("items", [])}

    def item_with_restaurant(name: str | None) -> str:
        if not name:
            return "None"
        restaurant = items_by_name.get(name, {}).get("restaurant")
        return f"{name} ({restaurant})" if restaurant else name

    return (
        "FoodPilot recommendation\n\n"
        + "\n".join(
            line for line in (
                f"Main: {item_with_restaurant(meal['main'])}",
                f"Side/add-on: {item_with_restaurant(meal['side'])}" if meal["side"] else None,
                f"Drink: {item_with_restaurant(meal['drink'])}" if meal["drink"] else None,
            )
            if line
        )
        + "\n\n"
        f"Totals: {result['totals']['kcal']} kcal, "
        f"{result['totals']['protein']}g protein, "
        f"{result['totals']['carbs']}g carbs, "
        f"{result['totals']['fats']}g fat\n\n"
        f"{meal['why_this_combo_fits']}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to FoodPilot! 🍔🤖\n\n"
        "Your AI-powered food recommendation assistant.\n\n"
        "FoodPilot searches meals across **6 popular restaurants** and finds options that match your calorie and macro goals:\n\n"
        "**A&W · Popeyes · Taco Bell · Wendy's · McDonald's · Tim Hortons**\n\n"
        "Try:\n\n"
        "`/recommend 650 30 35 20`\n\n"
        "*(kcal · protein · carbs · fats)*",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Use /recommend kcal protein carbs fats\n"
        "Example: /recommend 650 30 35 20\n\n"
        "You can also send the four numbers directly: 650 30 35 20"
    )


async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        goals = parse_goals(" ".join(context.args))
        result = await recommendation_for(goals)
        await update.message.reply_text(format_response(result))
    except ValueError as exc:
        await update.message.reply_text(str(exc))
    except httpx.HTTPError:
        await update.message.reply_text("FoodPilot is temporarily unavailable. Please try again later.")


async def plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        goals = parse_goals(update.message.text or "")
        result = await recommendation_for(goals)
        await update.message.reply_text(format_response(result))
    except ValueError:
        await update.message.reply_text("Use four values: kcal protein carbs fats\nExample: 650 30 35 20")
    except httpx.HTTPError:
        await update.message.reply_text("FoodPilot is temporarily unavailable. Please try again later.")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token.startswith("replace-with"):
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env before starting the Telegram bot")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("recommend", recommend))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_text))
    logger.info("FoodPilot Telegram bot is running")
    application.run_polling()


if __name__ == "__main__":
    main()
