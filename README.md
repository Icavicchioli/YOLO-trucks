# YOLO-trucks

Truck/depot monitoring app using YOLO + OpenCV + Tkinter.

This repo includes:
- A simple original example script: `YOLO test.py`
- A full modular app with GUI, zone-based warnings, and RFID CSV log placeholder.

## Features

- Live camera detection with YOLO (`ultralytics`)
- Target processing rate control (`TARGET_DPS`)
- Truck occupancy by centroid-in-zone logic (3 truck spaces)
- Warning rules for non-truck detections:
  - `car` -> `car detected`
  - `person` -> `people in depot`
  - anything else -> `warning, object in depot`
- Separate warning zones (`warn_car`, `warn_person`, `warn_other`)
- Tkinter GUI with:
  - Video feed
  - Detections + centroids
  - Zone overlays
  - Warning text
  - Visibility toggles
  - Manual zone editor (draw rectangles with mouse)
  - RFID ingress/egress table from CSV
- `.bat` launcher for Windows

## Project Structure

- `main.py`: App entrypoint
- `gui_app.py`: Tkinter UI and main runtime loop
- `detector.py`: YOLO inference and event evaluation
- `zones.py`: Zone helpers and persistence
- `zones.json`: Editable zone coordinates
- `rfid_log.py`: CSV read/write for ingress/egress (placeholder integration)
- `app_config.py`: Central config (camera/model/performance paths)
- `run_depot_monitor.bat`: Launcher
- `requirements.txt`: Python dependencies

## Requirements

- Python 3.9+
- Webcam
- Windows (for `.bat` launcher)

Install deps:

```bash
pip install -r requirements.txt
```

## Run

Option 1 (Windows):

```bat
run_depot_monitor.bat
```

Option 2:

```bash
python main.py
```

## Zone Setup (Manual)

1. Start app.
2. In **Zone editor**, select zone name from dropdown.
3. Click **Start editing selected zone**.
4. Drag on video to define rectangle.
5. Repeat for all zones.
6. Click **Save zones**.

Zones are stored in `zones.json`.

## Config

Edit `app_config.py`:
- `CAMERA_INDEX`
- `MODEL_PATH`
- `CONF_THRESHOLD`
- `IMG_SIZE`
- `TARGET_DPS`
- `FRAME_WIDTH`, `FRAME_HEIGHT`
- `ZONES_PATH`, `RFID_LOG_PATH`

## RFID Notes

RFID currently uses CSV-only placeholder logic (`rfid_log.py`):
- GUI buttons create manual ingress/egress rows in `rfid_log.csv`
- YOLO detections do **not** write RFID records
- Replace/add hardware reading integration later in `rfid_log.py`

## Legacy Example

`YOLO test.py` is kept as a minimal reference script.

