# Meal Roulette

A self-hosted weekly meal planning tool that generates randomized meal schedules based on personal preferences, supports per-person meal assignments, and pushes confirmed plans to a shared Google Calendar.

Built as a learning project to practice Python, PostgreSQL, API integration, and web development on a Raspberry Pi.

## What It Does

- Generates a weekly meal schedule (Monday–Sunday) from a personal meal database
- Handles group meals (shared dinners, weekend meals) and solo meals (weekday breakfasts/lunches)
- Respects per-person meal preferences so each person only gets meals they like
- Prevents duplicate dinners across the week
- Lets you reroll individual meal slots or flag meals as eating out
- Saves confirmed schedules to PostgreSQL
- Pushes confirmed schedules to a shared Google Calendar
- Includes both a CLI and a Flask web interface
- Manage meals, eaters, and preferences through the web UI (add/delete, with duplicate detection on meal names)

## How It Works

**Schedule defaults:**
- Weekdays: breakfast and lunch are solo (each person gets their own meal), dinner is a group meal
- Weekends: all meals are group meals
- These defaults are configurable in `config.py`

**Workflow:**
1. Run the app (CLI or web)
2. Review the generated schedule
3. Reroll any meals you don't want that week
4. Flag any meals as eating out
5. Confirm to save to the database and push to Google Calendar

## Tech Stack

- **Python 3.11** — scheduling logic, CLI, and Flask web server
- **PostgreSQL 15** — meal data, preferences, and schedule storage (runs in Docker)
- **Flask** — web interface for schedule review and editing
- **Google Calendar API** — pushes confirmed meal events to a shared calendar
- **Docker & Docker Compose** — containerized database
- **Raspberry Pi 5** — always-on host for the database and web interface

## Project Structure

```
meal-roulette/
├── docker-compose.yml          # PostgreSQL container config
├── schema.sql                  # Database schema DDL
├── README.md
└── app/
    ├── .env                    # DB credentials, Google Calendar ID (not committed)
    ├── credentials.json        # Google OAuth client config (not committed)
    ├── token.json              # Google OAuth token (not committed)
    ├── requirements.txt
    ├── config.py               # Schedule defaults, date logic, env loading
    ├── db.py                   # Database connection and query functions
    ├── scheduler.py            # Schedule building, display, reroll, eat-out logic
    ├── calendar_service.py     # Google Calendar auth and event creation
    ├── main.py                 # CLI entry point
    ├── app.py                  # Flask web entry point
    └── templates/
        ├── index.html              # Main schedule view
        ├── manage_eaters.html      # Add/delete eaters
        ├── manage_meals.html       # Add/delete meals
        └── manage_preferences.html # Manage per-eater meal preferences
```

## Database Schema

The database uses four tables:

- **meals** — stores meal definitions with a name, type (breakfast/lunch/dinner via PostgreSQL ENUM), and effort level
- **eaters** — the people using the system
- **eater_meal_preferences** — a many-to-many junction table mapping which eaters like which meals
- **meal_schedule** — the generated weekly plan with a composite primary key of (date, meal_type, eater_id) and an upsert strategy for re-runnability

## Setup

### Prerequisites

- Docker and Docker Compose
- Python 3.11+
- A Google Cloud project with the Calendar API enabled and OAuth 2.0 credentials

### Installation

1. Clone the repo:
   ```bash
   git clone git@github.com:srobinsonmsb/meal-roulette.git
   cd meal-roulette
   ```

2. Start the database:
   ```bash
   docker compose up -d
   ```

3. Create the `.env` file in the `app/` directory:
   ```
   DB_USER=mealplanner
   DB_PASSWORD=your_password
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=meal_planner
   GOOGLE_CALENDAR_ID=your_calendar_id
   ```

4. Set up the Python environment:
   ```bash
   cd app
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

5. Create the database schema:
   ```bash
   docker exec -i meal-planner-db psql -U mealplanner -d meal_planner < schema.sql
   ```

6. Add your Google OAuth `credentials.json` to the `app/` directory. On first run, you'll need to complete the OAuth flow in a browser to generate `token.json`.

7. Start the web UI and use the manage pages (`/manage/eaters`, `/manage/meals`, `/manage/preferences`) to add eaters, meals, and preferences.

### Running

**CLI:**
```bash
cd app
source venv/bin/activate
python main.py
```

**Web UI:**
```bash
cd app
source venv/bin/activate
python app.py
```
Then visit `http://your-host-ip:5000` in a browser.

## Changelog

- **Web management pages** — Added `/manage/meals`, `/manage/eaters`, and `/manage/preferences` routes with full add/delete support. No more direct SQL needed for day-to-day data management.
- **Duplicate meal detection** — Adding a meal through the web UI now warns on exact matches (blocked) and fuzzy matches (flagged but allowed).
- **Flask confirm/regenerate routes** — Schedule confirmation now saves to the database and pushes to Google Calendar. Regenerate clears the current schedule for a fresh draw.
- **Google Calendar dry run mode** — Calendar pushes default to dry run; set `dry_run = False` in `confirm_schedule()` to go live.
- **Database schema file** — `schema.sql` added to the repo root for easier setup.

## Future Plans

- Ingredient-level grocery list generation
- Nutritional data tracking
- Meal constraint rules (no repeat proteins, themed nights)
- Active/inactive meal flagging
- Improved web UI with better styling and mobile support
