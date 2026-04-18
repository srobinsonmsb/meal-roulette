
import psycopg2
import os
import dotenv

dotenv.load_dotenv()

user = os.getenv("DB_USER")
password = os.getenv("DB_PASSWORD")
host = os.getenv("DB_HOST")
port = os.getenv("DB_PORT")
database = os.getenv("DB_NAME")

def get_connection():
    conn = psycopg2.connect(
        database=database,
        user=user,
        password=password,
        host=host,
        port=port
    )
    return conn, conn.cursor()

def get_eater_ids(cur):
    cur.execute("SELECT eater_id FROM eaters")
    eaters = cur.fetchall()
    return [eater[0] for eater in eaters]

def get_eater_names(cur):
    cur.execute("SELECT eater_id, name FROM eaters")
    eaters = cur.fetchall()
    return {eater[0]: eater[1] for eater in eaters}

def assign_solo_meal(cur, eater_id, meal_type, exclude):
    cur.execute("""
        SELECT m.meal_id
        FROM meals m
        JOIN eater_meal_preferences p ON m.meal_id = p.meal_id
        WHERE p.eater_id = %s
        AND m.meal_type = %s
        AND m.meal_id != ALL(%s)
        ORDER BY random()
        LIMIT 1
    """, (eater_id, meal_type, exclude))
    result = cur.fetchone()
    return result[0] if result else None


def assign_group_meal(cur, eater_ids, meal_type, exclude):
    cur.execute("""
        SELECT p.meal_id
        FROM eater_meal_preferences p
        JOIN eaters e ON e.eater_id = p.eater_id
        JOIN meals m ON m.meal_id = p.meal_id
        WHERE e.eater_id = ANY(%s)
        AND m.meal_type = %s
        and m.meal_id != ALL(%s)
        GROUP BY p.meal_id
        HAVING count(*) = %s
        ORDER BY random()
        LIMIT 1
    """, (list(eater_ids), meal_type, exclude, len(eater_ids)))
    result = cur.fetchone()
    return result[0] if result else None

def assign_meals(cur, eater_schedule, eater_ids):
    assigned_group_meals = {}
    used_dinner_ids = []

    for (eater_id, date, meal_type), slot in eater_schedule.items():
        if slot["meal_id"] is not None:
            continue

        exclude = used_dinner_ids if meal_type == "dinner" else []

        if slot["group"]:
            group_key = (date, meal_type)
            if group_key not in assigned_group_meals:
                meal_id = assign_group_meal(cur, eater_ids, meal_type, exclude)
                assigned_group_meals[group_key] = meal_id
            slot["meal_id"] = assigned_group_meals[group_key]
        else:
            slot["meal_id"] = assign_solo_meal(cur, eater_id, meal_type, exclude)

        if meal_type == "dinner" and slot["meal_id"] is not None:
            used_dinner_ids.append(slot["meal_id"])

    return eater_schedule

def save_schedule_to_db(cur, eater_schedule):
    for (eater_id, date, meal_type), slot in eater_schedule.items():
        cur.execute("""
            INSERT INTO meal_schedule (eater_id, date, meal_type, meal_id, eat_out, group_meal)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (eater_id, date, meal_type)
            DO UPDATE SET
                meal_id = EXCLUDED.meal_id,
                eat_out = EXCLUDED.eat_out,
                group_meal = EXCLUDED.group_meal
        """, (eater_id, date, meal_type, slot["meal_id"], slot["eat_out"], slot["group"]))