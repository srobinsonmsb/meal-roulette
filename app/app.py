"""HTTP and browser clients share the same durable household module."""

from datetime import date, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory

import click
from dotenv import load_dotenv
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from .db import DataError, Database, SCHEMA_VERSION
from .backups import Backups
from .household import Household, HouseholdError
from .shopping import Shopping


def create_app(config=None):
    load_dotenv(Path(__file__).with_name(".env"))
    instance = Path(os.environ.get("MEAL_ROULETTE_DATA_DIR", Path(__file__).resolve().parent.parent / "instance")).resolve()
    app = Flask(__name__, instance_path=str(instance))
    app.config.from_mapping(
        DATABASE=os.environ.get("MEAL_ROULETTE_DATABASE", str(instance / "meal-roulette.sqlite3")),
        SECRET_KEY=os.environ.get("MEAL_ROULETTE_SECRET_KEY"),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        CALENDAR_ENABLED=os.environ.get("MEAL_ROULETTE_CALENDAR_ENABLED", "").lower() == "true",
        CALENDAR_PUBLISHER=None,
        BACKUP_UPLOADER=None,
    )
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"]:
        instance.mkdir(parents=True, exist_ok=True)
        secret = instance / "secret-key"
        try:
            with secret.open("x") as file:
                os.chmod(secret, 0o600)
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config["SECRET_KEY"] = secret.read_text()
    database = Database(app.config["DATABASE"])
    household = Household(database)
    shopping = Shopping(database)
    backups = Backups(database, uploader=app.config["BACKUP_UPLOADER"])
    app.extensions["database"] = database
    app.extensions["household"] = household
    app.extensions["shopping"] = shopping
    app.extensions["backups"] = backups

    @app.get("/api/health")
    def health():
        with database.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "schema_version": SCHEMA_VERSION, "version": "0.3.0", "calendar_enabled": app.config["CALENDAR_ENABLED"]}

    @app.template_filter("amount")
    def display_amount(value):
        number = Decimal(value)
        rounded = number.quantize(Decimal("0.001"))
        if rounded == 0 and number:
            return format(number, ".3g")
        result = format(rounded, "f").rstrip("0").rstrip(".")
        return ("≈" if rounded != number else "") + (result or "0")

    def body():
        data = request.get_json()
        if not isinstance(data, dict):
            raise HouseholdError("Expected a JSON object.")
        return data

    @app.before_request
    def protect_forms():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                raise HouseholdError("Changes must come from the household application.", 403)
            if not request.path.startswith("/api/") and not secrets.compare_digest(
                request.form.get("csrf_token", ""), session.get("csrf_token", secrets.token_hex(32))
            ):
                raise HouseholdError("Reload the form before making changes.", 403)

    @app.context_processor
    def form_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)
        return {"csrf_token": session["csrf_token"], "calendar_enabled": app.config["CALENDAR_ENABLED"]}

    @app.errorhandler(DataError)
    def data_error(error):
        status = getattr(error, "status", 400)
        if request.path.startswith("/api/"):
            return jsonify(error=str(error)), status
        return render_template("error.html", message=str(error)), status

    @app.errorhandler(sqlite3.IntegrityError)
    def invalid_record(error):
        return data_error(HouseholdError("The change violates a household data constraint."))

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return error

    @app.get("/api/collection")
    def collection():
        return household.collection()

    @app.route("/api/eaters", methods=["GET", "POST"])
    def eaters():
        if request.method == "GET":
            return jsonify(household.collection()["eaters"])
        return household.add_eater(body().get("name")), 201

    @app.route("/api/meals", methods=["GET", "POST"])
    def meals():
        if request.method == "GET":
            return jsonify(household.collection()["meals"])
        data = body()
        return household.add_meal(data.get("meal_description"), data.get("meal_type"), data.get("effort_level"), data.get("theme", ""), data.get("servings", "1")), 201

    @app.patch("/api/meals/<int:meal_id>")
    def edit_meal_api(meal_id):
        return household.edit_meal(meal_id, body())

    @app.route("/api/ingredients", methods=["GET", "POST"])
    def ingredients_api():
        if request.method == "GET":
            return jsonify(household.collection()["ingredients"])
        return shopping.add_ingredient(body().get("name")), 201

    @app.route("/api/meals/<int:meal_id>/ingredients", methods=["GET", "PUT"])
    def meal_ingredients_api(meal_id):
        if request.method == "GET":
            return jsonify(shopping.meal_ingredients(meal_id))
        return jsonify(shopping.replace_ingredients(meal_id, body().get("ingredients")))

    @app.route("/api/plans/<int:plan_id>/groceries", methods=["GET", "POST"])
    def groceries_api(plan_id):
        if request.method == "GET":
            return shopping.groceries(plan_id)
        data = body()
        return shopping.add_item(plan_id, data.get("revision"), data.get("name"), data.get("amount", "1"), data.get("unit", "each")), 201

    @app.patch("/api/plans/<int:plan_id>/groceries/<int:item_id>")
    def shopping_item_api(plan_id, item_id):
        data = body()
        revision = data.pop("revision", None)
        return shopping.change_item(plan_id, item_id, revision, data)

    @app.get("/api/routines")
    def routines_api():
        return jsonify(household.collection()["routines"])

    @app.route("/api/routines/<int:weekday>/<meal_type>", methods=["PUT", "DELETE"])
    def routine_api(weekday, meal_type):
        if request.method == "DELETE":
            household.remove_routine(weekday, meal_type)
            return "", 204
        return household.save_routine(weekday, meal_type, body())

    @app.delete("/api/eaters/<int:identifier>")
    @app.delete("/api/meals/<int:identifier>")
    def archive(identifier):
        household.archive(request.path.split("/")[2], identifier)
        return "", 204

    @app.route("/api/preferences", methods=["GET", "POST"])
    def preferences():
        if request.method == "GET":
            return jsonify(household.collection()["preferences"])
        data = body()
        household.preference(data.get("eater_id"), data.get("meal_id"))
        return "", 204

    @app.delete("/api/preferences/<int:eater_id>/<int:meal_id>")
    def remove_preference(eater_id, meal_id):
        household.preference(eater_id, meal_id, remove=True)
        return "", 204

    @app.route("/api/plans", methods=["GET", "POST"])
    def plans():
        if request.method == "GET":
            return jsonify(household.plans())
        data = body()
        return household.create_plan(data.get("week_start"), data.get("meal_types")), 201

    @app.get("/api/plans/<int:plan_id>")
    def plan(plan_id):
        return household.plan(plan_id)

    @app.post("/api/plans/<int:plan_id>/confirm")
    def confirm(plan_id):
        return household.confirm(plan_id, body().get("revision"))

    @app.post("/api/plans/<int:plan_id>/regenerate")
    def regenerate(plan_id):
        return household.regenerate(plan_id, body().get("revision"))

    @app.patch("/api/plans/<int:plan_id>/assignments/<int:eater_id>/<day>/<meal_type>")
    def change_assignment(plan_id, eater_id, day, meal_type):
        data = body()
        return household.change_assignment(plan_id, eater_id, day, meal_type, data.get("revision"), data.get("action"), data.get("meal_id"))

    @app.patch("/api/plans/<int:plan_id>/slots/<day>/<meal_type>")
    def override_api(plan_id, day, meal_type):
        data = body()
        return household.override_slot(plan_id, day, meal_type, data.get("revision"), data)

    def publish(plan_id, revision, dry_run):
        if type(dry_run) is not bool:
            raise HouseholdError("dry_run must be true or false.")
        current = household.plan(plan_id)
        if type(revision) is not int or revision != current["revision"]:
            raise HouseholdError("Reload the current plan before publishing it.", 409)
        if current["state"] != "confirmed":
            raise HouseholdError("Confirm the plan before publishing it.")
        if not dry_run and not app.config["CALENDAR_ENABLED"]:
            raise HouseholdError("Live calendar publishing is disabled. Enable it in the server configuration.")
        publisher = app.config["CALENDAR_PUBLISHER"]
        try:
            if callable(publisher) and not hasattr(publisher, "upsert"):
                return publisher(current, dry_run=dry_run)
            from .calendar_service import sync_plan

            return sync_plan(database, household, plan_id, revision, dry_run=dry_run, adapter=publisher)
        except HouseholdError:
            raise
        except Exception:
            raise HouseholdError("Calendar publishing failed. Your local plan is still saved.", 502) from None

    @app.post("/api/plans/<int:plan_id>/publish")
    def publish_api(plan_id):
        data = body()
        return publish(plan_id, data.get("revision"), data.get("dry_run", True))

    @app.get("/api/export")
    def export_data():
        response = jsonify(database.export_data())
        response.headers["Content-Disposition"] = 'attachment; filename="meal-roulette.json"'
        return response

    @app.post("/api/import")
    def import_data():
        database.import_data(body())
        return {"imported": True}, 201

    @app.get("/api/backup")
    def download_backup():
        with TemporaryDirectory() as folder:
            path = Path(folder) / "household.sqlite3"
            database.backup(path)
            data = path.read_bytes()
        return Response(data, mimetype="application/vnd.sqlite3", headers={
            "Content-Disposition": 'attachment; filename="meal-roulette.sqlite3"'
        })

    @app.get("/")
    def home():
        saved = household.plans()
        plan_id = request.args.get("plan", type=int)
        selected = household.plan(plan_id) if plan_id is not None else (household.plan(saved[0]["plan_id"]) if saved else None)
        today = date.today()
        monday = today + timedelta(days=(-today.weekday()) % 7)
        collection = household.collection()
        days = [(date.fromisoformat(selected["week_start"]) + timedelta(days=i)).isoformat() for i in range(7)] if selected else []
        return render_template("index.html", plan=selected, plans=saved, monday=monday.isoformat(), days=days, meals=collection["meals"], eaters=collection["eaters"])

    @app.post("/plans")
    def new_plan():
        types = request.form.getlist("meal_types")
        created = household.create_plan(request.form.get("week_start"), types or ["dinner"])
        return redirect(url_for("home", plan=created["plan_id"]))

    @app.post("/plans/<int:plan_id>/<operation>")
    def change_plan(plan_id, operation):
        revision = request.form.get("revision", type=int)
        if operation == "confirm":
            household.confirm(plan_id, revision)
        elif operation == "regenerate":
            household.regenerate(plan_id, revision)
        elif operation == "publish":
            result = publish(plan_id, revision, True)
            flash(f"Calendar preview: {result['events']} events. The plan remains saved.")
        elif operation == "publish-live":
            result = publish(plan_id, revision, False)
            flash(f"Calendar updated: {result['events']} events.")
        else:
            raise HouseholdError("Unknown plan operation.", 404)
        return redirect(url_for("home", plan=plan_id))

    @app.post("/plans/<int:plan_id>/assignments/<int:eater_id>/<day>/<meal_type>")
    def change_assignment_form(plan_id, eater_id, day, meal_type):
        household.change_assignment(
            plan_id, eater_id, day, meal_type,
            request.form.get("revision", type=int), request.form.get("action"),
            request.form.get("meal_id", type=int),
        )
        return redirect(url_for("home", plan=plan_id))

    @app.get("/manage/<kind>")
    def manage(kind):
        if kind not in ("meals", "eaters", "preferences", "routines"):
            raise HouseholdError("Page not found.", 404)
        return render_template("collection.html", kind=kind, **household.collection())

    @app.post("/manage/<kind>/add")
    def add_record(kind):
        if kind == "eaters":
            household.add_eater(request.form.get("eater_name"))
        elif kind == "meals":
            household.add_meal(request.form.get("meal_description"), request.form.get("meal_type"), request.form.get("effort_level", type=int), request.form.get("theme", ""), request.form.get("servings", "1"))
        elif kind == "preferences":
            household.preference(request.form.get("eater_id", type=int), request.form.get("meal_id", type=int))
        elif kind == "routines":
            household.save_routine(request.form.get("weekday", type=int), request.form.get("meal_type"), {
                "group_meal": request.form.get("group_meal") == "1", "kind": request.form.get("kind"),
                "max_effort": request.form.get("max_effort", type=int), "theme": request.form.get("theme", ""),
            })
        else:
            raise HouseholdError("Page not found.", 404)
        return redirect(url_for("manage", kind=kind))

    @app.post("/meals/<int:meal_id>/edit")
    def edit_meal_form(meal_id):
        household.edit_meal(meal_id, {
            "meal_description": request.form.get("meal_description"), "meal_type": request.form.get("meal_type"),
            "effort_level": request.form.get("effort_level", type=int), "theme": request.form.get("theme", ""), "servings": request.form.get("servings", "1"),
        })
        return redirect(url_for("meal_page", meal_id=meal_id))

    @app.get("/meals/<int:meal_id>")
    def meal_page(meal_id):
        meal = next((row for row in household.collection()["meals"] if row["meal_id"] == meal_id), None)
        if meal is None:
            raise HouseholdError("Meal not found.", 404)
        return render_template("meal.html", meal=meal, ingredients=shopping.meal_ingredients(meal_id))

    @app.post("/meals/<int:meal_id>/ingredients")
    def ingredients_form(meal_id):
        names = request.form.getlist("ingredient_name")
        amounts = request.form.getlist("amount")
        units = request.form.getlist("unit")
        if len(names) != len(amounts) or len(names) != len(units):
            raise HouseholdError("Each ingredient needs its amount and unit.")
        rows = [{"name": name, "amount": amount, "unit": unit} for name, amount, unit in zip(names, amounts, units) if name.strip() or amount.strip()]
        shopping.replace_ingredients(meal_id, rows)
        flash("Ingredient amounts saved.")
        return redirect(url_for("meal_page", meal_id=meal_id))

    @app.post("/meals/<int:meal_id>/restore")
    def restore_meal_form(meal_id):
        household.edit_meal(meal_id, {"active": 1})
        return redirect(url_for("meal_page", meal_id=meal_id))

    @app.get("/plans/<int:plan_id>/groceries")
    def groceries_page(plan_id):
        return render_template("groceries.html", groceries=shopping.groceries(plan_id))

    @app.post("/plans/<int:plan_id>/groceries/add")
    def add_shopping_form(plan_id):
        shopping.add_item(plan_id, request.form.get("revision", type=int), request.form.get("name"), request.form.get("amount", "1"), request.form.get("unit", "each"))
        return redirect(url_for("groceries_page", plan_id=plan_id))

    @app.post("/plans/<int:plan_id>/groceries/<int:item_id>")
    def change_shopping_form(plan_id, item_id):
        actions = {
            "purchased": {"checked": True, "excluded": False, "needs_review": False},
            "owned": {"excluded": True, "checked": False, "needs_review": False},
            "needed": {"checked": False, "excluded": False, "needs_review": False},
            "reviewed": {"needs_review": False}, "remove": {"active": False},
        }
        changes = actions.get(request.form.get("action"))
        if changes is None:
            raise HouseholdError("Choose a shopping-list action.")
        shopping.change_item(plan_id, item_id, request.form.get("revision", type=int), changes)
        return redirect(url_for("groceries_page", plan_id=plan_id))

    @app.get("/plans/<int:plan_id>/slots/<day>/<meal_type>")
    def slot_page(plan_id, day, meal_type):
        plan = household.plan(plan_id)
        try:
            valid = 0 <= (date.fromisoformat(day) - date.fromisoformat(plan["week_start"])).days < 7 and meal_type in plan["meal_types"]
        except ValueError:
            valid = False
        if not valid:
            raise HouseholdError("Choose a dinner within this plan.", 404)
        slots = [row for row in plan["assignments"] if row["date"] == day and row["meal_type"] == meal_type]
        rules = next((row for row in plan["overrides"] if row["date"] == day and row["meal_type"] == meal_type), None)
        if rules is None:
            rules = dict(slots[0]) if slots else {"kind": "meal", "group_meal": True, "theme": "", "max_effort": None}
            rules["eater_ids"] = [row["eater_id"] for row in slots]
        return render_template("slot.html", plan=plan, day=day, meal_type=meal_type, rules=rules, eaters=household.collection()["eaters"])

    @app.post("/routines/<int:weekday>/<meal_type>/remove")
    def remove_routine_form(weekday, meal_type):
        household.remove_routine(weekday, meal_type)
        return redirect(url_for("manage", kind="routines"))

    @app.post("/plans/<int:plan_id>/slots/<day>/<meal_type>")
    def override_form(plan_id, day, meal_type):
        household.override_slot(plan_id, day, meal_type, request.form.get("revision", type=int), {
            "eater_ids": request.form.getlist("eater_ids", type=int), "group_meal": request.form.get("group_meal") == "1",
            "kind": request.form.get("kind"), "max_effort": request.form.get("max_effort", type=int), "theme": request.form.get("theme", ""),
        })
        return redirect(url_for("home", plan=plan_id))

    @app.post("/manage/<kind>/archive/<int:identifier>")
    def archive_form(kind, identifier):
        if kind not in ("meals", "eaters"):
            raise HouseholdError("Page not found.", 404)
        household.archive(kind, identifier)
        return redirect(url_for("manage", kind=kind))

    @app.post("/manage/preferences/remove/<int:eater_id>/<int:meal_id>")
    def remove_preference_form(eater_id, meal_id):
        household.preference(eater_id, meal_id, remove=True)
        return redirect(url_for("manage", kind="preferences"))

    def command_errors(function):
        from functools import wraps

        @wraps(function)
        def run(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except (DataError, OSError, sqlite3.Error, json.JSONDecodeError) as error:
                raise click.ClickException(str(error)) from error
        return run

    @app.cli.command("export-data")
    @click.argument("destination", type=click.Path(path_type=Path))
    @command_errors
    def export_command(destination):
        with destination.open("x") as file:
            json.dump(database.export_data(), file, indent=2)
        click.echo(f"Exported household data to {destination}")

    @app.cli.command("sync-calendar")
    def sync_calendar_command():
        from .calendar_service import sync_pending

        result = sync_pending(app)
        click.echo(json.dumps(result))
        if result["failed"]:
            raise click.ClickException("Some Calendar updates remain queued.")

    @app.cli.command("authorize-google")
    def authorize_google_command():
        from .calendar_service import get_calendar_service

        previous = os.environ.get("MEAL_ROULETTE_GOOGLE_AUTHORIZE")
        os.environ["MEAL_ROULETTE_GOOGLE_AUTHORIZE"] = "true"
        try:
            get_calendar_service()
            click.echo("Google Calendar authorized locally. No meal events were published.")
        finally:
            if previous is None:
                os.environ.pop("MEAL_ROULETTE_GOOGLE_AUTHORIZE", None)
            else:
                os.environ["MEAL_ROULETTE_GOOGLE_AUTHORIZE"] = previous

    @app.cli.command("configure-backup")
    @click.option("--destination", required=True)
    @click.option("--interval-hours", type=int, default=24, show_default=True)
    @command_errors
    def configure_backup_command(destination, interval_hours):
        click.echo(json.dumps(backups.configure(destination, interval_hours)))

    @app.cli.command("disable-backups")
    @command_errors
    def disable_backups_command():
        backups.disable()
        click.echo("Automated backups disabled.")

    @app.cli.command("backup-due")
    @click.option("--force", is_flag=True)
    @command_errors
    def backup_due_command(force):
        click.echo(json.dumps(backups.run(force=force)))

    @app.cli.command("backup-status")
    @command_errors
    def backup_status_command():
        click.echo(json.dumps(backups.status()))

    @app.cli.command("import-data")
    @click.argument("source", type=click.Path(exists=True, path_type=Path))
    @command_errors
    def import_command(source):
        database.import_data(json.loads(source.read_text()))
        click.echo("Imported household data into the empty installation.")

    @app.cli.command("backup")
    @click.argument("destination", type=click.Path(path_type=Path))
    @command_errors
    def backup_command(destination):
        database.backup(destination)
        click.echo(f"Created database backup: {destination}")

    @app.cli.command("restore")
    @click.argument("source", type=click.Path(exists=True, path_type=Path))
    @click.option("--destination", required=True, type=click.Path(path_type=Path))
    @command_errors
    def restore_command(source, destination):
        database.restore_to_new(source, destination)
        click.echo(f"Restored to {destination}. Set MEAL_ROULETTE_DATABASE to this file on startup.")

    @app.cli.command("export-postgres")
    @click.argument("destination", type=click.Path(path_type=Path))
    @command_errors
    def export_postgres_command(destination):
        from .legacy import export_postgres

        document = export_postgres()
        with destination.open("x") as file:
            json.dump(document, file, indent=2)
        click.echo(f"Exported legacy PostgreSQL records to {destination}. The source was not modified.")

    return app
