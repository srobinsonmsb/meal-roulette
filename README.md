# Meal Roulette

A private, MIT-licensed household meal planner. Run one copy on your home server, plan the week together, and keep ownership of your data. There is no vendor login, advertising SDK, or central collection of household records.

## What it does

- Shared, durable draft and confirmed weekly plans, starting with dinner.
- Explicit per-person preference lists and shared/solo meal assignments.
- Quick/moderate/involved effort, themes, weekly routines, and per-date diner exceptions.
- Weekly dinner variety, with constrained days protected from losing their only candidate.
- Manual choices, rerolls, eating out, and simple leftovers labels.
- Meal ingredient amounts and yields; shared grocery quantities scaled to the people eating.
- Purchased/already-owned marks, manual shopping extras, and review when generated quantities change.
- One-way Google Calendar publication with stable event IDs, updates/removals, and durable retries.
- Versioned JSON export/import, online database backups, restore to a new installation, and legacy PostgreSQL conversion.
- An optional owner-configured local/cloud backup schedule.
- Web and native iOS clients of the same household server. See [the iOS project](ios/README.md).

Recipe instructions/imports, nutrition, other calendar/planner destinations, direct notifications, optional local authentication, and a device-only iOS edition remain [future branches](docs/roadmap.md).

## Start locally

Use Python 3.11 or newer. With uv:

~~~sh
uv sync --frozen
uv run flask --app app run
~~~

Open http://127.0.0.1:5000. For development access on your trusted household LAN, add --host 0.0.0.0. Alternatively, install app/requirements.txt in a virtual environment and run python -m app.

Add household members, named meals and preference lists, then create a week using its Monday date. Add ingredient amounts on each meal's details page to populate the grocery list. A recipe is not required.

SQLite is created automatically at instance/meal-roulette.sqlite3; no separate database service or Docker container is required. Keep the file on local disk and let clients connect over HTTP.

## Managed household server and Tailscale

~~~sh
uv sync --frozen
python3 deploy/install_service.py
systemctl --user status meal-roulette.service
tailscale serve --bg --https=8445 http://127.0.0.1:5057
~~~

Use the HTTPS URL printed by Tailscale. The server binds to loopback and trusts proxy headers only from loopback. The installer creates only Meal Roulette's own user service and Calendar/backup timers; it does not change Tailscale routes. Choose an unused Serve port to preserve other household services. Use loginctl enable-linger for your user if these services must persist after logout.

Configuration is optional. Copy app/.env.example to app/.env and set only the values you need. Useful options include MEAL_ROULETTE_DATABASE, MEAL_ROULETTE_DATA_DIR, MEAL_ROULETTE_TIMEZONE, and MEAL_ROULETTE_SECRET_KEY. The service installer accepts --port to change the local server port.

Health: GET /api/health. Operator logs: journalctl --user -u meal-roulette.service.

### Upgrading

1. With the old version, make a database backup and retain your private configuration.
2. Stop the application: systemctl --user stop meal-roulette.service.
3. Update the source and run uv sync --frozen.
4. Start the application: systemctl --user start meal-roulette.service.
5. Check /api/health and reopen a saved plan and grocery list.

Supported SQLite schema migrations run in a transaction at startup. Unknown/newer database versions are refused. Before downgrading code, restore a compatible backup into a new destination; do not open a newer database with older code.

## Planning and shopping rules

Effort levels are 1 quick, 2 moderate, and 3 involved. An effort-limited automatic choice excludes unknown effort. Automatic choices always require each relevant person's explicit approval. A draft with no possible choice leaves that assignment unfilled with an explanation.

Deliberate choices survive regeneration. A weekly exception overrides the reusable routine for that date; applying a new exception replaces that dinner's current assignments. Confirmed plans remain editable and stay confirmed.

Grocery amounts are divided by meal yield and multiplied by planned diners. Mass, volume, count, and custom units remain separate; compatible units combine. Cup, tbsp, and tsp use US measures. Missing ingredient records are shown as incomplete coverage. Changed generated quantities clear previous purchased/already-owned marks and need review; manual extras remain.

## Export and recovery

~~~sh
uv run flask --app app export-data instance/household.json
uv run flask --app app backup instance/household-backup.sqlite3
uv run flask --app app restore instance/household-backup.sqlite3 --destination /absolute/path/new-household.sqlite3
~~~

Point MEAL_ROULETTE_DATABASE at the restored file on startup. Restore never overwrites an existing destination.

Portable JSON imports require an empty installation and are atomic:

~~~sh
MEAL_ROULETTE_DATABASE=/absolute/path/new-empty.sqlite3 uv run flask --app app import-data instance/household.json
~~~

The browser also provides complete data-export and database-backup links. Exports include archived records, preferences, routines, exceptions, plans, assignments, shopping state, and publication mappings. Keep environment settings, provider configuration, and optional Google OAuth files separately.

### Optional automated backups

A local destination works without another tool:

~~~sh
uv run flask --app app configure-backup --destination local:/absolute/path/private-backups --interval-hours 24
uv run flask --app app backup-due --force
uv run flask --app app backup-status
~~~

For cloud storage, install rclone and configure a provider yourself, then use a destination such as chosen-remote:meal-backups. For encryption before upload, select an rclone crypt remote. Provider credentials remain in the owner's rclone configuration, not in application accounts.

The installed backup timer checks hourly; the configured interval controls when a snapshot is due. Snapshots and SHA-256 sidecars have unique names, do not overwrite existing backups, and are retained locally after upload failure. No automatic retention deletion is performed. Disable scheduling with disable-backups.

## Existing PostgreSQL household

The original schema.sql and docker-compose-example.yml describe the legacy installation. Keep it running, configure its DB_* settings in app/.env, and run:

~~~sh
uv run --extra migration flask --app app export-postgres instance/legacy-household.json
uv run flask --app app import-data instance/legacy-household.json
~~~

The source is read in a repeatable-read, read-only transaction. IDs, preferences, effort, dates, group/eating-out flags, and nullable assignments are preserved. Saved weeks become confirmed plans. Verify the imported records before switching clients. Prior Google events had no stored IDs, so they are not automatically adopted or deleted by the new integration.

## Google Calendar

Saving and confirming do not require Google libraries or credentials. Preview is available without contacting Google.

~~~sh
uv sync --frozen --extra calendar
uv run --extra calendar flask --app app authorize-google
~~~

Before authorizing, provide credentials.json under app/ or MEAL_ROULETTE_GOOGLE_DIR. Set GOOGLE_CALENDAR_ID and MEAL_ROULETTE_CALENDAR_ENABLED=true, then restart the managed server. Publishing a confirmed plan is an explicit action. After initial publication, confirmed-plan edits queue automatic updates; the Calendar timer processes retries each minute. Run sync-calendar manually to check or retry immediately.

The app updates/deletes only its managed events. Stable IDs make retries safe if the server stops between a provider response and saving local publication state. External Calendar edits do not alter the household plan.

## Development

~~~sh
uv sync --frozen --extra test
uv run --extra test pytest -q
python3 ios/generate_project.py
~~~

Backend tests exercise HTTP workflows using real temporary databases, plus migration/recovery and operator commands. Calendar and backup providers have controlled doubles. Native CI builds and tests the SwiftUI client against a synthetic local backend and produces a simulator artifact; it never accesses real household data.

See [the HTTP/data contract](docs/backend-interface.md), [domain glossary](GLOSSARY.md), [architecture decisions](docs/adr), and [iOS instructions](ios/README.md).

