-- Restaurant Management System schema (SQLite).
-- Prices are stored in cents (integers): floats would turn 12.10 + 0.20 into 12.299999...

DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS recipe;
DROP TABLE IF EXISTS ingredients;
DROP TABLE IF EXISTS dishes;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE categories (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE dishes (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    category_id INTEGER NOT NULL REFERENCES categories (id),
    vegetarian  INTEGER NOT NULL DEFAULT 0,
    gluten_free INTEGER NOT NULL DEFAULT 0,
    allergens   TEXT NOT NULL DEFAULT '',      -- comma separated: "gluten,milk"
    emoji       TEXT NOT NULL DEFAULT '🍽️',
    active      INTEGER NOT NULL DEFAULT 1     -- hidden from the menu when 0
);

CREATE TABLE ingredients (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    unit        TEXT NOT NULL,                  -- g, ml, piece
    stock       REAL NOT NULL DEFAULT 0 CHECK (stock >= 0),
    alert_level REAL NOT NULL DEFAULT 0         -- warn when stock falls below this
);

-- How much of each ingredient one portion of a dish uses
CREATE TABLE recipe (
    dish_id       INTEGER NOT NULL REFERENCES dishes (id) ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients (id) ON DELETE CASCADE,
    quantity      REAL NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (dish_id, ingredient_id)
);

CREATE TABLE customers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers (id) ON DELETE SET NULL,
    table_no    INTEGER,
    status      TEXT NOT NULL DEFAULT 'new'
                CHECK (status IN ('new', 'preparing', 'served', 'paid', 'cancelled')),
    total_cents INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- The price is copied into the order line: changing the menu later must not change old bills
CREATE TABLE order_items (
    id               INTEGER PRIMARY KEY,
    order_id         INTEGER NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    dish_id          INTEGER NOT NULL REFERENCES dishes (id),
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL
);

CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_orders_created ON orders (created_at);
CREATE INDEX idx_items_order ON order_items (order_id);
