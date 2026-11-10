"""SQLite access: one connection per request, the schema, and the demo data."""

import sqlite3
from pathlib import Path

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(demo: bool = True, admin_password: str = "admin") -> None:
    db = get_db()
    db.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        ("admin", generate_password_hash(admin_password)),
    )
    if demo:
        seed_demo(db)


# name, unit, stock, alert level
INGREDIENTS = [
    ("Pasta", "g", 5000, 1000), ("Tomato sauce", "ml", 4000, 800), ("Minced beef", "g", 3000, 800),
    ("Burger bun", "piece", 40, 10), ("Cheese", "g", 2500, 500), ("Pizza dough", "piece", 30, 8),
    ("Vegetables", "g", 6000, 1000), ("Tortilla", "piece", 50, 10), ("Chicken", "g", 4000, 1000),
    ("Seafood", "g", 300, 400), ("Rice noodles", "g", 2000, 400), ("Mint tea leaves", "g", 500, 100),
    ("Cola can", "piece", 48, 12), ("Orange", "piece", 7, 15), ("Cream", "ml", 100, 400),
]  # fmt: skip

# name, description, price (MAD), category, vegetarian, gluten free, allergens, emoji, recipe
DISHES = [
    ("Pasta bolognese", "Italian pasta with tomato and beef sauce", 65, "Main courses", 0, 0,
     "gluten", "🍝", {"Pasta": 150, "Tomato sauce": 120, "Minced beef": 100}),
    ("Cheeseburger", "Juicy beef burger with melted cheese", 55, "Main courses", 0, 0,
     "gluten,milk", "🍔", {"Burger bun": 1, "Minced beef": 150, "Cheese": 40}),
    ("Pizza margherita", "Cheesy pizza with fresh vegetables", 70, "Main courses", 1, 0,
     "gluten,milk", "🍕", {"Pizza dough": 1, "Tomato sauce": 100, "Cheese": 120, "Vegetables": 60}),
    ("Chicken tacos", "French tacos, chicken and fries, sauce biggy", 50, "Main courses", 0, 0,
     "gluten,milk", "🌯", {"Tortilla": 1, "Chicken": 150, "Cheese": 50}),
    ("Seafood soup", "Chinese-style soup with seafood and noodles", 45, "Starters", 0, 1,
     "shellfish,fish", "🍜", {"Seafood": 120, "Rice noodles": 60, "Vegetables": 80}),
    ("Garden salad", "Seasonal vegetables, olive oil and lemon", 35, "Starters", 1, 1,
     "", "🥗", {"Vegetables": 200}),
    ("Mint tea", "Moroccan mint tea, served in a teapot", 15, "Drinks", 1, 1,
     "", "🍵", {"Mint tea leaves": 10}),
    ("Cola", "33 cl can", 15, "Drinks", 1, 1, "", "🥤", {"Cola can": 1}),
    ("Fresh orange juice", "Pressed to order", 20, "Drinks", 1, 1, "", "🍊", {"Orange": 3}),
    ("Panna cotta", "Vanilla cream with red fruit coulis", 30, "Desserts", 1, 1,
     "milk", "🍮", {"Cream": 150}),
]  # fmt: skip

CATEGORIES = ["Starters", "Main courses", "Desserts", "Drinks"]


def seed_demo(db: sqlite3.Connection) -> None:
    db.execute("BEGIN")
    for i, name in enumerate(CATEGORIES):
        db.execute("INSERT INTO categories (name, position) VALUES (?, ?)", (name, i))
    for row in INGREDIENTS:
        db.execute("INSERT INTO ingredients (name, unit, stock, alert_level) VALUES (?,?,?,?)", row)
    for name, desc, price, cat, veg, gf, allergens, emoji, recipe in DISHES:
        cat_id = db.execute("SELECT id FROM categories WHERE name = ?", (cat,)).fetchone()[0]
        dish_id = db.execute(
            "INSERT INTO dishes (name, description, price_cents, category_id, vegetarian,"
            " gluten_free, allergens, emoji) VALUES (?,?,?,?,?,?,?,?)",
            (name, desc, price * 100, cat_id, veg, gf, allergens, emoji),
        ).lastrowid
        for ingredient, qty in recipe.items():
            ing_id = db.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient,)).fetchone()[0]
            db.execute("INSERT INTO recipe VALUES (?,?,?)", (dish_id, ing_id, qty))
    for name, phone in [("Walk-in customer", ""), ("Sara El Idrissi", "0611223344"),
                        ("Youssef Benali", "0622334455")]:  # fmt: skip
        db.execute("INSERT INTO customers (name, phone) VALUES (?, ?)", (name, phone))
    db.execute("COMMIT")


@click.command("init-db")
@click.option("--empty", is_flag=True, help="No demo menu, stock or customers.")
@click.option("--password", default="admin", show_default=True, help="Password of the admin user.")
def init_db_command(empty: bool, password: str) -> None:
    """Create (or reset) the database."""
    init_db(demo=not empty, admin_password=password)
    click.echo(f"Database ready: {current_app.config['DATABASE']}  (login: admin / {password})")
