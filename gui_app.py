"""Tkinter GUI for truck monitoring + warning zones + RFID log view."""

from __future__ import annotations

from dataclasses import dataclass
import time
import tkinter as tk
from tkinter import messagebox, ttk

import cv2
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
        self.show_centroids = tk.BooleanVar(value=True)
        self.show_zones = tk.BooleanVar(value=True)
        self.show_warnings = tk.BooleanVar(value=True)

        self.warning_text = tk.StringVar(value="No warnings")
        self.rfid_status_text = tk.StringVar(value="RFID serial: idle")
        self.truck_zone_state: dict[str, str] = {k: "free" for k in TRUCK_ZONE_KEYS}
        self.depot_card_widgets: dict[str, tuple[tk.Frame, tk.Label, tk.Label, tk.Label]] = {}
        self.rfid_bridge: RFIDSerialBridge | None = None

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
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)

        # ── Izquierda: video + checkboxes + depot cards ───────────────────
        left = ttk.Frame(self, padding=10, style="App.TFrame")
        left.grid(row=1, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.video_label = ttk.Label(left)
        self.video_label.grid(row=0, column=0, sticky="nsew")
        self.video_label.bind("<ButtonPress-1>", self.on_mouse_down)
        self.video_label.bind("<B1-Motion>", self.on_mouse_drag)
        self.video_label.bind("<ButtonRelease-1>", self.on_mouse_up)

        controls = ttk.Frame(left, padding=(0, 6, 0, 0), style="App.TFrame")
        controls.grid(row=1, column=0, sticky="ew")
        ttk.Checkbutton(controls, text="Detecciones", variable=self.show_detections).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(controls, text="Centroides", variable=self.show_centroids).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(controls, text="Zonas", variable=self.show_zones).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(controls, text="Alertas", variable=self.show_warnings).grid(row=0, column=3, sticky="w")

        depot_frame = ttk.LabelFrame(left, text="Estado de depósitos", style="App.TLabelframe")
        depot_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        depot_frame.columnconfigure(0, weight=1)
        self.depot_cards_container = ttk.Frame(depot_frame)
        self.depot_cards_container.grid(row=0, column=0)   # sin sticky → centrado
        self.depot_cards_container.columnconfigure((0, 1, 2), weight=1)
        self._build_depot_indicators()

        # ── Derecha: notebook (Operación / Configuración) ─────────────────
        right = ttk.Frame(self, padding=(0, 10, 10, 10), style="App.TFrame")
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(right, style="App.TNotebook")
        notebook.grid(row=0, column=0, sticky="nsew")

        # ── Tab 1: Operación ──────────────────────────────────────────────
        tab_op = ttk.Frame(notebook, padding=8, style="App.TFrame")
        tab_op.columnconfigure(0, weight=1)
        tab_op.rowconfigure(1, weight=1)
        notebook.add(tab_op, text="Operación")

        warning_frame = tk.Frame(
            tab_op,
            bg="#ffffff",
            bd=1,
            relief="solid",
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground="#d7dee6",
            highlightcolor="#d7dee6",
        )
        warning_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        warning_frame.grid_columnconfigure(0, weight=1)
        self.warning_title_label = tk.Label(
            warning_frame,
            text="Alertas",
            bg="#ffffff",
            fg="#203045",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        self.warning_title_label.grid(row=0, column=0, sticky="w")
        self.warning_value_label = tk.Label(
            warning_frame,
            textvariable=self.warning_text,
            bg="#ffffff",
            fg="#5f6d7b",
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
            wraplength=320,
        )
        self.warning_value_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        rfid_frame = ttk.LabelFrame(tab_op, text="RFID ingress/egress", style="App.TLabelframe")
        rfid_frame.grid(row=1, column=0, sticky="nsew")
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

        # ── Tab 2: Configuración ──────────────────────────────────────────
        tab_cfg = ttk.Frame(notebook, padding=8, style="App.TFrame")
        tab_cfg.columnconfigure(0, weight=1)
        notebook.add(tab_cfg, text="Configuración")

        model_frame = ttk.LabelFrame(tab_cfg, text="Modelo YOLO", style="App.TLabelframe")
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

        camera_frame = ttk.LabelFrame(tab_cfg, text="Cámara", style="App.TLabelframe")
        camera_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
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

        zone_frame = ttk.LabelFrame(tab_cfg, text="Editor de zonas", style="App.TLabelframe")
        zone_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
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

    def refresh_rfid_table(self) -> None:
        for row_id in self.rfid_tree.get_children():
            self.rfid_tree.delete(row_id)
        for row in read_rfid_events(RFID_LOG_PATH, limit=250):
            self.rfid_tree.insert("", tk.END, values=(row["timestamp"], row["event"], row["tag_id"]))

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
        self.detector = DepotDetector(model_path, CONF_THRESHOLD, IMG_SIZE, ALLOWED_LABELS)
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
            )
            badge.grid(row=0, column=1, rowspan=2, sticky="e")

            self.depot_card_widgets[key] = (card, title, status, badge)

    def update_depot_indicators(self) -> None:
        color_available = "#2f9e58"
        color_unavailable = "#c94847"
        for key in TRUCK_ZONE_KEYS:
            state = self.truck_zone_state.get(key, "free")
            available = state == "free"
            color = color_available if available else color_unavailable
            status_text = "Disponible" if available else "No disponible"
            widgets = self.depot_card_widgets.get(key)
            if widgets is None:
                continue
            badge_bg = "#257b44" if available else "#a63636"
            badge_text = "DISPONIBLE" if available else "NO DISPONIBLE"
            border_color = "#2a6f44" if available else "#b73e3e"
            card, title, status, badge = widgets
            card.configure(bg=color)
            card.configure(highlightbackground=border_color, highlightcolor=border_color)
            title.configure(bg=color)
            status.configure(bg=color, text=status_text)
            badge.configure(bg=badge_bg, text=badge_text)

    def _update_warning_panel(self, warnings: list[str]) -> None:
        has_warning = bool(warnings)
        value_color = "#b32020" if has_warning else "#5f6d7b"
        panel_border = "#e2b7b7" if has_warning else "#d7dee6"
        self.warning_value_label.configure(fg=value_color)
        self.warning_title_label.configure(fg="#8f1f1f" if has_warning else "#203045")
        self.warning_value_label.master.configure(
            highlightbackground=panel_border,
            highlightcolor=panel_border,
        )

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
            detections = self.detector.detect(frame)
            self._update_detection_tracks(detections)
            self.last_detection_ts = now
        else:
            self._decay_detection_tracks()
        self.current_detections = [track.detection for track in self.active_detection_tracks]

        eval_data = self.detector.evaluate(self.current_detections, self.zones)
        self.truck_zone_state = eval_data["truck_zone_state"]
        self.update_depot_indicators()
        warnings = eval_data["warnings"]
        self.warning_text.set(", ".join(warnings) if warnings else "No warnings")
        self._update_warning_panel(warnings)

        output = self.draw_overlays(frame, warnings)
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
        if self.rfid_bridge is not None:
            self.rfid_bridge.stop()
        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.destroy()
