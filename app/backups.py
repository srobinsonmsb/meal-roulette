"""Opt-in scheduled database backups to owner-configured local/rclone storage."""

from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from .db import DataError


def atomic_json(path, document):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x") as file:
            temporary.chmod(0o600)
            json.dump(document, file, indent=2)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class Backups:
    def __init__(self, database, uploader=None):
        self.database = database
        self.config_path = database.path.with_suffix(".backup-config.json")
        self.state_path = database.path.with_suffix(".backup-status.json")
        self.folder = database.path.parent / (database.path.stem + "-backups")
        self.uploader = uploader

    def configure(self, destination, interval_hours=24):
        if not isinstance(destination, str) or not re.fullmatch(r"[A-Za-z0-9_-]+:[^\r\n]*", destination):
            raise DataError("Use local:/absolute/directory or a configured rclone remote:path.")
        if destination.startswith("local:") and not Path(destination[6:]).is_absolute():
            raise DataError("Local backup storage must use an absolute directory.")
        if type(interval_hours) is not int or not 1 <= interval_hours <= 8760:
            raise DataError("Backup interval must be between 1 and 8760 hours.")
        atomic_json(self.config_path, {"enabled": True, "destination": destination, "interval_hours": interval_hours})
        return self.status()

    def disable(self):
        atomic_json(self.config_path, {"enabled": False})

    def status(self):
        config = json.loads(self.config_path.read_text()) if self.config_path.exists() else {"enabled": False}
        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        return {**config, **state}

    def _upload(self, source, destination):
        if self.uploader:
            return self.uploader(source, destination)
        if destination.startswith("local:"):
            path = Path(destination[6:])
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as data, path.open("xb") as output:
                shutil.copyfileobj(data, output)
            return
        binary = shutil.which("rclone")
        if not binary:
            raise DataError("Install rclone and configure an owner-selected remote before enabling cloud uploads.")
        result = subprocess.run([binary, "copyto", str(source), destination, "--immutable", "--timeout", "60s", "--retries", "2"], capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise DataError("Backup upload failed. The local snapshot was retained; check the configured remote.")

    def run(self, *, force=False):
        lock_path = self.database.path.with_suffix(".backup.lock")
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self.status()
            if not state["enabled"]:
                return {"disabled": True, "created": False}
            now = datetime.now(timezone.utc)
            if not force and state.get("last_success") and now - datetime.fromisoformat(state["last_success"]) < timedelta(hours=state["interval_hours"]):
                return {"disabled": False, "created": False, "due": False}
            self.folder.mkdir(parents=True, exist_ok=True)
            filename = "meal-roulette-" + now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".sqlite3"
            path = self.folder / filename
            try:
                self.database.backup(path)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                checksum = path.with_suffix(path.suffix + ".sha256")
                checksum.write_text(digest + "  " + filename + "\n")
                destination = state["destination"].rstrip("/") + "/" + filename
                self._upload(path, destination)
                self._upload(checksum, destination + ".sha256")
                atomic_json(self.state_path, {"last_success": now.isoformat(), "last_backup": filename, "last_error": None})
                return {"disabled": False, "created": True, "filename": filename}
            except Exception:
                atomic_json(self.state_path, {
                    "last_success": state.get("last_success"), "last_backup": state.get("last_backup"),
                    "last_error": "Backup failed; local snapshots are retained for recovery. Check the configured destination.",
                })
                raise
