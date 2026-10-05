# Servidor de PC (juegos de Windows en la tableta)

Para jugar los juegos **de una PC con Windows** en la tableta Android, con la misma
app que se usa para las consolas. Es una alternativa propia a Moonlight/Sunshine,
pensada para dar el menor retraso posible en la red de casa.

> **Estado:** funcional. Probado en una laptop MSI (Intel + NVIDIA con Advanced
> Optimus, cable de red) y una Samsung Galaxy Tab A9 por WiFi de 5 GHz, con Elden
> Ring Nightreign: ~60 fps, video + audio + mando + táctil.

```
 PC con Windows                                                     Tableta Android
 ┌───────────────────────────────────────────────┐                  ┌──────────────────┐
 │ pantalla --ddagrab--> NVENC (H.264) --+       │                  │                  │
 │ sonido   --loopback--> Opus ----------+-> TS ─┼── UDP 5000 ────> │ video + audio    │
 │                                               │                  │                  │
 │ control de Xbox 360 virtual <── ViGEmBus <────┼── UDP 9000 ───── │ mando + táctil   │
 │ mouse (SendInput)          <──────────────────┤                  │                  │
 │ estado / iniciar / detener <──────────────────┼── UDP 9200 ───── │ "Streaming → PC" │
 └───────────────────────────────────────────────┘                  └──────────────────┘
```

Todo vive en un solo programa, `pc_server.py`:

- **Video:** captura la pantalla con Desktop Duplication (`ddagrab` de ffmpeg) y
  la comprime con NVENC con ajustes de baja latencia (`p1`, `ull`, sin B-frames,
  intra-refresh). Va en MPEG-TS por UDP, igual que el servidor de las consolas, así
  que la app lo reproduce sin cambios.
- **Audio:** lo que suena en la PC, capturado por loopback de WASAPI y comprimido
  en Opus de 5 ms. Mientras transmite, la salida de Windows pasa a la bocina
  virtual de Steam para que **suene solo en la tableta**. Al detener vuelve la
  salida que había.
- **Mando:** el mismo JSON que la tableta le manda al ESP32 se convierte en un
  **control de Xbox 360 virtual** (ViGEmBus + `vgamepad`). Los juegos lo ven
  como un control real (jugador 1).
- **Táctil:** en la tableta, un dedo mueve el mouse y hace clic o arrastra; dos
  dedos dan clic derecho o scroll.
- **Pantalla de la PC:** se pone negra (brillo 0) mientras transmite y regresa
  al terminar.

## Requisitos

- Windows 10 u 11 con una **NVIDIA** (para NVENC).
- **Python 3.12** de python.org, instalado para todos los usuarios
  (`C:\Program Files\Python312`).
- **ffmpeg 8 o más nuevo**: `winget install Gyan.FFmpeg`. El servidor lo busca
  solo; si está en otro lado, se indica con `PS3RP_FFMPEG`.
- **ViGEmBus** (driver del control virtual): [ViGEmBus 1.22](https://github.com/nefarius/ViGEmBus/releases).
- **Steam** (opcional, recomendado): trae la bocina virtual *Steam Streaming
  Speakers*. Sin ella el audio se transmite igual, pero también suena en la PC.
- La PC **por cable** al router; la tableta en WiFi de 5 GHz.

Puede convivir con Sunshine: usan puertos distintos.

## Instalar

1. Copiar esta carpeta a la PC, por ejemplo `C:\ps3rp-pc`, junto con
   `deck-client/ui_mosaicos.py`, la carpeta `deck-client/iconos/` y
   `deck-client/remote_play_steam_assets/icon_256.png`. La ventana reusa los
   mosaicos y el ícono de la Deck.
2. Abrir PowerShell **como administrador** en esa carpeta y correr:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\instalar_tarea.ps1
   ```

Eso instala las librerías de Python (`vgamepad`, `pyaudiowpatch`, `pycaw`,
`pystray`, `pillow`) y abre los puertos UDP 9200 y 9000 en el firewall (solo
red local). También crea la tarea programada **"PS3RP PC Server"**, que arranca
el servidor al iniciar sesión, y el acceso directo **"Remote Play - Servidor de
PC"** en el escritorio. Se puede repetir sin problema.

> El servidor **tiene que correr en la sesión del usuario**, no por SSH ni como
> servicio: Windows solo deja capturar la pantalla y crear el control virtual
> desde el escritorio real. Por eso se usa una tarea programada interactiva.

## Usar

1. En la tableta: **Configurar cliente → IP de la PC (juegos)** (una sola vez).
2. **Streaming → PC (juegos de Windows)**. La app le avisa a la PC, que empieza
   a transmitir a la tableta.
3. Para salir: **L1 + R1 + SELECT + START**. Si la tableta deja de mandar el
   mando por 60 s, la PC deja de transmitir sola.

En la PC, el servidor arranca oculto con un **ícono junto al reloj**: un punto gris
significa esperando y uno verde, transmitiendo. Al ícono o al acceso directo del
escritorio se le da doble clic para abrir la ventana: muestra el estado, los fps y
Mbps reales, el audio, el mando y la tableta conectada, y tiene los botones
**Detener transmisión**, **Ocultar** y **Salir**. Si el servidor estaba apagado,
el acceso directo lo arranca.

## Para que se vea lo más fluido posible

Medido con un juego a 60 fps:

- **Pantalla de la PC a 60 Hz** mientras se juega. Con 144 Hz, los cuadros del
  juego quedan desfasados de la pantalla de 60 Hz de la tableta.
- **Juego en ventana sin bordes** o pantalla completa sin bordes.
- **Ritmo parejo** en la tableta (*Configurar cliente*, **+50 ms** por defecto).
  Los cuadros se muestran a ritmo parejo, según la hora en que se capturaron, en
  vez de en cuanto llegan. Quita los tirones que mete el WiFi (~20 ms de desfase
  normal) a cambio de ese retraso extra. Con *Apagado* se dibuja cada cuadro en
  cuanto llega.
- **PC por cable.** La tableta, cerca del router en 5 GHz.

**Lo que queda:** en una laptop con Optimus (la pantalla en la Intel y el juego
en la NVIDIA), la captura de Windows se salta algún cuadro más o menos cada 15 s
(un tirón de ~140 ms). Es igual con cualquier ajuste de captura. En una PC con la
pantalla conectada directo a la NVIDIA no debería pasar.

## Ajustes

Variables de entorno, opcionales; los valores por defecto son los medidos como
mejores:

| Variable | Defecto | Qué hace |
|---|---|---|
| `PS3RP_PC_FPS` | `240` | Cuántas veces por segundo se revisa la pantalla. Solo sale un cuadro cuando cambió, con la hora de la revisión: a 240 el 98 % de los cuadros de un juego a 60 salen parejos; a 90, ninguno. |
| `PS3RP_PC_DUP_FRAMES` | `0` | `1` = repetir cuadros aunque la pantalla no cambie. Con repetidos la tableta recibe más de 60 a destiempo y su pantalla tira cuadros buenos. |
| `PS3RP_PC_BITRATE_MBPS` | `15` | Bitrate real aproximado a 60 fps. Internamente se escala por `FPS/60`, porque NVENC lo reparte según el tope. |
| `PS3RP_PC_INTRA_REFRESH` | `1` | Refresco por franjas en vez de cuadros clave enteros (sin "parpadeo" cada medio segundo). Con `0`, cuadro clave cada 30. |
| `PS3RP_PC_MAX_INTERLEAVE_US` | `50000` | Cuánto espera el audio al video. Con la pantalla quieta no sale video y el audio sigue igual. |
| `PS3RP_PC_SALIDA_VIRTUAL` | `Steam Streaming Speakers` | Salida de audio a la que se cambia Windows mientras transmite. Vacía = no cambiar. |
| `PS3RP_PC_APAGAR_PANTALLA` | `1` | Brillo 0 mientras transmite. |
| `PS3RP_PC_SIN_VENTANA` | — | `1` = sin ventana ni ícono (solo el servidor). |
| `PS3RP_PC_PUERTO_VIDEO` / `_MANDO` / `_RELEVO` | `5000` / `9000` / `5099` | Puertos. `_RELEVO` es local (ver abajo). |
| `PS3RP_FFMPEG` | — | Ruta de `ffmpeg.exe` si no se encuentra solo. |

## Protocolo

- **UDP 9200** (JSON): `get_config` (estado), `set_config` (`{"ip": ...}`:
  transmitir a esa IP; si ya transmitía, se reinicia), `stop_server` y
  `mostrar_ventana` (solo desde la misma PC, lo usa el acceso directo). Es el
  mismo protocolo que `windows-server/config_listener.ps1`.
- **UDP 9000**: el JSON del mando (`GamepadState.toJson` de la app) y los
  eventos táctiles `{"mouse": {"ev": "mover|clic|clic_der|izq_abajo|izq_arriba|scroll", "x": 0..1, "y": 0..1}}`.
- **UDP 5000**: MPEG-TS hacia la tableta. ffmpeg no lo manda directo: lo manda a
  `127.0.0.1:5099` y el servidor lo reenvía. Si la red se atora y Windows dice
  que el buffer está lleno (`WSAENOBUFS`), se tira ese paquete y se sigue. Directo,
  ffmpeg se cerraba y la tableta se quedaba 1–2 s sin imagen.

## Detalles de la laptop con Optimus

- Con un juego abierto, la pantalla puede pasar de la Intel a la NVIDIA. Un
  vigía revisa cada segundo en qué tarjeta está la pantalla y reinicia la captura
  si cambia, o si ffmpeg se cae. Con la pantalla en la NVIDIA, NVENC toma los
  cuadros directo; con la pantalla en la Intel se copian a memoria primero
  (`hwdownload`).
- Si el servidor se cerró a la fuerza, al arrancar mata el ffmpeg que haya
  quedado vivo: si no, seguía mandando video a la tableta encima del nuevo. Al
  arrancar también regresa la salida de audio y el brillo de antes.

## Archivos

| Archivo | Qué es |
|---|---|
| `pc_server.py` | El servidor: video, audio, mando, táctil, relevo y vigía |
| `pc_gui.py` | Ventana en mosaicos e ícono junto al reloj (reusa `deck-client/ui_mosaicos.py`) |
| `abrir_servidor.pyw` | Lo que abre el acceso directo: muestra la ventana o arranca el servidor |
| `instalar_tarea.ps1` | Instalación: librerías, firewall, tarea programada y acceso directo |
| `icono.ico` | Ícono del acceso directo |

Logs junto al servidor: `pc_server.log` (lo que hace el servidor), `ffmpeg.log`
(avisos de ffmpeg) y `ffmpeg_progreso.log` (cuadros y bytes por segundo).
