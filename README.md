# Remote Play — cualquier consola, desde un handheld

Streaming de video/audio + control remoto real para jugar consolas antiguas
desde un handheld portátil (Steam Deck hoy, ROG Ally X en desarrollo),
capturando la salida de video verdadera de la consola por HDMI y reinyectando
el control como si fuera un mando físico conectado por USB.

No es un emulador. La consola sigue siendo la consola real: lo único que se
reemplaza es la pantalla (por una capturadora HDMI + streaming) y el mando
(por un microcontrolador que emula el protocolo del control original).

## Cómo funciona

Tres piezas que se comunican por red local:

1. **PC con Windows** (`windows-server/`) — corre el software de Remote Play
   oficial de la consola y una capturadora HDMI USB. Un servidor propio usa
   `ffmpeg` con codificación por hardware (NVENC) para capturar la señal y
   re-transmitirla como MPEG-TS por UDP hacia el handheld, y recibe el
   estado del control por UDP para inyectarlo del lado de la consola.
2. **ESP32-S3** (`deck-client/esp32_firmware/`) — puente USB entre el PC y
   la consola. Recibe el estado del control por UDP y lo reinyecta emulando
   el protocolo HID del control original (hoy: DualShock 3 para PS3), sin
   que la consola note diferencia con un mando físico real.
3. **Cliente handheld** — lee el control físico del dispositivo, lo manda
   por UDP al ESP32 a alta frecuencia (120 Hz por defecto), y reproduce el
   stream de video/audio que llega del servidor. Hoy: Steam Deck
   (`deck-client/`). En desarrollo: ROG Ally X (`rog-ally-client/`).

```
 Consola  --HDMI-->  Capturadora USB  --ffmpeg-->  PC Windows  --UDP/red-->  Handheld
    ^                                                   ^                       |
    |                                                   |                       v
    +---------- USB (control emulado) ---- ESP32-S3 <--UDP-- (estado del control)
```

## Estructura del repo

- **`deck-client/`** — cliente para Steam Deck (SteamOS/Linux): lectura del
  mando con `pygame`, envío UDP al ESP32, reproducción del stream con
  `ffplay`, menú y modo "solo control" en Tkinter. Incluye el firmware del
  ESP32-S3 (`esp32_firmware/`) y toda la bitácora de ajuste de latencia en
  `OPCIONES.md`.
- **`windows-server/`** — servidor de captura/streaming para Windows +
  Nvidia (PowerShell + ffmpeg), con interfaz gráfica y un lanzador nativo
  (`.exe`) para no depender de abrir PowerShell a mano.
- **`rog-ally-client/`** — puerto del cliente a Windows para la ROG Ally X
  (Python + pygame, compilado como `.exe` único con PyInstaller).
  **En desarrollo — todavía sin verificar contra hardware real.**

## Estado actual

| Pieza | Estado |
|---|---|
| Cliente Steam Deck | ✅ Funcional. Streaming + control probados de punta a punta, con meses de ajuste de latencia. |
| Servidor Windows | ✅ Funcional. Interfaz gráfica + lanzador nativo para arrancar/detener sin terminal. |
| Cliente ROG Ally X (Windows) | 🚧 En desarrollo. Compilado (mando XInput, brillo por WMI, menú, modo control) pero pendiente de probar contra hardware real: mapeo de botones, brillo, latencia. |

## Próxima consola objetivo: PS2

El diseño (capturadora HDMI/componente + microcontrolador emulando el mando
original) es deliberadamente genérico por consola. El soporte de PS2 es el
siguiente objetivo en la hoja de ruta.

## Qué hace falta para correrlo (no incluido en este repo)

- **El software de Remote Play oficial** de la consola correspondiente, del
  lado del PC — es software de terceros, con licencia propia; no se
  redistribuye aquí.
- **ffmpeg** — no se incluye por tamaño (los binarios superan el límite de
  GitHub). Se usa el build de [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)
  ("full_build"), colocado junto a los scripts del servidor.
- Una **capturadora HDMI** compatible con DirectShow, con salida de audio
  digital.
- Un **ESP32-S3** flasheado con el firmware de `deck-client/esp32_firmware/`.
