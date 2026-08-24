import logging
import os
import secrets

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

from database import fetch_menu_items, init_db, save_menu_items
from llama_client import (
    NutritionLabel,
    extract_nutrition_catalog,
    extract_nutrition_catalog_from_pdf,
    extract_nutrition_label,
    parse_pdf,
)
from recommendation_engine import (
    GoalInput,
    NutritionGoals,
    build_meal_response,
    choose_combo,
    combo_fits,
    is_condiment,
    is_drink,
    score_match,
    to_menu_item,
)

app = FastAPI()
logger = logging.getLogger(__name__)


init_db()


@app.get("/")
def read_root():
    return {"message": "FoodPilot API is running"}


@app.post("/recommendations")
def recommend_items(payload: NutritionGoals):
    goals = payload.goals
    items = []
    for item_data in fetch_menu_items():
        item = to_menu_item(item_data)
        score = score_match(item, goals)
        items.append(
            {
                "restaurant": item_data.get("restaurant") or item_data.get("restaurant_name") or "Unknown",
                "item_name": item.name,
                "name": item.name,
                "kcal": item.kcal,
                "protein": item.protein,
                "carbs": item.carbs,
                "fats": item.fats,
                "score": round(score, 2),
            }
        )

    selected = choose_combo(items, goals)
    if not selected:
        return {
            "meal": {
                "main": None,
                "side": None,
                "drink": None,
                "why_this_combo_fits": "No valid meal bundle was found within the requested tolerance windows. Please adjust your calorie or macro targets.",
            },
            "totals": {"kcal": 0, "protein": 0, "carbs": 0, "fats": 0},
        }

    selected.sort(key=lambda item: item["score"], reverse=True)
    response = build_meal_response(selected, goals)
    response["items"] = selected[:3]
    return response


@app.post("/admin/nutrition-labels")
def ingest_nutrition_label(
    admin_key: str = Header(..., alias="X-Admin-Key"),
    restaurant_name: str = Form(default="Uploaded Labels"),
    file: UploadFile = File(...),
):
    configured_key = os.getenv("ADMIN_INGEST_KEY")
    if not configured_key or not secrets.compare_digest(admin_key, configured_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Upload a PDF nutrition label")

    restaurant_name = restaurant_name.strip()
    if not restaurant_name:
        raise HTTPException(status_code=422, detail="Restaurant name cannot be empty")

    try:
        pdf_bytes = file.file.read()
        pdf_text = parse_pdf(pdf_bytes, file.filename or "nutrition-label.pdf")
        if not pdf_text:
            raise ValueError("LlamaParse returned no text")
    except Exception as exc:
        logger.exception("LlamaParse failed while processing nutrition PDF")
        raise HTTPException(status_code=502, detail="LlamaParse could not read the PDF") from exc

    labels = extract_nutrition_catalog(pdf_text)
    if not labels:
        try:
            labels = extract_nutrition_catalog_from_pdf(pdf_bytes)
            if not labels:
                labels = [extract_nutrition_label(pdf_text[:10_000])]
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Vision extraction failed")
            raise HTTPException(status_code=502, detail="Could not extract nutrition data from PDF images") from exc

    if not labels:
        raise HTTPException(status_code=422, detail="No nutrition labels could be parsed from the uploaded PDF")

    saved_items = []
    for label in labels:
        if not isinstance(label, NutritionLabel):
            continue
        saved_items.append(
            {
                "restaurant": restaurant_name,
                "name": label.name,
                "kcal": label.calories,
                "protein": label.protein,
                "carbs": label.carbs,
                "fats": label.fats,
                "serving_size": label.serving_size,
                "source": "pdf-import",
            }
        )

    if not saved_items:
        raise HTTPException(status_code=422, detail="No usable nutrition entries were extracted from the uploaded PDF")

    save_menu_items(saved_items)
    return saved_items[0]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
