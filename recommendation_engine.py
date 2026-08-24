import json
import logging
import os
from typing import Optional

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

STRICT_TOLERANCE = {"kcal": 100, "protein": 5, "carbs": 10, "fats": 5}
RELAXED_TOLERANCE = {"kcal": 150, "protein": 8, "carbs": 15, "fats": 8}


class GoalInput(BaseModel):
    kcal: Optional[float] = Field(default=None, gt=0)
    protein: Optional[float] = Field(default=None, gt=0)
    carbs: Optional[float] = Field(default=None, gt=0)
    fats: Optional[float] = Field(default=None, gt=0)


class NutritionGoals(BaseModel):
    goals: GoalInput


class MenuItem(BaseModel):
    name: str
    kcal: float
    protein: float
    carbs: float
    fats: float


def score_match(item: MenuItem, goals: GoalInput) -> float:
    if all(value is None for value in [goals.kcal, goals.protein, goals.carbs, goals.fats]):
        return 0.0

    score = 100.0
    weights = {"kcal": 0.45, "protein": 0.25, "carbs": 0.15, "fats": 0.15}

    for field_name, weight in weights.items():
        target = getattr(goals, field_name)
        if target is None:
            continue
        item_value = getattr(item, field_name)
        score -= abs(item_value - target) / target * (100.0 * weight)

    return max(score, 0.0)


def item_name(item: dict) -> str:
    return str(item.get("item_name") or item.get("name") or "Untitled Item").strip()


def item_value(item: dict, field_name: str) -> float:
    key_map = {"kcal": "calories", "protein": "protein", "carbs": "carbs", "fats": "fats"}
    value = item.get(field_name)
    if value is None:
        value = item.get(key_map.get(field_name, field_name))
    return float(value or 0)


def to_menu_item(item: dict) -> MenuItem:
    return MenuItem(
        name=item_name(item),
        kcal=item_value(item, "kcal"),
        protein=item_value(item, "protein"),
        carbs=item_value(item, "carbs"),
        fats=item_value(item, "fats"),
    )


def is_drink(item: dict) -> bool:
    name = item_name(item).lower()
    normalized_name = " ".join(filter(None, __import__("re").sub(r"[^a-z0-9]+", " ", name).split()))
    restaurant = str(item.get("restaurant") or "").lower()
    drink_markers = (
        "drink", "soda", "cola", "coke", "sprite", "tea", "lemonade", "milkshake", "coffee",
        "water", "juice", "frosty", "shake", "float", "iced tea", "sweet tea",
    )
    for marker in drink_markers:
        if " " in marker:
            if marker in normalized_name:
                return True
        else:
            if marker in normalized_name.split():
                return True
    return "drink" in restaurant


def item_role(item: dict) -> str:
    if is_drink(item):
        return "drink"
    protein = item_value(item, "protein")
    carbs = item_value(item, "carbs")
    kcal = item_value(item, "kcal")
    if protein >= 15 and (carbs <= 45 or kcal >= 300):
        return "main"
    if carbs >= 20 and protein < 12:
        return "side"
    if protein >= 8 and carbs <= 15:
        return "addon"
    return "main" if protein >= 8 else "side"


def contains_goal(item: dict, goals: GoalInput) -> bool:
    for field_name in ["kcal", "protein", "carbs", "fats"]:
        target = getattr(goals, field_name)
        if target is not None:
            item_value_float = item_value(item, field_name)
            if item_value_float > target * 1.5:
                return False
    return True


def combo_fits(
    goals: GoalInput,
    items: list[dict],
    tolerance: dict[str, float] | None = None,
) -> bool:
    totals = {
        "kcal": sum(item_value(item, "kcal") for item in items),
        "protein": sum(item_value(item, "protein") for item in items),
        "carbs": sum(item_value(item, "carbs") for item in items),
        "fats": sum(item_value(item, "fats") for item in items),
    }
    tolerance = tolerance or STRICT_TOLERANCE
    for field_name, max_delta in tolerance.items():
        target = getattr(goals, field_name)
        if target is None:
            continue
        actual = totals[field_name]
        if abs(actual - target) > max_delta:
            return False
    return True


def combo_score(goals: GoalInput, items: list[dict]) -> float:
    weights = {"kcal": 0.45, "protein": 0.25, "carbs": 0.15, "fats": 0.15}
    totals = {
        "kcal": sum(item_value(item, "kcal") for item in items),
        "protein": sum(item_value(item, "protein") for item in items),
        "carbs": sum(item_value(item, "carbs") for item in items),
        "fats": sum(item_value(item, "fats") for item in items),
    }
    main_count = sum(1 for item in items if item_role(item) == "main")
    side_count = sum(1 for item in items if item_role(item) == "side")
    addon_count = sum(1 for item in items if item_role(item) == "addon")
    drink_count = sum(1 for item in items if is_drink(item))

    final_score = 100.0
    for field_name, weight in weights.items():
        target = getattr(goals, field_name)
        if target is None:
            continue
        actual = totals[field_name]
        if field_name == "protein" and actual < target * 0.85:
            final_score -= 35.0
        if field_name == "carbs" and actual < target * 0.75:
            final_score -= 25.0
        final_score -= abs(actual - target) / target * (100.0 * weight)

    if drink_count == 0:
        final_score -= 40.0
    if main_count == 0:
        final_score -= 25.0
    if side_count == 0 and addon_count == 0 and len(items) > 1:
        final_score -= 20.0
    if main_count >= 1 and (side_count + addon_count) >= 1 and drink_count >= 1:
        final_score += 60.0
    if main_count > 1:
        final_score -= 25.0
    if drink_count > 1:
        final_score -= 10.0
    if len(items) == 2:
        final_score -= 10.0
    if len(items) == 1:
        final_score -= 25.0
    if len(items) > 3:
        final_score -= 15.0
    return max(final_score, 0.0)


def generate_combo_candidates(
    items: list[dict],
    goals: GoalInput,
    tolerance: dict[str, float] | None = None,
) -> list[dict]:
    if not items:
        return []

    ranked = sorted(items, key=lambda item: score_match(to_menu_item(item), goals), reverse=True)
    preferred_restaurant = ranked[0].get("restaurant") or "Unknown"
    restaurant_groups = []
    for restaurant_name in {item.get("restaurant") or "Unknown" for item in ranked}:
        restaurant_group = [item for item in ranked if (item.get("restaurant") or "Unknown") == restaurant_name]
        restaurant_groups.append(restaurant_group)
    restaurant_groups.sort(key=lambda group: 0 if (group[0].get("restaurant") or "Unknown") == preferred_restaurant else 1)

    fallback_drinks = [item for item in ranked if is_drink(item)]
    candidates = []

    for restaurant_items in restaurant_groups:
        food_pool = [item for item in restaurant_items if not is_drink(item)]
        if not food_pool:
            continue

        drink_pool = [item for item in restaurant_items if is_drink(item)]
        if not drink_pool:
            drink_pool = fallback_drinks

        for item in food_pool:
            candidate = [item]
            if combo_fits(goals, candidate, tolerance):
                candidates.append({
                    "items": candidate,
                    "heuristic_score": combo_score(goals, candidate),
                    "restaurant": item.get("restaurant") or "Unknown",
                })

        for combo_size in [3, 2, 1]:
            for combo in __import__("itertools").combinations(food_pool, combo_size):
                for drink in drink_pool[:3]:
                    candidate = list(combo) + [drink]
                    if len(candidate) > 3:
                        continue
                    if not combo_fits(goals, candidate, tolerance):
                        continue
                    candidates.append({
                        "items": candidate,
                        "heuristic_score": combo_score(goals, candidate),
                        "restaurant": (candidate[0].get("restaurant") or "Unknown") if candidate else "Unknown",
                    })

    return sorted(candidates, key=lambda candidate: candidate["heuristic_score"], reverse=True)


def rank_combo_with_llm(candidates: list[dict], goals: GoalInput) -> list[dict] | None:
    if not candidates:
        return None

    api_key = os.getenv("LLAMA_API_KEY")
    if not api_key:
        return None

    base_url = os.getenv("LLAMA_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    model = os.getenv("LLAMA_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    candidate_payload = []
    for index, candidate in enumerate(candidates[:8]):
        items = []
        for item in candidate["items"]:
            items.append({
                "restaurant": item.get("restaurant") or "Unknown",
                "name": item_name(item),
                "kcal": item_value(item, "kcal"),
                "protein": item_value(item, "protein"),
                "carbs": item_value(item, "carbs"),
                "fats": item_value(item, "fats"),
            })
        candidate_payload.append({"index": index, "items": items, "heuristic_score": round(candidate["heuristic_score"], 2)})

    prompt = (
        "You are choosing the best restaurant meal bundle for a nutrition goal. "
        "Select the single best candidate based on realistic meal structure, same-restaurant preference, "
        "target closeness, and protein/carbs balance. Prefer one main item, one side or add-on, and one drink when possible; "
        "do not return mixed restaurants unless no valid same-restaurant option exists. "
        "Return only valid JSON: {\"winner_index\": <integer>, \"reason\": \"short explanation\"}."
    )
    request = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps({
                "goals": {
                    "kcal": goals.kcal,
                    "protein": goals.protein,
                    "carbs": goals.carbs,
                    "fats": goals.fats,
                },
                "candidates": candidate_payload,
            }, ensure_ascii=False)},
        ],
    }
    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=request,
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(content)
        winner_index = int(parsed.get("winner_index", 0))
        winner = candidates[winner_index] if 0 <= winner_index < len(candidates) else candidates[0]
        return winner["items"]
    except Exception:
        logger.exception("LLM bundle selection failed; falling back to heuristic ranking")
        return None


def choose_combo(items: list[dict], goals: GoalInput) -> list[dict]:
    candidates = generate_combo_candidates(items, goals)
    if not candidates:
        candidates = generate_combo_candidates(items, goals, RELAXED_TOLERANCE)
    if not candidates:
        return []

    llm_choice = rank_combo_with_llm(candidates, goals)
    if llm_choice is not None:
        llm_choice = sorted(llm_choice, key=lambda item: score_match(to_menu_item(item), goals), reverse=True)
        return llm_choice[:3]

    best_combo = candidates[0]["items"]
    best_combo = sorted(best_combo, key=lambda item: score_match(to_menu_item(item), goals), reverse=True)
    return best_combo[:3]


def build_meal_response(items: list[dict], goals: GoalInput) -> dict:
    if not items:
        return {
            "meal": {
                "main": None,
                "side": None,
                "drink": None,
                "why_this_combo_fits": "No valid meal was found for the provided goals.",
            },
            "totals": {"kcal": 0, "protein": 0, "carbs": 0, "fats": 0},
        }

    main = None
    side = None
    drink = None
    for item in items:
        if is_drink(item):
            drink = item
        elif item_role(item) == "main" and main is None:
            main = item
        elif item_role(item) in {"side", "addon"} and side is None:
            side = item

    if main is None:
        main = items[0]
    if side is None and len(items) > 1:
        side = next((item for item in items if item != main and not is_drink(item)), None)
    if drink is None:
        drink = next((item for item in items if is_drink(item)), None)

    meal = {
        "main": main.get("item_name") if main else None,
        "side": side.get("item_name") if side else None,
        "drink": drink.get("item_name") if drink else None,
        "why_this_combo_fits": "This bundle keeps the meal in one restaurant, includes a drink, and balances the target nutrition goals as closely as possible.",
    }
    if goals.kcal is not None or goals.protein is not None or goals.carbs is not None or goals.fats is not None:
        meal["why_this_combo_fits"] = (
            "This bundle stays within the same restaurant, adds a drink, and prioritizes a realistic main + side/add-on structure "
            "while staying closest to the requested calorie and macro targets."
        )

    totals = {
        "kcal": round(sum(item_value(item, "kcal") for item in items), 1),
        "protein": round(sum(item_value(item, "protein") for item in items), 1),
        "carbs": round(sum(item_value(item, "carbs") for item in items), 1),
        "fats": round(sum(item_value(item, "fats") for item in items), 1),
    }
    return {"meal": meal, "totals": totals}
