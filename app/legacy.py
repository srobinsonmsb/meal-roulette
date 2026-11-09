"""Read-only export of the original PostgreSQL household and conversion to v1."""

from datetime import date, datetime, timedelta, timezone
import os

from .db import DataError, MEAL_TYPES


def export_postgres():
    try:
        import psycopg2
    except ImportError:
        raise DataError("Install app/requirements-migration.txt to export PostgreSQL data.") from None
    connection = None
    try:
        connection = psycopg2.connect(
            dbname=os.environ.get("DB_NAME"), user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD"), host=os.environ.get("DB_HOST"),
            port=os.environ.get("DB_PORT"),
        )
        connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with connection.cursor() as cursor:
            tables = {}
            for table, columns in {
                "eaters": ("eater_id", "name"),
                "meals": ("meal_id", "meal_description", "meal_type", "effort_level"),
                "eater_meal_preferences": ("eater_id", "meal_id"),
                "meal_schedule": ("date", "group_meal", "meal_type", "meal_id", "eater_id", "eat_out"),
            }.items():
                cursor.execute(f"SELECT {', '.join(columns)} FROM {table}")
                tables[table] = [dict(zip(columns, row)) for row in cursor.fetchall()]
            for row in tables["meal_schedule"]:
                row["date"] = row["date"].isoformat()
            return {
                "format": "meal-roulette-postgres", "version": 1,
                "exported_at": datetime.now(timezone.utc).isoformat(), "data": tables,
            }
    except psycopg2.Error:
        raise DataError("PostgreSQL export failed. Check the local DB_* configuration and source schema.") from None
    finally:
        if connection:
            connection.close()


def convert_export(document):
    try:
        if type(document["version"]) is not int or document["version"] != 1:
            raise ValueError("unsupported version")
        source = document["data"]
        if set(source) != {"eaters", "meals", "eater_meal_preferences", "meal_schedule"}:
            raise ValueError("missing legacy tables")
        result = {
            "eaters": [dict(row, active=1) for row in source["eaters"]],
            "meals": [dict(row, active=1) for row in source["meals"]],
            "eater_meal_preferences": source["eater_meal_preferences"],
            "plans": [], "assignments": [],
        }
        weeks = {}
        now = document.get("exported_at", datetime.now(timezone.utc).isoformat())
        for row in sorted(source["meal_schedule"], key=lambda item: item["date"]):
            day = date.fromisoformat(row["date"])
            monday = (day - timedelta(days=day.weekday())).isoformat()
            if monday not in weeks:
                weeks[monday] = {
                    "plan_id": len(weeks) + 1, "week_start": monday,
                    "state": "confirmed", "revision": 1, "meal_types": [],
                    "created_at": now, "updated_at": now, "confirmed_at": now,
                }
            plan = weeks[monday]
            if row["meal_type"] not in plan["meal_types"]:
                plan["meal_types"].append(row["meal_type"])
            result["assignments"].append({
                "plan_id": plan["plan_id"], "eater_id": row["eater_id"],
                "date": row["date"], "meal_type": row["meal_type"], "meal_id": row["meal_id"],
                "group_meal": int(bool(row["group_meal"])),
                "kind": "eating_out" if row["eat_out"] else "meal",
            })
        for plan in weeks.values():
            plan["meal_types"] = [kind for kind in MEAL_TYPES if kind in plan["meal_types"]]
            result["plans"].append(plan)
        return {"format": "meal-roulette", "version": 1, "data": result}
    except (KeyError, TypeError, ValueError) as error:
        raise DataError(f"Invalid legacy PostgreSQL export: {error}") from error
