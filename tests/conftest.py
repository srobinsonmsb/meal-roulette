import pytest

from app import create_app


@pytest.fixture
def make_app(tmp_path):
    def factory(name="household", **config):
        return create_app({
            "TESTING": True, "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / (name + ".sqlite3")), **config,
        })
    return factory


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded(client):
    eaters = []
    for name in ("Scott", "Lee"):
        response = client.post("/api/eaters", json={"name": name})
        assert response.status_code == 201
        eaters.append(response.json["eater_id"])
    meals = []
    for index in range(9):
        response = client.post("/api/meals", json={"meal_description": f"Dinner {index}", "meal_type": "dinner"})
        assert response.status_code == 201
        meal = response.json["meal_id"]
        meals.append(meal)
        for eater in eaters:
            assert client.post("/api/preferences", json={"eater_id": eater, "meal_id": meal}).status_code == 204
    solo = client.post("/api/meals", json={"meal_description": "Scott's breakfast", "meal_type": "breakfast"}).json["meal_id"]
    client.post("/api/preferences", json={"eater_id": eaters[0], "meal_id": solo})
    return {"eaters": eaters, "meals": meals, "solo": solo}
