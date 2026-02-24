# YOLO-trucks — Truck Depot Occupancy Control

Demo de monitoreo de depósito en tiempo real desarrollado para **UIA × Accenture**.
Detecta camiones y autos con YOLO, monitorea ocupación de espacios por zonas, y registra eventos RFID de ingreso/egreso.

---

## Estructura del proyecto

| Archivo | Descripción |
|---|---|
| `main.py` | Entrypoint de la app |
| `gui_app.py` | UI Tkinter y loop principal |
| `detector.py` | Inferencia YOLO y evaluación de zonas |
| `zones.py` | Helpers de zonas y persistencia |
| `zones.json` | Coordenadas de zonas (editables desde la GUI) |
| `rfid_log.py` | Lectura/escritura CSV de eventos RFID |
| `rfid_serial_bridge.py` | Bridge serial Arduino → CSV |
| `app_config.py` | Configuración central |
| `run_depot_monitor.bat` | Launcher Windows |
| `requirements.txt` | Dependencias Python |
| `RFID_logger/RFID_logger.ino` | Firmware Arduino Nano para lectores RFID |

---

## Requisitos

- Python 3.9+
- Webcam
- Windows (el `.bat` launcher es para Windows; en Linux/Mac usar `python main.py`)

```bash
pip install -r requirements.txt
```

---

## Cómo correr

**Windows:**
```bat
run_depot_monitor.bat
```

**Cualquier plataforma:**
```bash
python main.py
```

---

## Capturas

| Pantalla principal (detecciones) | Tab Configuración |
|---|---|
| ![Pantalla detección](imgs/pantalla%20deteccion.png) | ![Pantalla config](imgs/pantalla%20config.png) |

---

## Interfaz

La GUI tiene dos tabs en el panel derecho:

### Tab "Operación"
- Panel de **alertas** activas
- Tabla de **eventos RFID** (ingreso/egreso) con entrada manual y refresh
- Estado de depósitos (disponible / no disponible / alerta) — mostrado debajo del video

### Tab "Configuración"
- **Selector de modelo YOLO** — elegir entre Nano/Small/Medium/Large/XLarge y aplicar en caliente
- **Selector de cámara** — detecta cámaras disponibles, permite cambiar sin reiniciar
- **Editor de zonas** — dibuja zonas con el mouse directamente sobre el video

### Panel izquierdo
- Feed de video en tiempo real con overlays (detecciones, centroides, zonas, alertas)
- Checkboxes para activar/desactivar cada overlay
- Cards de estado de los 3 depósitos

---

## Configuración (`app_config.py`)

| Variable | Descripción |
|---|---|
| `CAMERA_INDEX` | Índice de cámara por defecto |
| `AVAILABLE_MODELS` | Lista de modelos YOLO disponibles |
| `MODEL_PATH` | Modelo activo por defecto — cambiar el índice `[0]` por `[1]`..`[4]` para otro modelo |
| `CONF_THRESHOLD` | Umbral de confianza para detecciones (0.0–1.0) |
| `IMG_SIZE` | Tamaño de imagen para inferencia YOLO |
| `ALLOWED_LABELS` | Clases a detectar (default: `truck`, `car`) |
| `DETECTION_TTL_FRAMES` | Frames de persistencia de detección (reduce parpadeo) |
| `TARGET_DPS` | Ciclos de detección por segundo |
| `FRAME_WIDTH`, `FRAME_HEIGHT` | Resolución del video mostrado (también afecta velocidad) |
| `RFID_SERIAL_PORT` | Puerto COM del Arduino (vacío = autodetección) |
| `RFID_SERIAL_BAUDRATE` | Baudrate del Arduino (default: 115200) |
| `RFID_SERIAL_AUTOSTART` | Iniciar bridge serial automáticamente |

### Modelos disponibles

```python
AVAILABLE_MODELS = (
    ("yolov8n.pt", "Nano    — más rápido, recomendado sin GPU"),
    ("yolov8s.pt", "Small"),
    ("yolov8m.pt", "Medium"),
    ("yolov8l.pt", "Large"),
    ("yolov8x.pt", "XLarge  — más preciso, requiere GPU"),
)
MODEL_PATH = AVAILABLE_MODELS[0][0]  # cambiar el primer índice
```

Sin GPU (CPU only) se recomienda `yolov8n.pt`. Los modelos se descargan automáticamente la primera vez.

---

## Editor de zonas

1. Abrir tab **Configuración**
2. Seleccionar zona en el dropdown
3. Hacer clic en **Editar zona seleccionada**
4. Arrastrar sobre el video para dibujar el rectángulo
5. Repetir para cada zona
6. Hacer clic en **Guardar zonas**

Zonas disponibles: `truck_space_1`, `truck_space_2`, `truck_space_3`, `warn_car`.
Se guardan en `zones.json`.

---

## RFID — Hardware

### Componentes
- Arduino Nano
- 2× módulo RC522 (MFRC522 o compatible)
- CD4504B (level shifter 5V → 3.3V) — 6 canales necesarios

### Pinout Arduino Nano

| Señal | Pin Nano | Notas |
|---|---|---|
| SCK | D13 | SPI hardware — level shift |
| MISO | D12 | SPI hardware — directo (no level shift) |
| MOSI | D11 | SPI hardware — level shift |
| SS lector INGRESS | D10 | level shift |
| RST lector INGRESS | D9 | level shift |
| SS lector EGRESS | D8 | level shift |
| RST lector EGRESS | D7 | level shift |

**Level shifter CD4504B:** `VCC = 5V` (lado Nano), `VDD = 3.3V` (lado RC522). MISO va directo sin level shifter.

> Para el adaptador de niveles se puede usar el CD4504B o un divisor resistivo (1kΩ serie + 2kΩ a GND por canal). Resistencias de 10kΩ generan problemas de timing en SCK — usar 1kΩ/2kΩ o directamente el integrado.

### Firmware (`RFID_logger/RFID_logger.ino`)

Lee UIDs de hasta 2 lectores RC522 y los envía por serial a 115200 baud en el formato:

```
INGRESS,<UID_HEX>
EGRESS,<UID_HEX>
```

El bridge Python (`rfid_serial_bridge.py`) escucha el puerto serial y agrega las filas al CSV `rfid_log.csv` automáticamente.

### Configuración del puerto serial

En `app_config.py`:
```python
RFID_SERIAL_PORT = ""        # vacío = autodetección del COM
RFID_SERIAL_BAUDRATE = 115200
RFID_SERIAL_AUTOSTART = True
```

---

## Notas de performance

- Sin GPU, usar `yolov8n.pt` y `TARGET_DPS = 2`
- Reducir `FRAME_WIDTH`/`FRAME_HEIGHT` también ayuda (default: 640×360)
- El selector de modelo en la tab Configuración permite comparar modelos en caliente durante el demo

---

## Ejemplo de referencia

`YOLO test.py` es un script mínimo original, mantenido como referencia.
