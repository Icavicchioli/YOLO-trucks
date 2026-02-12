"""Serial bridge for Arduino RFID events -> CSV log."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Dict, List

from rfid_log import add_rfid_event

try:
    import serial
    import serial.tools.list_ports
except Exception:  # pragma: no cover - optional dependency at runtime
    serial = None


@dataclass
class RFIDBridgeEvent:
    kind: str
    message: str
    event: str = ""
    tag_id: str = ""


class RFIDSerialBridge:
    """Background serial reader that writes parsed RFID events to CSV."""

    def __init__(self, csv_path: str, port: str, baudrate: int = 115200, auto_scan: bool = True) -> None:
        self.csv_path = csv_path
        self.port = port.strip()
        self.baudrate = baudrate
        self.auto_scan = auto_scan

        self._events: queue.Queue[RFIDBridgeEvent] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="rfid-serial-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def drain_events(self) -> List[RFIDBridgeEvent]:
        events: List[RFIDBridgeEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def _emit_status(self, message: str) -> None:
        self._events.put(RFIDBridgeEvent(kind="status", message=message))

    def _emit_rfid_event(self, event: str, tag_id: str, source: str) -> None:
        self._events.put(
            RFIDBridgeEvent(
                kind="rfid_event",
                message=f"{source}: {event} {tag_id}",
                event=event,
                tag_id=tag_id,
            )
        )

    @staticmethod
    def _parse_line(line: str) -> Dict[str, str] | None:
        parts = [p.strip() for p in line.split(",", maxsplit=1)]
        if len(parts) != 2:
            return None
        event_raw, tag_id = parts
        event_map = {"INGRESS": "ingress", "EGRESS": "egress"}
        event = event_map.get(event_raw.upper())
        if event is None or not tag_id:
            return None
        return {"event": event, "tag_id": tag_id.upper()}

    def _auto_find_port(self) -> str | None:
        if serial is None:
            return None
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            return None

        preferred = ("arduino", "ch340", "usb serial", "cp210")
        for p in ports:
            hay = f"{p.device} {p.description} {p.manufacturer}".lower()
            if any(token in hay for token in preferred):
                return p.device

        if len(ports) == 1:
            return ports[0].device
        return None

    def _resolve_port(self) -> str | None:
        if self.port:
            return self.port
        if self.auto_scan:
            return self._auto_find_port()
        return None

    def _run(self) -> None:
        if serial is None:
            self._emit_status("pyserial not installed")
            return

        while not self._stop_event.is_set():
            resolved_port = self._resolve_port()
            if not resolved_port:
                self._emit_status("serial port not found")
                time.sleep(2.0)
                continue

            try:
                self._emit_status(f"connecting {resolved_port}")
                with serial.Serial(resolved_port, self.baudrate, timeout=0.5) as ser:
                    self._emit_status(f"connected {resolved_port}")
                    while not self._stop_event.is_set():
                        raw = ser.readline()
                        if not raw:
                            continue
                        line = raw.decode("utf-8", errors="ignore").strip()
                        if not line:
                            continue
                        if line == "RFID_LOGGER_READY":
                            self._emit_status(f"device ready {resolved_port}")
                            continue
                        parsed = self._parse_line(line)
                        if parsed is None:
                            continue

                        event = parsed["event"]
                        tag_id = parsed["tag_id"]
                        add_rfid_event(self.csv_path, event, tag_id, f"serial:{resolved_port}")
                        self._emit_rfid_event(event, tag_id, resolved_port)
            except Exception as exc:
                self._emit_status(f"disconnected ({exc})")
                time.sleep(2.0)
