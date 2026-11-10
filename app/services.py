"""Business rules, kept out of the routes so they can be tested on their own.

- A dish is available only if every ingredient of its recipe is in stock for one portion.
- Placing an order takes the ingredients out of stock in one transaction: either the whole
  order goes through, or nothing changes (no half-taken stock if one dish runs out).
- Cancelling an order puts its ingredients back.
- An order moves forward only: new -> preparing -> served -> paid (or cancelled before serving).
"""

from __future__ import annotations

import csv
import io
import sqlite3
from collections import defaultdict

STATUS_FLOW = {
    "new": {"preparing", "cancelled"},
    "preparing": {"served", "cancelled"},
    "served": {"paid"},
    "paid": set(),
    "cancelled": set(),
}


class OrderError(ValueError):
    """An order that cannot be placed or changed (out of stock, wrong status…)."""


def money(cents: int | None) -> str:
    """1250 -> '12.50 MAD'"""
    return f"{(cents or 0) / 100:,.2f} MAD".replace(",", " ")


# ---------- menu ----------

def menu(db: sqlite3.Connection, *, category: int | None = None, vegetarian: bool = False,
         gluten_free: bool = False, without: str = "", include_inactive: bool = False) -> list[dict]:  # fmt: skip
    """Dishes with their category and how many portions the stock still allows."""
    sql = """SELECT d.*, c.name AS category, c.position FROM dishes d
             JOIN categories c ON c.id = d.category_id WHERE 1 = 1"""
    args: list = []
    if not include_inactive:
        sql += " AND d.active = 1"
    if category:
        sql += " AND d.category_id = ?"
        args.append(category)
    if vegetarian:
        sql += " AND d.vegetarian = 1"
    if gluten_free:
        sql += " AND d.gluten_free = 1"
    sql += " ORDER BY c.position, d.name"
    portions = portions_left(db)
    dishes = []
    for row in db.execute(sql, args):
        dish = dict(row)
        dish["allergen_list"] = [a for a in dish["allergens"].split(",") if a]
        if without and without in dish["allergen_list"]:
            continue
        dish["portions_left"] = portions.get(dish["id"])
        dish["available"] = bool(dish["active"]) and (dish["portions_left"] is None or dish["portions_left"] > 0)
        dishes.append(dish)
    return dishes


def portions_left(db: sqlite3.Connection) -> dict[int, int]:
    """For each dish with a recipe: how many portions the current stock can make."""
    left: dict[int, int] = {}
    for row in db.execute(
        """SELECT r.dish_id, MIN(CAST(i.stock / r.quantity AS INTEGER)) AS portions
           FROM recipe r JOIN ingredients i ON i.id = r.ingredient_id GROUP BY r.dish_id"""
    ):
        left[row["dish_id"]] = row["portions"]
    return left


def recipe(db: sqlite3.Connection, dish_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(
        """SELECT i.id, i.name, i.unit, r.quantity FROM recipe r
           JOIN ingredients i ON i.id = r.ingredient_id WHERE r.dish_id = ? ORDER BY i.name""",
        (dish_id,),
    )]  # fmt: skip


def low_stock(db: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in db.execute(
        "SELECT * FROM ingredients WHERE stock <= alert_level ORDER BY stock / MAX(alert_level, 1)"
    )]


# ---------- orders ----------

def place_order(db: sqlite3.Connection, lines: list[tuple[int, int]], customer_id: int | None = None,
                table_no: int | None = None) -> int:  # fmt: skip
    """Create an order from (dish_id, quantity) lines and take its ingredients out of stock."""
    lines = [(int(d), int(q)) for d, q in lines if int(q) > 0]
    if not lines:
        raise OrderError("the order is empty")
    db.execute("BEGIN IMMEDIATE")  # lock the database: two waiters cannot sell the last portion
    try:
        needed: dict[int, float] = defaultdict(float)
        total = 0
        priced = []
        for dish_id, qty in lines:
            dish = db.execute("SELECT * FROM dishes WHERE id = ?", (dish_id,)).fetchone()
            if dish is None or not dish["active"]:
                raise OrderError(f"dish {dish_id} is not on the menu")
            for ing in db.execute("SELECT * FROM recipe WHERE dish_id = ?", (dish_id,)):
                needed[ing["ingredient_id"]] += ing["quantity"] * qty
            total += dish["price_cents"] * qty
            priced.append((dish_id, qty, dish["price_cents"]))
        for ing_id, amount in needed.items():
            ing = db.execute("SELECT name, stock, unit FROM ingredients WHERE id = ?", (ing_id,)).fetchone()
            if ing["stock"] < amount:
                raise OrderError(f"not enough {ing['name']}: {ing['stock']:g} {ing['unit']} left, "
                                 f"{amount:g} needed")  # fmt: skip
        for ing_id, amount in needed.items():
            db.execute("UPDATE ingredients SET stock = stock - ? WHERE id = ?", (amount, ing_id))
        order_id = db.execute(
            "INSERT INTO orders (customer_id, table_no, total_cents) VALUES (?, ?, ?)",
            (customer_id, table_no, total),
        ).lastrowid
        db.executemany(
            "INSERT INTO order_items (order_id, dish_id, quantity, unit_price_cents) VALUES (?,?,?,?)",
            [(order_id, *line) for line in priced],
        )
        db.execute("COMMIT")
        return order_id
    except Exception:
        db.execute("ROLLBACK")
        raise


def set_status(db: sqlite3.Connection, order_id: int, status: str) -> None:
    db.execute("BEGIN IMMEDIATE")  # read and change the status under the same lock
    try:
        order = db.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            raise OrderError("unknown order")
        if status not in STATUS_FLOW.get(order["status"], set()):
            raise OrderError(f"an order that is '{order['status']}' cannot become '{status}'")
        if status == "cancelled":  # the dishes were not served: their ingredients go back
            db.execute(
                """UPDATE ingredients SET stock = stock + (
                       SELECT SUM(r.quantity * oi.quantity) FROM order_items oi
                       JOIN recipe r ON r.dish_id = oi.dish_id
                       WHERE oi.order_id = ? AND r.ingredient_id = ingredients.id)
                   WHERE id IN (SELECT r.ingredient_id FROM order_items oi
                                JOIN recipe r ON r.dish_id = oi.dish_id WHERE oi.order_id = ?)""",
                (order_id, order_id),
            )
        db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def orders(db: sqlite3.Connection, status: str | None = None, limit: int = 200) -> list[dict]:
    sql = """SELECT o.*, c.name AS customer, c.phone,
                    GROUP_CONCAT(oi.quantity || ' × ' || d.name, ', ') AS item_list
             FROM orders o
             LEFT JOIN customers c ON c.id = o.customer_id
             LEFT JOIN order_items oi ON oi.order_id = o.id
             LEFT JOIN dishes d ON d.id = oi.dish_id"""
    args: list = []
    if status:
        sql += " WHERE o.status = ?"
        args.append(status)
    sql += " GROUP BY o.id ORDER BY o.id DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in db.execute(sql, args)]


# ---------- reports ----------

def report(db: sqlite3.Connection) -> dict:
    """Sales figures. Only paid orders count as revenue."""
    paid = "o.status = 'paid'"
    totals = db.execute(
        f"SELECT COUNT(*) AS orders, COALESCE(SUM(total_cents), 0) AS revenue FROM orders o WHERE {paid}"
    ).fetchone()
    by_day = db.execute(
        f"""SELECT date(created_at) AS day, COUNT(*) AS orders, SUM(total_cents) AS revenue
            FROM orders o WHERE {paid} GROUP BY day ORDER BY day DESC LIMIT 14"""
    ).fetchall()
    top = db.execute(
        f"""SELECT d.name, d.emoji, SUM(oi.quantity) AS sold, SUM(oi.quantity * oi.unit_price_cents) AS revenue
            FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN dishes d ON d.id = oi.dish_id
            WHERE {paid} GROUP BY d.id ORDER BY sold DESC LIMIT 5"""
    ).fetchall()
    open_orders = db.execute(
        "SELECT status, COUNT(*) AS n FROM orders WHERE status IN ('new', 'preparing', 'served') GROUP BY status"
    ).fetchall()
    return {
        "orders": totals["orders"],
        "revenue": totals["revenue"],
        "average": totals["revenue"] // totals["orders"] if totals["orders"] else 0,
        "by_day": [dict(r) for r in by_day],
        "top": [dict(r) for r in top],
        "open": {r["status"]: r["n"] for r in open_orders},
    }


def to_csv(rows: list[dict], columns: list[str]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()
