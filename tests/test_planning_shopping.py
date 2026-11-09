from datetime import date, timedelta

import pytest

from test_household import WEEK, assignment_url, create_plan


def set_meal(client, meal_id, **changes):
    response = client.patch(f"/api/meals/{meal_id}", json=changes)
    assert response.status_code == 200, response.json


def override(client, plan, day, diners, **rules):
    response = client.patch(f"/api/plans/{plan['plan_id']}/slots/{day}/dinner", json={
        "revision": plan["revision"], "eater_ids": diners, "group_meal": True,
        **rules,
    })
    assert response.status_code == 200, response.json
    return response.json


def one_dinner(client, seeded):
    plan = create_plan(client)
    for offset in range(1, 7):
        day = (date.fromisoformat(WEEK) + timedelta(days=offset)).isoformat()
        plan = override(client, plan, day, [])
    meal = seeded["meals"][0]
    response = client.patch(assignment_url(plan, plan["assignments"][0]), json={"revision": plan["revision"], "action": "meal", "meal_id": meal})
    assert response.status_code == 200
    return response.json


def ingredients(client, meal_id, rows):
    response = client.put(f"/api/meals/{meal_id}/ingredients", json={"ingredients": rows})
    assert response.status_code == 200, response.json
    return response.json


def test_routines_use_effort_themes_and_one_week_diner_exceptions(client, seeded):
    for meal in seeded["meals"]:
        set_meal(client, meal, effort_level=3, theme="pasta")
    quick = seeded["meals"][0]
    set_meal(client, quick, effort_level=1, theme="tacos")
    response = client.put("/api/routines/0/dinner", json={"group_meal": True, "max_effort": 1, "theme": "tacos"})
    assert response.status_code == 200
    plan = create_plan(client)
    assert all(row["meal_id"] == quick and row["max_effort"] == 1 for row in plan["assignments"][:2])
    assert client.patch(assignment_url(plan, plan["assignments"][0]), json={"revision": 1, "action": "reroll"}).status_code == 409
    changed = override(client, plan, WEEK, [seeded["eaters"][0]], group_meal=False, max_effort=3, theme="pasta")
    monday = [row for row in changed["assignments"] if row["date"] == WEEK]
    assert len(monday) == 1 and not monday[0]["group_meal"] and monday[0]["theme"] == "pasta"
    assert client.get("/api/routines").json[0]["theme"] == "tacos"
    next_week = create_plan(client, "2026-11-16")
    assert all(row["meal_id"] == quick for row in next_week["assignments"][:2])


def test_unknown_effort_is_not_silently_allowed_by_a_limit(client, seeded):
    client.put("/api/routines/0/dinner", json={"max_effort": 1})
    plan = create_plan(client)
    assert all(row["meal_id"] is None and row["reason"] for row in plan["assignments"][:2])
    assert client.put("/api/routines/0/dinner", json={"max_effort": 5}).status_code == 400


def test_constrained_days_keep_their_only_candidate_when_a_full_week_is_possible(client, seeded):
    for meal in seeded["meals"]:
        set_meal(client, meal, effort_level=3, theme="regular")
    only = seeded["meals"][0]
    set_meal(client, only, effort_level=1, theme="tacos")
    client.put("/api/routines/1/dinner", json={"max_effort": 1, "theme": "tacos"})
    plan = create_plan(client)
    assert all(row["meal_id"] is not None for row in plan["assignments"])
    assert all(row["meal_id"] == only for row in plan["assignments"] if row["date"] == "2026-11-10")
    assert len({row["meal_id"] for row in plan["assignments"]}) == 7


def test_extended_browser_workflows_render_and_save(client, seeded):
    plan = one_dinner(client, seeded)
    meal = seeded["meals"][0]
    for page in ("/manage/routines", f"/meals/{meal}", f"/plans/{plan['plan_id']}/groceries", f"/plans/{plan['plan_id']}/slots/{WEEK}/dinner"):
        response = client.get(page)
        assert response.status_code == 200, page
    with client.session_transaction() as session:
        token = session["csrf_token"]
    response = client.post(f"/meals/{meal}/ingredients", data={"csrf_token": token, "ingredient_name": ["Rice", ""], "amount": ["100", ""], "unit": ["g", "each"]})
    assert response.status_code == 302
    response = client.get(f"/plans/{plan['plan_id']}/groceries")
    assert response.status_code == 200 and b"Rice" in response.data
    response = client.post("/manage/routines/add", data={"csrf_token": token, "weekday": "4", "meal_type": "dinner", "group_meal": "1", "kind": "eating_out"})
    assert response.status_code == 302
    assert client.get("/api/routines").json[0]["kind"] == "eating_out"


def test_draft_regeneration_keeps_intentional_choices_and_labels(client, seeded):
    plan = create_plan(client)
    chosen = plan["assignments"][2]
    plan = client.patch(assignment_url(plan, chosen), json={"revision": plan["revision"], "action": "meal", "meal_id": chosen["meal_id"]}).json
    plan = client.patch(assignment_url(plan, plan["assignments"][0]), json={"revision": plan["revision"], "action": "leftovers"}).json
    client.put("/api/routines/4/dinner", json={"kind": "eating_out"})
    result = client.post(f"/api/plans/{plan['plan_id']}/regenerate", json={"revision": plan["revision"]})
    assert result.status_code == 200
    new = result.json
    assert new["assignments"][0]["kind"] == "leftovers"
    assert new["assignments"][2]["meal_id"] == chosen["meal_id"]
    assert all(row["kind"] == "eating_out" for row in new["assignments"] if row["date"] == "2026-11-13")


def test_scaled_shared_ingredients_combine_compatible_units(client, seeded):
    plan = one_dinner(client, seeded)
    meal = seeded["meals"][0]
    set_meal(client, meal, servings="2")
    ingredients(client, meal, [{"name": "Flour", "amount": "0.5", "unit": "kg"}, {"name": "Milk", "amount": "250", "unit": "ml"}])
    other = seeded["meals"][1]
    ingredients(client, other, [{"name": " FLOUR ", "amount": "100", "unit": "g"}, {"name": "milk", "amount": "1", "unit": "l"}])
    plan = override(client, plan, "2026-11-10", [seeded["eaters"][0]], group_meal=False)
    tuesday = next(row for row in plan["assignments"] if row["date"] == "2026-11-10")
    client.patch(assignment_url(plan, tuesday), json={"revision": plan["revision"], "action": "meal", "meal_id": other})
    shopping = client.get(f"/api/plans/{plan['plan_id']}/groceries").json
    assert shopping["warnings"] == []
    totals = {(row["name"].casefold(), row["unit"]): row["amount"] for row in shopping["items"]}
    assert totals == {("flour", "g"): "600", ("milk", "ml"): "1250"}
    assert len(client.get("/api/ingredients").json) == 2


def test_incompatible_units_stay_separate_and_missing_records_are_visible(client, seeded):
    plan = one_dinner(client, seeded)
    url = f"/api/plans/{plan['plan_id']}/groceries"
    assert client.get(url).json["warnings"]
    ingredients(client, seeded["meals"][0], [{"name": "Tomato", "amount": "2", "unit": "each"}, {"name": "Tomato", "amount": "100", "unit": "g"}])
    result = client.get(url).json
    assert not result["warnings"]
    assert {row["unit"] for row in result["items"]} == {"each", "g"}


def test_quantity_changes_require_review_without_losing_manual_items(client, seeded, make_app):
    plan = one_dinner(client, seeded)
    meal = seeded["meals"][0]
    ingredients(client, meal, [{"name": "Onion", "amount": "1", "unit": "each"}])
    url = f"/api/plans/{plan['plan_id']}/groceries"
    groceries = client.get(url).json
    onion = groceries["items"][0]
    checked = client.patch(f"{url}/{onion['item_id']}", json={"revision": groceries["revision"], "checked": True}).json
    extra = client.post(url, json={"revision": checked["revision"], "name": "Dish soap"})
    assert extra.status_code == 201
    ingredients(client, meal, [{"name": "Onion", "amount": "2", "unit": "each"}])
    result = make_app().test_client().get(url).json
    onion = next(row for row in result["items"] if row["name"] == "Onion")
    assert onion["amount"] == "4" and onion["previous_amount"] == "2"
    assert onion["needs_review"] and not onion["checked"]
    assert any(row["name"] == "Dish soap" and row["manual"] for row in result["items"])
    stale = client.patch(f"{url}/{onion['item_id']}", json={"revision": checked["revision"], "checked": True})
    assert stale.status_code == 409


def test_labels_remove_generated_ingredients_and_leave_manual_shopping(client, seeded):
    plan = one_dinner(client, seeded)
    ingredients(client, seeded["meals"][0], [{"name": "Onion", "amount": "1", "unit": "each"}])
    url = f"/api/plans/{plan['plan_id']}/groceries"
    grocery = client.get(url).json
    client.post(url, json={"revision": grocery["revision"], "name": "Soap"})
    for slot in plan["assignments"]:
        plan = client.patch(assignment_url(plan, slot), json={"revision": plan["revision"], "action": "leftovers"}).json
    result = client.get(url).json
    assert [row["name"] for row in result["items"]] == ["Soap"]


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", True])
def test_invalid_ingredient_replacement_is_atomic(client, seeded, amount):
    meal = seeded["meals"][0]
    original = ingredients(client, meal, [{"name": "Rice", "amount": "100", "unit": "g"}])
    bad = client.put(f"/api/meals/{meal}/ingredients", json={"ingredients": [{"name": "Invalid ingredient", "amount": amount, "unit": "g"}]})
    assert bad.status_code == 400
    assert client.get(f"/api/meals/{meal}/ingredients").json == original
    assert len(client.get("/api/ingredients").json) == 1


class Calendar:
    key = "test-calendar"

    def __init__(self):
        self.events = {}
        self.fail = False

    def upsert(self, event_id, event):
        if self.fail:
            raise RuntimeError("Offline")
        self.events[event_id] = event

    def delete(self, event_id):
        self.events.pop(event_id, None)


def test_calendar_publish_retry_updates_and_removals_use_stable_ids(app, client, seeded, make_app):
    calendar = Calendar()
    app.config.update(CALENDAR_PUBLISHER=calendar, CALENDAR_ENABLED=True)
    plan = create_plan(client)
    plan = client.post(f"/api/plans/{plan['plan_id']}/confirm", json={"revision": 1}).json
    url = f"/api/plans/{plan['plan_id']}/publish"
    assert client.post(url, json={"revision": plan["revision"], "dry_run": False}).status_code == 200
    ids = set(calendar.events)
    assert len(ids) == 14
    assert client.post(url, json={"revision": plan["revision"], "dry_run": False}).status_code == 200
    assert set(calendar.events) == ids
    plan = client.patch(assignment_url(plan, plan["assignments"][0]), json={"revision": plan["revision"], "action": "leftovers"}).json
    assert plan["calendar_job"]
    calendar.fail = True
    assert app.test_cli_runner().invoke(args=["sync-calendar"]).exit_code != 0
    saved = client.get(f"/api/plans/{plan['plan_id']}").json
    assert saved["calendar_job"]["attempts"] == 1 and saved["state"] == "confirmed"
    calendar.fail = False
    restarted = make_app(CALENDAR_PUBLISHER=calendar, CALENDAR_ENABLED=True)
    assert restarted.test_cli_runner().invoke(args=["sync-calendar"]).exit_code == 0
    plan = restarted.test_client().get(f"/api/plans/{plan['plan_id']}").json
    assert plan["calendar_job"] is None
    assert set(calendar.events) == ids
    assert any(event["summary"].startswith("Leftovers") for event in calendar.events.values())
    plan = override(client, plan, WEEK, [])
    assert app.test_cli_runner().invoke(args=["sync-calendar"]).exit_code == 0
    assert len(calendar.events) == 12
