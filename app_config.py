"""Application configuration for the depot monitor."""

CAMERA_INDEX = 0
MODEL_PATH = "yolov8m.pt"
CONF_THRESHOLD = 0.15
IMG_SIZE = 640
ALLOWED_LABELS = ("truck", "car")
DETECTION_TTL_FRAMES = 10

# Keep this as requested: detection cycles per second.
TARGET_DPS = 2

FRAME_WIDTH = 960
FRAME_HEIGHT = 540
WINDOW_TITLE = "Depot Truck Monitor"

ZONES_PATH = "zones.json"
RFID_LOG_PATH = "rfid_log.csv"
