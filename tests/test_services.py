"""Business rules: stock, orders, statuses, reports."""

import pytest

from app import services
from app.services import OrderError


def dish_id(db, name):
    return db.execute("SELECT id FROM dishes WHERE name = ?", (name,)).fetchone()["id"]


def stock(db, name):
    return db.execute("SELECT stock FROM ingredients WHERE name = ?", (name,)).fetchone()["stock"]


def test_money_formatting():
    assert services.money(1250) == "12.50 MAD"
    assert services.money(123456) == "1 234.56 MAD"
    assert services.money(None) == "0.00 MAD"


def test_order_takes_ingredients_out_of_stock_and_prices_in_cents(db):
    beef, buns = stock(db, "Minced beef"), stock(db, "Burger bun")
    order_id = services.place_order(db, [(dish_id(db, "Cheeseburger"), 2), (dish_id(db, "Cola"), 1)])
    assert stock(db, "Minced beef") == beef - 300
    assert stock(db, "Burger bun") == buns - 2
    total = db.execute("SELECT total_cents FROM orders WHERE id = ?", (order_id,)).fetchone()[0]
    assert total == 2 * 5500 + 1500


def test_order_is_all_or_nothing(db):
    """The burger is fine but the soup is short: nothing at all may leave the stock."""
    beef = stock(db, "Minced beef")
    with pytest.raises(OrderError, match="Seafood"):
        services.place_order(db, [(dish_id(db, "Cheeseburger"), 1), (dish_id(db, "Seafood soup"), 50)])
    assert stock(db, "Minced beef") == beef
    assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_shared_ingredient_is_counted_across_dishes(db):
    """Two dishes using the same ingredient must be checked together, not one by one."""
    db.execute("UPDATE ingredients SET stock = 200 WHERE name = 'Minced beef'")
    # 1 burger (150 g) + 1 bolognese (100 g) = 250 g > 200 g, though each alone fits
    with pytest.raises(OrderError, match="Minced beef"):
        services.place_order(db, [(dish_id(db, "Cheeseburger"), 1), (dish_id(db, "Pasta bolognese"), 1)])


def test_empty_or_hidden_dish_orders_are_refused(db):
    with pytest.raises(OrderError, match="empty"):
        services.place_order(db, [(dish_id(db, "Cola"), 0)])
    db.execute("UPDATE dishes SET active = 0 WHERE name = 'Cola'")
    with pytest.raises(OrderError, match="not on the menu"):
        services.place_order(db, [(dish_id(db, "Cola"), 1)])


def test_portions_left_and_sold_out(db):
    menu = {d["name"]: d for d in services.menu(db)}
    assert menu["Panna cotta"]["portions_left"] == 0  # 100 ml cream, 150 ml a portion
    assert not menu["Panna cotta"]["available"]
    assert menu["Fresh orange juice"]["portions_left"] == 2  # 7 oranges, 3 a glass
    assert menu["Cola"]["available"]


def test_menu_filters(db):
    names = lambda **f: {d["name"] for d in services.menu(db, **f)}  # noqa: E731
    assert "Cheeseburger" not in names(vegetarian=True)
    assert names(gluten_free=True) >= {"Garden salad", "Mint tea"}
    assert not any("milk" in d["allergen_list"] for d in services.menu(db, without="milk"))


def test_status_flow_and_cancel_restores_stock(db):
    tea = stock(db, "Mint tea leaves")
    order_id = services.place_order(db, [(dish_id(db, "Mint tea"), 3)])
    assert stock(db, "Mint tea leaves") == tea - 30
    with pytest.raises(OrderError):
        services.set_status(db, order_id, "paid")  # cannot skip the kitchen
    services.set_status(db, order_id, "preparing")
    services.set_status(db, order_id, "cancelled")
    assert stock(db, "Mint tea leaves") == tea
    with pytest.raises(OrderError):
        services.set_status(db, order_id, "preparing")  # a cancelled order stays cancelled


def test_old_bills_keep_their_price(db):
    cola = dish_id(db, "Cola")
    order_id = services.place_order(db, [(cola, 1)])
    db.execute("UPDATE dishes SET price_cents = 9900 WHERE id = ?", (cola,))
    line = db.execute("SELECT unit_price_cents FROM order_items WHERE order_id = ?", (order_id,)).fetchone()
    assert line[0] == 1500


def test_report_counts_only_paid_orders(db):
    paid = services.place_order(db, [(dish_id(db, "Cola"), 2)])
    services.place_order(db, [(dish_id(db, "Cheeseburger"), 1)])  # still open
    for status in ("preparing", "served", "paid"):
        services.set_status(db, paid, status)
    report = services.report(db)
    assert report["revenue"] == 3000 and report["orders"] == 1
    assert report["top"][0]["name"] == "Cola"
    assert report["open"] == {"new": 1}


def test_low_stock_list(db):
    assert {i["name"] for i in services.low_stock(db)} == {"Seafood", "Orange", "Cream"}
