# yolo_cam_demo.py
# Requisitos: pip install ultralytics opencv-python
import cv2
import numpy as np
import time
from ultralytics import YOLO

# Parámeteros
CAM_IDX = 0               # cambia si tu cámara no es 0
IMG_SIZE = 640            # tamaño de inferencia (se ajusta internamente)
CONF_THRESHOLD = 0.45     # umbral de confianza mínimo para mostrar detecciones
TARGET_FPS = 4            # limitar la tasa de procesamiento (4 fps)

def draw_box(frame, xyxy, label, conf):
    x1, y1, x2, y2 = map(int, xyxy)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
    # Centroide de la caja
    cx = int((x1 + x2) / 2)
    cy = int((y1 + y2) / 2)
    cv2.circle(frame, (cx, cy), 3, (0, 200, 0), -1)
    txt = f"{label} {conf:.2f}"
    cv2.putText(frame, txt, (x1, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,200,0), 1, cv2.LINE_AA)

def main():
    # Cargar modelo (ultralytics descargará yolov8n.pt la primera vez)
    model = YOLO("yolov8n.pt")

    cap = cv2.VideoCapture(CAM_IDX)
    if not cap.isOpened():
        print("No se pudo abrir la cámara. Revisa CAM_IDX.")
        return

    while True:
        loop_start = time.perf_counter()
        ret, frame = cap.read()
        if not ret:
            break

        # Inferencia (devuelve un objeto results; usamos el primer item)
        results = model(frame, imgsz=IMG_SIZE, conf=CONF_THRESHOLD)[0]

        # results.boxes contiene las detecciones (si hay)
        boxes = results.boxes
        if boxes is not None and len(boxes) > 0:
            # boxes.xyxy -> tensor (N,4), boxes.conf -> (N,), boxes.cls -> (N,)
            xyxy_arr = boxes.xyxy.cpu().numpy()      # Nx4
            conf_arr = boxes.conf.cpu().numpy()      # N
            cls_arr  = boxes.cls.cpu().numpy().astype(int)  # N (índices)
            for xyxy, conf, cls_idx in zip(xyxy_arr, conf_arr, cls_arr):
                label = model.names.get(cls_idx, str(cls_idx))
                draw_box(frame, xyxy, label, float(conf))

        # Mostrar imagen
        cv2.imshow("YOLOv8 Camera Demo", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            break

        # Limitar FPS
        if TARGET_FPS > 0:
            min_loop = 1.0 / TARGET_FPS
            elapsed = time.perf_counter() - loop_start
            if elapsed < min_loop:
                time.sleep(min_loop - elapsed)

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
