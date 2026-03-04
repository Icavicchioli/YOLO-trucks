"""Tkinter GUI for truck monitoring + warning zones + RFID log view."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import time
import tkinter as tk
from tkinter import messagebox, ttk

import cv2
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates
import matplotlib.ticker
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import Image, ImageTk

from app_config import (
    ALLOWED_LABELS,
    AVAILABLE_MODELS,
    CAMERA_INDEX,
    CONF_THRESHOLD,
    DETECTION_TTL_FRAMES,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    IMG_SIZE,
    MODEL_PATH,
    RFID_LOG_PATH,
    RFID_SERIAL_AUTOSTART,
    RFID_SERIAL_BAUDRATE,
    RFID_SERIAL_PORT,
    TARGET_DPS,
    WINDOW_TITLE,
    ZONES_PATH,
)
from detector import DepotDetector, Detection
from rfid_log import add_rfid_event, read_rfid_events
from rfid_serial_bridge import RFIDSerialBridge
from zones import DEFAULT_ZONES, TRUCK_ZONE_KEYS, load_zones, normalize_box, save_zones


@dataclass
class DetectionTrack:
    detection: Detection
    ttl_frames: int


class DepotMonitorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        self.configure(bg="#edf1f5")
        self.minsize(1280, 760)
        self._configure_opencv_logging()
        self._configure_styles()

        self._conf_var = tk.DoubleVar(value=CONF_THRESHOLD)
        self.detector = DepotDetector(MODEL_PATH, CONF_THRESHOLD, IMG_SIZE, ALLOWED_LABELS)
        self.detection_ttl_frames = max(1, DETECTION_TTL_FRAMES)
        self.active_detection_tracks: list[DetectionTrack] = []
        self.zones = load_zones(ZONES_PATH, FRAME_WIDTH, FRAME_HEIGHT)

        self.model_selection = tk.StringVar(value=MODEL_PATH)

        self.cap = None
        self.active_camera_index = CAMERA_INDEX
        self.available_camera_indices: list[int] = []
        self.camera_selection = tk.StringVar(value=str(CAMERA_INDEX))
        self.camera_status_text = tk.StringVar(value="Camera not connected")

        self.current_detections: list[Detection] = []
        self.last_detection_ts = 0.0
        self.running = True

        self.show_detections = tk.BooleanVar(value=True)
        self.show_centroids = tk.BooleanVar(value=False)
        self.show_zones = tk.BooleanVar(value=False)

        self.rfid_status_text = tk.StringVar(value="RFID serial: idle")
        self.truck_zone_state: dict[str, str] = {k: "free" for k in TRUCK_ZONE_KEYS}
        self.depot_card_widgets: dict[str, tuple[tk.Frame, tk.Label, tk.Label, tk.Label]] = {}
        self.dash_depot_card_widgets: dict[str, tuple[tk.Frame, tk.Label, tk.Label, tk.Label]] = {}
        self.rfid_bridge: RFIDSerialBridge | None = None

        self.occupancy_history: deque[tuple[datetime, dict[str, str]]] = deque(maxlen=300)
        self._last_history_ts = 0.0

        self.edit_mode = False
        self.edit_zone_name = tk.StringVar(value=list(self.zones.keys())[0])
        self.drag_start: tuple[int, int] | None = None
        self.temp_box: list[int] | None = None

        self._build_layout()
        self.refresh_camera_list()
        if not self.connect_camera(self.active_camera_index) and self.available_camera_indices:
            self.connect_camera(self.available_camera_indices[0])
        self.refresh_rfid_table()
        self.start_rfid_bridge()
        self.update_depot_indicators()
        self.after(350, self.poll_rfid_bridge)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(3000, self._update_dashboard_charts)
        self.after(10, self.update_frame)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background="#f0f2f5")
        style.configure(
            "App.TLabelframe",
            background="#ffffff",
            borderwidth=1,
            relief="solid",
            padding=10,
        )
        style.configure(
            "App.TLabelframe.Label",
            background="#ffffff",
            foreground="#1a1a2e",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure("App.TLabel", background="#f0f2f5", foreground="#1a1a2e", font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background="#f0f2f5", foreground="#6b7280", font=("Segoe UI", 9))
        style.configure("App.TNotebook", background="#f0f2f5", borderwidth=0)
        style.configure("App.TNotebook.Tab", font=("Segoe UI", 10), padding=(12, 6))
        self.configure(bg="#f0f2f5")

    def _build_banner(self) -> None:
        banner = tk.Frame(self, bg="#0f1923", pady=10)
        banner.grid(row=0, column=0, columnspan=2, sticky="ew")
        banner.columnconfigure(1, weight=1)

        # Branding izquierda
        left_brand = tk.Frame(banner, bg="#0f1923")
        left_brand.grid(row=0, column=0, sticky="w", padx=(20, 0))
        tk.Label(
            left_brand, text="UIA", bg="#0f1923", fg="#A100FF",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0)
        tk.Label(
            left_brand, text=" × ", bg="#0f1923", fg="#7a8a9a",
            font=("Segoe UI", 13),
        ).grid(row=0, column=1)
        tk.Label(
            left_brand, text="Accenture", bg="#0f1923", fg="#A100FF",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=2)

        # Título centro
        tk.Label(
            banner,
            text="Truck Depot Occupancy Control",
            bg="#0f1923",
            fg="#ffffff",
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=1)

        # Badge DEMO derecha
        badge_frame = tk.Frame(banner, bg="#A100FF", padx=10, pady=4)
        badge_frame.grid(row=0, column=2, sticky="e", padx=(0, 20))
        tk.Label(
            badge_frame, text="DEMO", bg="#A100FF", fg="white",
            font=("Segoe UI", 9, "bold"),
        ).pack()

    def _build_layout(self) -> None:
        self._build_banner()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        main_notebook = ttk.Notebook(self, style="App.TNotebook")
        main_notebook.grid(row=1, column=0, sticky="nsew")

        # ── Tab 0: Dashboard (full width, sin video) ──────────────────────
        tab_dash = ttk.Frame(main_notebook, padding=8, style="App.TFrame")
        main_notebook.add(tab_dash, text="Dashboard")
        self._build_dashboard_tab(tab_dash)

        # ── Tab 1: Series de tiempo ───────────────────────────────────────
        tab_series = ttk.Frame(main_notebook, padding=8, style="App.TFrame")
        main_notebook.add(tab_series, text="Series de tiempo")
        self._build_timeseries_tab(tab_series)

        self._draw_initial_charts()

        # ── Tab 2: Monitor (video + RFID) ─────────────────────────────────
        tab_monitor = ttk.Frame(main_notebook, style="App.TFrame")
        main_notebook.add(tab_monitor, text="Monitor")
        self._build_monitor_tab(tab_monitor)

        # ── Tab 3: Configuración ──────────────────────────────────────────
        tab_cfg = ttk.Frame(main_notebook, padding=8, style="App.TFrame")
        tab_cfg.columnconfigure(0, weight=1)
        main_notebook.add(tab_cfg, text="Configuración")
        self._build_config_tab(tab_cfg)

    def _build_monitor_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=3)
        parent.columnconfigure(1, weight=2)
        parent.rowconfigure(0, weight=1)

        # ── Izquierda: video + checkboxes + depot cards ───────────────────
        left = ttk.Frame(parent, padding=(10, 10, 10, 10), style="App.TFrame")
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.video_label = ttk.Label(left, anchor="center")
        self.video_label.grid(row=0, column=0, sticky="nsew")
        self.video_label.bind("<ButtonPress-1>", self.on_mouse_down)
        self.video_label.bind("<B1-Motion>", self.on_mouse_drag)
        self.video_label.bind("<ButtonRelease-1>", self.on_mouse_up)

        controls = ttk.Frame(left, padding=(0, 6, 0, 0), style="App.TFrame")
        controls.grid(row=1, column=0, sticky="ew")
        ttk.Checkbutton(controls, text="Detecciones", variable=self.show_detections).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(controls, text="Centroides", variable=self.show_centroids).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(controls, text="Zonas", variable=self.show_zones).grid(row=0, column=2, sticky="w")

        depot_frame = ttk.LabelFrame(left, text="Estado de depósitos", style="App.TLabelframe")
        depot_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        depot_frame.columnconfigure(0, weight=1)
        self.depot_cards_container = ttk.Frame(depot_frame)
        self.depot_cards_container.grid(row=0, column=0, sticky="ew")
        self.depot_cards_container.columnconfigure((0, 1, 2), weight=1)
        self._build_depot_indicators()

        # ── Derecha: RFID log ─────────────────────────────────────────────
        right = ttk.Frame(parent, padding=(0, 10, 10, 10), style="App.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        rfid_frame = ttk.LabelFrame(right, text="RFID ingress/egress", style="App.TLabelframe")
        rfid_frame.grid(row=0, column=0, sticky="nsew")
        rfid_frame.columnconfigure(0, weight=1)
        rfid_frame.rowconfigure(2, weight=1)

        entry_row = ttk.Frame(rfid_frame)
        entry_row.grid(row=0, column=0, sticky="ew")
        entry_row.columnconfigure(0, weight=1)
        self.tag_entry = ttk.Entry(entry_row)
        self.tag_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(entry_row, text="Ingress", command=self.log_ingress).grid(row=0, column=1, padx=(4, 0))
        ttk.Button(entry_row, text="Egress", command=self.log_egress).grid(row=0, column=2, padx=(4, 0))
        ttk.Button(entry_row, text="↺", command=self.refresh_rfid_table, width=2).grid(row=0, column=3, padx=(4, 0))

        ttk.Label(rfid_frame, textvariable=self.rfid_status_text, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 4)
        )

        self.rfid_tree = ttk.Treeview(
            rfid_frame,
            columns=("timestamp", "event", "tag_id"),
            show="headings",
            height=8,
        )
        for col, width in (("timestamp", 130), ("event", 70), ("tag_id", 100)):
            self.rfid_tree.heading(col, text=col)
            self.rfid_tree.column(col, width=width, anchor="w")
        self.rfid_tree.grid(row=2, column=0, sticky="nsew")

    def _build_config_tab(self, parent: ttk.Frame) -> None:
        model_frame = ttk.LabelFrame(parent, text="Modelo YOLO", style="App.TLabelframe")
        model_frame.grid(row=0, column=0, sticky="ew")
        model_frame.columnconfigure(0, weight=1)

        model_labels = [desc for _, desc in AVAILABLE_MODELS]
        model_paths = [path for path, _ in AVAILABLE_MODELS]
        current_desc = next(
            (desc for path, desc in AVAILABLE_MODELS if path == MODEL_PATH),
            model_labels[0],
        )
        self._model_paths = model_paths
        self._model_combo_var = tk.StringVar(value=current_desc)
        model_combo = ttk.Combobox(
            model_frame,
            state="readonly",
            textvariable=self._model_combo_var,
            values=model_labels,
        )
        model_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(model_frame, text="Apply", command=self.apply_model_selection).grid(
            row=0, column=1, padx=(6, 0)
        )
        self.model_status_text = tk.StringVar(value=f"Modelo activo: {MODEL_PATH}")
        ttk.Label(model_frame, textvariable=self.model_status_text, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        det_frame = ttk.LabelFrame(parent, text="Detección", style="App.TLabelframe")
        det_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        det_frame.columnconfigure(1, weight=1)

        self._conf_label = tk.StringVar(value=f"{CONF_THRESHOLD:.2f}")
        ttk.Label(det_frame, text="Umbral confianza").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Scale(
            det_frame,
            from_=0.05, to=0.95,
            orient="horizontal",
            variable=self._conf_var,
            command=self._on_conf_change,
        ).grid(row=0, column=1, sticky="ew")
        ttk.Label(det_frame, textvariable=self._conf_label, width=4).grid(row=0, column=2, padx=(6, 0))

        camera_frame = ttk.LabelFrame(parent, text="Cámara", style="App.TLabelframe")
        camera_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
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
        ttk.Label(camera_frame, textvariable=self.camera_status_text, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        zone_frame = ttk.LabelFrame(parent, text="Editor de zonas", style="App.TLabelframe")
        zone_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        zone_frame.columnconfigure(0, weight=1)

        ttk.Label(zone_frame, text="Zona").grid(row=0, column=0, sticky="w")
        zone_picker = ttk.Combobox(
            zone_frame,
            state="readonly",
            textvariable=self.edit_zone_name,
            values=list(self.zones.keys()),
        )
        zone_picker.grid(row=1, column=0, sticky="ew", pady=(2, 6))

        self.edit_btn = ttk.Button(zone_frame, text="Editar zona seleccionada", command=self.toggle_edit_mode)
        self.edit_btn.grid(row=2, column=0, sticky="ew")

        ttk.Button(zone_frame, text="Guardar zonas", command=self.save_zones_to_disk).grid(
            row=3, column=0, sticky="ew", pady=(6, 0)
        )
        ttk.Button(zone_frame, text="Resetear zonas", command=self.reset_zones).grid(
            row=4, column=0, sticky="ew", pady=(6, 0)
        )

        rfid_mgmt_frame = ttk.LabelFrame(parent, text="Registro RFID", style="App.TLabelframe")
        rfid_mgmt_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        rfid_mgmt_frame.columnconfigure(0, weight=1)
        ttk.Button(rfid_mgmt_frame, text="Eliminar todas las entradas", command=self.clear_rfid_log).grid(
            row=0, column=0, sticky="ew"
        )

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
            text="Detener edición" if self.edit_mode else "Editar zona seleccionada"
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

    def clear_rfid_log(self) -> None:
        if not messagebox.askyesno("Confirmar", "¿Eliminar todas las entradas del registro RFID?"):
            return
        from pathlib import Path
        csv_file = Path(RFID_LOG_PATH)
        if csv_file.exists():
            csv_file.unlink()
        self.refresh_rfid_table()

    def refresh_rfid_table(self) -> None:
        rows = read_rfid_events(RFID_LOG_PATH, limit=250)
        for tree in (self.rfid_tree, self.dash_rfid_tree):
            for row_id in tree.get_children():
                tree.delete(row_id)
            for row in rows:
                tree.insert("", tk.END, values=(row["timestamp"], row["event"], row["tag_id"]))

    def start_rfid_bridge(self) -> None:
        if not RFID_SERIAL_AUTOSTART:
            self.rfid_status_text.set("RFID serial: disabled")
            return

        self.rfid_bridge = RFIDSerialBridge(
            csv_path=RFID_LOG_PATH,
            port=RFID_SERIAL_PORT,
            baudrate=RFID_SERIAL_BAUDRATE,
            auto_scan=(RFID_SERIAL_PORT.strip() == ""),
        )
        self.rfid_bridge.start()
        self.rfid_status_text.set("RFID serial: starting")

    def poll_rfid_bridge(self) -> None:
        if not self.running:
            return
        table_changed = False
        if self.rfid_bridge is not None:
            for event in self.rfid_bridge.drain_events():
                if event.kind == "status":
                    self.rfid_status_text.set(f"RFID serial: {event.message}")
                elif event.kind == "rfid_event":
                    self.rfid_status_text.set(f"RFID serial: {event.message}")
                    table_changed = True
        if table_changed:
            self.refresh_rfid_table()
        self.after(350, self.poll_rfid_bridge)

    @staticmethod
    def _configure_opencv_logging() -> None:
        # Avoid noisy backend probing warnings on startup.
        try:
            cv2.setLogLevel(cv2.LOG_LEVEL_ERROR)
            return
        except Exception:
            pass
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except Exception:
            pass

    @staticmethod
    def _camera_backends() -> list[int]:
        backends: list[int] = []
        for name in ("CAP_DSHOW", "CAP_MSMF", "CAP_ANY"):
            backend = getattr(cv2, name, None)
            if isinstance(backend, int) and backend not in backends:
                backends.append(backend)
        return backends or [0]

    def probe_cameras(self, max_index: int = 10) -> list[int]:
        available: list[int] = []
        for idx in range(max_index + 1):
            for backend in self._camera_backends():
                cap = cv2.VideoCapture(idx, backend)
                if not cap.isOpened():
                    cap.release()
                    continue
                ok, _ = cap.read()
                cap.release()
                if ok:
                    available.append(idx)
                    break
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
        for backend in self._camera_backends():
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
            ok, _ = cap.read()
            if ok:
                return cap
            cap.release()
        return None

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
        self.active_detection_tracks = []
        self.camera_status_text.set(f"Using camera {index}")
        if old_cap and old_cap.isOpened():
            old_cap.release()
        return True

    def _on_conf_change(self, _value: str) -> None:
        val = self._conf_var.get()
        self._conf_label.set(f"{val:.2f}")
        self.detector.conf_threshold = val

    def apply_model_selection(self) -> None:
        selected_desc = self._model_combo_var.get()
        model_labels = [desc for _, desc in AVAILABLE_MODELS]
        try:
            idx = model_labels.index(selected_desc)
        except ValueError:
            return
        model_path = self._model_paths[idx]
        self.model_status_text.set(f"Cargando {model_path}…")
        self.update_idletasks()
        self.detector = DepotDetector(model_path, self._conf_var.get(), IMG_SIZE, ALLOWED_LABELS)
        self.model_status_text.set(f"Modelo activo: {model_path}")

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

    def _build_dashboard_tab(self, parent: ttk.Frame) -> None:
        # Dashboard sin series temporales por depósito.
        parent.columnconfigure(0, weight=50)
        parent.columnconfigure(1, weight=50)
        parent.rowconfigure(0, weight=0)
        parent.rowconfigure(1, weight=1)

        # ── Status cards (row 0, col 0) ────────────────────────────────────
        dash_depot_frame = ttk.LabelFrame(parent, text="Estado de depósitos", style="App.TLabelframe")
        dash_depot_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6), padx=(0, 4))
        dash_depot_frame.columnconfigure(0, weight=1)
        dash_cards_container = ttk.Frame(dash_depot_frame)
        dash_cards_container.grid(row=0, column=0, sticky="ew")
        dash_cards_container.columnconfigure((0, 1, 2), weight=1)

        for idx, key in enumerate(TRUCK_ZONE_KEYS):
            dash_cards_container.columnconfigure(idx, weight=1)
            card = tk.Frame(
                dash_cards_container,
                bg="#c94847", bd=1, relief="solid",
                padx=12, pady=8,
                highlightthickness=1, highlightbackground="#b73e3e", highlightcolor="#b73e3e",
            )
            card.grid(row=0, column=idx, sticky="ew", padx=(0, 6 if idx < len(TRUCK_ZONE_KEYS) - 1 else 0))
            card.columnconfigure(0, weight=1)
            title = tk.Label(card, text=f"Depósito {idx + 1}", bg="#c94847", fg="white",
                             font=("Segoe UI", 11, "bold"), anchor="w")
            title.grid(row=0, column=0, sticky="w")
            status = tk.Label(card, text="No disponible", bg="#c94847", fg="white",
                              font=("Segoe UI", 10), anchor="w", width=14)
            status.grid(row=1, column=0, sticky="w", pady=(2, 0))
            badge = tk.Label(card, text="NO DISPONIBLE", bg="#a63636", fg="white",
                             font=("Segoe UI", 8, "bold"), padx=8, pady=3, width=13, anchor="center")
            badge.grid(row=0, column=1, rowspan=2, sticky="e")
            self.dash_depot_card_widgets[key] = (card, title, status, badge)

        # ── Total occupancy chart (row 0, col 1) ──────────────────────────
        fig_total = Figure(figsize=(6.0, 2.2), dpi=90, facecolor="#f0f2f5")
        self._ax_total = fig_total.add_subplot(111)
        self._canvas_total = FigureCanvasTkAgg(fig_total, master=parent)
        self._canvas_total.get_tk_widget().grid(row=0, column=1, sticky="nsew", pady=(0, 4))

        # ── Bottom left: torta (row 1, col 0) ─────────────────────────────
        pie_container = ttk.Frame(parent, style="App.TFrame")
        pie_container.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        pie_container.columnconfigure(0, weight=1)
        pie_container.rowconfigure(0, weight=1)

        fig_pie = Figure(figsize=(5.4, 4.8), dpi=90, facecolor="#f0f2f5")
        fig_pie.subplots_adjust(left=0.05, right=0.95, top=0.90, bottom=0.06)
        self._ax_pie = fig_pie.add_subplot(111)
        self._canvas_pie = FigureCanvasTkAgg(fig_pie, master=pie_container)
        self._canvas_pie.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        # ── Bottom right: RFID (row 1, col 1) ─────────────────────────────
        dash_rfid_frame = ttk.LabelFrame(parent, text="RFID ingress/egress", style="App.TLabelframe")
        dash_rfid_frame.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
        dash_rfid_frame.columnconfigure(0, weight=1)
        dash_rfid_frame.rowconfigure(0, weight=1)
        self.dash_rfid_tree = ttk.Treeview(
            dash_rfid_frame,
            columns=("timestamp", "event", "tag_id"),
            show="headings",
            height=10,
        )
        for col, width in (("timestamp", 130), ("event", 70), ("tag_id", 100)):
            self.dash_rfid_tree.heading(col, text=col)
            self.dash_rfid_tree.column(col, width=width, anchor="w")
        self.dash_rfid_tree.grid(row=0, column=0, sticky="nsew")

    def _build_timeseries_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        series_frame = ttk.LabelFrame(parent, text="Series temporales por depósito", style="App.TLabelframe")
        series_frame.grid(row=0, column=0, sticky="nsew")
        series_frame.columnconfigure(0, weight=1)
        series_frame.rowconfigure(0, weight=1)

        self._fig_zones = Figure(figsize=(5.8, 7.0), dpi=90, facecolor="#f0f2f5")
        self._fig_zones.subplots_adjust(hspace=0.22, top=0.97, bottom=0.10, left=0.10, right=0.98)
        self._axes_zones = []
        for i in range(len(TRUCK_ZONE_KEYS)):
            if i == 0:
                ax = self._fig_zones.add_subplot(len(TRUCK_ZONE_KEYS), 1, i + 1)
            else:
                ax = self._fig_zones.add_subplot(len(TRUCK_ZONE_KEYS), 1, i + 1, sharex=self._axes_zones[0])
            self._axes_zones.append(ax)
        self._canvas_zones = FigureCanvasTkAgg(self._fig_zones, master=series_frame)
        self._canvas_zones.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def _draw_initial_charts(self) -> None:
        # Total
        self._ax_total.set_facecolor("#f0f2f5")
        self._ax_total.set_title("Zonas ocupadas — total", fontsize=10)
        self._ax_total.set_ylabel("N°", fontsize=8)
        self._ax_total.set_ylim(0, len(TRUCK_ZONE_KEYS) + 0.3)
        self._ax_total.tick_params(labelsize=7)
        self._ax_total.figure.tight_layout(pad=1.2)
        self._canvas_total.draw()

        # Pie
        self._ax_pie.set_facecolor("#f0f2f5")
        self._ax_pie.pie(
            [len(TRUCK_ZONE_KEYS)],
            labels=["Libre"],
            colors=["#2f9e58"],
            autopct="%1.0f%%",
            startangle=90,
            radius=1.10,
            pctdistance=0.68,
            labeldistance=1.05,
            textprops={"fontsize": 9},
        )
        self._ax_pie.set_aspect("equal", adjustable="box")
        self._ax_pie.set_title("Ocupación actual", fontsize=10, pad=8)
        self._canvas_pie.draw()

        # Zonas individuales
        zone_colors = ["#4e8ef7", "#f7a74e", "#a74ef7"]
        for i, ax in enumerate(self._axes_zones):
            ax.set_facecolor("#f0f2f5")
            ax.set_title(f"Depósito {i + 1}", fontsize=8, pad=3)
            ax.set_ylim(-0.05, 1.05)
            ax.set_yticks([0, 1])
            ax.set_yticklabels(["Libre", "Ocup."], fontsize=6)
            ax.grid(axis="y", color="#d8dee6", linewidth=0.7, alpha=0.8)
            if i < len(TRUCK_ZONE_KEYS) - 1:
                ax.tick_params(axis="x", labelbottom=False)
            else:
                ax.tick_params(axis="x", labelsize=7)
                ax.set_xlabel("Hora", fontsize=7, labelpad=2)
            ax.tick_params(labelsize=6)
        self._canvas_zones.draw()

    def _build_depot_indicators(self) -> None:
        for idx, key in enumerate(TRUCK_ZONE_KEYS):
            self.depot_cards_container.columnconfigure(idx, weight=1)
            card = tk.Frame(
                self.depot_cards_container,
                bg="#c94847",
                bd=1,
                relief="solid",
                padx=12,
                pady=8,
                highlightthickness=1,
                highlightbackground="#b73e3e",
                highlightcolor="#b73e3e",
            )
            card.grid(row=0, column=idx, sticky="ew", padx=(0, 6 if idx < len(TRUCK_ZONE_KEYS) - 1 else 0))
            card.columnconfigure(0, weight=1)

            title = tk.Label(
                card,
                text=f"Depósito {idx + 1}",
                bg="#c94847",
                fg="white",
                font=("Segoe UI", 11, "bold"),
                anchor="w",
            )
            title.grid(row=0, column=0, sticky="w")
            status = tk.Label(
                card,
                text="No disponible",
                bg="#c94847",
                fg="white",
                font=("Segoe UI", 10),
                anchor="w",
                width=14,
            )
            status.grid(row=1, column=0, sticky="w", pady=(2, 0))
            badge = tk.Label(
                card,
                text="NO DISPONIBLE",
                bg="#a63636",
                fg="white",
                font=("Segoe UI", 8, "bold"),
                padx=8,
                pady=3,
                width=13,
                anchor="center",
            )
            badge.grid(row=0, column=1, rowspan=2, sticky="e")

            self.depot_card_widgets[key] = (card, title, status, badge)

    def _apply_card_state(self, widgets: tuple, available: bool) -> None:
        color = "#2f9e58" if available else "#c94847"
        badge_bg = "#257b44" if available else "#a63636"
        badge_text = "DISPONIBLE" if available else "NO DISPONIBLE"
        border_color = "#2a6f44" if available else "#b73e3e"
        status_text = "Disponible" if available else "No disponible"
        card, title, status, badge = widgets
        card.configure(bg=color, highlightbackground=border_color, highlightcolor=border_color)
        title.configure(bg=color)
        status.configure(bg=color, text=status_text)
        badge.configure(bg=badge_bg, text=badge_text)

    def update_depot_indicators(self) -> None:
        for key in TRUCK_ZONE_KEYS:
            available = self.truck_zone_state.get(key, "free") == "free"
            for widget_dict in (self.depot_card_widgets, self.dash_depot_card_widgets):
                widgets = widget_dict.get(key)
                if widgets is not None:
                    self._apply_card_state(widgets, available)

    def update_frame(self) -> None:
        if not self.running:
            return

        if self.cap is None:
            self.after(200, self.update_frame)
            return

        ret, frame = self.cap.read()
        if not ret:
            self.after(200, self.update_frame)
            return

        frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
        now = time.perf_counter()
        if TARGET_DPS <= 0 or (now - self.last_detection_ts) >= (1.0 / TARGET_DPS):
            detections = self.detector.detect(frame)
            self._update_detection_tracks(detections)
            self.last_detection_ts = now
        else:
            self._decay_detection_tracks()
        self.current_detections = [track.detection for track in self.active_detection_tracks]

        eval_data = self.detector.evaluate(self.current_detections, self.zones)
        self.truck_zone_state = eval_data["truck_zone_state"]
        self.update_depot_indicators()

        if now - self._last_history_ts >= 2.0:
            self.occupancy_history.append((datetime.now(), dict(self.truck_zone_state)))
            self._last_history_ts = now

        output = self.draw_overlays(frame)
        rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
        photo = ImageTk.PhotoImage(image=Image.fromarray(rgb))
        self.video_label.configure(image=photo)
        self.video_label.image = photo

        self.after(15, self.update_frame)

    @staticmethod
    def _centroid_distance_sq(a: tuple[int, int], b: tuple[int, int]) -> int:
        dx = a[0] - b[0]
        dy = a[1] - b[1]
        return dx * dx + dy * dy

    def _decay_detection_tracks(self) -> None:
        for track in self.active_detection_tracks:
            track.ttl_frames -= 1
        self.active_detection_tracks = [t for t in self.active_detection_tracks if t.ttl_frames > 0]

    def _update_detection_tracks(self, detections: list[Detection]) -> None:
        self._decay_detection_tracks()
        distance_threshold_sq = 60 * 60
        used_track_indices: set[int] = set()

        for det in detections:
            best_idx = -1
            best_dist_sq = distance_threshold_sq + 1
            for idx, track in enumerate(self.active_detection_tracks):
                if idx in used_track_indices or track.detection.label != det.label:
                    continue
                dist_sq = self._centroid_distance_sq(track.detection.centroid, det.centroid)
                if dist_sq < best_dist_sq and dist_sq <= distance_threshold_sq:
                    best_dist_sq = dist_sq
                    best_idx = idx

            if best_idx >= 0:
                self.active_detection_tracks[best_idx].detection = det
                self.active_detection_tracks[best_idx].ttl_frames = self.detection_ttl_frames
                used_track_indices.add(best_idx)
            else:
                self.active_detection_tracks.append(
                    DetectionTrack(detection=det, ttl_frames=self.detection_ttl_frames)
                )

    def _update_dashboard_charts(self) -> None:
        if not self.running:
            return

        # ── Pie chart ─────────────────────────────────────────────────────
        occupied = sum(1 for s in self.truck_zone_state.values() if s == "occupied")
        free = len(TRUCK_ZONE_KEYS) - occupied
        self._ax_pie.clear()
        self._ax_pie.set_facecolor("#f0f2f5")
        if occupied == 0 and free == 0:
            self._ax_pie.text(0, 0, "Sin datos", ha="center", va="center", fontsize=9)
        else:
            labels, sizes, colors = [], [], []
            if occupied:
                labels.append(f"Ocupado ({occupied})")
                sizes.append(occupied)
                colors.append("#c94847")
            if free:
                labels.append(f"Libre ({free})")
                sizes.append(free)
                colors.append("#2f9e58")
            self._ax_pie.pie(
                sizes, labels=labels, colors=colors,
                autopct="%1.0f%%", startangle=90,
                radius=1.10, pctdistance=0.68, labeldistance=1.05,
                textprops={"fontsize": 9},
            )
        self._ax_pie.set_aspect("equal", adjustable="box")
        self._ax_pie.set_title("Ocupación actual", fontsize=10, pad=6)
        self._canvas_pie.draw()

        # ── Total occupancy (top, full width) ────────────────────────────
        self._ax_total.clear()
        self._ax_total.set_facecolor("#f0f2f5")
        if len(self.occupancy_history) >= 2:
            times = [t for t, _ in self.occupancy_history]
            totals = [sum(1 for s in state.values() if s == "occupied") for _, state in self.occupancy_history]
            self._ax_total.fill_between(times, totals, step="post", alpha=0.4, color="#c94847")
            self._ax_total.step(times, totals, where="post", color="#c94847", linewidth=2)
            self._ax_total.set_ylim(0, len(TRUCK_ZONE_KEYS) + 0.3)
            self._ax_total.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
            total_locator = matplotlib.dates.AutoDateLocator(minticks=3, maxticks=6)
            self._ax_total.xaxis.set_major_locator(total_locator)
            self._ax_total.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
        else:
            self._ax_total.text(0.5, 0.5, "Esperando datos…", ha="center", va="center",
                                transform=self._ax_total.transAxes, fontsize=9)
        self._ax_total.set_title("Zonas ocupadas — total", fontsize=10)
        self._ax_total.set_ylabel("N°", fontsize=8)
        self._ax_total.tick_params(axis="x", labelsize=7, rotation=0)
        self._ax_total.tick_params(axis="y", labelsize=7)
        self._ax_total.figure.tight_layout(pad=1.2)
        self._canvas_total.draw()

        # ── Individual zone charts (bottom right) ─────────────────────────
        zone_colors = ["#4e8ef7", "#f7a74e", "#a74ef7"]
        has_data = len(self.occupancy_history) >= 2
        zone_locator = matplotlib.dates.AutoDateLocator(minticks=3, maxticks=5)
        zone_formatter = matplotlib.dates.DateFormatter("%H:%M")
        times = [t for t, _ in self.occupancy_history] if has_data else []
        for i, (key, ax) in enumerate(zip(TRUCK_ZONE_KEYS, self._axes_zones)):
            ax.clear()
            ax.set_facecolor("#f0f2f5")
            ax.set_ylim(-0.05, 1.05)
            ax.set_yticks([0, 1])
            ax.set_yticklabels(["Libre", "Ocup."], fontsize=6)
            ax.grid(axis="y", color="#d8dee6", linewidth=0.7, alpha=0.8)
            if has_data:
                vals = [1 if s.get(key) == "occupied" else 0 for _, s in self.occupancy_history]
                ax.fill_between(times, vals, step="post", alpha=0.55, color=zone_colors[i])
                ax.step(times, vals, where="post", color=zone_colors[i], linewidth=1.5)
                ax.xaxis.set_major_locator(zone_locator)
                ax.xaxis.set_major_formatter(zone_formatter)
            else:
                ax.text(0.5, 0.5, "Esperando datos…", ha="center", va="center",
                        transform=ax.transAxes, fontsize=7)
            ax.set_title(f"Depósito {i + 1}", fontsize=8, pad=3)
            if i < len(TRUCK_ZONE_KEYS) - 1:
                ax.tick_params(axis="x", labelbottom=False)
            else:
                ax.tick_params(axis="x", labelsize=7, rotation=0)
                ax.set_xlabel("Hora", fontsize=7, labelpad=2)
            ax.tick_params(axis="y", labelsize=6)
        self._fig_zones.subplots_adjust(hspace=0.22, top=0.97, bottom=0.10, left=0.10, right=0.98)
        self._canvas_zones.draw()

        self.after(3000, self._update_dashboard_charts)

    def draw_overlays(self, frame):
        output = frame.copy()

        if self.show_zones.get():
            for key, box in self.zones.items():
                x1, y1, x2, y2 = box
                if key.startswith("truck_space"):
                    zone_state = self.truck_zone_state.get(key, "free")
                    color = (0, 200, 0) if zone_state == "occupied" else (0, 0, 255)
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

        return output

    def on_close(self) -> None:
        self.running = False
        if self.rfid_bridge is not None:
            self.rfid_bridge.stop()
        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.destroy()
