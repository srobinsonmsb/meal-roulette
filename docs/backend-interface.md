# Household backend interface, schema/data version 2

The web interface and JSON clients use the same household operations. The application factory is app.create_app; it accepts a DATABASE path and configuration overrides. Each request opens its own SQLite connection. Importing the package does not start a server or open a database.

The current contract serves one trusted household per server. There is no public signup, external application authentication, or central data collection. Browser forms carry a session-bound CSRF token. JSON mutations require a JSON object, and cross-origin mutations are refused.

## Collection

| Method and path | Result |
| --- | --- |
| GET /api/collection | eaters, meals, preferences, including archived entries |
| GET or POST /api/eaters | List entries, or add one with name |
| GET or POST /api/meals | List entries, or add one with meal_description and meal_type |
| DELETE /api/eaters/{eater_id} | Archive; retain history |
| DELETE /api/meals/{meal_id} | Archive; retain history |
| GET or POST /api/preferences | List entries, or approve eater_id + meal_id |
| DELETE /api/preferences/{eater_id}/{meal_id} | Remove automatic approval |

Creation returns 201. Successful preference and archive operations return 204. IDs are positive integers. Mealtimes are breakfast, lunch, and dinner. Effort is 1 quick, 2 moderate, or 3 involved; migrated values are preserved until explicitly edited. Meals also record theme and serving yield.

PATCH /api/meals/{meal_id} updates named meal fields. GET/PUT /api/meals/{meal_id}/ingredients reads/replaces the ingredient list; replacement uses an object with an ingredients array of name (or ingredient_id), amount, and unit. POST /api/ingredients accepts a name and reuses its normalized identity.

GET /api/routines lists routines. PUT/DELETE /api/routines/{weekday}/{meal_type} writes/removes a routine. Weekdays are 0 Monday through 6 Sunday; values include group_meal (boolean), kind, max_effort (nullable 1–3), and theme. Unknown effort is ineligible when an effort limit is set.

## Weekly plans

| Method and path | Input / result |
| --- | --- |
| GET /api/plans | Saved weeks with plan_id, week_start, state, revision |
| POST /api/plans | week_start (Monday, YYYY-MM-DD), optional meal_types array (default dinner); returns 201 |
| GET /api/plans/{plan_id} | Complete persisted plan and assignments |
| POST /api/plans/{plan_id}/confirm | revision; marks the current plan confirmed |
| POST /api/plans/{plan_id}/regenerate | revision; replaces assignments in a draft only |
| PATCH /api/plans/{plan_id}/assignments/{eater_id}/{date}/{meal_type} | revision, action, optional meal_id |
| POST /api/plans/{plan_id}/publish | revision, optional dry_run boolean (default true) |

Assignment actions are reroll, meal (requires meal_id), eating_out, or leftovers. The assignment's stable identity includes plan, eater, date, and mealtime; display row numbers never identify a mutation.

Every plan mutation requires the revision returned by the latest read. Writes take an immediate transaction, check the revision, apply the change, and increment the revision atomically. Stale versions return 409 and leave data unchanged. Clients must reload and let the household resolve the conflict. Missing/invalid revisions return 400.

The response includes state (draft or confirmed), revision, timestamps, chosen mealtimes, and assignments with names, IDs, group_meal, kind, and reason. A meal assignment with no eligible choice has a null meal_id and an explanatory reason. The generator never treats an unlisted meal as approved. Rerolling with no eligible alternative returns 409 without consuming a revision.

Group rerolls and manual meal choices update the relevant group rows together. Eating-out and leftovers labels apply to the selected person. Such labels do not require a meal, although an underlying meal_id may be retained for data preservation. Their kind determines what is displayed and included in grocery requirements.

Confirmed plans stay confirmed when edited. Confirmation does not authenticate with or publish to Google. Calendar preview and initial live publication are explicit operations. Live publication uses stable event IDs and persisted mappings; repeated publication updates managed events and removes no-longer-planned events. Once published, confirmed-plan changes create a durable sync job processed by the operator's Calendar timer. Provider failure preserves the local plan and a retry record.

PATCH /api/plans/{plan_id}/slots/{date}/{meal_type} applies a weekly exception with revision, eater_ids, group_meal, kind, max_effort, and theme. It replaces that dinner's current assignments while leaving the reusable routine unchanged. Draft regeneration preserves deliberate choices and labels; otherwise weekly exceptions take precedence over routines, then configured defaults. Dinner matching considers the week's constraints together so a valid constrained dinner is not lost to an earlier unconstrained random choice.

## Shared groceries

GET /api/plans/{plan_id}/groceries returns the derived list with its own revision, warnings, and items. POST adds a manual name/amount/unit entry and requires that revision. PATCH /api/plans/{plan_id}/groceries/{item_id} requires revision and accepts checked, excluded (already owned), needs_review, or active (manual items only).

List synchronization combines compatible ingredient quantities divided by meal yield for each planned diner. Amounts are decimal strings. g/kg/mg combine as mass; ml/l and US tsp/tbsp/cup combine as volume; each/item combine as counts. Other units combine only with identical normalized units. No mass/volume or ingredient-density conversion is guessed.

Missing ingredient records and unassigned meals produce warnings. Removed generated requirements become inactive; manual extras remain. Changed/reintroduced quantities clear purchased/already-owned marks, retain previous_amount, and set needs_review. A stale shopping mutation returns 409 without overwriting another shopper's state. Marking an item purchased or already owned acknowledges the current quantity.

Known input failures return a JSON error and an appropriate 400/403/404/409 status; HTTP method/content-type errors use their normal HTTP status. A provider failure returns 502.

## Ownership and recovery

- GET /api/export downloads portable JSON.
- POST /api/import accepts a native export or the legacy PostgreSQL export format. Requires an empty installation; success returns 201.
- GET /api/backup downloads a consistent SQLite database backup.
- CLI restore creates a new destination only. It does not replace an active database.

Native export envelope:

~~~json
{
  "format": "meal-roulette",
  "version": 2,
  "data": {
    "settings": [{"key": "instance_id", "value": "32-lowercase-hexadecimal-characters"}],
    "eaters": [],
    "meals": [],
    "eater_meal_preferences": [],
    "plans": [],
    "assignments": [],
    "routines": [],
    "slot_overrides": [],
    "ingredients": [],
    "meal_ingredients": [],
    "shopping_state": [],
    "shopping_items": [],
    "calendar_publications": [],
    "calendar_jobs": [],
    "calendar_state": []
  }
}
~~~

Rows contain the documented SQLite table columns; plan meal_types is represented as a JSON array. IDs and references remain intact. Plan dates and assignment dates are ISO calendar dates; timestamps are ISO strings. All tables, including empty ones, must be present. Export is taken in a read transaction; import is an all-or-nothing write transaction.

The database has an application identifier and schema version 2. Version 1 databases upgrade transactionally; native version 1 JSON exports remain importable, with defaults for new fields. Unsupported/newer formats are refused instead of being reinitialized. Future schema changes must include a migration and recovery story; new application versions must not silently discard existing household data. Household installation identity is part of export/recovery so Calendar event IDs remain stable.

The legacy envelope uses format meal-roulette-postgres, version 1, an exported_at timestamp, and the four original tables under data. Each meal_schedule row is placed into the appropriate Monday-based confirmed plan. PostgreSQL is read only; conversion is applied to the export, not the source database.

Database backups are created through SQLite's online backup API, including committed WAL content. Restore validates the SQLite integrity, foreign-key references, application identity, and version, then copies into a new destination. Environment settings and optional integration credentials are configured separately.
