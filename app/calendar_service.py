import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from config import calendar_id

SCOPES = ['https://www.googleapis.com/auth/calendar.events']


def get_calendar_service():
    creds = None
    token_path = os.path.join(os.path.dirname(__file__), 'token.json')
    creds_path = os.path.join(os.path.dirname(__file__), 'credentials.json')

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=8080)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)


def create_calendar_event(service, event):
    try:
        created_event = service.events().insert(calendarId=calendar_id, body=event).execute()
        print(f"Event created: {created_event.get('htmlLink')}")
        return created_event
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

#Each slot will get it's own event. If breakfast, the time will be 7-7:30, lunch is 12 to 12:30, and dinner is 6 to 6:30. If eating out, the meal name is ignored and the event is titled "Eating Out - {eater_name}". Each event will be created at times relative to the meal type (breakfast, lunch, dinner) but the date will be the same as the date of the meal in the schedule. The event description will include the meal name and eater name for that slot. If eating out, the event description will just include the eater name.
def create_events_for_schedule(service, eater_schedule, dry_run=False):
    time_mapping = {
        "breakfast": ("07:00:00", "07:30:00"),
        "lunch": ("12:00:00", "12:30:00"),
        "dinner": ("18:00:00", "18:30:00"),
    }

    for (eater_id, date, meal_type), slot in eater_schedule.items():
        start_time, end_time = time_mapping.get(meal_type, ("12:00:00", "12:30:00"))

        if slot["meal_id"] is None and not slot["eat_out"]:
            print(f"Skipping {slot['eater_name']} on {date} for {meal_type}: no meal assigned.")
            continue

        if slot["eat_out"]:
            summary = f"Eating Out - {slot['eater_name']}"
        else:
            summary = f"{slot['meal_name']} - {slot['eater_name']}"

        if dry_run:
            print(f"[DRY RUN] Would create: '{summary}' on {date} at {start_time}")
            continue

        event = {
            'summary': summary,
            'start': {
                'dateTime': f"{date}T{start_time}",
                'timeZone': 'America/Chicago',
            },
            'end': {
                'dateTime': f"{date}T{end_time}",
                'timeZone': 'America/Chicago',
            },
        }
        create_calendar_event(service, event)