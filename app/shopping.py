"""Ingredient records and a shared shopping list derived from the household plan."""

from decimal import Decimal
import hashlib
import json
import uuid

from .household import HouseholdError, positive_id, text
from .quantities import base_quantity, quantity, unit_name


class Shopping:
    def __init__(self, database):
        self.database = database

    def _ingredient(self, conn, name):
        name = text(name, "Ingredient name")
        normalized = " ".join(name.casefold().split())
        conn.execute("INSERT OR IGNORE INTO ingredients(name,normalized_name) VALUES (?,?)", (name, normalized))
        return dict(conn.execute("SELECT * FROM ingredients WHERE normalized_name=?", (normalized,)).fetchone())

    def add_ingredient(self, name):
        with self.database.connect(write=True) as conn:
            return self._ingredient(conn, name)

    def meal_ingredients(self, meal_id):
        positive_id(meal_id)
        with self.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM meals WHERE meal_id=?", (meal_id,)).fetchone():
                raise HouseholdError("Meal not found.", 404)
            return [dict(row) for row in conn.execute("SELECT mi.*, i.name FROM meal_ingredients mi JOIN ingredients i USING(ingredient_id) WHERE meal_id=? ORDER BY i.name,mi.unit", (meal_id,))]

    def replace_ingredients(self, meal_id, entries):
        positive_id(meal_id)
        if not isinstance(entries, list):
            raise HouseholdError("Send a list of ingredient amounts.")
        with self.database.connect(write=True) as conn:
            if not conn.execute("SELECT 1 FROM meals WHERE meal_id=? AND active=1", (meal_id,)).fetchone():
                raise HouseholdError("Active meal not found.", 404)
            conn.execute("DELETE FROM meal_ingredients WHERE meal_id=?", (meal_id,))
            seen = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise HouseholdError("Each ingredient needs a name or identifier, amount, and unit.")
                if "ingredient_id" in entry:
                    identifier = positive_id(entry["ingredient_id"])
                    if not conn.execute("SELECT 1 FROM ingredients WHERE ingredient_id=?", (identifier,)).fetchone():
                        raise HouseholdError("Ingredient not found.", 404)
                else:
                    identifier = self._ingredient(conn, entry.get("name"))["ingredient_id"]
                unit = unit_name(entry.get("unit", "each"))
                key = (identifier, unit)
                if key in seen:
                    raise HouseholdError("Combine duplicate ingredient/unit rows before saving.")
                seen.add(key)
                conn.execute("INSERT INTO meal_ingredients VALUES (?,?,?,?)", (meal_id, identifier, quantity(entry.get("amount")), unit))
        return self.meal_ingredients(meal_id)

    def _sync(self, conn, plan_id):
        positive_id(plan_id)
        plan = conn.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not plan:
            raise HouseholdError("Plan not found.", 404)
        amounts = {}
        warnings = set()
        for slot in conn.execute("SELECT a.*, m.meal_description, m.servings FROM assignments a LEFT JOIN meals m USING(meal_id) WHERE plan_id=? AND kind='meal'", (plan_id,)):
            if slot["meal_id"] is None:
                warnings.add(f"No meal assigned for {slot['date']} {slot['meal_type']}.")
                continue
            rows = list(conn.execute("SELECT mi.*, i.name FROM meal_ingredients mi JOIN ingredients i USING(ingredient_id) WHERE meal_id=?", (slot["meal_id"],)))
            if not rows:
                warnings.add(f"Ingredients have not been recorded for {slot['meal_description']}.")
            for row in rows:
                amount, unit = base_quantity(row["amount"], row["unit"])
                key = (row["ingredient_id"], unit)
                if key not in amounts:
                    amounts[key] = {"name": row["name"], "amount": Decimal(0)}
                amounts[key]["amount"] += amount / Decimal(quantity(slot["servings"]))
        desired = [{"source_key": f"ingredient:{identifier}:{unit}", "ingredient_id": identifier, "name": value["name"], "unit": unit, "amount": format(value["amount"].normalize(), "f")} for (identifier, unit), value in sorted(amounts.items())]
        fingerprint = hashlib.sha256(json.dumps([desired, sorted(warnings)], sort_keys=True).encode()).hexdigest()
        state = conn.execute("SELECT * FROM shopping_state WHERE plan_id=?", (plan_id,)).fetchone()
        if not state or state["fingerprint"] != fingerprint:
            previous = {row["source_key"]: dict(row) for row in conn.execute("SELECT * FROM shopping_items WHERE plan_id=? AND manual=0", (plan_id,))}
            keys = {row["source_key"] for row in desired}
            for item in desired:
                old = previous.get(item["source_key"])
                if old is None:
                    conn.execute("INSERT INTO shopping_items(plan_id,source_key,ingredient_id,name,unit,amount) VALUES (?,?,?,?,?,?)", (plan_id, item["source_key"], item["ingredient_id"], item["name"], item["unit"], item["amount"]))
                elif old["amount"] != item["amount"] or not old["active"]:
                    conn.execute("UPDATE shopping_items SET name=?,amount=?,previous_amount=?,active=1,checked=0,excluded=0,needs_review=1 WHERE item_id=?", (item["name"], item["amount"], old["amount"], old["item_id"]))
            for key, old in previous.items():
                if key not in keys and old["active"]:
                    conn.execute("UPDATE shopping_items SET active=0 WHERE item_id=?", (old["item_id"],))
            conn.execute("INSERT INTO shopping_state VALUES (?,1,?) ON CONFLICT(plan_id) DO UPDATE SET revision=revision+1,fingerprint=excluded.fingerprint", (plan_id, fingerprint))
        state = dict(conn.execute("SELECT * FROM shopping_state WHERE plan_id=?", (plan_id,)).fetchone())
        items = []
        for row in conn.execute("SELECT * FROM shopping_items WHERE plan_id=? AND active=1 ORDER BY name COLLATE NOCASE,unit", (plan_id,)):
            item = dict(row)
            for field in ("checked", "excluded", "manual", "active", "needs_review"):
                item[field] = bool(item[field])
            items.append(item)
        return {"plan_id": plan_id, "week_start": plan["week_start"], "revision": state["revision"], "items": items, "warnings": sorted(warnings)}

    def groceries(self, plan_id):
        with self.database.connect(write=True) as conn:
            return self._sync(conn, plan_id)

    def change_item(self, plan_id, item_id, revision, changes):
        with self.database.connect(write=True) as conn:
            current = self._sync(conn, plan_id)
            if type(revision) is not int or revision != current["revision"]:
                raise HouseholdError("The shopping list changed. Reload it before saving.", 409)
            item = conn.execute("SELECT * FROM shopping_items WHERE plan_id=? AND item_id=? AND active=1", (plan_id, item_id)).fetchone()
            if not item:
                raise HouseholdError("Shopping item not found.", 404)
            if not isinstance(changes, dict) or not changes or set(changes) - {"checked", "excluded", "needs_review", "active"} or any(type(v) is not bool for v in changes.values()):
                raise HouseholdError("Choose purchased, already owned, or reviewed using boolean values.")
            if "active" in changes and not item["manual"]:
                raise HouseholdError("Mark a generated item as already owned instead of deleting its requirements.")
            if changes.get("checked") is True and "excluded" not in changes:
                changes["excluded"] = False
            if changes.get("excluded") is True and "checked" not in changes:
                changes["checked"] = False
            if changes.get("checked", bool(item["checked"])) and changes.get("excluded", bool(item["excluded"])):
                raise HouseholdError("Choose purchased or already owned, not both.")
            if changes.get("checked") or changes.get("excluded"):
                changes.setdefault("needs_review", False)
            if changes.get("needs_review") and not item["previous_amount"]:
                raise HouseholdError("This item does not have a changed quantity to review.")
            for key, value in changes.items():
                conn.execute(f"UPDATE shopping_items SET {key}=? WHERE item_id=?", (int(value), item_id))
            conn.execute("UPDATE shopping_state SET revision=revision+1 WHERE plan_id=?", (plan_id,))
            return self._sync(conn, plan_id)

    def add_item(self, plan_id, revision, name, amount="1", unit="each"):
        with self.database.connect(write=True) as conn:
            current = self._sync(conn, plan_id)
            if type(revision) is not int or revision != current["revision"]:
                raise HouseholdError("The shopping list changed. Reload it before saving.", 409)
            conn.execute("INSERT INTO shopping_items(plan_id,source_key,name,unit,amount,manual) VALUES (?,?,?,?,?,1)", (plan_id, "manual:" + uuid.uuid4().hex, text(name, "Shopping item"), unit_name(unit), quantity(amount)))
            conn.execute("UPDATE shopping_state SET revision=revision+1 WHERE plan_id=?", (plan_id,))
            return self._sync(conn, plan_id)
