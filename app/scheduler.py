
from db import get_connection, get_eater_ids, assign_group_meal, assign_solo_meal

def backfill_eater_schedule(eater_ids, schedule_with_dates):
    eater_schedule = {}
    for eater_id in eater_ids:
        for (date, meal), group in schedule_with_dates.items():
            eater_schedule[(eater_id, date, meal)] = {
                "date": date,
                "meal_type": meal,
                "group": group,
                "meal_id": None,
                "eat_out": False
            }
    return eater_schedule

def assign_meal_names(cur, eater_schedule):
    meal_ids = set(slot["meal_id"] for slot in eater_schedule.values() if slot["meal_id"] is not None)
    
    if not meal_ids:
        return eater_schedule
    
    cur.execute("SELECT meal_id, meal_description FROM meals WHERE meal_id = ANY(%s)", (list(meal_ids),))
    meal_names = dict(cur.fetchall())
    
    for slot in eater_schedule.values():
        slot["meal_name"] = meal_names.get(slot["meal_id"])
    
    return eater_schedule

def assign_eater_names(cur, eater_schedule):
    eater_ids = set(eater_id for (eater_id, _, _) in eater_schedule.keys())
    
    if not eater_ids:
        return eater_schedule
    
    cur.execute("SELECT eater_id, name FROM eaters WHERE eater_id = ANY(%s)", (list(eater_ids),))
    eater_names = dict(cur.fetchall())
    
    for (eater_id, _, _), slot in eater_schedule.items():
        slot["eater_name"] = eater_names.get(eater_id)
    
    return eater_schedule

meal_order = {"breakfast": 1, "lunch": 2, "dinner": 3}

def display_schedule(eater_schedule):
    slot_lookup = {}
    for index, (eater_id, date, meal_type) in enumerate(sorted(eater_schedule.keys(), key=lambda x: (x[1], meal_order[x[2]], x[0]))):
        slot = eater_schedule[(eater_id, date, meal_type)]
        meal_name = slot.get("meal_name", "No meal assigned")
        eater_name = slot.get("eater_name", "Unknown eater")
        eat_out_flag = " (Eating Out)" if slot.get("eat_out") else ""
        print(f"{index + 1}. {eater_name} on {date} for {meal_type}: {meal_name}{eat_out_flag}")
        slot_lookup[index + 1] = (eater_id, date, meal_type)
    return slot_lookup

def reroll_slot(cur, eater_schedule, slot_lookup, slot_number, eater_ids):
    if slot_number not in slot_lookup:
        print("Invalid slot number.")
        return
    
    eater_id, date, meal_type = slot_lookup[slot_number]
    slot = eater_schedule[(eater_id, date, meal_type)]
    
    if slot["group"]:
        new_meal_id = assign_group_meal(cur, eater_ids, meal_type, [slot["meal_id"]])

    else:
        new_meal_id = assign_solo_meal(cur, eater_id, meal_type, [slot["meal_id"]])
    
    if new_meal_id is None:
        print("No alternative meal available for this slot.")
        return
    
    cur.execute("SELECT meal_description FROM meals WHERE meal_id = %s", (new_meal_id,))
    result = cur.fetchone()
    if result:
        new_meal_name = result[0]
    else:
        new_meal_name = "Unknown meal"
    
    if slot["group"]:
        for (other_eater_id, other_date, other_meal_type), other_slot in eater_schedule.items():
            if other_date == date and other_meal_type == meal_type and other_slot["group"]:
                other_slot["meal_id"] = new_meal_id
                other_slot["meal_name"] = new_meal_name
    else:
        slot["meal_name"] = new_meal_name
        slot["meal_id"] = new_meal_id

    print(f"Slot {slot_number} has been rerolled with a new meal.")

# def eat_out_slot(cur, eater_schedule, slot_lookup, slot_number):
#     if slot_number not in slot_lookup:
#         print("Invalid slot number.")
#         return
#     else:
#         slot = eater_schedule[slot_lookup[slot_number]]
#         return
    
#     eater_id, date, meal_type = slot_lookup[slot_number]
#     slot = eater_schedule[(eater_id, date, meal_type)]
    
#     slot["eat_out"] = True
#     print(f"Slot {slot_number} has been flagged as eating out.")

def eat_out_slot(eater_schedule, slot_lookup, slot_number):
    if slot_number not in slot_lookup:
        print("Invalid slot number.")
        return

    eater_id, date, meal_type = slot_lookup[slot_number]
    slot = eater_schedule[(eater_id, date, meal_type)]

    slot["eat_out"] = True

    print(f"Slot {slot_number} has been flagged as eating out.")