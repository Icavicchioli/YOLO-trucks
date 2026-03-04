# YOLO-trucks — Depot Truck Monitor

Aplicación de monitoreo en tiempo real para ocupación de depósitos usando detección con YOLO + registro RFID.

## Qué hace

- Detecta `truck` y `car` en cámara en vivo.
- Evalúa ocupación de 3 zonas de depósito configurables.
- Muestra estado de disponibilidad por depósito.
- Registra eventos RFID de `INGRESS`/`EGRESS` en CSV.
- Grafica ocupación total y series temporales por depósito.

## Estructura del proyecto

| Archivo | Descripción |
|---|---|
| `main.py` | Entrypoint de la aplicación |
| `gui_app.py` | Interfaz Tkinter y lógica principal |
| `detector.py` | Inferencia YOLO y evaluación de zonas |
| `zones.py` | Utilidades de zonas y persistencia |
| `zones.json` | Coordenadas de zonas |
| `app_config.py` | Configuración central |
| `rfid_log.py` | Lectura/escritura de log RFID |
| `rfid_serial_bridge.py` | Bridge serial Arduino → CSV |
| `rfid_log.csv` | Log de eventos RFID |
| `requirements.txt` | Dependencias Python |
| `run_depot_monitor.bat` | Launcher para Windows |
| `RFID_logger_ingress/RFID_logger_ingress.ino` | Firmware Arduino (ingreso) |
| `RFID_logger_egress/RFID_logger_egress.ino` | Firmware Arduino (egreso) |

## Requisitos

- Python 3.9+
- Webcam
- (Opcional) Arduino + RC522 para RFID serial

Instalación:

```bash
pip install -r requirements.txt
```

## Cómo correr

Windows:

```bat
run_depot_monitor.bat
```

Cualquier plataforma:

```bash
python main.py
```

## Tabs de la interfaz

La app usa 4 tabs principales:

### 1) Dashboard

- Estado de depósitos (cards disponibles/no disponibles)
- Gráfico de ocupación total
- Gráfico de torta de ocupación actual
- Tabla RFID resumida

### 2) Series de tiempo

- 3 gráficos temporales independientes (Depósito 1/2/3)
- Eje temporal compartido para comparar ocupación

### 3) Monitor

- Video en vivo con overlays opcionales:
  - Detecciones
  - Centroides
  - Zonas
- Cards de estado de depósitos
- Tabla RFID completa + ingreso/egreso manual

### 4) Configuración

- Selección de modelo YOLO (hot-swap)
- Umbral de confianza
- Selección de cámara
- Editor de zonas (dibujar/guardar/resetear)
- Limpieza de log RFID

## Configuración (`app_config.py`)

Parámetros principales:

- `CAMERA_INDEX`: cámara por defecto.
- `AVAILABLE_MODELS`: modelos disponibles para seleccionar en UI.
- `MODEL_PATH`: modelo inicial al arrancar.
- `CONF_THRESHOLD`: umbral de confianza.
- `IMG_SIZE`: tamaño de inferencia.
- `ALLOWED_LABELS`: clases permitidas.
- `DETECTION_TTL_FRAMES`: persistencia visual de detecciones.
- `TARGET_DPS`: frecuencia de inferencia (detections per second).
- `FRAME_WIDTH`, `FRAME_HEIGHT`: resolución del frame en UI.
- `RFID_SERIAL_PORT`: puerto serial (vacío = autodetección).
- `RFID_SERIAL_BAUDRATE`: baudrate serial.
- `RFID_SERIAL_AUTOSTART`: inicia bridge serial automáticamente.

## Zonas y ocupación

Zonas esperadas en `zones.json`:

- `truck_space_1`
- `truck_space_2`
- `truck_space_3`
- `warn_car`

Edición desde la UI:

1. Ir a `Configuración`.
2. Seleccionar zona.
3. Click en `Editar zona seleccionada`.
4. Arrastrar en el video para redefinir rectángulo.
5. Guardar con `Guardar zonas`.

## RFID (serial + CSV)

Formato esperado desde firmware por serial:

```txt
INGRESS,<UID_HEX>
EGRESS,<UID_HEX>
```

El bridge agrega los eventos en `rfid_log.csv` con timestamp.

## Hardware RFID recomendado

- Arduino Nano
- 2x RC522 (uno para ingreso y otro para egreso)
- Adaptación de niveles 5V → 3.3V para señales desde Nano a RC522

## Dependencias

Incluidas en `requirements.txt`:

- `ultralytics`
- `opencv-python`
- `Pillow`
- `pyserial`

## Notas de performance

- Sin GPU, usar `yolov8n.pt` o `yolov8s.pt`.
- Bajar `FRAME_WIDTH`/`FRAME_HEIGHT` mejora fluidez.
- Ajustar `TARGET_DPS` según hardware.

## Script de referencia

`YOLO test.py` se conserva como script mínimo de referencia.
