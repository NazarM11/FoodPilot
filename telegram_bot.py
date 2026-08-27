import logging
import os
import re

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


_KCAL_WORDS = r"(?:kcal|kcals?|cal(?:orie)?s?|cals?)"
_PROTEIN_WORDS = r"(?:proteins?|prots?)"
_CARB_WORDS = r"(?:carb(?:ohydrate)?s?|carbs?)"
_FAT_WORDS = r"(?:fats?|lipids?)"

_NUMBER_PATTERNS = {
    "kcal": (
        rf"(?:max(?:imum)?|under|below|less than|no more than|at most|around|about|up to)\s*(\d+(?:\.\d+)?)\s*{_KCAL_WORDS}",
        rf"(\d+(?:\.\d+)?)\s*{_KCAL_WORDS}",
        rf"{_KCAL_WORDS}\s*(?:max(?:imum)?|under|below|less than|no more than|at most|around|about|up to)?\s*(\d+(?:\.\d+)?)",
    ),
    "protein": (
        rf"(?:preferably|about|around|at least|minimum(?: of)?|over|more than|up to|max(?:imum)?|under)\s*(\d+(?:\.\d+)?)\s*(?:g(?:rams?)?\s*(?:of\s+)?)?{_PROTEIN_WORDS}",
        rf"(\d+(?:\.\d+)?)\s*(?:g(?:rams?)?\s*(?:of\s+)?)?{_PROTEIN_WORDS}",
        rf"{_PROTEIN_WORDS}\s*(?:preferably|about|around|at least|over|more than|up to|max(?:imum)?|under)?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)?",
    ),
    "carbs": (
        rf"(?:preferably|about|around|max(?:imum)?|under|below|less than|no more than|at most|up to)\s*(\d+(?:\.\d+)?)\s*(?:g(?:rams?)?\s*(?:of\s+)?)?{_CARB_WORDS}",
        rf"(\d+(?:\.\d+)?)\s*(?:g(?:rams?)?\s*(?:of\s+)?)?{_CARB_WORDS}",
        rf"{_CARB_WORDS}\s*(?:preferably|about|around|max(?:imum)?|under|below|less than|no more than|at most|up to)?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)?",
    ),
    "fats": (
        rf"(?:preferably|about|around|max(?:imum)?|under|below|less than|no more than|at most|up to)\s*(\d+(?:\.\d+)?)\s*(?:g(?:rams?)?\s*(?:of\s+)?)?{_FAT_WORDS}",
        rf"(\d+(?:\.\d+)?)\s*(?:g(?:rams?)?\s*(?:of\s+)?)?{_FAT_WORDS}",
        rf"{_FAT_WORDS}\s*(?:preferably|about|around|max(?:imum)?|under|below|less than|no more than|at most|up to)?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)?",
    ),
}

_FILLER = r"(?:(?:the|my|our|your|on|of|in|it)\s+)*"
_MODERATE = (
    r"not\s+(?:to+|too)\s+(?:much|many)",
    r"not\s+(?:that|so)\s+(?:much|many)",
    r"not\s+much",
    r"too\s+(?:much|many)",
    r"way\s+too\s+(?:much|many)",
    r"not\s+a\s+lot\s+of",
    r"a\s+little",
    r"a\s+bit\s+of",
    r"low(?:er)?(?:\s+on)?",
    r"light\s+on",
    r"go\s+easy\s+on",
    r"easy\s+on",
    r"watch(?:ing)?\s+(?:my|the)",
    r"cut(?:ting)?\s+(?:back|down)(?:\s+on)?",
    r"limit(?:ing)?",
    r"keep\s+(?:it\s+)?low(?:\s+on)?",
    r"without\s+too\s+(?:much|many)",
    r"minimal",
    r"moderate",
)
_MODERATE_RE = "|".join(f"(?:{phrase})" for phrase in _MODERATE)

_QUALITATIVE_LIMITS = (
    ("carbs", rf"(?:{_MODERATE_RE})\s+{_FILLER}{_CARB_WORDS}\b|{_CARB_WORDS}\s*-?\s*(?:free|conscious)|\bketo\b|\blow\s*carb", 30.0),
    ("fats", rf"(?:{_MODERATE_RE})\s+{_FILLER}{_FAT_WORDS}\b|\blow\s*fat\b|\blean\b", 15.0),
    ("kcal", rf"(?:{_MODERATE_RE})\s+{_FILLER}{_KCAL_WORDS}\b|light\s+(?:meal|something)|small\s+meal|something\s+light|not\s+too\s+(?:heavy|big)", 600.0),
    ("protein", rf"(?:{_MODERATE_RE})\s+{_FILLER}{_PROTEIN_WORDS}\b", 20.0),
)

_PROTEIN_PRIORITY = (
    r"as\s+much\s+protein\s+as\s+possible",
    r"max(?:imum|imize)?\s+protein",
    r"highest\s+protein",
    r"high\s+protein",
    r"plenty\s+of\s+protein",
    r"lots?\s+of\s+protein",
    r"a\s+lot\s+of\s+protein",
    r"more\s+protein",
    r"protein[-\s]?(?:heavy|rich|packed|focused)",
    r"protein\s+heavy",
    r"l[oi]aded\s+with\s+protein",
    r"full\s+of\s+protein",
    r"good\s+(?:amount\s+of\s+|source\s+of\s+)protein",
    r"decent\s+(?:amount\s+of\s+)protein",
    r"protein\s+please",
    r"extra\s+protein",
    r"big\s+on\s+protein",
    r"post[-\s]?workout",
    r"(?:build(?:ing)?|gain(?:ing|s)?)\s+muscle",
    r"muscle\s+(?:building|gain)",
)
_PROTEIN_PRIORITY_RE = "|".join(f"(?:{phrase})" for phrase in _PROTEIN_PRIORITY)
_NEGATION_RE = re.compile(r"\bnot\b|\bno\b|n't\b|\bwithout\b|\bhardly\b|\bbarely\b")


def _has_unnegated_protein_priority(lowered: str) -> bool:
    for match in re.finditer(_PROTEIN_PRIORITY_RE, lowered):
        prefix = lowered[max(0, match.start() - 15):match.start()]
        if not _NEGATION_RE.search(prefix):
            return True
    return False


def parse_goals(text: str) -> dict:
    values = text.replace(",", " ").split()
    if len(values) == 4 and all(re.fullmatch(r"\d+(?:\.\d+)?", value) for value in values):
        kcal, protein, carbs, fats = (float(value) for value in values)
        return {"kcal": kcal, "protein": protein, "carbs": carbs, "fats": fats}

    lowered = text.lower()

    goals = {}
    for field_name, patterns in _NUMBER_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                goals[field_name] = float(next(group for group in match.groups() if group is not None))
                break

    if "kcal" not in goals:
        compact = re.sub(r"[,/|;]+", " ", lowered)
        stripped = re.sub(
            rf"{_KCAL_WORDS}|{_PROTEIN_WORDS}|{_CARB_WORDS}|{_FAT_WORDS}|g(?:rams?)?",
            " ",
            compact,
        )
        tokens = stripped.split()
        if tokens and all(re.fullmatch(r"\d+(?:\.\d+)?", token) for token in tokens):
            numbers = [float(token) for token in tokens]
            fields = ("kcal", "protein", "carbs", "fats")
            if 2 <= len(numbers) <= 4:
                for field_name, number in zip(fields, numbers):
                    goals.setdefault(field_name, number)

    for field_name, pattern, ceiling in _QUALITATIVE_LIMITS:
        if field_name not in goals and re.search(pattern, lowered):
            goals[field_name] = ceiling

    if _has_unnegated_protein_priority(lowered):
        goals["maximize_protein"] = True

    if not goals:
        raise ValueError(
            "Tell me your goals, for example: max 700 calories and preferably 40g protein, "
            "or something like \"not too much carbs, plenty of protein\""
        )
    return goals


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
        "Your AI food recommendation assistant.\n\n"
        "Tell me what you want in your own words. I search across **6 popular restaurants**:\n\n"
        "**A&W · Popeyes · Taco Bell · Wendy's · McDonald's · Tim Hortons**\n\n"
            "Just tell me what you want, for example:\n\n"
            "I want something under 700 calories with plenty of protein and not too much fat.",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Tell me what kind of meal you want in your own words.\n\n"
        "Example: I want something under 700 calories with plenty of protein and not too much fat."
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


_HELP_TEXT = (
    "Tell me what you want in your own words. For example:\n\n"
    "• something under 700 calories with plenty of protein and not too much fat\n"
    "• 300 cals, 20 prot\n"
    "• low carb, protein packed\n"
    "• 700 40 30 20  (kcal / protein / carbs / fat)\n"
    "• go easy on the carbs, post-workout meal"
)


async def plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        goals = parse_goals(update.message.text or "")
        result = await recommendation_for(goals)
        await update.message.reply_text(format_response(result))
    except ValueError:
        await update.message.reply_text(_HELP_TEXT)
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
