"""RFID ingress/egress CSV utilities."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List

CSV_HEADERS = ["timestamp", "event", "tag_id", "notes"]


def ensure_csv(path: str) -> None:
    csv_file = Path(path)
    if csv_file.exists():
        return
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()


def add_rfid_event(path: str, event: str, tag_id: str, notes: str = "") -> None:
    """Placeholder write path until RFID hardware integration is available."""
    ensure_csv(path)
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "tag_id": tag_id,
        "notes": notes,
    }
    with Path(path).open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerow(record)


def read_rfid_events(path: str, limit: int = 200) -> List[Dict[str, str]]:
    ensure_csv(path)
    with Path(path).open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if limit > 0:
        rows = rows[-limit:]
    rows.reverse()
    return rows

