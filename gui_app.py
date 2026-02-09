"""Tkinter GUI for truck monitoring + warning zones + RFID log view."""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

import cv2
from PIL import Image, ImageTk

from app_config import (
    CAMERA_INDEX,
    CONF_THRESHOLD,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    IMG_SIZE,
    MODEL_PATH,
    RFID_LOG_PATH,
    TARGET_DPS,
    WINDOW_TITLE,
    ZONES_PATH,
)
from detector import DepotDetector, Detection
from rfid_log import add_rfid_event, read_rfid_events
from zones import DEFAULT_ZONES, TRUCK_ZONE_KEYS, load_zones, normalize_box, save_zones


class DepotMonitorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)

        self.detector = DepotDetector(MODEL_PATH, CONF_THRESHOLD, IMG_SIZE)
        self.zones = load_zones(ZONES_PATH, FRAME_WIDTH, FRAME_HEIGHT)

        self.cap = None
        self.active_camera_index = CAMERA_INDEX
        self.available_camera_indices: list[int] = []
        self.camera_selection = tk.StringVar(value=str(CAMERA_INDEX))
        self.camera_status_text = tk.StringVar(value="Camera not connected")

        self.current_detections: list[Detection] = []
        self.last_detection_ts = 0.0
        self.running = True

        self.show_detections = tk.BooleanVar(value=True)
        self.show_centroids = tk.BooleanVar(value=True)
        self.show_zones = tk.BooleanVar(value=True)
        self.show_warnings = tk.BooleanVar(value=True)

        self.warning_text = tk.StringVar(value="No warnings")
        self.occupancy_text = tk.StringVar(value="")
        self.truck_zone_state: dict[str, str] = {k: "free" for k in TRUCK_ZONE_KEYS}

        self.edit_mode = False
        self.edit_zone_name = tk.StringVar(value=list(self.zones.keys())[0])
        self.drag_start: tuple[int, int] | None = None
        self.temp_box: list[int] | None = None

        self._build_layout()
        self.refresh_camera_list()
        if not self.connect_camera(self.active_camera_index) and self.available_camera_indices:
            self.connect_camera(self.available_camera_indices[0])
        self.refresh_rfid_table()
        self.update_occupancy_text({k: False for k in TRUCK_ZONE_KEYS})

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(10, self.update_frame)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=8)
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.video_label = ttk.Label(left)
        self.video_label.grid(row=0, column=0, sticky="nsew")
        self.video_label.bind("<ButtonPress-1>", self.on_mouse_down)
        self.video_label.bind("<B1-Motion>", self.on_mouse_drag)
        self.video_label.bind("<ButtonRelease-1>", self.on_mouse_up)

        controls = ttk.Frame(left, padding=(0, 8, 0, 0))
        controls.grid(row=1, column=0, sticky="ew")

        ttk.Checkbutton(controls, text="Show detections", variable=self.show_detections).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Checkbutton(controls, text="Show centroids", variable=self.show_centroids).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Checkbutton(controls, text="Show zones", variable=self.show_zones).grid(
            row=0, column=2, sticky="w"
        )
        ttk.Checkbutton(controls, text="Show warnings", variable=self.show_warnings).grid(
            row=0, column=3, sticky="w"
        )

        right = ttk.Frame(self, padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(8, weight=1)

        camera_frame = ttk.LabelFrame(right, text="Camera", padding=8)
        camera_frame.grid(row=0, column=0, sticky="ew")
        camera_frame.columnconfigure(0, weight=1)

        self.camera_combo = ttk.Combobox(
            camera_frame,
            state="readonly",
            textvariable=self.camera_selection,
            values=[],
        )
        self.camera_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(camera_frame, text="Refresh", command=self.refresh_camera_list).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk.Button(camera_frame, text="Apply", command=self.apply_camera_selection).grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk.Label(camera_frame, textvariable=self.camera_status_text).grid(row=1, column=0, columnspan=3, sticky="w")

        ttk.Label(right, text="Warnings", font=("Segoe UI", 11, "bold")).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Label(right, textvariable=self.warning_text, foreground="red").grid(row=2, column=0, sticky="w")

        ttk.Label(right, text="Truck occupancy", font=("Segoe UI", 11, "bold")).grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Label(right, textvariable=self.occupancy_text).grid(row=4, column=0, sticky="w")

        zone_frame = ttk.LabelFrame(right, text="Zone editor", padding=8)
        zone_frame.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        zone_frame.columnconfigure(0, weight=1)

        ttk.Label(zone_frame, text="Zone").grid(row=0, column=0, sticky="w")
        zone_picker = ttk.Combobox(
            zone_frame,
            state="readonly",
            textvariable=self.edit_zone_name,
            values=list(self.zones.keys()),
        )
        zone_picker.grid(row=1, column=0, sticky="ew", pady=(2, 6))

        self.edit_btn = ttk.Button(zone_frame, text="Start editing selected zone", command=self.toggle_edit_mode)
        self.edit_btn.grid(row=2, column=0, sticky="ew")

        ttk.Button(zone_frame, text="Save zones", command=self.save_zones_to_disk).grid(
            row=3, column=0, sticky="ew", pady=(6, 0)
        )
        ttk.Button(zone_frame, text="Reset zones", command=self.reset_zones).grid(
            row=4, column=0, sticky="ew", pady=(6, 0)
        )

        rfid_frame = ttk.LabelFrame(right, text="RFID ingress/egress (CSV)", padding=8)
        rfid_frame.grid(row=8, column=0, sticky="nsew", pady=(10, 0))
        rfid_frame.columnconfigure(0, weight=1)
        rfid_frame.rowconfigure(2, weight=1)

        entry_row = ttk.Frame(rfid_frame)
        entry_row.grid(row=0, column=0, sticky="ew")
        entry_row.columnconfigure(0, weight=1)
        self.tag_entry = ttk.Entry(entry_row)
        self.tag_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(entry_row, text="Ingress", command=self.log_ingress).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(entry_row, text="Egress", command=self.log_egress).grid(row=0, column=2, padx=(6, 0))

        ttk.Button(rfid_frame, text="Reload list", command=self.refresh_rfid_table).grid(
            row=1, column=0, sticky="ew", pady=(6, 6)
        )

        self.rfid_tree = ttk.Treeview(
            rfid_frame,
            columns=("timestamp", "event", "tag_id", "notes"),
            show="headings",
            height=12,
        )
        for col, width in (
            ("timestamp", 160),
            ("event", 90),
            ("tag_id", 120),
            ("notes", 180),
        ):
            self.rfid_tree.heading(col, text=col)
            self.rfid_tree.column(col, width=width, anchor="w")
        self.rfid_tree.grid(row=2, column=0, sticky="nsew")

    def on_mouse_down(self, event: tk.Event) -> None:
        if not self.edit_mode:
            return
        self.drag_start = (event.x, event.y)
        self.temp_box = [event.x, event.y, event.x, event.y]

    def on_mouse_drag(self, event: tk.Event) -> None:
        if not self.edit_mode or not self.drag_start:
            return
        self.temp_box = [self.drag_start[0], self.drag_start[1], event.x, event.y]

    def on_mouse_up(self, event: tk.Event) -> None:
        if not self.edit_mode or not self.drag_start:
            return
        self.temp_box = [self.drag_start[0], self.drag_start[1], event.x, event.y]
        zone = normalize_box(self.temp_box, FRAME_WIDTH, FRAME_HEIGHT)
        self.zones[self.edit_zone_name.get()] = zone
        self.drag_start = None
        self.temp_box = None

    def toggle_edit_mode(self) -> None:
        self.edit_mode = not self.edit_mode
        self.edit_btn.configure(
            text="Stop editing selected zone" if self.edit_mode else "Start editing selected zone"
        )

    def save_zones_to_disk(self) -> None:
        save_zones(ZONES_PATH, self.zones)
        messagebox.showinfo("Zones", f"Saved to {ZONES_PATH}")

    def reset_zones(self) -> None:
        self.zones = dict(DEFAULT_ZONES)
        save_zones(ZONES_PATH, self.zones)

    def log_ingress(self) -> None:
        tag = self.tag_entry.get().strip() or "manual-tag"
        add_rfid_event(RFID_LOG_PATH, "ingress", tag, "manual entry")
        self.tag_entry.delete(0, tk.END)
        self.refresh_rfid_table()

    def log_egress(self) -> None:
        tag = self.tag_entry.get().strip() or "manual-tag"
        add_rfid_event(RFID_LOG_PATH, "egress", tag, "manual entry")
        self.tag_entry.delete(0, tk.END)
        self.refresh_rfid_table()

    def refresh_rfid_table(self) -> None:
        for row_id in self.rfid_tree.get_children():
            self.rfid_tree.delete(row_id)
        for row in read_rfid_events(RFID_LOG_PATH, limit=250):
            self.rfid_tree.insert("", tk.END, values=(row["timestamp"], row["event"], row["tag_id"], row["notes"]))

    def probe_cameras(self, max_index: int = 10) -> list[int]:
        available: list[int] = []
        for idx in range(max_index + 1):
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                cap.release()
                continue
            ok, _ = cap.read()
            cap.release()
            if ok:
                available.append(idx)
        return available

    def refresh_camera_list(self) -> None:
        self.available_camera_indices = self.probe_cameras()
        values = [str(i) for i in self.available_camera_indices]
        self.camera_combo.configure(values=values)
        if values:
            if str(self.active_camera_index) in values:
                self.camera_selection.set(str(self.active_camera_index))
            else:
                self.camera_selection.set(values[0])
            self.camera_status_text.set("Select camera and click Apply")
        else:
            self.camera_selection.set("")
            self.camera_status_text.set("No camera found")

    def _open_camera(self, index: int):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        ok, _ = cap.read()
        if not ok:
            cap.release()
            return None
        return cap

    def connect_camera(self, index: int) -> bool:
        new_cap = self._open_camera(index)
        if new_cap is None:
            self.camera_status_text.set(f"Failed to open camera {index}")
            return False
        old_cap = self.cap
        self.cap = new_cap
        self.active_camera_index = index
        self.camera_selection.set(str(index))
        self.last_detection_ts = 0.0
        self.current_detections = []
        self.camera_status_text.set(f"Using camera {index}")
        if old_cap and old_cap.isOpened():
            old_cap.release()
        return True

    def apply_camera_selection(self) -> None:
        value = self.camera_selection.get().strip()
        if not value:
            messagebox.showwarning("Camera", "No camera selected")
            return
        try:
            index = int(value)
        except ValueError:
            messagebox.showwarning("Camera", "Invalid camera index")
            return
        if not self.connect_camera(index):
            messagebox.showerror("Camera", f"Could not open camera {index}")

    def update_occupancy_text(self, occupancy: dict[str, bool]) -> None:
        lines = []
        for key in TRUCK_ZONE_KEYS:
            state = self.truck_zone_state.get(key, "free")
            if state == "warning":
                status = "warning"
            else:
                status = "occupied" if occupancy.get(key, False) else "free"
            lines.append(f"{key}: {status}")
        self.occupancy_text.set(" | ".join(lines))

    def update_frame(self) -> None:
        if not self.running:
            return

        if self.cap is None:
            self.warning_text.set("No camera connected")
            self.after(200, self.update_frame)
            return

        ret, frame = self.cap.read()
        if not ret:
            self.warning_text.set("Camera read failed")
            self.after(200, self.update_frame)
            return

        frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
        now = time.perf_counter()
        if TARGET_DPS <= 0 or (now - self.last_detection_ts) >= (1.0 / TARGET_DPS):
            self.current_detections = self.detector.detect(frame)
            self.last_detection_ts = now

        eval_data = self.detector.evaluate(self.current_detections, self.zones)
        self.truck_zone_state = eval_data["truck_zone_state"]
        self.update_occupancy_text(eval_data["truck_occupancy"])
        warnings = eval_data["warnings"]
        self.warning_text.set(", ".join(warnings) if warnings else "No warnings")

        output = self.draw_overlays(frame, warnings)
        rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
        photo = ImageTk.PhotoImage(image=Image.fromarray(rgb))
        self.video_label.configure(image=photo)
        self.video_label.image = photo

        self.after(15, self.update_frame)

    def draw_overlays(self, frame, warnings: list[str]):
        output = frame.copy()

        if self.show_zones.get():
            for key, box in self.zones.items():
                x1, y1, x2, y2 = box
                if key.startswith("truck_space"):
                    zone_state = self.truck_zone_state.get(key, "free")
                    if zone_state == "occupied":
                        color = (0, 200, 0)  # green
                    elif zone_state == "warning":
                        color = (0, 255, 255)  # yellow
                    else:
                        color = (0, 0, 255)  # red
                elif key == "warn_car":
                    color = (0, 0, 255)
                elif key == "warn_person":
                    color = (0, 255, 255)
                else:
                    color = (180, 105, 255)
                cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
                cv2.putText(output, key, (x1, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        if self.show_detections.get():
            for det in self.current_detections:
                x1, y1, x2, y2 = det.bbox
                if det.label == "truck":
                    color = (0, 200, 0)
                elif det.label == "car":
                    color = (0, 0, 255)
                elif det.label == "person":
                    color = (0, 255, 255)
                else:
                    color = (180, 105, 255)

                cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
                text = f"{det.label} {det.confidence:.2f}"
                cv2.putText(output, text, (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

                if self.show_centroids.get():
                    cv2.circle(output, det.centroid, 4, color, -1)

        if self.edit_mode and self.temp_box:
            x1, y1, x2, y2 = normalize_box(self.temp_box, FRAME_WIDTH, FRAME_HEIGHT)
            cv2.rectangle(output, (x1, y1), (x2, y2), (255, 255, 255), 2)

        if self.show_warnings.get() and warnings:
            cv2.putText(
                output,
                " | ".join(warnings),
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2,
            )

        return output

    def on_close(self) -> None:
        self.running = False
        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.destroy()
