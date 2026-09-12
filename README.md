![Remote Play](branding/banner.png)

# Remote Play — cualquier consola, desde un handheld

Streaming de video/audio + control remoto real para jugar consolas antiguas
desde un handheld portátil (Steam Deck y ROG Ally X, ambos probados contra
hardware real), capturando la salida de video verdadera de la consola por
HDMI y reinyectando el control como si fuera un mando físico conectado por
USB.

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
   stream de video/audio que llega del servidor. Steam Deck
   (`deck-client/`) y ROG Ally X (`rog-ally-client/`), ambos probados
   contra hardware real.

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
  **Probado de punta a punta contra hardware real** (video, audio y
  control en modo streaming, más el modo control). Ver
  `rog-ally-client/README_ALLY.md` para el detalle de cada bug encontrado
  y corregido durante la prueba.

## Estado actual

| Pieza | Estado |
|---|---|
| Cliente Steam Deck | ✅ Funcional. Streaming + control probados de punta a punta, con meses de ajuste de latencia. |
| Servidor Windows | ✅ Funcional. Interfaz gráfica + lanzador nativo para arrancar/detener sin terminal. |
| Cliente ROG Ally X (Windows) | ✅ Funcional. Probado de punta a punta contra hardware real: streaming (video/audio/control) y modo control. |
| PS2 (Open PS2 Loader / PADEMU) | ✅ Funcional en el juego (jugable en tiempo real, confirmado a 60 fps con Lossless Scaling). Pendiente: el menú de OPL a veces pierde el control por USB unos segundos (se recupera solo). |
| Xbox 360 (RGH/JTAG + Aurora) | ✅ Funcional vía hiddriver360 (ver sección abajo). |

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

## PS2 (via Open PS2 Loader / PADEMU)

El diseño (capturadora HDMI/componente + microcontrolador emulando el mando
original) es deliberadamente genérico por consola: el **mismo ESP32-S3**
que emula un DualShock 3 para el PS3 sirve también para PS2, sin cambiar
nada de hardware — sólo hace falta que la consola tenga [Open PS2
Loader](https://github.com/ps2homebrew/Open-PS2-Loader) (OPL) instalado.

**Confirmado jugable en tiempo real (2026-09-11)**, incluso a 60 fps
activando el toggle de Lossless Scaling / generación de cuadros
(`PS3RP_LSFG` en "Configurar cliente" de la Deck, ver más arriba).

### Por qué hace falta un ajuste específico de USB

Un DualShock 3 real reporta su clase de dispositivo USB como `0xE0`
("Wireless Controller"), no como HID genérico — es una rareza de diseño del
propio chip de Sony (el mismo hace Bluetooth). El driver PADEMU de OPL
revisa esa clase explícitamente, así que un mando emulado con la clase
genérica de HID **no lo reconoce**, aunque funcione perfecto en un PC. El
firmware de este proyecto (`deck-client/esp32_firmware/ds3_controller/ds3_controller.ino`)
ya declara la clase correcta (`0xE0`/`0x01`/`0x01`, copiada del propio código
fuente de OPL) — no hace falta tocar nada para esto, ya viene resuelto.

### Requisitos y configuración

1. **OPL 1.0.0 o más nuevo** — PADEMU (el driver que traduce DualShock 3/4 a
   mando de PS2) se agregó en esa versión. Con una copia más vieja de OPL,
   el ESP32-S3 no va a aparecer como mando en absoluto.
2. Conectar el ESP32-S3 al puerto USB del PS2 (el más alejado del panel
   frontal suele dar mejores resultados si hay más de uno disponible),
   igual que con el PS3.
3. Dentro de OPL, entrar a la configuración de PADEMU del juego (vive en los
   ajustes **del juego**, no en la configuración global de OPL) y:
   - Elegir modo **USB** (no Bluetooth) para el puerto que se vaya a usar.
   - Activarlo y guardar la configuración antes de arrancar el juego.
4. Cargar el juego — PADEMU toma el control desde ahí.

Los nombres exactos de los menús pueden variar un poco entre builds de OPL;
si algo no coincide, la [wiki del propio
proyecto](https://github.com/ps2homebrew/Open-PS2-Loader/wiki) y su
changelog son la referencia más al día.

### Limitación conocida, sin resolver

El **menú de OPL** (el navegador de juegos, antes de cargar uno) a veces deja
de leer el control por USB después de unos segundos. **Dentro del juego,
con PADEMU activo, no pasa** — es un problema puntual del menú del propio
OPL, no del firmware ni de la consola. El ESP32-S3 tiene un vigilante que
detecta cuando el USB se atasca y se reinicia solo para recuperarse (tarda
unos segundos); mientras tanto, cargar el juego también lo destraba. La
causa de fondo todavía no se identificó.

## Xbox 360 (RGH/JTAG + Aurora, vía hiddriver360)

El mismo ESP32-S3 también sirve para conectar un DualShock 3 (real o
emulado) a una Xbox 360 modificada (RGH o JTAG), usando el plugin de
terceros [hiddriver360](https://github.com/EinTim23/hiddriver360). **No
hace falta ningún chip adicional** — solo el cable USB de datos que ya
tienes.

### Requisitos

- Xbox 360 con RGH/JTAG, dashboard [Aurora](https://www.aurora-project.org/)
  y **DashLaunch** instalado (el loader que lee `launch.ini` y carga
  plugins antes de que arranque el dashboard).
- El plugin `hiddriver.xex` — usa la versión parchada de la comunidad
  ([sudoxyz/hiddriver360 v0.6-patch](https://github.com/sudoxyz/hiddriver360/releases/tag/v0.6-patch)),
  no la v0.6-beta oficial: esa versión tiene un bug (pide el Report
  Descriptor con el índice de interfaz mal puesto) que hace que **ningún**
  control HID genérico se llegue a reconocer.

### Instalación (el paso que más cuesta)

1. Copia `hiddriver.xex` a la **misma unidad USB desde la que arranca
   DashLaunch** (`Usb:\hiddriver.xex`, por ejemplo) — **no al disco duro
   interno** (`Hdd1:`). DashLaunch carga los plugins de `[Plugins]` antes
   de que el disco duro interno termine de montarse, así que un plugin
   ahí simplemente nunca se carga, sin ningún error visible.
2. Agrega una línea en la sección `[Plugins]` del **`launch.ini` que
   DashLaunch usa de verdad** — ojo, puede haber más de una copia de
   `launch.ini` en distintas unidades (`Hdd1:`, `Usb0:`, etc.) y solo una
   está activa. Para confirmar cuál es sin adivinar, conéctate por XBDM
   (puerto 730) y pide la lista de módulos cargados:
   ```
   modules
   ```
   Si `Xbdm.xex`/`JRPC2.xex` u otros plugins ya aparecen cargados, compara
   sus rutas en cada copia de `launch.ini` contra esa lista para encontrar
   la que realmente está en efecto, y agrega ahí:
   ```ini
   [Plugins]
   plugin2 = Usb:\hiddriver.xex
   ```
3. Reinicia la consola por completo (apagado real, no solo salir de un
   juego). Vuelve a pedir `modules` por XBDM — si `hiddriver.xex` aparece
   en la lista, el plugin ya está activo.
4. Conecta el DualShock 3 (real o el emulado por este proyecto) por USB.

### Por qué también hace falta el selector de modo del ESP32-S3

Un DualShock 3 real reporta su clase de dispositivo USB como genérica
(`0x00`/`0x00`/`0x00`) al conectarse por cable — hiddriver360 exige
exactamente eso para reconocerlo. Esto **choca con lo que necesita PS2**
(clase `0xE0`, ver arriba), así que ya no hay un solo ajuste de firmware
que sirva para las tres consolas a la vez.

El firmware resuelve esto con un selector guardado en memoria flash,
usando el mismo botón **BOOT** que ya trae la placa (no hace falta
hardware nuevo):

1. Con el ESP32-S3 ya encendido y corriendo (nunca al conectarlo/resetear
   — `BOOT` es un pin de arranque del chip), mantén **BOOT** presionado
   ~1.5 segundos.
2. El LED empieza a ciclar de color cada ~0.7s: **amarillo = PS3**,
   **azul = PS2/OPL**, **morado = Xbox 360**.
3. Suelta el botón en el color que quieras — la placa guarda el modo y se
   reinicia sola para aplicarlo.

El modo elegido queda guardado permanentemente (sobrevive apagados y
reflasheos del firmware) hasta que se vuelva a cambiar a mano.

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

Una vez flasheado, el mismo botón **BOOT** (ya con el firmware corriendo,
sin resetear) sirve para elegir a qué consola se conecta la placa — ver
"Por qué también hace falta el selector de modo del ESP32-S3" en la
sección de Xbox 360 más arriba para los colores del LED y el gesto exacto.
