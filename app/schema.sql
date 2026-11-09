CREATE TABLE eaters (
    eater_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
CREATE TABLE meals (
    meal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_description TEXT NOT NULL CHECK (length(trim(meal_description)) > 0),
    meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner')),
    effort_level INTEGER,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
CREATE TABLE eater_meal_preferences (
    eater_id INTEGER NOT NULL REFERENCES eaters(eater_id),
    meal_id INTEGER NOT NULL REFERENCES meals(meal_id),
    PRIMARY KEY (eater_id, meal_id)
);
CREATE TABLE plans (
    plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ('draft', 'confirmed')),
    revision INTEGER NOT NULL CHECK (revision > 0),
    meal_types TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_at TEXT
);
CREATE TABLE assignments (
    plan_id INTEGER NOT NULL REFERENCES plans(plan_id),
    eater_id INTEGER NOT NULL REFERENCES eaters(eater_id),
    date TEXT NOT NULL,
    meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner')),
    meal_id INTEGER REFERENCES meals(meal_id),
    group_meal INTEGER NOT NULL CHECK (group_meal IN (0, 1)),
    kind TEXT NOT NULL CHECK (kind IN ('meal', 'eating_out', 'leftovers')),
    PRIMARY KEY (plan_id, eater_id, date, meal_type)
);
CREATE INDEX assignment_meals ON assignments(meal_id);
