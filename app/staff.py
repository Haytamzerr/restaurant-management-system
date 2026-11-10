"""Staff pages (login required): dashboard, dishes, stock, customers, orders, reports, exports."""

import sqlite3
from datetime import date

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from app import services
from app.auth import login_required
from app.db import get_db
from app.public import ALLERGENS

bp = Blueprint("staff", __name__, url_prefix="/staff")


@bp.before_request
@login_required
def require_login():
    return None


def _number(name: str, default=None, kind=float):
    try:
        return kind(request.form.get(name, "").replace(",", "."))
    except ValueError:
        return default


# ---------- dashboard ----------

@bp.route("/")
def dashboard():
    db = get_db()
    return render_template(
        "staff/dashboard.html",
        report=services.report(db),
        low=services.low_stock(db),
        recent=services.orders(db, limit=8),
        unavailable=[d for d in services.menu(db) if not d["available"]],
    )


# ---------- dishes ----------

@bp.route("/dishes")
def dishes():
    return render_template("staff/dishes.html", dishes=services.menu(get_db(), include_inactive=True))


@bp.route("/dishes/new", methods=["GET", "POST"])
@bp.route("/dishes/<int:dish_id>", methods=["GET", "POST"])
def dish_form(dish_id: int | None = None):
    db = get_db()
    dish = db.execute("SELECT * FROM dishes WHERE id = ?", (dish_id,)).fetchone() if dish_id else None
    if dish_id and dish is None:
        abort(404)
    if request.method == "POST":
        price = _number("price")
        name = request.form.get("name", "").strip()
        if not name or price is None or price < 0:
            flash("A dish needs a name and a positive price", "error")
        else:
            values = (
                name, request.form.get("description", "").strip(), round(price * 100),
                int(request.form["category_id"]), int("vegetarian" in request.form),
                int("gluten_free" in request.form), ",".join(request.form.getlist("allergens")),
                request.form.get("emoji", "🍽️").strip() or "🍽️", int("active" in request.form),
            )  # fmt: skip
            try:
                db.execute("BEGIN")
                if dish:
                    db.execute(
                        """UPDATE dishes SET name=?, description=?, price_cents=?, category_id=?,
                           vegetarian=?, gluten_free=?, allergens=?, emoji=?, active=? WHERE id=?""",
                        (*values, dish_id),
                    )
                else:
                    dish_id = db.execute(
                        """INSERT INTO dishes (name, description, price_cents, category_id, vegetarian,
                           gluten_free, allergens, emoji, active) VALUES (?,?,?,?,?,?,?,?,?)""",
                        values,
                    ).lastrowid
                # the recipe: one quantity field per ingredient, empty or 0 = not used
                db.execute("DELETE FROM recipe WHERE dish_id = ?", (dish_id,))
                for ing in db.execute("SELECT id FROM ingredients").fetchall():
                    qty = _number(f"ing_{ing['id']}", 0)
                    if qty and qty > 0:
                        db.execute("INSERT INTO recipe VALUES (?,?,?)", (dish_id, ing["id"], qty))
                db.execute("COMMIT")
                flash(f"“{name}” saved", "ok")
                return redirect(url_for("staff.dishes"))
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK")
                flash(f"A dish called “{name}” already exists", "error")
    used = {r["id"]: r["quantity"] for r in services.recipe(db, dish_id)} if dish_id else {}
    return render_template(
        "staff/dish_form.html", dish=dish, used=used, allergens=ALLERGENS,
        categories=db.execute("SELECT * FROM categories ORDER BY position").fetchall(),
        ingredients=db.execute("SELECT * FROM ingredients ORDER BY name").fetchall(),
    )  # fmt: skip


@bp.route("/dishes/<int:dish_id>/delete", methods=["POST"])
def delete_dish(dish_id: int):
    db = get_db()
    if db.execute("SELECT 1 FROM order_items WHERE dish_id = ? LIMIT 1", (dish_id,)).fetchone():
        db.execute("UPDATE dishes SET active = 0 WHERE id = ?", (dish_id,))
        flash("This dish is in past orders: it was hidden from the menu instead of deleted", "ok")
    else:
        db.execute("DELETE FROM dishes WHERE id = ?", (dish_id,))
        flash("Dish deleted", "ok")
    return redirect(url_for("staff.dishes"))


# ---------- stock ----------

@bp.route("/stock", methods=["GET", "POST"])
def stock():
    db = get_db()
    if request.method == "POST":
        name, unit = request.form.get("name", "").strip(), request.form.get("unit", "").strip()
        qty, alert = _number("stock", 0), _number("alert_level", 0)
        if not name or not unit or qty is None or qty < 0:
            flash("An ingredient needs a name, a unit and a stock of 0 or more", "error")
        else:
            try:
                db.execute("INSERT INTO ingredients (name, unit, stock, alert_level) VALUES (?,?,?,?)",
                           (name, unit, qty, alert or 0))  # fmt: skip
                flash(f"“{name}” added", "ok")
            except sqlite3.IntegrityError:
                flash(f"“{name}” already exists", "error")
        return redirect(url_for("staff.stock"))
    return render_template("staff/stock.html",
                           ingredients=db.execute("SELECT * FROM ingredients ORDER BY name").fetchall())  # fmt: skip


@bp.route("/stock/<int:ingredient_id>", methods=["POST"])
def update_stock(ingredient_id: int):
    """Restock (add a delivery) or correct the count after an inventory."""
    db = get_db()
    amount, alert = _number("amount"), _number("alert_level")
    if amount is None:
        flash("Enter a quantity", "error")
    elif request.form.get("mode") == "set":
        if amount < 0:
            flash("Stock cannot be negative", "error")
        else:
            db.execute("UPDATE ingredients SET stock = ? WHERE id = ?", (amount, ingredient_id))
    else:
        db.execute("UPDATE ingredients SET stock = MAX(0, stock + ?) WHERE id = ?", (amount, ingredient_id))
    if alert is not None and alert >= 0:
        db.execute("UPDATE ingredients SET alert_level = ? WHERE id = ?", (alert, ingredient_id))
    return redirect(url_for("staff.stock"))


# ---------- customers ----------

@bp.route("/customers", methods=["GET", "POST"])
def customers():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            db.execute("INSERT INTO customers (name, phone) VALUES (?, ?)",
                       (name, request.form.get("phone", "").strip()))  # fmt: skip
            flash(f"“{name}” added", "ok")
        return redirect(request.form.get("back") or url_for("staff.customers"))
    rows = db.execute(
        """SELECT c.*, COUNT(o.id) AS orders, COALESCE(SUM(CASE WHEN o.status = 'paid'
           THEN o.total_cents END), 0) AS spent
           FROM customers c LEFT JOIN orders o ON o.customer_id = c.id
           GROUP BY c.id ORDER BY c.name"""
    ).fetchall()
    return render_template("staff/customers.html", customers=rows)


# ---------- orders ----------

@bp.route("/orders")
def orders():
    status = request.args.get("status") or None
    return render_template("staff/orders.html", orders=services.orders(get_db(), status),
                           status=status, flow=services.STATUS_FLOW)  # fmt: skip


@bp.route("/orders/new", methods=["GET", "POST"])
def new_order():
    db = get_db()
    if request.method == "POST":
        lines = [(int(k[5:]), v) for k, v in request.form.items() if k.startswith("dish_") and v.strip()]
        try:
            order_id = services.place_order(
                db, [(d, int(q)) for d, q in lines],
                customer_id=request.form.get("customer_id", type=int),
                table_no=request.form.get("table_no", type=int),
            )  # fmt: skip
            flash(f"Order #{order_id} sent to the kitchen", "ok")
            return redirect(url_for("staff.orders"))
        except (services.OrderError, ValueError) as error:
            flash(f"Order not placed: {error}", "error")
    return render_template(
        "staff/order_form.html", dishes=services.menu(db),
        customers=db.execute("SELECT * FROM customers ORDER BY name").fetchall(),
    )  # fmt: skip


@bp.route("/orders/<int:order_id>/status", methods=["POST"])
def order_status(order_id: int):
    try:
        services.set_status(get_db(), order_id, request.form["status"])
    except services.OrderError as error:
        flash(str(error), "error")
    return redirect(request.referrer or url_for("staff.orders"))


# ---------- reports and exports ----------

@bp.route("/reports")
def reports():
    return render_template("staff/reports.html", report=services.report(get_db()))


EXPORTS = {
    "orders": ("SELECT o.id, o.created_at, o.status, o.table_no, c.name AS customer, o.total_cents "
               "FROM orders o LEFT JOIN customers c ON c.id = o.customer_id ORDER BY o.id",
               ["id", "created_at", "status", "table_no", "customer", "total_mad"]),
    "stock": ("SELECT name, unit, stock, alert_level FROM ingredients ORDER BY name",
              ["name", "unit", "stock", "alert_level"]),
    "menu": ("SELECT d.name, c.name AS category, d.price_cents, d.vegetarian, d.gluten_free, "
             "d.allergens, d.active FROM dishes d JOIN categories c ON c.id = d.category_id "
             "ORDER BY c.position, d.name",
             ["name", "category", "price_mad", "vegetarian", "gluten_free", "allergens", "active"]),
}  # fmt: skip


@bp.route("/export/<what>.csv")
def export(what: str):
    if what not in EXPORTS:
        abort(404)
    sql, columns = EXPORTS[what]
    rows = []
    for r in get_db().execute(sql):
        row = dict(r)
        for key in ("total_cents", "price_cents"):
            if key in row:
                row[key.replace("_cents", "_mad")] = f"{row.pop(key) / 100:.2f}"
        rows.append(row)
    return Response(
        services.to_csv(rows, columns), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={what}_{date.today()}.csv"},
    )  # fmt: skip
