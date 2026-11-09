"""A household's meal collection and durable weekly-plan operations."""

from datetime import date, datetime, timedelta, timezone
import json

from .db import DataError, MEAL_TYPES
from .config import build_weekly_schedule
from .scheduler import choose_meal, distinct_dinners, eligible_meals


class HouseholdError(DataError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def parse_week(value):
    try:
        week = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HouseholdError("Choose a week using its Monday date (YYYY-MM-DD).") from None
    if week.weekday() != 0:
        raise HouseholdError("The start of a plan must be a Monday.")
    return week


def parse_meal_types(values):
    if not isinstance(values, list) or not values or any(v not in MEAL_TYPES for v in values) or len(set(values)) != len(values):
        raise HouseholdError("Choose distinct mealtimes: breakfast, lunch, dinner.")
    return [value for value in MEAL_TYPES if value in values]


def positive_id(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise HouseholdError("Expected a positive integer identifier.")
    return value


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise HouseholdError(f"{label} is required.")
    return value.strip()


def effort(value):
    if value is not None and (type(value) is not int or not 1 <= value <= 3):
        raise HouseholdError("Effort must be 1 (quick), 2 (moderate), 3 (involved), or null.")
    return value


def theme_name(value):
    if not isinstance(value, str):
        raise HouseholdError("A theme must be text.")
    return " ".join(value.split())


def pattern(data):
    group = data.get("group_meal", True)
    kind = data.get("kind", "meal")
    if type(group) is not bool or kind not in ("meal", "eating_out", "leftovers"):
        raise HouseholdError("Choose shared/solo planning and a valid dinner label.")
    return {"group_meal": int(group), "kind": kind, "max_effort": effort(data.get("max_effort")), "theme": theme_name(data.get("theme", ""))}


class Household:
    def __init__(self, database):
        self.database = database

    def collection(self):
        with self.database.connect() as conn:
            return {
                "eaters": [dict(row) for row in conn.execute("SELECT * FROM eaters ORDER BY eater_id")],
                "meals": [dict(row) for row in conn.execute("SELECT * FROM meals ORDER BY meal_id")],
                "preferences": [dict(row) for row in conn.execute("SELECT * FROM eater_meal_preferences ORDER BY eater_id, meal_id")],
                "routines": [dict(row) for row in conn.execute("SELECT * FROM routines ORDER BY weekday, meal_type")],
                "ingredients": [dict(row) for row in conn.execute("SELECT * FROM ingredients ORDER BY name")],
            }

    def add_eater(self, name):
        name = text(name, "Name")
        with self.database.connect(write=True) as conn:
            eater_id = conn.execute("INSERT INTO eaters(name) VALUES (?)", (name,)).lastrowid
            return {"eater_id": eater_id, "name": name, "active": 1}

    def add_meal(self, description, meal_type, effort_level=None, theme="", servings="1"):
        from .quantities import quantity

        description = text(description, "Meal name")
        effort_level = effort(effort_level)
        theme = theme_name(theme)
        servings = quantity(servings)
        if meal_type not in MEAL_TYPES:
            raise HouseholdError("Choose breakfast, lunch, or dinner.")
        with self.database.connect(write=True) as conn:
            if conn.execute("SELECT 1 FROM meals WHERE lower(meal_description)=lower(?) AND meal_type=? AND active=1", (description, meal_type)).fetchone():
                raise HouseholdError("That meal already exists.", 409)
            meal_id = conn.execute("INSERT INTO meals(meal_description, meal_type, effort_level, theme, servings) VALUES (?, ?, ?, ?, ?)", (description, meal_type, effort_level, theme, servings)).lastrowid
            return dict(conn.execute("SELECT * FROM meals WHERE meal_id=?", (meal_id,)).fetchone())

    def edit_meal(self, meal_id, data):
        from .quantities import quantity

        positive_id(meal_id)
        if not isinstance(data, dict) or not data or set(data) - {"meal_description", "meal_type", "effort_level", "theme", "servings", "active"}:
            raise HouseholdError("Choose meal name, mealtime, effort, theme, servings, or archive status to change.")
        with self.database.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM meals WHERE meal_id=?", (meal_id,)).fetchone()
            if not row:
                raise HouseholdError("Meal not found.", 404)
            values = dict(row)
            values.update(data)
            values["meal_description"] = text(values["meal_description"], "Meal name")
            if "effort_level" in data:
                values["effort_level"] = effort(values["effort_level"])
            values["theme"] = theme_name(values["theme"])
            values["servings"] = quantity(values["servings"])
            if values["meal_type"] not in MEAL_TYPES or values["active"] not in (0, 1):
                raise HouseholdError("Invalid mealtime or archive status.")
            conn.execute("UPDATE meals SET meal_description=?, meal_type=?, effort_level=?, theme=?, servings=?, active=? WHERE meal_id=?", [values[k] for k in ("meal_description", "meal_type", "effort_level", "theme", "servings", "active", "meal_id")])
            return values

    def save_routine(self, weekday, meal_type, data):
        if type(weekday) is not int or not 0 <= weekday <= 6 or meal_type not in MEAL_TYPES:
            raise HouseholdError("Choose a weekday from 0 (Monday) to 6 (Sunday) and a mealtime.")
        values = pattern(data)
        with self.database.connect(write=True) as conn:
            conn.execute("""INSERT INTO routines(weekday,meal_type,group_meal,kind,max_effort,theme) VALUES (?,?,?,?,?,?)
                ON CONFLICT(weekday,meal_type) DO UPDATE SET group_meal=excluded.group_meal,kind=excluded.kind,max_effort=excluded.max_effort,theme=excluded.theme""",
                (weekday, meal_type, values["group_meal"], values["kind"], values["max_effort"], values["theme"]))
            return dict(conn.execute("SELECT * FROM routines WHERE weekday=? AND meal_type=?", (weekday, meal_type)).fetchone())

    def remove_routine(self, weekday, meal_type):
        with self.database.connect(write=True) as conn:
            conn.execute("DELETE FROM routines WHERE weekday=? AND meal_type=?", (weekday, meal_type))

    def preference(self, eater_id, meal_id, *, remove=False):
        positive_id(eater_id)
        positive_id(meal_id)
        with self.database.connect(write=True) as conn:
            if not conn.execute("SELECT 1 FROM eaters WHERE eater_id=? AND active=1", (eater_id,)).fetchone() or not conn.execute("SELECT 1 FROM meals WHERE meal_id=? AND active=1", (meal_id,)).fetchone():
                raise HouseholdError("Choose an active household member and meal.", 404)
            if remove:
                conn.execute("DELETE FROM eater_meal_preferences WHERE eater_id=? AND meal_id=?", (eater_id, meal_id))
            else:
                conn.execute("INSERT OR IGNORE INTO eater_meal_preferences VALUES (?, ?)", (eater_id, meal_id))

    def archive(self, kind, identifier):
        positive_id(identifier)
        table, key = {"eaters": ("eaters", "eater_id"), "meals": ("meals", "meal_id")}[kind]
        with self.database.connect(write=True) as conn:
            result = conn.execute(f"UPDATE {table} SET active=0 WHERE {key}=?", (identifier,))
            if not result.rowcount:
                raise HouseholdError("Record not found.", 404)

    def plans(self):
        with self.database.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT plan_id, week_start, state, revision FROM plans ORDER BY week_start DESC")]

    def plan(self, plan_id):
        with self.database.connect() as conn:
            conn.execute("BEGIN")
            return self._plan(conn, plan_id)

    def _plan(self, conn, plan_id):
        positive_id(plan_id)
        plan = conn.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not plan:
            raise HouseholdError("Plan not found.", 404)
        result = dict(plan)
        result["meal_types"] = json.loads(result["meal_types"])
        result["overrides"] = [dict(row) for row in conn.execute("SELECT * FROM slot_overrides WHERE plan_id=?", (plan_id,))]
        for row in result["overrides"]:
            row["eater_ids"] = json.loads(row["eater_ids"])
        job = conn.execute("SELECT requested_revision, attempts, last_error FROM calendar_jobs WHERE plan_id=?", (plan_id,)).fetchone()
        result["calendar_job"] = dict(job) if job else None
        result["calendar_state"] = [dict(row) for row in conn.execute("SELECT calendar_key,revision,synced_at FROM calendar_state WHERE plan_id=?", (plan_id,))]
        result["assignments"] = []
        for row in conn.execute(
            """SELECT a.*, e.name AS eater_name, m.meal_description AS meal_name
               FROM assignments a JOIN eaters e USING(eater_id)
               LEFT JOIN meals m USING(meal_id) WHERE plan_id=?
               ORDER BY date, CASE a.meal_type WHEN 'breakfast' THEN 1 WHEN 'lunch' THEN 2 ELSE 3 END, eater_id""",
            (plan_id,),
        ):
            assignment = dict(row)
            assignment["group_meal"] = bool(assignment["group_meal"])
            assignment["reason"] = "No eligible meal under the preference lists, weekly variety, effort and theme rules. Unknown effort is excluded when an effort limit applies." if assignment["kind"] == "meal" and assignment["meal_id"] is None else None
            result["assignments"].append(assignment)
        return result

    def create_plan(self, week_start, meal_types=None):
        week = parse_week(week_start)
        meal_types = parse_meal_types(["dinner"] if meal_types is None else meal_types)
        with self.database.connect(write=True) as conn:
            if conn.execute("SELECT 1 FROM plans WHERE week_start=?", (week.isoformat(),)).fetchone():
                raise HouseholdError("A plan already exists for this week. Open it to make changes.", 409)
            if not conn.execute("SELECT 1 FROM eaters WHERE active=1").fetchone():
                raise HouseholdError("Add a household member before generating a plan.")
            now = timestamp()
            plan_id = conn.execute(
                "INSERT INTO plans(week_start,state,revision,meal_types,created_at,updated_at) VALUES (?,'draft',1,?,?,?)",
                (week.isoformat(), json.dumps(meal_types), now, now),
            ).lastrowid
            self._generate(conn, plan_id, week, meal_types)
            return self._plan(conn, plan_id)

    def _generate(self, conn, plan_id, week, meal_types):
        eaters = [row[0] for row in conn.execute("SELECT eater_id FROM eaters WHERE active=1 ORDER BY eater_id")]
        used_dinners = {row[0] for row in conn.execute("SELECT meal_id FROM assignments WHERE plan_id=? AND meal_type='dinner' AND kind='meal' AND meal_id IS NOT NULL", (plan_id,))}
        weekly_schedule = build_weekly_schedule()
        routines = {(row["weekday"], row["meal_type"]): dict(row) for row in conn.execute("SELECT * FROM routines")}
        overrides = {(row["date"], row["meal_type"]): dict(row) for row in conn.execute("SELECT * FROM slot_overrides WHERE plan_id=?", (plan_id,))}
        requests = []
        for offset in range(7):
            day = week + timedelta(days=offset)
            for meal_type in meal_types:
                rules = {"group_meal": int(weekly_schedule[(day.strftime("%A"), meal_type)]), "kind": "meal", "max_effort": None, "theme": ""}
                rules.update(routines.get((day.weekday(), meal_type), {}))
                override = overrides.get((day.isoformat(), meal_type))
                if override:
                    rules.update(override)
                diners = json.loads(override["eater_ids"]) if override else eaters
                existing = {r["eater_id"]: dict(r) for r in conn.execute("SELECT * FROM assignments WHERE plan_id=? AND date=? AND meal_type=?", (plan_id, day.isoformat(), meal_type))}
                targets = [e for e in diners if e not in existing]
                fixed = {r["meal_id"] for r in existing.values() if r["kind"] == "meal" and r["meal_id"] is not None}
                groups = [targets] if rules["group_meal"] else [[e] for e in targets]
                for group in groups:
                    if not group:
                        continue
                    required = next(iter(fixed)) if rules["group_meal"] and len(fixed) == 1 else None
                    excluded = (used_dinners - ({required} if required else set())) if meal_type == "dinner" else set()
                    candidates = eligible_meals(conn, group, meal_type, excluded, rules["max_effort"], rules["theme"], required) if rules["kind"] == "meal" and not (rules["group_meal"] and len(fixed) > 1) else []
                    requests.append({"day": day.isoformat(), "meal_type": meal_type, "diners": group, "rules": rules, "required": required, "candidates": candidates})
        options = {index: row["candidates"] for index, row in enumerate(requests) if row["meal_type"] == "dinner" and row["required"] is None}
        matches = distinct_dinners(options)
        for index, request in enumerate(requests):
            rules = request["rules"]
            candidates = request["candidates"]
            if request["required"] is not None:
                meal_id = request["required"] if request["required"] in candidates else None
            elif request["meal_type"] == "dinner":
                meal_id = matches.get(index)
            else:
                import random

                meal_id = random.choice(candidates) if candidates else None
            for eater_id in request["diners"]:
                conn.execute(
                    "INSERT INTO assignments(plan_id,eater_id,date,meal_type,meal_id,group_meal,kind,max_effort,theme) VALUES (?,?,?,?,?,?,?,?,?)",
                    (plan_id, eater_id, request["day"], request["meal_type"], meal_id, int(rules["group_meal"]), rules["kind"], rules["max_effort"], rules["theme"]),
                )

    def _check_revision(self, conn, plan_id, revision):
        positive_id(plan_id)
        plan = conn.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not plan:
            raise HouseholdError("Plan not found.", 404)
        if type(revision) is not int or revision < 1:
            raise HouseholdError("Send the plan revision with each change.")
        if plan["revision"] != revision:
            raise HouseholdError("The plan changed on another device. Reload it before saving.", 409)
        return plan

    def _bump(self, conn, plan_id):
        conn.execute("UPDATE plans SET revision=revision+1, updated_at=? WHERE plan_id=?", (timestamp(), plan_id))
        if conn.execute("SELECT 1 FROM calendar_state WHERE plan_id=? LIMIT 1", (plan_id,)).fetchone():
            conn.execute("""INSERT INTO calendar_jobs(plan_id,requested_revision) SELECT plan_id,revision FROM plans WHERE plan_id=? AND state='confirmed'
                ON CONFLICT(plan_id) DO UPDATE SET requested_revision=excluded.requested_revision,attempts=0,last_error=NULL""", (plan_id,))

    def confirm(self, plan_id, revision):
        with self.database.connect(write=True) as conn:
            self._check_revision(conn, plan_id, revision)
            conn.execute("UPDATE plans SET state='confirmed', confirmed_at=COALESCE(confirmed_at, ?) WHERE plan_id=?", (timestamp(), plan_id))
            self._bump(conn, plan_id)
            return self._plan(conn, plan_id)

    def regenerate(self, plan_id, revision):
        with self.database.connect(write=True) as conn:
            plan = self._check_revision(conn, plan_id, revision)
            if plan["state"] != "draft":
                raise HouseholdError("A confirmed plan cannot be regenerated. Edit its individual meals.")
            if not conn.execute("SELECT 1 FROM eaters WHERE active=1").fetchone():
                raise HouseholdError("Add a household member before generating a plan.")
            conn.execute("DELETE FROM assignments WHERE plan_id=? AND manual=0", (plan_id,))
            self._generate(conn, plan_id, date.fromisoformat(plan["week_start"]), json.loads(plan["meal_types"]))
            self._bump(conn, plan_id)
            return self._plan(conn, plan_id)

    def change_assignment(self, plan_id, eater_id, day, meal_type, revision, action, meal_id=None):
        positive_id(eater_id)
        with self.database.connect(write=True) as conn:
            self._check_revision(conn, plan_id, revision)
            slot = conn.execute(
                "SELECT * FROM assignments WHERE plan_id=? AND eater_id=? AND date=? AND meal_type=?",
                (plan_id, eater_id, day, meal_type),
            ).fetchone()
            if not slot:
                raise HouseholdError("Meal assignment not found.", 404)
            if action in ("eating_out", "leftovers"):
                conn.execute("UPDATE assignments SET kind=?, manual=1 WHERE plan_id=? AND eater_id=? AND date=? AND meal_type=?", (action, plan_id, eater_id, day, meal_type))
            elif action in ("meal", "reroll"):
                targets = [eater_id]
                if slot["group_meal"]:
                    targets = [row[0] for row in conn.execute(
                        "SELECT eater_id FROM assignments WHERE plan_id=? AND date=? AND meal_type=? AND group_meal=1 AND (kind='meal' OR eater_id=?)",
                        (plan_id, day, meal_type, eater_id),
                    )]
                if action == "reroll":
                    excluded = {
                        row["meal_id"] for row in conn.execute(
                            "SELECT eater_id, date, meal_id FROM assignments WHERE plan_id=? AND meal_type='dinner' AND kind='meal' AND meal_id IS NOT NULL",
                            (plan_id,),
                        ) if not (row["date"] == day and row["eater_id"] in targets)
                    } if meal_type == "dinner" else set()
                    excluded.add(slot["meal_id"])
                    meal_id = choose_meal(conn, targets, meal_type, excluded, slot["max_effort"], slot["theme"])
                    if meal_id is None:
                        raise HouseholdError("No alternative meal satisfies the current preferences and weekly variety rule.", 409)
                else:
                    positive_id(meal_id)
                    if not conn.execute("SELECT 1 FROM meals WHERE meal_id=? AND active=1 AND meal_type=?", (meal_id, meal_type)).fetchone():
                        raise HouseholdError("Choose an active meal for this mealtime.")
                for target in targets:
                    conn.execute("UPDATE assignments SET kind='meal', meal_id=?, manual=1 WHERE plan_id=? AND eater_id=? AND date=? AND meal_type=?", (meal_id, plan_id, target, day, meal_type))
            else:
                raise HouseholdError("Choose meal, reroll, eating_out, or leftovers.")
            self._bump(conn, plan_id)
            return self._plan(conn, plan_id)

    def override_slot(self, plan_id, day, meal_type, revision, data):
        rules = pattern(data)
        diners = data.get("eater_ids")
        if not isinstance(diners, list) or any(type(e) is not int or e < 1 for e in diners) or len(set(diners)) != len(diners):
            raise HouseholdError("Choose a distinct list of household members for this dinner.")
        try:
            chosen_date = date.fromisoformat(day)
        except (TypeError, ValueError):
            raise HouseholdError("Choose a valid dinner date.") from None
        with self.database.connect(write=True) as conn:
            plan = self._check_revision(conn, plan_id, revision)
            if not 0 <= (chosen_date - date.fromisoformat(plan["week_start"])).days <= 6 or meal_type not in json.loads(plan["meal_types"]):
                raise HouseholdError("Choose a date and mealtime covered by this plan.")
            active = {r[0] for r in conn.execute("SELECT eater_id FROM eaters WHERE active=1")}
            if set(diners) - active:
                raise HouseholdError("Choose active household members.")
            conn.execute("""INSERT INTO slot_overrides VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(plan_id,date,meal_type)
                DO UPDATE SET eater_ids=excluded.eater_ids,group_meal=excluded.group_meal,kind=excluded.kind,max_effort=excluded.max_effort,theme=excluded.theme""",
                (plan_id, day, meal_type, json.dumps(diners), rules["group_meal"], rules["kind"], rules["max_effort"], rules["theme"]))
            conn.execute("DELETE FROM assignments WHERE plan_id=? AND date=? AND meal_type=?", (plan_id, day, meal_type))
            self._generate(conn, plan_id, date.fromisoformat(plan["week_start"]), json.loads(plan["meal_types"]))
            self._bump(conn, plan_id)
            return self._plan(conn, plan_id)
