![Remote Play](branding/banner.png)

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

1. **PC con Windows** (`windows-server/`) — tiene conectada una capturadora
   HDMI USB a la salida de video/audio de la consola. Un servidor propio usa
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

## Configurar servidor y cliente desde el menú de la Deck

El menú del cliente (`deck-client/client_menu.py`) tiene dos pantallas para
ajustar todo sin ir a tocar la PC ni editar texto a mano, con navegación
completa por el mando (cruceta + A/B, izquierda/derecha cambia cada valor):

- **Configurar servidor** — elige el modo de captura de la PC Windows
  (720p/1080p MJPEG, o los modos crudos sin comprimir para medir latencia) y
  confirma la IP de la Deck, todo por red. Habla por UDP (puerto 9200) con
  `config_listener.ps1`, un proceso propio e independiente de la ventana del
  servidor: si el servidor ya está transmitiendo, lo reinicia con la config
  nueva; si está apagado, la guarda para la próxima vez que le den Iniciar.
  Tiene además un botón para mandar la IP actual de la Deck al servidor sin
  tocar el modo — útil si la IP cambia y no se quiere ir a escribirla a mano
  en la PC.
- **Configurar cliente** — las variables de latencia del lado de la Deck
  (documentadas en `deck-client/OPCIONES.md`), en una pantalla con scroll en
  vez de tener que ponerlas como opciones de lanzamiento de Steam cada vez.

## Próxima consola objetivo: PS2

El diseño (capturadora HDMI/componente + microcontrolador emulando el mando
original) es deliberadamente genérico por consola. El soporte de PS2 es el
siguiente objetivo en la hoja de ruta.

## Qué hace falta para correrlo (no incluido en este repo)

- **ffmpeg** — no se incluye por tamaño (ver abajo cómo instalarlo).
- Una **capturadora HDMI** compatible con DirectShow, con salida de audio
  digital.
- Un **ESP32-S3** flasheado con el firmware de `deck-client/esp32_firmware/`
  (ver abajo cómo).

## Instalar ffmpeg (para que arranque el servidor)

`windows-server/start_server_gui.ps1`, `start_server_stream.bat` y
`detectar_dispositivos.ps1` buscan `ffmpeg.exe` en una ruta **fija**, con el
número de versión incluido en el nombre de la carpeta:

```
windows-server/ffmpeg-9.0.1-full_build/bin/ffmpeg.exe
```

Pasos:

1. Descargar exactamente esa versión (el build "full", con todos los
   codecs) desde el sitio oficial de [gyan.dev](https://www.gyan.dev/ffmpeg/builds/):

   **https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.1-full_build.7z**

   (Es un `.7z`, no un `.zip` — hace falta [7-Zip](https://www.7-zip.org/)
   para extraerlo; Windows no lo abre nativamente.)
2. Extraer el `.7z` **dentro de `windows-server/`**, junto a
   `start_server_stream.bat`. Al extraerlo debe quedar la carpeta
   `ffmpeg-9.0.1-full_build/` ahí mismo (no un nivel más adentro).
3. Confirmar que exista `windows-server/ffmpeg-9.0.1-full_build/bin/ffmpeg.exe`
   (y `ffplay.exe`, `ffprobe.exe` al lado).

> Si en el futuro usas otra versión de ffmpeg, la carpeta extraída va a
> tener otro nombre (por ejemplo `ffmpeg-9.2.0-full_build`). Los scripts NO
> la detectan sola: hay que **renombrar la carpeta** a
> `ffmpeg-9.0.1-full_build` para que coincida con la ruta que buscan, o
> editar esa ruta en los tres archivos mencionados arriba.

## Flashear el firmware del ESP32-S3

El archivo a subir es `deck-client/esp32_firmware/ds3_controller/ds3_controller.ino`
(los demás `.ino` de esa carpeta son pruebas de desarrollo, no hace falta
tocarlos).

> ⚠️ **Poné tu red WiFi acá antes de subir el firmware.** Cerca del inicio del
> archivo vas a encontrar:
> ```cpp
> const char *WIFI_SSID = "TU_RED_WIFI_2.4GHZ";
> const char *WIFI_PASSWORD = "TU_CONTRASENA_WIFI";
> ```
> Reemplazá esos dos valores por los de tu propia red — el ESP32-S3-WROOM-1
> solo tiene radio de 2.4 GHz, así que tiene que ser una red (o banda) de
> 2.4 GHz.
>
> **Nunca subas tu contraseña real a un repositorio o fork público.** Si
> vas a compartir tu copia del proyecto, dejá esos dos valores como
> placeholders (como están en este repo) y que cada quien ponga los suyos
> localmente antes de flashear.

1. En el Arduino IDE, con soporte de ESP32 instalado:
   - **Herramientas → Board**: `ESP32S3 Dev Module`
   - **Herramientas → USB Mode**: `USB-OTG (TinyUSB)`
   - Instalar la librería **ArduinoJson** (Benoit Blanchon, v7.x) desde el
     Gestor de Librerías.
2. Conectar la placa por su **puerto USB nativo** (no el de
   programación/COM).
3. Para que el Arduino IDE detecte la placa y suba el sketch: mantener
   **BOOT**, tocar **RESET**, soltar **RESET**, soltar **BOOT**, y recién
   ahí darle a Subir (el auto-reset no entra solo por USB nativo en esta
   placa).
