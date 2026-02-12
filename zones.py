"""Zone definitions and helpers for centroid-in-box checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

Box = List[int]
ZoneMap = Dict[str, Box]

TRUCK_ZONE_KEYS = ("truck_space_1", "truck_space_2", "truck_space_3")
WARNING_ZONE_KEYS = ("warn_car",)

DEFAULT_ZONES: ZoneMap = {
    "truck_space_1": [40, 260, 300, 520],
    "truck_space_2": [330, 260, 620, 520],
    "truck_space_3": [650, 260, 930, 520],
    "warn_car": [0, 0, 960, 540],
}


def normalize_box(box: Box, frame_w: int | None = None, frame_h: int | None = None) -> Box:
    x1, y1, x2, y2 = box
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))

    if frame_w is not None:
        left = max(0, min(left, frame_w - 1))
        right = max(0, min(right, frame_w - 1))
    if frame_h is not None:
        top = max(0, min(top, frame_h - 1))
        bottom = max(0, min(bottom, frame_h - 1))

    return [left, top, right, bottom]


def point_in_box(x: int, y: int, box: Box) -> bool:
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def load_zones(path: str, frame_w: int, frame_h: int) -> ZoneMap:
    zone_file = Path(path)
    if not zone_file.exists():
        save_zones(path, DEFAULT_ZONES)
        return dict(DEFAULT_ZONES)

    data = json.loads(zone_file.read_text(encoding="utf-8"))
    zones: ZoneMap = dict(DEFAULT_ZONES)
    for key, value in data.items():
        if key not in zones:
            continue
        if not isinstance(value, list) or len(value) != 4:
            continue
        zones[key] = normalize_box([int(v) for v in value], frame_w, frame_h)
    return zones


def save_zones(path: str, zones: ZoneMap) -> None:
    zone_file = Path(path)
    serializable = {key: [int(v) for v in box] for key, box in zones.items()}
    zone_file.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
