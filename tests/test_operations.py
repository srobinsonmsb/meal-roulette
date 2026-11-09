from pathlib import Path
import sqlite3
import subprocess
import sys

from test_household import create_plan


def test_version_one_database_upgrades_without_losing_household(make_app, tmp_path):
    path = tmp_path / "version-one.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(Path("app/schema.sql").read_text())
        connection.execute("PRAGMA application_id=1297241164")
        connection.execute("PRAGMA user_version=1")
        connection.execute("INSERT INTO eaters(eater_id,name) VALUES (12,'Scott')")
        connection.execute("INSERT INTO meals(meal_id,meal_description,meal_type,effort_level) VALUES (42,'Chili','dinner',3)")
        connection.execute("INSERT INTO eater_meal_preferences VALUES (12,42)")
        connection.execute("INSERT INTO plans VALUES (5,'2026-11-09','confirmed',7,'[\"dinner\"]','2026-11-08','2026-11-08','2026-11-08')")
        connection.execute("INSERT INTO assignments VALUES (5,12,'2026-11-09','dinner',42,1,'meal')")
    client = make_app("version-one").test_client()
    plan = client.get("/api/plans/5").json
    assert plan["revision"] == 7 and plan["state"] == "confirmed"
    assert plan["assignments"][0]["meal_id"] == 42
    assert client.get("/api/health").json["schema_version"] == 2
    assert client.get("/api/meals").json[0]["servings"] == "1"
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_scheduled_local_backup_and_restore(app, client, seeded, make_app, tmp_path):
    create_plan(client)
    destination = tmp_path / "owner-backups"
    runner = app.test_cli_runner()
    assert runner.invoke(args=["configure-backup", "--destination", "local:" + str(destination)]).exit_code == 0
    result = runner.invoke(args=["backup-due"])
    assert result.exit_code == 0, result.output
    files = list(destination.glob("*.sqlite3"))
    assert len(files) == 1 and files[0].with_suffix(".sqlite3.sha256").exists()
    assert runner.invoke(args=["backup-due"]).exit_code == 0
    assert len(list(destination.glob("*.sqlite3"))) == 1
    restore = tmp_path / "scheduled-restore.sqlite3"
    assert runner.invoke(args=["restore", str(files[0]), "--destination", str(restore)]).exit_code == 0
    assert make_app("scheduled-restore").test_client().get("/api/export").json == client.get("/api/export").json
    assert runner.invoke(args=["disable-backups"]).exit_code == 0
    assert '"disabled": true' in runner.invoke(args=["backup-due", "--force"]).output


def test_backup_provider_failure_preserves_local_snapshot_and_records_status(make_app, tmp_path):
    def unavailable(source, destination):
        raise RuntimeError("Unavailable remote")

    app = make_app("failed-backup", BACKUP_UPLOADER=unavailable)
    runner = app.test_cli_runner()
    assert runner.invoke(args=["configure-backup", "--destination", "chosen-provider:meal-backups"]).exit_code == 0
    assert runner.invoke(args=["backup-due"]).exit_code != 0
    snapshots = list((tmp_path / "failed-backup-backups").glob("*.sqlite3"))
    assert len(snapshots) == 1
    assert "local snapshots are retained" in runner.invoke(args=["backup-status"]).output.lower()
    assert app.test_client().get("/api/health").status_code == 200


def test_service_installer_write_only_creates_only_its_units(tmp_path):
    target = tmp_path / "units"
    result = subprocess.run([sys.executable, "deploy/install_service.py", "--write-only", "--unit-dir", str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert {path.name for path in target.iterdir()} == {
        "meal-roulette.service", "meal-roulette-calendar.service", "meal-roulette-calendar.timer",
        "meal-roulette-backup.service", "meal-roulette-backup.timer",
    }
    assert "app.server" in (target / "meal-roulette.service").read_text()
