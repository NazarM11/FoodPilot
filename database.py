from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "foodpilot.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS restaurants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            restaurant_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            calories REAL NOT NULL,
            protein REAL NOT NULL,
            carbs REAL NOT NULL,
            fats REAL NOT NULL DEFAULT 0,
            serving_size TEXT,
            source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            menu_item_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, menu_item_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (menu_item_id) REFERENCES menu_items(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_recent_choices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            menu_item_id INTEGER NOT NULL,
            selected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (menu_item_id) REFERENCES menu_items(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_recent_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            search_query TEXT NOT NULL,
            searched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(menu_items)")}
    for column, definition in {
        "fats": "REAL NOT NULL DEFAULT 0",
        "serving_size": "TEXT",
        "source": "TEXT",
        "category": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE menu_items ADD COLUMN {column} {definition}")
    conn.execute("DROP INDEX IF EXISTS idx_menu_items_restaurant_item")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_menu_items_restaurant_category_item "
        "ON menu_items (restaurant_id, category, item_name)"
    )
    conn.commit()
    conn.close()


def seed_sample_data() -> None:
    conn = get_connection()

    restaurant_names = ["Green Bowl", "Fuel Kitchen", "Sunrise Grill"]
    for name in restaurant_names:
        conn.execute(
            "INSERT OR IGNORE INTO restaurants (name) VALUES (?)",
            (name,),
        )

    existing = conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
    if existing == 0:
        items = [
            ("Green Bowl", "Chicken Bowl", 800, 50, 90, 20),
            ("Green Bowl", "Salmon Salad", 760, 45, 60, 25),
            ("Fuel Kitchen", "Veggie Wrap", 600, 32, 70, 18),
            ("Sunrise Grill", "Protein Shake", 350, 25, 20, 10),
            ("Fuel Kitchen", "Greek Yogurt Bowl", 520, 18, 50, 15),
        ]
        for restaurant_name, item_name, calories, protein, carbs, fats in items:
            restaurant_id = conn.execute(
                "SELECT id FROM restaurants WHERE name = ?",
                (restaurant_name,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO menu_items (restaurant_id, item_name, calories, protein, carbs, fats) VALUES (?, ?, ?, ?, ?, ?)",
                (restaurant_id, item_name, calories, protein, carbs, fats),
            )

    conn.commit()
    conn.close()


def fetch_menu_items() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """
         SELECT m.id, r.name AS restaurant, m.item_name, m.calories, m.protein, m.carbs,
             m.fats, m.serving_size, m.source
        FROM menu_items m
        JOIN restaurants r ON r.id = m.restaurant_id
        ORDER BY m.item_name ASC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_menu_items(items: list[dict]) -> None:
    conn = get_connection()
    try:
        for item in items:
            restaurant = str(item.get("restaurant") or "Uploaded Labels").strip()
            name = str(item.get("name") or item.get("item_name") or "").strip()
            if not name:
                continue
            restaurant_row = conn.execute(
                "SELECT id FROM restaurants WHERE name = ?",
                (restaurant,),
            ).fetchone()
            if restaurant_row is None:
                restaurant_id = conn.execute(
                    "INSERT INTO restaurants (name) VALUES (?) RETURNING id",
                    (restaurant,),
                ).fetchone()[0]
            else:
                restaurant_id = restaurant_row[0]
            conn.execute(
                """
                INSERT INTO menu_items
                    (restaurant_id, item_name, category, calories, protein, carbs, fats, serving_size, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(restaurant_id, category, item_name) DO UPDATE SET
                    calories = excluded.calories,
                    protein = excluded.protein,
                    carbs = excluded.carbs,
                    fats = excluded.fats,
                    serving_size = excluded.serving_size,
                    source = excluded.source
                """,
                (
                    restaurant_id,
                    name,
                    str(item.get("category") or ""),
                    float(item.get("kcal") or item.get("calories") or 0),
                    float(item.get("protein") or 0),
                    float(item.get("carbs") or 0),
                    float(item.get("fats") or 0),
                    item.get("serving_size"),
                    item.get("source"),
                ),
            )
        conn.commit()
    finally:
        conn.close()
