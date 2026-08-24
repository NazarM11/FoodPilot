from fastapi.testclient import TestClient

from llama_client import NutritionLabel
from main import GoalInput, app, combo_fits, is_drink

client = TestClient(app)


def test_is_drink_detects_frosty_and_other_drink_names():
    assert is_drink({"item_name": "Large Chocolate Frosty"}) is True
    assert is_drink({"item_name": "Diet Coke"}) is True
    assert is_drink({"item_name": "Classic Burger"}) is False


def test_recommendations_returns_ranked_matches(monkeypatch):
    monkeypatch.setattr(
        "main.fetch_menu_items",
        lambda: [{
            "item_name": "Chicken Bowl",
            "calories": 800,
            "protein": 50,
            "carbs": 90,
            "fats": 20,
        }],
    )
    payload = {
        "goals": {
            "kcal": 800,
            "protein": 50,
            "carbs": 90,
            "fats": 20,
        }
    }

    response = client.post("/recommendations", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) > 0

    top_item = data["items"][0]
    assert top_item["name"] == "Chicken Bowl"
    assert top_item["score"] >= 0
    assert "carbs" in top_item
    assert "fats" in top_item


def test_recommendations_prefers_same_restaurant_and_adds_drink(monkeypatch):
    monkeypatch.setattr(
        "main.fetch_menu_items",
        lambda: [
            {"restaurant": "Burger House", "item_name": "Classic Burger", "calories": 650, "protein": 30, "carbs": 40, "fats": 24},
            {"restaurant": "Burger House", "item_name": "Coke", "calories": 150, "protein": 0, "carbs": 39, "fats": 0},
            {"restaurant": "Burger House", "item_name": "Fries", "calories": 320, "protein": 4, "carbs": 34, "fats": 15},
            {"restaurant": "Other Spot", "item_name": "Salad Bowl", "calories": 500, "protein": 28, "carbs": 35, "fats": 12},
        ],
    )

    response = client.post(
        "/recommendations",
        json={"goals": {"kcal": 800, "protein": 30, "carbs": 80, "fats": 25}},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) <= 4
    assert any(item["name"].lower() == "coke" for item in items)
    restaurants = {item["restaurant"] for item in items}
    assert len(restaurants) == 1
    assert list(restaurants)[0] == "Burger House"
    totals = {
        "kcal": sum(item["kcal"] for item in items),
        "protein": sum(item["protein"] for item in items),
        "carbs": sum(item["carbs"] for item in items),
        "fats": sum(item["fats"] for item in items),
    }
    assert abs(totals["kcal"] - 800) <= 50
    assert abs(totals["protein"] - 30) <= 5
    assert abs(totals["carbs"] - 80) <= 10
    assert abs(totals["fats"] - 25) <= 5


def test_recommendations_prefers_main_plus_side_plus_drink(monkeypatch):
    monkeypatch.setattr(
        "main.fetch_menu_items",
        lambda: [
            {"restaurant": "Wendy's", "item_name": "Grilled Chicken Wrap", "calories": 440, "protein": 36, "carbs": 18, "fats": 18},
            {"restaurant": "Wendy's", "item_name": "Fries", "calories": 240, "protein": 20, "carbs": 30, "fats": 8},
            {"restaurant": "Wendy's", "item_name": "Sprite", "calories": 80, "protein": 4, "carbs": 12, "fats": 0},
            {"restaurant": "Other Spot", "item_name": "Salad Bowl", "calories": 500, "protein": 28, "carbs": 35, "fats": 12},
        ],
    )

    response = client.post(
        "/recommendations",
        json={"goals": {"kcal": 750, "protein": 60, "carbs": 60, "fats": 30}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "meal" in payload
    assert "totals" in payload
    meal = payload["meal"]
    assert set(meal.keys()) == {"main", "side", "drink", "why_this_combo_fits"}
    assert meal["drink"]
    assert meal["main"]
    assert meal["side"]
    assert "sprite" in meal["drink"].lower() or "drink" in meal["drink"].lower()
    totals = payload["totals"]
    assert abs(totals["kcal"] - 750) <= 50
    assert abs(totals["protein"] - 60) <= 5
    assert abs(totals["carbs"] - 60) <= 10
    assert abs(totals["fats"] - 30) <= 5


def test_recommendations_rejects_out_of_tolerance_fallback(monkeypatch):
    monkeypatch.setattr(
        "main.fetch_menu_items",
        lambda: [
            {"restaurant": "Popeyes", "item_name": "Deluxe Chicken Sandwich", "calories": 740, "protein": 34, "carbs": 55, "fats": 42},
            {"restaurant": "Popeyes", "item_name": "Large Chocolate Frosty", "calories": 424, "protein": 8.2, "carbs": 64, "fats": 15},
            {"restaurant": "Popeyes", "item_name": "Large Vanilla Frosty", "calories": 424, "protein": 8.2, "carbs": 64, "fats": 15},
        ],
    )

    response = client.post(
        "/recommendations",
        json={"goals": {"kcal": 750, "protein": 60, "carbs": 80, "fats": 30}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meal"]["main"] is None
    assert payload["meal"]["side"] is None
    assert payload["meal"]["drink"] is None
    assert "No valid meal bundle" in payload["meal"]["why_this_combo_fits"]
    assert payload["totals"] == {"kcal": 0, "protein": 0, "carbs": 0, "fats": 0}


def test_meal_response_never_uses_non_drink_as_drink(monkeypatch):
    monkeypatch.setattr(
        "main.fetch_menu_items",
        lambda: [
            {"restaurant": "Wendy's", "item_name": "Steak Quesadilla", "calories": 650, "protein": 30, "carbs": 35, "fats": 31},
            {"restaurant": "Wendy's", "item_name": "Fries", "calories": 320, "protein": 4, "carbs": 34, "fats": 15},
            {"restaurant": "Wendy's", "item_name": "Lemonade", "calories": 260, "protein": 0, "carbs": 67, "fats": 0},
        ],
    )

    response = client.post(
        "/recommendations",
        json={"goals": {"kcal": 900, "protein": 30, "carbs": 100, "fats": 30}},
    )

    assert response.status_code == 200
    meal = response.json()["meal"]
    assert meal["drink"]
    assert "quesadilla" not in meal["drink"].lower()
    assert "fries" not in meal["drink"].lower()
    assert "lemonade" in meal["drink"].lower()


def test_combo_fits_uses_user_tight_tolerance_windows():
    goals = GoalInput(kcal=750, protein=60, carbs=60, fats=30)
    valid_combo = [
        {"item_name": "Chicken Bowl", "calories": 720, "protein": 58, "carbs": 55, "fats": 28},
        {"item_name": "Lemonade", "calories": 30, "protein": 0, "carbs": 5, "fats": 0},
    ]
    invalid_combo = [
        {"item_name": "Large Burger", "calories": 900, "protein": 70, "carbs": 80, "fats": 40},
        {"item_name": "Lemonade", "calories": 30, "protein": 0, "carbs": 5, "fats": 0},
    ]

    assert combo_fits(goals, valid_combo) is True
    assert combo_fits(goals, invalid_combo) is False


def test_nutrition_label_upload_saves_llama_result(monkeypatch):
    label = NutritionLabel(
        name="Test Granola",
        calories=210,
        protein=6,
        carbs=32,
        fats=8,
        serving_size="45 g",
    )
    monkeypatch.setenv("ADMIN_INGEST_KEY", "test-admin-key")
    monkeypatch.setattr("main.extract_nutrition_label", lambda label_text: label)
    monkeypatch.setattr("main.parse_pdf", lambda pdf_bytes, filename: "Test Granola, 210 calories, 6g protein, 32g carbs, 8g fat")

    response = client.post(
        "/admin/nutrition-labels",
        headers={"X-Admin-Key": "test-admin-key"},
        files={"file": ("label.pdf", b"not a real pdf", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Test Granola"

    recommendations = client.post(
        "/recommendations",
        json={"goals": {"kcal": 210, "protein": 6, "carbs": 32, "fats": 8}},
    )
    assert recommendations.status_code == 200
    payload = recommendations.json()
    assert len(payload["items"]) <= 3
    assert all("score" in item for item in payload["items"])
