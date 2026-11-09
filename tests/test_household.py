from concurrent.futures import ThreadPoolExecutor
import copy
from threading import Barrier

import pytest


WEEK = "2026-11-09"


def create_plan(client, week=WEEK, meal_types=None):
    response = client.post("/api/plans", json={"week_start": week, **({"meal_types": meal_types} if meal_types else {})})
    assert response.status_code == 201, response.json
    return response.json


def assignment_url(plan, slot):
    return f"/api/plans/{plan['plan_id']}/assignments/{slot['eater_id']}/{slot['date']}/{slot['meal_type']}"


def test_empty_browser_does_not_generate_a_new_plan(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/plans").json == []
    assert client.post("/api/plans", json={"week_start": WEEK}).status_code == 400


def test_generation_respects_lists_groups_and_weekly_variety(client, seeded):
    unlisted = client.post("/api/meals", json={"meal_description": "Only Scott approves", "meal_type": "dinner"}).json
    client.post("/api/preferences", json={"eater_id": seeded["eaters"][0], "meal_id": unlisted["meal_id"]})
    plan = create_plan(client)
    assert len(plan["assignments"]) == 14
    for offset in range(0, 14, 2):
        first, second = plan["assignments"][offset:offset+2]
        assert first["group_meal"] and second["group_meal"]
        assert first["meal_id"] == second["meal_id"]
        assert first["meal_id"] in seeded["meals"]
    assert len({slot["meal_id"] for slot in plan["assignments"]}) == 7


def test_optional_mealtimes_preserve_solo_defaults(client, seeded):
    plan = create_plan(client, meal_types=["breakfast", "dinner"])
    weekday = [slot for slot in plan["assignments"] if slot["date"] == WEEK and slot["meal_type"] == "breakfast"]
    assert not any(slot["group_meal"] for slot in weekday)
    assert weekday[0]["meal_id"] == seeded["solo"]
    assert weekday[1]["meal_id"] is None
    assert weekday[1]["reason"]
    weekend = [slot for slot in plan["assignments"] if slot["date"] == "2026-11-14" and slot["meal_type"] == "breakfast"]
    assert all(slot["group_meal"] and slot["meal_id"] is None for slot in weekend)


def test_draft_confirmation_and_later_changes_survive_restart(client, seeded, make_app):
    plan = create_plan(client)
    plan = client.patch(assignment_url(plan, plan["assignments"][0]), json={"revision": plan["revision"], "action": "eating_out"}).json
    reopened = make_app().test_client()
    assert reopened.get(f"/api/plans/{plan['plan_id']}").json == plan
    confirmed = reopened.post(f"/api/plans/{plan['plan_id']}/confirm", json={"revision": plan["revision"]}).json
    assert confirmed["state"] == "confirmed"
    assert confirmed["confirmed_at"]
    third = make_app().test_client()
    assert third.get(f"/api/plans/{plan['plan_id']}").json == confirmed
    revised = third.patch(assignment_url(confirmed, confirmed["assignments"][1]), json={"revision": confirmed["revision"], "action": "leftovers"}).json
    assert revised["state"] == "confirmed"
    assert revised["assignments"][0]["kind"] == "eating_out"
    assert revised["assignments"][1]["kind"] == "leftovers"
    page = third.get(f"/?plan={plan['plan_id']}")
    assert page.status_code == 200
    assert b"Eating out" in page.data and b"Leftovers" in page.data


def test_two_devices_cannot_overwrite_each_other(client, seeded, make_app):
    plan = create_plan(client)
    barrier = Barrier(2)
    apps = [make_app(), make_app()]

    def edit(index):
        browser = apps[index].test_client()
        barrier.wait()
        return browser.patch(assignment_url(plan, plan["assignments"][index]), json={"revision": 1, "action": "eating_out"}).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(edit, [0, 1]))
    assert sorted(statuses) == [200, 409]
    saved = client.get(f"/api/plans/{plan['plan_id']}").json
    assert saved["revision"] == 2
    assert sum(slot["kind"] == "eating_out" for slot in saved["assignments"]) == 1


def test_reroll_updates_group_without_repeating_other_dinners(client, seeded):
    plan = create_plan(client)
    original = plan["assignments"][0]["meal_id"]
    other_dinners = {slot["meal_id"] for slot in plan["assignments"][2:]}
    response = client.patch(assignment_url(plan, plan["assignments"][0]), json={"revision": 1, "action": "reroll"})
    assert response.status_code == 200
    first, second = response.json["assignments"][:2]
    assert first["meal_id"] == second["meal_id"]
    assert first["meal_id"] not in other_dinners | {original}


def test_reroll_does_not_change_another_persons_eating_out_label(client, seeded):
    plan = create_plan(client)
    client.patch(assignment_url(plan, plan["assignments"][0]), json={"revision": 1, "action": "eating_out"})
    response = client.patch(assignment_url(plan, plan["assignments"][1]), json={"revision": 2, "action": "reroll"})
    assert response.status_code == 200
    assert response.json["assignments"][0]["kind"] == "eating_out"
    assert response.json["assignments"][1]["kind"] == "meal"


def test_reroll_of_unassigned_slot_can_recover_after_preferences_added(client):
    eater = client.post("/api/eaters", json={"name": "Scott"}).json["eater_id"]
    meal = client.post("/api/meals", json={"meal_description": "Tacos", "meal_type": "dinner"}).json["meal_id"]
    plan = create_plan(client)
    assert all(slot["meal_id"] is None for slot in plan["assignments"])
    before = client.get(f"/api/plans/{plan['plan_id']}").json
    assert client.patch(assignment_url(plan, plan["assignments"][0]), json={"revision": 1, "action": "reroll"}).status_code == 409
    assert client.get(f"/api/plans/{plan['plan_id']}").json == before
    client.post("/api/preferences", json={"eater_id": eater, "meal_id": meal})
    response = client.patch(assignment_url(plan, plan["assignments"][0]), json={"revision": 1, "action": "reroll"})
    assert response.status_code == 200
    assert response.json["assignments"][0]["meal_id"] == meal


def test_archive_keeps_history_and_export_but_excludes_new_selection(client, seeded):
    plan = create_plan(client)
    meal = plan["assignments"][0]["meal_id"]
    assert client.delete(f"/api/meals/{meal}").status_code == 204
    assert client.delete(f"/api/eaters/{seeded['eaters'][1]}").status_code == 204
    assert client.get(f"/api/plans/{plan['plan_id']}").json == plan
    following = create_plan(client, "2026-11-16")
    assert all(slot["eater_id"] == seeded["eaters"][0] and slot["meal_id"] != meal for slot in following["assignments"])
    exported = client.get("/api/export").json["data"]
    assert next(row for row in exported["meals"] if row["meal_id"] == meal)["active"] == 0


def test_editing_one_week_does_not_change_another_week(client, seeded):
    first = create_plan(client)
    second = create_plan(client, "2026-11-16")
    client.patch(assignment_url(first, first["assignments"][0]), json={"revision": 1, "action": "leftovers"})
    assert client.get(f"/api/plans/{second['plan_id']}").json == second
    assert client.post("/api/plans", json={"week_start": WEEK}).status_code == 409


@pytest.mark.parametrize("payload", [{"week_start": "2026-11-10"}, {"week_start": "bad"}, {"week_start": WEEK, "meal_types": ["tea"]}, {"week_start": WEEK, "meal_types": []}, {"week_start": WEEK, "meal_types": ["dinner", "dinner"]}])
def test_invalid_plan_input_does_not_create_a_plan(client, seeded, payload):
    assert client.post("/api/plans", json=payload).status_code == 400
    assert client.get("/api/plans").json == []


@pytest.mark.parametrize("revision", [None, "1", True, 0])
def test_changes_require_a_real_revision(client, seeded, revision):
    plan = create_plan(client)
    assert client.post(f"/api/plans/{plan['plan_id']}/confirm", json={"revision": revision}).status_code == 400
    assert client.get(f"/api/plans/{plan['plan_id']}").json == plan


def test_confirmation_does_not_require_calendar_credentials(client, seeded):
    plan = create_plan(client)
    assert client.post(f"/api/plans/{plan['plan_id']}/confirm", json={"revision": 1}).status_code == 200
    assert client.post(f"/api/plans/{plan['plan_id']}/publish", json={"revision": 2}).status_code == 200
    assert client.post(f"/api/plans/{plan['plan_id']}/publish", json={"revision": 2, "dry_run": False}).status_code == 400


def test_calendar_failure_cannot_erase_confirmed_plan(app, client, seeded):
    calls = []

    def failing_provider(plan, *, dry_run):
        calls.append(plan["state"])
        raise RuntimeError("Provider unavailable")

    app.config["CALENDAR_PUBLISHER"] = failing_provider
    plan = create_plan(client)
    saved = client.post(f"/api/plans/{plan['plan_id']}/confirm", json={"revision": 1}).json
    assert calls == []
    assert client.post(f"/api/plans/{plan['plan_id']}/publish", json={"revision": 2}).status_code == 502
    assert calls == ["confirmed"]
    assert client.get(f"/api/plans/{plan['plan_id']}").json == saved


def test_export_import_is_complete_and_refuses_overwriting(client, seeded, make_app):
    plan = create_plan(client)
    client.post(f"/api/plans/{plan['plan_id']}/confirm", json={"revision": 1})
    document = client.get("/api/export").json
    target = make_app("imported").test_client()
    assert target.post("/api/import", json=document).status_code == 201
    assert target.get("/api/export").json == document
    assert target.post("/api/import", json=document).status_code == 400
    assert target.get("/api/export").json == document


def test_failed_import_rolls_back_every_table(client, seeded, make_app):
    create_plan(client)
    good = client.get("/api/export").json
    broken = copy.deepcopy(good)
    broken["data"]["eater_meal_preferences"].append({"eater_id": 999, "meal_id": seeded["meals"][0]})
    target = make_app("rollback").test_client()
    empty = target.get("/api/export").json
    assert target.post("/api/import", json=broken).status_code == 400
    assert target.get("/api/export").json == empty
    assert target.post("/api/import", json=good).status_code == 201


def test_database_backup_and_restore_into_a_new_installation(app, client, seeded, make_app, tmp_path):
    create_plan(client)
    exported = client.get("/api/export").json
    downloaded = client.get("/api/backup")
    assert downloaded.status_code == 200 and downloaded.data.startswith(b"SQLite format 3")
    backup = tmp_path / "backup.sqlite3"
    backup.write_bytes(downloaded.data)
    destination = tmp_path / "restored.sqlite3"
    runner = app.test_cli_runner()
    result = runner.invoke(args=["restore", str(backup), "--destination", str(destination)])
    assert result.exit_code == 0, result.output
    restored = make_app("restored").test_client()
    assert restored.get("/api/export").json == exported
    assert runner.invoke(args=["restore", str(backup), "--destination", str(destination)]).exit_code != 0
    assert runner.invoke(args=["backup", str(backup)]).exit_code != 0
    assert restored.get("/api/export").json == exported


def test_cli_portable_export_and_import(app, client, seeded, make_app, tmp_path):
    create_plan(client)
    path = tmp_path / "export.json"
    assert app.test_cli_runner().invoke(args=["export-data", str(path)]).exit_code == 0
    target = make_app("cli-import")
    assert target.test_cli_runner().invoke(args=["import-data", str(path)]).exit_code == 0
    assert target.test_client().get("/api/export").json == client.get("/api/export").json


def test_legacy_postgres_export_preserves_ids_flags_effort_and_saved_weeks(client):
    document = {
        "format": "meal-roulette-postgres", "version": 1, "exported_at": "2026-11-08T12:00:00+00:00",
        "data": {
            "eaters": [{"eater_id": 12, "name": "Scott"}],
            "meals": [{"meal_id": 42, "meal_description": "Chili", "meal_type": "dinner", "effort_level": 3}],
            "eater_meal_preferences": [{"eater_id": 12, "meal_id": 42}],
            "meal_schedule": [
                {"eater_id": 12, "date": WEEK, "meal_type": "dinner", "meal_id": 42, "group_meal": True, "eat_out": True},
                {"eater_id": 12, "date": "2026-11-16", "meal_type": "dinner", "meal_id": None, "group_meal": False, "eat_out": False},
            ],
        },
    }
    assert client.post("/api/import", json=document).status_code == 201
    plans = client.get("/api/plans").json
    assert len(plans) == 2 and all(plan["state"] == "confirmed" for plan in plans)
    old = client.get("/api/plans/1").json["assignments"][0]
    assert old["eater_id"] == 12 and old["meal_id"] == 42 and old["group_meal"] and old["kind"] == "eating_out"
    assert client.get("/api/meals").json[0]["effort_level"] == 3
    assert client.post("/api/eaters", json={"name": "Lee"}).json["eater_id"] > 12


def test_browser_forms_and_get_requests_do_not_bypass_change_protection(client, seeded):
    for page in ("/", "/manage/eaters", "/manage/meals", "/manage/preferences"):
        assert client.get(page).status_code == 200
    assert client.post("/manage/eaters/add", data={"eater_name": "Unwanted"}).status_code == 403
    with client.session_transaction() as session:
        token = session["csrf_token"]
    assert client.post("/manage/eaters/add", data={"eater_name": "Guest", "csrf_token": token}).status_code == 302
    assert client.post("/api/eaters", json={"name": "Unwanted"}, headers={"Origin": "https://unrelated.example"}).status_code == 403
    plan = create_plan(client)
    assert client.get(f"/api/plans/{plan['plan_id']}/confirm").status_code == 405
    assert client.get(f"/api/plans/{plan['plan_id']}").json["state"] == "draft"


def test_browser_can_create_confirm_and_reopen_the_same_week(client, seeded, make_app):
    client.get("/")
    with client.session_transaction() as session:
        token = session["csrf_token"]
    response = client.post("/plans", data={"csrf_token": token, "week_start": WEEK, "meal_types": "dinner"})
    assert response.status_code == 302
    plan = client.get("/api/plans/1").json
    assert client.post("/plans/1/confirm", data={"csrf_token": token, "revision": plan["revision"]}).status_code == 302
    assert make_app().test_client().get("/?plan=1").status_code == 200
    assert client.get("/api/plans/1").json["state"] == "confirmed"
    assert client.post("/api/plans/1/regenerate", json={"revision": 2}).status_code == 400


def test_malformed_exports_and_invalid_backups_do_not_change_household(client, seeded, make_app, tmp_path):
    create_plan(client)
    document = client.get("/api/export").json
    target = make_app("invalid-import")
    empty = target.test_client().get("/api/export").json
    invalid = copy.deepcopy(document)
    invalid["data"]["meals"][0]["effort_level"] = {"unexpected": "object"}
    assert target.test_client().post("/api/import", json=invalid).status_code == 400
    assert target.test_client().get("/api/export").json == empty
    backup = tmp_path / "not-a-backup.sqlite3"
    backup.write_bytes(b"not sqlite")
    destination = tmp_path / "must-not-exist.sqlite3"
    result = target.test_cli_runner().invoke(args=["restore", str(backup), "--destination", str(destination)])
    assert result.exit_code != 0 and not destination.exists()
    assert client.get("/api/export").json == document


def test_http_errors_are_json_for_api_clients(client):
    assert client.post("/api/eaters", json=[]).status_code == 400
    response = client.post("/api/eaters", data="name=Scott")
    assert response.status_code == 415 and response.json["error"]
    response = client.get("/api/plans/99999")
    assert response.status_code == 404 and response.json["error"]


def test_solo_dinner_reroll_cannot_reuse_other_eaters_dinner_on_same_date(client, seeded, make_app):
    plan = create_plan(client)
    document = client.get("/api/export").json
    first, second = document["data"]["assignments"][:2]
    # The export is date/eater ordered; select both Monday dinner assignments explicitly.
    monday = [row for row in document["data"]["assignments"] if row["date"] == WEEK]
    first, second = monday
    unused = next(meal for meal in seeded["meals"] if meal not in {slot["meal_id"] for slot in plan["assignments"]})
    first["group_meal"] = second["group_meal"] = 0
    second["meal_id"] = unused
    document["data"]["eater_meal_preferences"] = [
        row for row in document["data"]["eater_meal_preferences"]
        if row["eater_id"] != first["eater_id"] or row["meal_id"] in (first["meal_id"], unused)
    ]
    target = make_app("solo-import").test_client()
    assert target.post("/api/import", json=document).status_code == 201
    response = target.patch(assignment_url(plan, first), json={"revision": 1, "action": "reroll"})
    assert response.status_code == 409
    assert target.get(f"/api/plans/{plan['plan_id']}").json["revision"] == 1
