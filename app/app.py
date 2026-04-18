from flask import Flask, render_template, session, redirect, url_for, flash, request
import difflib
from db import get_connection, get_eater_ids, assign_meals, save_schedule_to_db, get_eater_names
from scheduler import backfill_eater_schedule, assign_meal_names, assign_eater_names, meal_order, reroll_slot, eat_out_slot
from config import build_weekly_schedule, get_upcoming_monday, get_dates_for_week, backfill_schedule_with_dates
from calendar_service import get_calendar_service, create_events_for_schedule
import os

app = Flask(__name__)
app.secret_key = 'meal-planner-secret-key'

def generate_schedule():
    conn, cur = get_connection()
    eater_ids = get_eater_ids(cur)

    weekly_schedule = build_weekly_schedule()
    upcoming_monday = get_upcoming_monday()
    dates_per_day = get_dates_for_week(upcoming_monday)
    schedule_with_dates = backfill_schedule_with_dates(weekly_schedule, dates_per_day)

    eater_schedule = backfill_eater_schedule(eater_ids, schedule_with_dates)
    assign_meals(cur, eater_schedule, eater_ids)
    assign_meal_names(cur, eater_schedule)
    assign_eater_names(cur, eater_schedule)

    cur.close()
    conn.close()

    return eater_schedule, eater_ids

eater_schedule = None
eater_ids = None
slot_lookup = None


@app.route('/')
def home():
    global eater_schedule, eater_ids
    global slot_lookup
    slot_lookup = {}
    if eater_schedule is None:
        eater_schedule, eater_ids = generate_schedule()

    sorted_keys = sorted(eater_schedule.keys(), key=lambda x: (x[1], meal_order[x[2]], x[0]))
    schedule_list = []
    for index, (eater_id, date, meal_type) in enumerate(sorted_keys):
        slot = eater_schedule[(eater_id, date, meal_type)]
        schedule_list.append({
            'index': index + 1,
            'eater_name': slot.get('eater_name', 'Unknown'),
            'date': str(date),
            'meal_type': meal_type,
            'meal_name': slot.get('meal_name', 'No meal assigned'),
            'eat_out': slot.get('eat_out', False),
            'group': slot.get('group', False),
        })
        slot_lookup[index + 1] = (eater_id, date, meal_type)

    return render_template('index.html', schedule=schedule_list)


@app.route('/reroll/<int:slot_number>')
def reroll(slot_number):
    global eater_schedule, eater_ids, slot_lookup
    if eater_schedule is None:
        return redirect(url_for('home'))
    if slot_lookup is None:
        return redirect(url_for('home'))
    if slot_number in slot_lookup:
        conn, cur = get_connection()
        reroll_slot(cur, eater_schedule, slot_lookup, slot_number, eater_ids)
        assign_meal_names(cur, eater_schedule)
        cur.close()
        conn.close()
    return redirect(url_for('home'))

@app.route('/eat-out/<int:slot_number>')
def eat_out(slot_number):
    global eater_schedule, slot_lookup
    if eater_schedule is None:
        return redirect(url_for('home'))
    if slot_lookup is None:
        return redirect(url_for('home'))
    if slot_number in slot_lookup:
        eat_out_slot(eater_schedule, slot_lookup, slot_number)
    return redirect(url_for('home'))

@app.route('/confirm')
def confirm_schedule():
    global eater_schedule
    if eater_schedule is None:
        return redirect(url_for('home'))
    conn, cur = get_connection()
    save_schedule_to_db(cur, eater_schedule)
    conn.commit()
    cur.close()
    conn.close()

    flash("Schedule confirmed and saved to database.", "success")

    service = get_calendar_service()
    dry_run = True  # Set to False to actually create events in Google Calendar
    create_events_for_schedule(service, eater_schedule, dry_run=dry_run)

    if dry_run:
        flash("Dry run complete. Check console output for event details.", "info")
    else:
        flash("Calendar events created successfully.", "success")

    eater_schedule = None
    return redirect(url_for('home'))

@app.route('/regenerate')
def regenerate():
    global eater_schedule
    eater_schedule = None
    return redirect(url_for('home'))

@app.route('/manage/eaters')
def manage_eaters():
    conn, cur = get_connection()
    eaters = get_eater_names(cur)
    cur.close()
    conn.close()
    return render_template('manage_eaters.html', eaters=eaters)

@app.route('/manage/eaters/add', methods=['POST'])
def add_eater():
    eater_name = request.form.get('eater_name')
    if eater_name:
        conn, cur = get_connection()
        cur.execute("INSERT INTO eaters (name) VALUES (%s)", (eater_name,))
        conn.commit()
        cur.close()
        conn.close()
        flash(f"{eater_name} added.", "success")
    return redirect(url_for('manage_eaters'))

@app.route('/manage/eaters/delete/<int:eater_id>')
def delete_eater(eater_id):
    conn, cur = get_connection()
    cur.execute("DELETE FROM eater_meal_preferences WHERE eater_id = %s", (eater_id,))
    cur.execute("DELETE FROM meal_schedule WHERE eater_id = %s", (eater_id,))
    cur.execute("DELETE FROM eaters WHERE eater_id = %s", (eater_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash(f"Eater with ID {eater_id} deleted.", "success")
    return redirect(url_for('manage_eaters'))

@app.route('/manage/meals')
def manage_meals():
    conn, cur = get_connection()
    cur.execute("SELECT meal_id, meal_description, meal_type FROM meals")
    meals = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('manage_meals.html', meals=meals)

@app.route('/manage/meals/delete/<int:meal_id>')
def delete_meal(meal_id):
    conn, cur = get_connection()
    cur.execute("DELETE FROM meal_schedule WHERE meal_id = %s", (meal_id,))
    cur.execute("DELETE FROM eater_meal_preferences WHERE meal_id = %s", (meal_id,))
    cur.execute("DELETE FROM meals WHERE meal_id = %s", (meal_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('manage_meals'))

@app.route('/manage/meals/add', methods=['POST'])
def add_meal():
    meal_description = request.form.get('meal_description')
    meal_type = request.form.get('meal_type')
    if not (meal_description and meal_type):
        return redirect(url_for('manage_meals'))

    conn, cur = get_connection()
    cur.execute("SELECT meal_description FROM meals")
    existing = [row[0] for row in cur.fetchall()]

    if meal_description.lower() in [e.lower() for e in existing]:
        flash(f"A meal named '{meal_description}' already exists.", "error")
        cur.close()
        conn.close()
        return redirect(url_for('manage_meals'))

    close_matches = difflib.get_close_matches(meal_description, existing, n=3, cutoff=0.6)

    cur.execute("INSERT INTO meals (meal_description, meal_type) VALUES (%s, %s)", (meal_description, meal_type.lower()))
    conn.commit()
    cur.close()
    conn.close()

    if close_matches:
        flash(f"Meal '{meal_description}' added. Similar meals already exist: {', '.join(close_matches)}", "warning")
    else:
        flash(f"Meal '{meal_description}' added.", "success")

    return redirect(url_for('manage_meals'))

@app.route('/manage/preferences')
def manage_preferences():
    conn, cur = get_connection()
    cur.execute("SELECT eater_id, name FROM eaters")
    eaters = cur.fetchall()
    cur.execute("SELECT meal_id, meal_description FROM meals")
    meals = cur.fetchall()
    cur.execute("SELECT eater_id, meal_id FROM eater_meal_preferences")
    preferences = cur.fetchall()
    cur.close()
    conn.close()

    pref_dict = {eater_id: set() for eater_id, _ in eaters}
    for eater_id, meal_id in preferences:
        pref_dict[eater_id].add(meal_id)

    return render_template('manage_preferences.html', eaters=eaters, meals=meals, preferences=pref_dict)

@app.route('/manage/preferences/add', methods=['POST'])
def add_preference():
    eater_id = request.form.get('eater_id', type=int)
    meal_id = request.form.get('meal_id', type=int)
    if eater_id and meal_id:
        conn, cur = get_connection()
        cur.execute(
            "INSERT INTO eater_meal_preferences (eater_id, meal_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (eater_id, meal_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("Preference added.", "success")
    return redirect(url_for('manage_preferences'))

@app.route('/manage/preferences/delete/<int:eater_id>/<int:meal_id>')
def delete_preference(eater_id, meal_id):
    conn, cur = get_connection()
    cur.execute(
        "DELETE FROM eater_meal_preferences WHERE eater_id = %s AND meal_id = %s",
        (eater_id, meal_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    flash("Preference removed.", "success")
    return redirect(url_for('manage_preferences'))

app.run(host='0.0.0.0', port=5000, debug=True)