from db import get_connection, get_eater_ids, assign_meals, save_schedule_to_db
from scheduler import backfill_eater_schedule, assign_meal_names, assign_eater_names, display_schedule, reroll_slot, eat_out_slot
from config import build_weekly_schedule, get_upcoming_monday, get_dates_for_week, backfill_schedule_with_dates
from calendar_service import get_calendar_service, create_events_for_schedule

def main():
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

    slot_lookup = display_schedule(eater_schedule)
    while True:
        print("\nEnter the slot number to reroll a meal, 'e' to flag row as eating out, 'q' to quit or 'c' to confirm:")
        user_input = input("Your choice: ")
        if user_input.lower() == 'q':
            break
        elif user_input.lower() == 'e':
            slot_number = int(input("Enter the slot number to flag as eating out: "))
            eat_out_slot(eater_schedule, slot_lookup, slot_number)
            slot_lookup = display_schedule(eater_schedule)
        elif user_input.lower() == 'c':
            print("Schedule confirmed.")
            save_schedule_to_db(cur, eater_schedule)
            conn.commit()
            print("Schedule saved to database.")
            service = get_calendar_service()
            create_events_for_schedule(service, eater_schedule)
            print("Calendar events created.")
            break
        else:
            try:
                slot_number = int(user_input)
                reroll_slot(cur, eater_schedule, slot_lookup, slot_number, eater_ids)
                slot_lookup = display_schedule(eater_schedule)
            except ValueError:
                print("Invalid input. Please enter a valid slot number or 'q' to quit.")
        
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()