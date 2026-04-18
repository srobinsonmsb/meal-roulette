import datetime
import os
from dotenv import load_dotenv

load_dotenv()

calendar_id = os.getenv("GOOGLE_CALENDAR_ID")

def build_weekly_schedule():
    weekday = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    weekend = ["Saturday", "Sunday"]

    weekly_schedule = {}

    for day in weekday:
            weekly_schedule[(day, "breakfast")] = False
            weekly_schedule[(day, "lunch")] = False
            weekly_schedule[(day, "dinner")] = True

    for day in weekend:
            weekly_schedule[(day, "breakfast")] = True
            weekly_schedule[(day, "lunch")] = True
            weekly_schedule[(day, "dinner")] = True

    return weekly_schedule
    
def get_upcoming_monday():
    today = datetime.date.today()
    if today.weekday() == 0:  # Monday
        return today
    else:
        return today + datetime.timedelta((0 - today.weekday()) % 7)

def get_dates_for_week(start_date):
    dates = {}
    for i in range(7):
        date = start_date + datetime.timedelta(days=i)
        day_name = date.strftime("%A")
        dates[day_name] = date
    return dates


def backfill_schedule_with_dates(weekly_schedule, dates_per_day):
    schedule_with_dates = {}
    for (day, meal), value in weekly_schedule.items():
        if day in dates_per_day:
            date = dates_per_day[day]
            schedule_with_dates[(date, meal)] = value
    return schedule_with_dates

