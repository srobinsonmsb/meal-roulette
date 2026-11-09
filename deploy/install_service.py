#!/usr/bin/env python3
"""Install only Meal Roulette's user services; Tailscale routes are configured separately."""

import argparse
from pathlib import Path
import subprocess


def quote(value):
    return '"' + str(value).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-dir", type=Path, default=Path.home() / ".config/systemd/user")
    parser.add_argument("--write-only", action="store_true")
    parser.add_argument("--port", type=int, default=5057)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    root = Path(__file__).resolve().parent.parent
    python = root / ".venv/bin/python"
    if not python.exists():
        parser.error("Create the project's .venv first (uv sync --frozen).")
    common = (
        "[Service]\nType=oneshot\n"
        + f"WorkingDirectory={str(root).replace('%', '%%')}\n"
    )
    units = {
        "meal-roulette.service": (
            "[Unit]\nDescription=Meal Roulette household planner\nAfter=network.target\n\n"
            "[Service]\nType=simple\n"
            + f"WorkingDirectory={str(root).replace('%', '%%')}\n"
            + f"Environment=MEAL_ROULETTE_PORT={args.port}\nEnvironment=PYTHONUNBUFFERED=1\n"
            + f"ExecStart={quote(python)} -m app.server\nRestart=on-failure\nRestartSec=3\nTimeoutStopSec=15\nNoNewPrivileges=true\n\n[Install]\nWantedBy=default.target\n"
        ),
        "meal-roulette-calendar.service": "[Unit]\nDescription=Publish queued Meal Roulette calendar updates\n\n" + common + f"ExecStart={quote(python)} -m flask --app app sync-calendar\n",
        "meal-roulette-calendar.timer": "[Unit]\nDescription=Retry Meal Roulette calendar updates\n\n[Timer]\nOnBootSec=2m\nOnUnitActiveSec=60s\nUnit=meal-roulette-calendar.service\n\n[Install]\nWantedBy=timers.target\n",
        "meal-roulette-backup.service": "[Unit]\nDescription=Run due Meal Roulette backups\n\n" + common + f"ExecStart={quote(python)} -m flask --app app backup-due\n",
        "meal-roulette-backup.timer": "[Unit]\nDescription=Check optional Meal Roulette backup schedule\n\n[Timer]\nOnBootSec=5m\nOnUnitActiveSec=1h\nUnit=meal-roulette-backup.service\n\n[Install]\nWantedBy=timers.target\n",
    }
    args.unit_dir.mkdir(parents=True, exist_ok=True)
    for name, contents in units.items():
        (args.unit_dir / name).write_text(contents)
    print(f"Wrote {len(units)} Meal Roulette units to {args.unit_dir}")
    if not args.write_only:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "meal-roulette.service", "meal-roulette-calendar.timer", "meal-roulette-backup.timer"], check=True)
        subprocess.run(["systemctl", "--user", "restart", "meal-roulette.service"], check=True)


if __name__ == "__main__":
    main()
