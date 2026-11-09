ALTER TABLE meals ADD COLUMN theme TEXT NOT NULL DEFAULT '';
ALTER TABLE meals ADD COLUMN servings TEXT NOT NULL DEFAULT '1';
ALTER TABLE assignments ADD COLUMN max_effort INTEGER;
ALTER TABLE assignments ADD COLUMN theme TEXT NOT NULL DEFAULT '';
ALTER TABLE assignments ADD COLUMN manual INTEGER NOT NULL DEFAULT 0 CHECK (manual IN (0,1));
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE routines (
    routine_id INTEGER PRIMARY KEY AUTOINCREMENT,
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast','lunch','dinner')),
    group_meal INTEGER NOT NULL CHECK (group_meal IN (0,1)),
    kind TEXT NOT NULL CHECK (kind IN ('meal','eating_out','leftovers')),
    max_effort INTEGER CHECK (max_effort BETWEEN 1 AND 3),
    theme TEXT NOT NULL DEFAULT '',
    UNIQUE (weekday, meal_type)
);
CREATE TABLE slot_overrides (
    plan_id INTEGER NOT NULL REFERENCES plans(plan_id),
    date TEXT NOT NULL,
    meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast','lunch','dinner')),
    eater_ids TEXT NOT NULL,
    group_meal INTEGER NOT NULL CHECK (group_meal IN (0,1)),
    kind TEXT NOT NULL CHECK (kind IN ('meal','eating_out','leftovers')),
    max_effort INTEGER CHECK (max_effort BETWEEN 1 AND 3),
    theme TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (plan_id,date,meal_type)
);
CREATE TABLE ingredients (
    ingredient_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE
);
CREATE TABLE meal_ingredients (
    meal_id INTEGER NOT NULL REFERENCES meals(meal_id),
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(ingredient_id),
    amount TEXT NOT NULL,
    unit TEXT NOT NULL,
    PRIMARY KEY (meal_id,ingredient_id,unit)
);
CREATE TABLE shopping_state (
    plan_id INTEGER PRIMARY KEY REFERENCES plans(plan_id),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    fingerprint TEXT NOT NULL
);
CREATE TABLE shopping_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(plan_id),
    source_key TEXT NOT NULL,
    ingredient_id INTEGER REFERENCES ingredients(ingredient_id),
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    amount TEXT NOT NULL,
    previous_amount TEXT,
    checked INTEGER NOT NULL DEFAULT 0 CHECK (checked IN (0,1)),
    excluded INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0,1)),
    manual INTEGER NOT NULL DEFAULT 0 CHECK (manual IN (0,1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    needs_review INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0,1)),
    UNIQUE (plan_id,source_key)
);
CREATE TABLE calendar_publications (
    calendar_key TEXT NOT NULL,
    plan_id INTEGER NOT NULL REFERENCES plans(plan_id),
    eater_id INTEGER NOT NULL REFERENCES eaters(eater_id),
    date TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    event_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    PRIMARY KEY (calendar_key,plan_id,eater_id,date,meal_type)
);
CREATE TABLE calendar_jobs (
    plan_id INTEGER PRIMARY KEY REFERENCES plans(plan_id),
    requested_revision INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
CREATE TABLE calendar_state (
    calendar_key TEXT NOT NULL,
    plan_id INTEGER NOT NULL REFERENCES plans(plan_id),
    revision INTEGER NOT NULL,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (calendar_key,plan_id)
);
