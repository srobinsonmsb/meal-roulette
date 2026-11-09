"""One-way Calendar publishing with stable event identities and durable retries."""

from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo

from .household import HouseholdError

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def get_calendar_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    folder = Path(os.environ.get("MEAL_ROULETTE_GOOGLE_DIR", Path(__file__).parent))
    token_path = folder / "token.json"
    creds_path = folder / "credentials.json"
    creds = Credentials.from_authorized_user_file(token_path, SCOPES) if token_path.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif os.environ.get("MEAL_ROULETTE_GOOGLE_AUTHORIZE") == "true":
            creds = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES).run_local_server(port=8080)
        else:
            raise RuntimeError("Authorize Google Calendar locally before enabling background sync.")
        temporary = token_path.with_suffix(".tmp")
        temporary.write_text(creds.to_json())
        temporary.chmod(0o600)
        temporary.replace(token_path)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


class GoogleCalendar:
    def __init__(self):
        self.key = os.environ["GOOGLE_CALENDAR_ID"]
        self.service = get_calendar_service()

    def upsert(self, event_id, event):
        resource = self.service.events()
        try:
            resource.update(calendarId=self.key, eventId=event_id, body=event).execute()
        except Exception as error:
            if getattr(getattr(error, "resp", None), "status", None) not in (404, 410):
                raise
            try:
                resource.insert(calendarId=self.key, body=dict(event, id=event_id)).execute()
            except Exception as insert_error:
                if getattr(getattr(insert_error, "resp", None), "status", None) != 409:
                    raise
                resource.update(calendarId=self.key, eventId=event_id, body=event).execute()

    def delete(self, event_id):
        try:
            self.service.events().delete(calendarId=self.key, eventId=event_id).execute()
        except Exception as error:
            if getattr(getattr(error, "resp", None), "status", None) not in (404, 410):
                raise


def entries_for_plan(plan, installation_id, calendar_key):
    zone = os.environ.get("MEAL_ROULETTE_TIMEZONE", "America/Chicago")
    ZoneInfo(zone)
    times = {"breakfast": ("07:00:00", "07:30:00"), "lunch": ("12:00:00", "12:30:00"), "dinner": ("18:00:00", "18:30:00")}
    entries = {}
    for slot in plan["assignments"]:
        if slot["kind"] == "meal" and slot["meal_id"] is None:
            continue
        label = {"eating_out": "Eating out", "leftovers": "Leftovers"}.get(slot["kind"], slot["meal_name"])
        start, end = times[slot["meal_type"]]
        key = (slot["eater_id"], slot["date"], slot["meal_type"])
        event_id = uuid.uuid5(uuid.UUID(installation_id), f"{calendar_key}:{key[0]}:{key[1]}:{key[2]}").hex
        entries[key] = (event_id, {
            "summary": f"{label} - {slot['eater_name']}",
            "start": {"dateTime": f"{slot['date']}T{start}", "timeZone": zone},
            "end": {"dateTime": f"{slot['date']}T{end}", "timeZone": zone},
            "description": "Managed by Meal Roulette. Make meal-plan changes in the household planner.",
            "extendedProperties": {"private": {"mealRouletteInstance": installation_id, "mealRoulettePlan": str(plan["plan_id"])}},
        })
    return entries


def sync_plan(database, household, plan_id, revision, *, dry_run=True, adapter=None):
    lock_path = database.path.with_suffix(".calendar.lock")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        plan = household.plan(plan_id)
        if type(revision) is not int or revision != plan["revision"]:
            raise HouseholdError("Reload the current plan before publishing it.", 409)
        if plan["state"] != "confirmed":
            raise HouseholdError("Confirm the plan before publishing it.")
        with database.connect() as conn:
            installation = conn.execute("SELECT value FROM settings WHERE key='instance_id'").fetchone()[0]
        if dry_run:
            entries = entries_for_plan(plan, installation, getattr(adapter, "key", os.environ.get("GOOGLE_CALENDAR_ID", "preview")))
            return {"dry_run": True, "events": len(entries), "entries": [event for _, event in entries.values()]}
        try:
            adapter = adapter or GoogleCalendar()
            entries = entries_for_plan(plan, installation, adapter.key)
            with database.connect() as conn:
                existing = [dict(row) for row in conn.execute("SELECT * FROM calendar_publications WHERE calendar_key=? AND plan_id=?", (adapter.key, plan_id))]
            for key, (event_id, event) in entries.items():
                adapter.upsert(event_id, event)
                with database.connect(write=True) as conn:
                    conn.execute("INSERT OR REPLACE INTO calendar_publications VALUES (?,?,?,?,?,?,?)", (adapter.key, plan_id, *key, event_id, revision))
            for old in existing:
                if (old["eater_id"], old["date"], old["meal_type"]) not in entries:
                    adapter.delete(old["event_id"])
                    with database.connect(write=True) as conn:
                        conn.execute("DELETE FROM calendar_publications WHERE calendar_key=? AND plan_id=? AND event_id=?", (adapter.key, plan_id, old["event_id"]))
            with database.connect(write=True) as conn:
                conn.execute("INSERT OR REPLACE INTO calendar_state VALUES (?,?,?,?)", (adapter.key, plan_id, revision, datetime.now(timezone.utc).isoformat()))
                conn.execute("DELETE FROM calendar_jobs WHERE plan_id=? AND requested_revision<=?", (plan_id, revision))
            return {"dry_run": False, "events": len(entries), "revision": revision, "pending_changes": household.plan(plan_id)["revision"] != revision}
        except Exception:
            with database.connect(write=True) as conn:
                conn.execute("""INSERT INTO calendar_jobs(plan_id,requested_revision,attempts,last_error) VALUES (?,?,1,?)
                    ON CONFLICT(plan_id) DO UPDATE SET requested_revision=max(calendar_jobs.requested_revision,excluded.requested_revision),attempts=calendar_jobs.attempts+1,last_error=excluded.last_error""",
                    (plan_id, revision, "Calendar sync failed. Local changes are saved; retry after checking the integration."))
            raise


def sync_pending(app):
    if not app.config["CALENDAR_ENABLED"]:
        return {"synced": 0, "failed": 0, "disabled": True}
    database = app.extensions["database"]
    household = app.extensions["household"]
    with database.connect() as conn:
        jobs = [dict(row) for row in conn.execute("SELECT * FROM calendar_jobs ORDER BY plan_id")]
    synced = failed = 0
    for job in jobs:
        try:
            plan = household.plan(job["plan_id"])
            sync_plan(database, household, plan["plan_id"], plan["revision"], dry_run=False, adapter=app.config["CALENDAR_PUBLISHER"])
            synced += 1
        except Exception:
            failed += 1
    return {"synced": synced, "failed": failed, "disabled": False}
