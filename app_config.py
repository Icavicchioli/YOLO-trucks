"""Application configuration for the depot monitor."""

CAMERA_INDEX = 0
MODEL_PATH = "yolov8n.pt"
CONF_THRESHOLD = 0.45
IMG_SIZE = 640

# Keep this as requested: detection cycles per second.
TARGET_DPS = 4

FRAME_WIDTH = 960
FRAME_HEIGHT = 540
WINDOW_TITLE = "Depot Truck Monitor"

ZONES_PATH = "zones.json"
RFID_LOG_PATH = "rfid_log.csv"
