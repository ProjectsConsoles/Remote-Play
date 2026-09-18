# Opciones de configuración

Todas las perillas del proyecto, de los dos lados. Ninguna requiere editar
código: son variables de entorno.

Los valores **por defecto son los buenos** — están ahí porque se midieron. Esta
lista es para diagnosticar o experimentar, no una lista de cosas por ajustar.

---

## Cómo se pasan

**En Modo Juego (lo normal).** Propiedades del juego → *Opciones de
lanzamiento*, con `%command%` al final:

```
PS3RP_MODO=control %command%
```

Varias juntas, separadas por espacios:

```
PS3RP_INPUT_RATE=60 PS3RP_STATS=1 %command%
```

**Desde una terminal (Modo Escritorio):**

```bash
PS3RP_MODO=control ./start_client_stream.sh
```

**Del lado del servidor (Windows):** normalmente no hace falta tocar nada, la
interfaz gráfica (`iniciar_servidor.bat`) las pone sola.

---

## Cliente — Steam Deck (`start_client_stream.sh`)

### Modo de arranque

| Variable | Default | Qué hace |
|---|---|---|
| `PS3RP_MODO` | *(vacío: pregunta)* | `streaming` o `control` para saltarse el menú. Útil para dejar **dos accesos directos distintos** en Steam. |
| `PS3RP_BRILLO` | *(vacío: 1 %)* | Brillo de la pantalla en modo control, en unidades crudas (0–65535). `PS3RP_BRILLO=0` la apaga del todo. |
| `PS3RP_BACKLIGHT` | `/sys/class/backlight/amdgpu_bl0` | Carpeta del backlight. Solo si alguna vez cambia de nombre. |

> **Por qué el default no es 0.** Con la pantalla completamente negra en Modo
> Juego no hay forma de distinguir *"el modo control está andando"* de *"se
> colgó"*. El 1 % queda apenas visible y ahorra batería igual.

> **El brillo también se ajusta a mano** desde la barra de la ventana del modo
> control, sin salir. `PS3RP_BRILLO` solo fija con cuánto arranca. La barra no
> baja de 1 %: a oscuras total no se vería a sí misma para volver a subirla, y
> esa ventana no escucha el mando a propósito.

### Cómo se sale

- **"Salir" en el modo control** devuelve al **selector**, no cierra la
  aplicación. Al volver, mata su cliente de input y restaura el brillo.
- **Cancelar el selector** (botón **B** o Escape) es lo que cierra la
  aplicación entera.
- **Cerrar el streaming** cierra la aplicación, como siempre.
- `PS3RP_MODO` fijo se salta el selector; ahí el modo control sí termina la
  aplicación al salir, porque no habría menú al que volver.

### Control remoto (ESP32 → PS3)

| Variable | Default | Qué hace |
|---|---|---|
| `PS3RP_ESP32_IP` | `192.168.0.40` | IP del ESP32-S3. |
| `PS3RP_ESP32_PORT` | `9000` | Puerto UDP del ESP32. |
| `PS3RP_INPUT` | `1` | `0` = solo video, sin control. |
| `PS3RP_INPUT_RATE` | `120` | Hz a los que se manda el estado del mando. |
| `PS3RP_PS_COMBO` | `SELECT+R1` | Qué acorde hace de botón PS. También `SELECT+L1+R1`, o `none` para apagarlo. |

> **Por qué 120 Hz y no 60.** El firmware del ESP32 manda su reporte HID cada
> 8 ms (125 Hz). A 60 Hz se regalaban hasta ~16 ms de espera pura en cada
> pulsación. Medido: 118.9 Hz efectivos, sin errores.

> **Por qué el botón PS es un acorde.** El botón ☰ (START) lo intercepta Steam y
> el botón Steam también. El ancla del acorde (⧉ = SELECT) se retiene 80 ms; los
> demás pasan al instante, para que un `R1` en el acorde no retrase cada disparo
> del juego. Por eso el ancla debe ser un botón de menú.

### Video y latencia

| Variable | Default | Qué hace |
|---|---|---|
| `PS3RP_PLAYER` | `gstreamer` | **Default desde 2026-09-18** ("igualito a la tele" en 3 de 3 arranques; ffplay caia en un retraso distinto cada vez). `ffplay` es el de antes, con watchdog y Lossless Scaling. `gstreamer` usa el gst-launch del runtime Freedesktop 25.08 (via el flatpak de mpv; el GStreamer de SteamOS no trae decodificador H.264) con `vah264dec`, `sync=false` y colas que tiran lo atrasado. `mpv` usa el flatpak `io.mpv.Mpv` (instalar: `flatpak install --user flathub io.mpv.Mpv`) en modo `--untimed`: pinta cada cuadro apenas llega, sin la cola de retraso que ffplay arma al arrancar. Con mpv NO hay watchdog ni ajuste de Lossless Scaling. Si no esta instalado, cae a ffplay con un AVISO. |
| `PS3RP_VSYNC` | `0` | `1` devuelve el vsync (`vblank_mode` + present mode de Mesa). |
| `PS3RP_WIFI_SIN_AHORRO` | `1` | `1` apaga el power save del WiFi (`wlan0`) en cada arranque, `0` lo regresa a prendido. Menos jitter/delay (se noto a ojo en la Deck), algo mas de bateria. Necesita instalar una vez `sudoers-wifi-powersave` (instrucciones en su encabezado); sin eso no rompe nada, solo deja un AVISO en `~/ps3rp_client.log`. |
| `PS3RP_PRESENT` | `mailbox` | Modo de presentación Vulkan. `fifo` = con cola (más lag). |
| `PS3RP_SYNC` | `audio` | Reloj maestro de ffplay. `video` y `ext` existen pero **midieron peor**. |
| `PS3RP_FIFO` | `1500` | Buffer UDP en **paquetes de 188 bytes**, no en bytes. |
| `PS3RP_NOAUDIO` | `0` | `1` quita el audio. **Es de medición, no para jugar.** |
| `PS3RP_AUDIO_MS` | *(vacío)* | Achica el buffer de salida de audio. ⚠️ **Baja el lag pero desincroniza el audio del video.** Ya se probó y se descartó. |

> ⚠️ **`SDL_RENDER_VSYNC` no existe como perilla y no funcionaría.** El ffplay de
> SteamOS no enlaza SDL2 real sino sdl2-compat sobre SDL3, que ignora esa
> variable. Está medido. El vsync se apaga por debajo, a nivel Mesa.

### Watchdog de atasco de video

Reinicia `ffplay` solo si el video se queda atrasado.

| Variable | Default | Qué hace |
|---|---|---|
| `PS3RP_WATCHDOG` | `1` | `0` = nunca reiniciar solo. |
| `PS3RP_VQ_MAX` | `100` | KB de video encolado a partir de los cuales sospecha. |
| `PS3RP_VQ_SECS` | `10` | Segundos seguidos por encima del tope antes de actuar. |
| `PS3RP_VQ_ESPERA` | `90` | Veda tras un reinicio, para que no se realimente. |
| `PS3RP_FD_SALTO` | `6` | Salto en `fd=` (cuadros descartados por ffplay) en 1s que reacciona de golpe - detecta rafagas del servidor que descuadran Lossless Scaling sin llenar vq/aq. Con lsfg activo baja el multiplier en vez de reiniciar ffplay (ver abajo); sin lsfg, reinicia ffplay. |
| `PS3RP_LSFG_CONF` | `~/.config/lsfg-vk/conf.toml` | Donde esta el conf.toml de lsfg-vk, para bajarle el multiplier un momento en vez de reiniciar ffplay. |
| `PS3RP_LSFG_PAUSA` | `4` | Segundos que se deja el multiplier de lsfg en 1 antes de restaurarlo solo. |
| `PS3RP_VQ_ARRANQUE` | `0` (apagado) | Reintento de **arranque**: cada arranque de ffplay aterriza en un nivel de retraso distinto (`vq` 0-23 KB en unas corridas, 60-78 en otras) y se queda ahi. Si en los segundos 20-50 `vq` se queda >= este valor 8 s seguidos, reinicia ffplay para volver a tirar el dado. Apagado por defecto (reiniciaba el video muy seguido); para probarlo, `40`. |
| `PS3RP_VQ_ARRANQUE_INTENTOS` | `3` | Cuantos reintentos de arranque como maximo (no cuentan para el tope de 5 reinicios del watchdog). Un reinicio normal del watchdog los repone. |

> **El reinicio se autoalimenta**: reiniciar sube la cola, lo que dispara otro
> reinicio. La veda de 90 s es lo que rompe el bucle. Si algún día se retocan
> estos números, tenerlo presente.

### Diagnóstico

| Variable | Default | Qué hace |
|---|---|---|
| `PS3RP_STATS` | `0` | `1` vuelca todas las líneas de estado de ffplay al log. |
| `PS3RP_STATS_EVERY` | `30` | Segundos entre líneas de estadísticas. `0` lo apaga. |

**El log del cliente vive en `~/ps3rp_client.log`.** Dos campos importan:

- **`A-V`** — dice si el desfase de audio se genera en el stream (crece) o no
  (se queda cerca de 0).
- **`vq`** — video encolado. Si sube y se queda arriba, hay atasco.

---

## Servidor — PC Windows (`start_server_stream.bat`)

Lo normal es no tocarlas: la interfaz (`iniciar_servidor.bat`) las pone sola.

| Variable | Qué hace |
|---|---|
| `PS3RP_IP` | IP de la Deck. Si viene puesta, el `.bat` **no pregunta**. Igual valida. |
| `PS3RP_MODO` | Modo de captura (ver tabla abajo). |
| `PS3RP_GUI` | `1` = saltarse los `pause`. **Obligatorio si se corre con la ventana oculta**, o un mensaje de error queda esperando una tecla que nadie puede presionar. |

### Modos de captura

| Clave | Resolución | Bitrate | Notas |
|---|---|---|---|
| `mjpeg720` | 1280x720 60 fps | 5M | **Default. El único probado a fondo.** |
| `mjpeg1080` | 1920x1080 60 fps | 8M | Más nítido, más carga de wifi. Sin probar. |
| `crudo480` | 720x480 60 fps | 5M | Sin comprimir. Prueba de latencia. |
| `crudo640` | 640x480 60 fps | 5M | Sin comprimir, pide menos por el USB. |

También funcionan sin variables: `start_server_stream.bat crudo`, el atajo
`probar_modo_crudo.bat`, o la línea `set MODO_CRUDO=1` arriba del `.bat`.

> **Los modos crudos llevan `-aspect 16:9`** porque 720x480 no es 16:9 y sin eso
> la Deck lo mostraría achatado. No reescala nada, solo marca el stream. Si la
> imagen sale estirada **al revés**, es que la capturadora ya manda barras
> negras: quitar ese `-aspect`.

**Los logs del servidor van a `server-share\logs\`**, dos por corrida.
`revisar_log.bat` los resume: fps, `speed`, cuadros duplicados/tirados y avisos
de `real-time buffer full`.

---

## Recetas

| Si te pasa esto | Prueba esto |
|---|---|
| El PS3 no responde a los botones | **Reconectar el cable USB del ESP32 antes que nada.** Pasó varias veces y siempre se curó así. |
| Pantalla negra en la Deck | La IP de la Deck cambió. ffmpeg manda UDP al vacío sin dar ningún error. |
| El acorde del botón PS se dispara solo en un juego | `PS3RP_PS_COMBO="SELECT+L1+R1"` |
| Quieres saber si el lag es del video o del control | `PS3RP_STATS=1` y mirar `vq` y los `[stats]` del cliente de input |
| El menú de arranque estorba | `PS3RP_MODO=streaming` o `=control` |
| El servidor no arranca y no ves por qué | Abrir `start_server_stream.bat` **directo**: muestra la consola con todo |

---

## Lo que ya se descartó (no volver a perseguir)

Cada una de estas se probó y se midió. Están aquí para no repetir el trabajo:

- **Comprar capturadora nueva no arregla el lag.** La vista previa local de la
  capturadora se ve instantánea, y el modo sin comprimir no mejoró nada.
- **El buffer de salida de audio de la Deck** (`PS3RP_AUDIO_MS`): baja el lag
  pero desincroniza. El retraso del audio se genera en la PC, no aquí.
- **`SDL_RENDER_VSYNC` y `MESA_VK_WSI_PRESENT_MODE=immediate`**: los dos son
  letra muerta en este sistema. Verificar siempre en el log que un ajuste se
  aceptó, no darlo por hecho.
- **La red hacia el ESP32**: ping de 3–16 ms. No es el problema.
- **Parte del lag no es del pipeline**: un juego de PS3 trae ~100 ms propios
  (render interno + v-sync) antes de que la señal salga por el HDMI. El XMB no
  los tiene, por eso se siente más rápido.
