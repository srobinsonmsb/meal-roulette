"""SQLite lifecycle and a versioned, portable household-data format."""

from contextlib import closing, contextmanager
from datetime import date
import json
from pathlib import Path
import sqlite3
import uuid

APPLICATION_ID = 0x4D52544C
SCHEMA_VERSION = 2
MEAL_TYPES = ("breakfast", "lunch", "dinner")
TABLES = {
    "settings": ("key", "value"),
    "eaters": ("eater_id", "name", "active"),
    "meals": ("meal_id", "meal_description", "meal_type", "effort_level", "active", "theme", "servings"),
    "eater_meal_preferences": ("eater_id", "meal_id"),
    "plans": ("plan_id", "week_start", "state", "revision", "meal_types", "created_at", "updated_at", "confirmed_at"),
    "assignments": ("plan_id", "eater_id", "date", "meal_type", "meal_id", "group_meal", "kind", "max_effort", "theme", "manual"),
    "routines": ("routine_id", "weekday", "meal_type", "group_meal", "kind", "max_effort", "theme"),
    "slot_overrides": ("plan_id", "date", "meal_type", "eater_ids", "group_meal", "kind", "max_effort", "theme"),
    "ingredients": ("ingredient_id", "name", "normalized_name"),
    "meal_ingredients": ("meal_id", "ingredient_id", "amount", "unit"),
    "shopping_state": ("plan_id", "revision", "fingerprint"),
    "shopping_items": ("item_id", "plan_id", "source_key", "ingredient_id", "name", "unit", "amount", "previous_amount", "checked", "excluded", "manual", "active", "needs_review"),
    "calendar_publications": ("calendar_key", "plan_id", "eater_id", "date", "meal_type", "event_id", "revision"),
    "calendar_jobs": ("plan_id", "requested_revision", "attempts", "last_error"),
    "calendar_state": ("calendar_key", "plan_id", "revision", "synced_at"),
}


class DataError(ValueError):
    """A data operation was refused without changing the household's records."""


class Database:
    def __init__(self, path):
        if str(path) == ":memory:":
            raise DataError("Use a database file so household data survives restart.")
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect(write=True) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            identity = conn.execute("PRAGMA application_id").fetchone()[0]
            if identity == 0 and version == 0:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                    raise DataError("The selected database is not a Meal Roulette database.")
                for statement in Path(__file__).with_name("schema.sql").read_text().split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
                version = 1
                conn.execute("PRAGMA user_version=1")
            elif identity != APPLICATION_ID or not 1 <= version <= SCHEMA_VERSION:
                raise DataError("Unsupported database format/version; upgrade before opening it.")
            if version < 2:
                migration = Path(__file__).with_name("migrations") / "002-planning-and-shopping.sql"
                for statement in migration.read_text().split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("INSERT INTO settings VALUES ('instance_id', ?)", (uuid.uuid4().hex,))
                conn.execute("PRAGMA user_version=2")
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def connect(self, *, write=False):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def export_data(self):
        with self.connect() as conn:
            conn.execute("BEGIN")
            data = {}
            for table in TABLES:
                rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                if table == "plans":
                    for row in rows:
                        row["meal_types"] = json.loads(row["meal_types"])
                if table == "slot_overrides":
                    for row in rows:
                        row["eater_ids"] = json.loads(row["eater_ids"])
                data[table] = rows
            return {"format": "meal-roulette", "version": SCHEMA_VERSION, "data": data}

    def import_data(self, document):
        if isinstance(document, dict) and document.get("format") == "meal-roulette-postgres":
            from .legacy import convert_export

            document = convert_export(document)
        if not isinstance(document, dict) or document.get("format") != "meal-roulette" or type(document.get("version")) is not int or not 1 <= document["version"] <= SCHEMA_VERSION:
            raise DataError("Expected a supported Meal Roulette data export.")
        if document["version"] == 1:
            from copy import deepcopy

            document = deepcopy(document)
            source = document.get("data")
            legacy_tables = {"eaters", "meals", "eater_meal_preferences", "plans", "assignments"}
            if not isinstance(source, dict) or set(source) != legacy_tables:
                raise DataError("The version 1 export must contain every household data table.")
            try:
                for row in source["meals"]:
                    row.update(theme="", servings="1")
                for row in source["assignments"]:
                    row.update(max_effort=None, theme="", manual=0)
                for table in set(TABLES) - legacy_tables:
                    source[table] = []
                source["settings"] = [{"key": "instance_id", "value": uuid.uuid4().hex}]
            except (TypeError, AttributeError):
                raise DataError("Invalid version 1 export rows.") from None
        data = document.get("data")
        if not isinstance(data, dict) or set(data) != set(TABLES):
            raise DataError("The export must contain every household data table.")
        with self.connect(write=True) as conn:
            if any(conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in TABLES if table != "settings"):
                raise DataError("Import requires an empty installation; existing data was not changed.")
            try:
                conn.execute("DELETE FROM settings")
                for table, columns in TABLES.items():
                    if not isinstance(data[table], list):
                        raise DataError(f"Invalid rows for {table}.")
                    for row in data[table]:
                        if not isinstance(row, dict) or set(row) != set(columns):
                            raise DataError(f"Invalid columns for {table}.")
                        values = dict(row)
                        for column, value in values.items():
                            if column.endswith("_id") or column == "revision":
                                if value is None and ((column == "meal_id" and table == "assignments") or (column == "ingredient_id" and table == "shopping_items")):
                                    continue
                                if type(value) is not int or not 1 <= value <= 2**63 - 1:
                                    raise DataError(f"Invalid identifier in {table}.")
                            elif column in ("active", "group_meal", "manual", "checked", "excluded", "needs_review"):
                                if type(value) not in (int, bool) or value not in (0, 1):
                                    raise DataError(f"Invalid boolean in {table}.")
                            elif column in ("effort_level", "max_effort", "weekday", "requested_revision", "attempts"):
                                if value is not None and (type(value) is not int or not -2**63 <= value <= 2**63 - 1):
                                    raise DataError("Effort must be an integer or null.")
                            elif column not in ("meal_types", "eater_ids") and value is not None and not isinstance(value, str):
                                raise DataError(f"Invalid text value in {table}.")
                        if table == "plans":
                            week = date.fromisoformat(values["week_start"])
                            types = values["meal_types"]
                            if week.weekday() != 0 or week.isoformat() != values["week_start"] or not isinstance(types, list) or not types or len(set(types)) != len(types) or any(t not in MEAL_TYPES for t in types):
                                raise DataError("Invalid plan week or meal coverage.")
                            values["meal_types"] = json.dumps(types)
                        if table == "slot_overrides":
                            if not isinstance(values["eater_ids"], list) or any(type(x) is not int or x < 1 for x in values["eater_ids"]):
                                raise DataError("Invalid diners in a weekly exception.")
                            values["eater_ids"] = json.dumps(values["eater_ids"])
                        if table == "meals":
                            from .quantities import quantity

                            quantity(values["servings"])
                        if table == "meal_ingredients":
                            from .quantities import quantity, unit_name

                            quantity(values["amount"])
                            unit_name(values["unit"])
                        if table == "shopping_items":
                            from decimal import Decimal, InvalidOperation

                            try:
                                for field in ("amount", "previous_amount"):
                                    if values[field] is not None:
                                        amount = Decimal(values[field])
                                        if not amount.is_finite() or amount <= 0 or abs(amount.adjusted()) > 60:
                                            raise ValueError("Invalid shopping quantity")
                            except InvalidOperation:
                                raise DataError("Invalid shopping quantity.") from None
                        if table == "ingredients" and values["normalized_name"] != " ".join(values["name"].casefold().split()):
                            raise DataError("Ingredient identity does not match its name.")
                        if "max_effort" in values and values["max_effort"] is not None and values["max_effort"] not in (1, 2, 3):
                            raise DataError("Maximum effort must be 1, 2, 3, or null.")
                        conn.execute(
                            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                            [values[column] for column in columns],
                        )
                for row in conn.execute("SELECT a.date, a.meal_type, p.week_start, p.meal_types FROM assignments a JOIN plans p USING(plan_id)"):
                    offset = (date.fromisoformat(row["date"]) - date.fromisoformat(row["week_start"])).days
                    if not 0 <= offset <= 6 or row["meal_type"] not in json.loads(row["meal_types"]):
                        raise DataError("An assignment falls outside its plan's week or meal coverage.")
                identity = conn.execute("SELECT value FROM settings WHERE key='instance_id'").fetchone()
                if not identity or len(identity[0]) != 32 or any(c not in '0123456789abcdef' for c in identity[0]):
                    raise DataError("The export is missing its household installation identity.")
            except (sqlite3.Error, TypeError, ValueError) as error:
                raise DataError(f"Invalid export: {error}") from error

    def backup(self, destination):
        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation makes a typo safe: existing files are never overwritten.
        with destination.open("xb"):
            pass
        try:
            with self.connect() as source, closing(sqlite3.connect(destination)) as target:
                source.backup(target)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    @staticmethod
    def restore_to_new(source, destination):
        source = Path(source).expanduser().resolve()
        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as backup:
            if backup.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID or not 1 <= backup.execute("PRAGMA user_version").fetchone()[0] <= SCHEMA_VERSION:
                raise DataError("The backup is not a supported Meal Roulette database.")
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or backup.execute("PRAGMA foreign_key_check").fetchone():
                raise DataError("The backup failed integrity validation.")
            with destination.open("xb"):
                pass
            try:
                with closing(sqlite3.connect(destination)) as target:
                    backup.backup(target)
            except Exception:
                destination.unlink(missing_ok=True)
                raise
