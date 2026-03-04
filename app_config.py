"""Application configuration for the depot monitor."""

CAMERA_INDEX = 1

# Modelos disponibles: (archivo, descripción)
# Más pequeño = más rápido en CPU. Más grande = más preciso.
AVAILABLE_MODELS = (
    ("yolov8n.pt", "YOLOv8n  —  Nano    (más rápido, recomendado sin GPU)"),
    ("yolov8s.pt", "YOLOv8s  —  Small"),
    ("yolov8m.pt", "YOLOv8m  —  Medium"),
    ("yolov8l.pt", "YOLOv8l  —  Large"),
    ("yolov8x.pt", "YOLOv8x  —  XLarge  (más preciso, requiere GPU)"),
)
MODEL_PATH = AVAILABLE_MODELS[2][0]  # cambiar índice para usar otro modelo por defecto
# hay que cambiar el primero, asi agarra la fila entera
CONF_THRESHOLD = 0.15
IMG_SIZE = 640
ALLOWED_LABELS = ("truck", "car")
DETECTION_TTL_FRAMES = 40

# Keep this as requested: detection cycles per second.
TARGET_DPS = 2

FRAME_WIDTH = 760
FRAME_HEIGHT = int(FRAME_WIDTH * 9 / 16)
WINDOW_TITLE = "Depot Truck Monitor"

ZONES_PATH = "zones.json"
RFID_LOG_PATH = "rfid_log.csv"
RFID_SERIAL_PORT = ""
RFID_SERIAL_BAUDRATE = 115200
RFID_SERIAL_AUTOSTART = True