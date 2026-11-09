"""Synthetic household for the native-client CI tests; never reads real household data."""

import os
from pathlib import Path
import tempfile

from waitress import serve

from app import create_app


def main():
    with tempfile.TemporaryDirectory(prefix="meal-roulette-native-test-") as folder:
        app = create_app({"DATABASE": str(Path(folder) / "fixture.sqlite3"), "SECRET_KEY": "native-test-only", "TESTING": True})
        client = app.test_client()
        eaters = [client.post("/api/eaters", json={"name": name}).json["eater_id"] for name in ("Alex", "Sam")]
        for index in range(9):
            meal = client.post("/api/meals", json={"meal_description": f"Dinner {index+1}", "meal_type": "dinner", "effort_level": 1, "servings": "2"}).json["meal_id"]
            for eater in eaters:
                client.post("/api/preferences", json={"eater_id": eater, "meal_id": meal})
            client.put(f"/api/meals/{meal}/ingredients", json={"ingredients": [{"name": "Onion", "amount": "1", "unit": "each"}]})
        response = client.post("/api/plans", json={"week_start": "2026-11-09"})
        assert response.status_code == 201
        serve(app, host="127.0.0.1", port=int(os.environ.get("MEAL_ROULETTE_PORT", "5057")))


if __name__ == "__main__":
    main()
