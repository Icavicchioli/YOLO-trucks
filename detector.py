"""YOLO detection and depot-specific event evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

from ultralytics import YOLO

from zones import TRUCK_ZONE_KEYS, point_in_box


@dataclass
class Detection:
    label: str
    confidence: float
    bbox: List[int]
    centroid: tuple[int, int]


class DepotDetector:
    def __init__(
        self,
        model_path: str,
        conf_threshold: float,
        img_size: int,
        allowed_labels: Sequence[str] | None = None,
    ) -> None:
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.img_size = img_size
        self.allowed_labels = {label.lower() for label in (allowed_labels or [])}

    def detect(self, frame) -> List[Detection]:
        result = self.model(frame, imgsz=self.img_size, conf=self.conf_threshold, verbose=False)[0]
        boxes = result.boxes
        detections: List[Detection] = []
        if boxes is None or len(boxes) == 0:
            return detections

        xyxy_arr = boxes.xyxy.cpu().numpy()
        conf_arr = boxes.conf.cpu().numpy()
        cls_arr = boxes.cls.cpu().numpy().astype(int)

        for xyxy, conf, cls_idx in zip(xyxy_arr, conf_arr, cls_arr):
            x1, y1, x2, y2 = [int(v) for v in xyxy]
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            label = str(self.model.names.get(cls_idx, cls_idx)).lower()
            if self.allowed_labels and label not in self.allowed_labels:
                continue
            detections.append(
                Detection(
                    label=label,
                    confidence=float(conf),
                    bbox=[x1, y1, x2, y2],
                    centroid=(cx, cy),
                )
            )
        return detections

    def evaluate(self, detections: List[Detection], zones: Dict[str, List[int]]) -> Dict[str, object]:
        truck_occupancy: Dict[str, bool] = {}
        zone_has_warning_object: Dict[str, bool] = {}
        for key in TRUCK_ZONE_KEYS:
            box = zones[key]
            occupied = any(
                det.label == "truck" and point_in_box(det.centroid[0], det.centroid[1], box)
                for det in detections
            )
            warning_in_zone = any(
                det.label != "truck" and point_in_box(det.centroid[0], det.centroid[1], box)
                for det in detections
            )
            truck_occupancy[key] = occupied
            zone_has_warning_object[key] = warning_in_zone

        warning_messages: List[str] = []
        for det in detections:
            x, y = det.centroid
            if det.label == "truck":
                continue
            if det.label == "car" and point_in_box(x, y, zones["warn_car"]):
                warning_messages.append("car detected")

        unique_warnings = list(dict.fromkeys(warning_messages))
        zone_state: Dict[str, str] = {}
        for key in TRUCK_ZONE_KEYS:
            if zone_has_warning_object[key]:
                zone_state[key] = "warning"
            elif truck_occupancy[key]:
                zone_state[key] = "occupied"
            else:
                zone_state[key] = "free"

        return {
            "truck_occupancy": truck_occupancy,
            "warnings": unique_warnings,
            "truck_zone_state": zone_state,
        }
