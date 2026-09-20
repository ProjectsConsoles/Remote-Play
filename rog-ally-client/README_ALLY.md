# PS3 Remote Play - Cliente ROG Ally X (Windows)

Porteo del cliente de la Steam Deck (carpeta `PS3 Remote Play SteamOS` en la
Deck) a Windows/ROG Ally X. Un solo `.exe` (PyInstaller) en vez de varios
scripts sueltos.

**Compilado el 2026-09-07 en este mismo server** (Windows 10 19045, Python
3.12.7 embeddable + pygame 2.6.1 + PyInstaller 6.22.2), porque es una maquina
Windows x64 igual que la Ally. **No probado contra la ROG Ally X real ni contra
un mando fisico** — no habia acceso a la consola en el momento de hacerlo. Ver
"Lo que falta verificar" abajo antes de confiar en esto para jugar.

## Contenido de esta carpeta

- `RemotePlay_Ally.exe` — el cliente. Doble click para lanzarlo (o un
  acceso directo con variables de entorno, ver mas abajo).
- `ffplay.exe` — copiado del mismo `ffmpeg-9.0.1-full_build` que usa el
  servidor de este proyecto. Tiene que estar junto al .exe (o indicar otra
  ruta con `PS3RP_FFPLAY`).
- `src/` — el codigo fuente (`main_client.py`, `gamepad_common.py`,
  `brightness_win.py`). Para volver a compilar tras un cambio, ver
  "Recompilar" abajo.
- `ps3rp_ally_client.log` — aparece junto al .exe la primera vez que corre.
  No hay consola (el .exe es `--windowed`); todo lo que en la Deck iba a
  stdout/stderr aca va a este log.

## Como se lanza

Doble click en `RemotePlay_Ally.exe`. Sale un menu (Streaming / Solo
control), navegable con mouse, teclado (flechas + Enter/Escape) o el mando
(dpad/stick + A/B).

Para saltarse el menu o cambiar algo, usar variables de entorno **antes** de
lanzar el .exe (ej. un acceso directo de Windows con
`cmd /c "set PS3RP_MODO=streaming && start RemotePlay_Ally.exe"`, o un
`.bat`):

| Variable | Default | Que hace |
|---|---|---|
| `PS3RP_MODO` | *(vacio: pregunta)* | `streaming` o `control`, salta el menu |
| `PS3RP_ESP32_IP` | `192.168.0.40` | IP del ESP32-S3 (el mismo que usa la Deck) |
| `PS3RP_ESP32_PORT` | `9000` | Puerto UDP del ESP32 |
| `PS3RP_INPUT` | `1` | `0` = no mandar input, solo video |
| `PS3RP_INPUT_RATE` | `120` | Hz del envio de input (mismo default que la Deck) |
| `PS3RP_PS_COMBO` | `SELECT+R1` | Acorde para el boton PS. `none` lo apaga |
| `PS3RP_STREAM_PORT` | `5000` | Puerto UDP donde ffplay espera el stream |
| `PS3RP_FULLSCREEN` | `1` | `0` = ventana de ffplay sin pantalla completa (util para probar) |
| `PS3RP_BRILLO` | *(vacio: 1%)* | Brillo fijo al entrar en modo control, 1-100 |
| `PS3RP_WIFI_SIN_AHORRO` | `1` | `1` pone el adaptador WiFi en *Rendimiento maximo* (plan de energia, AC y bateria) al abrir la app; `0` devuelve los valores originales que se guardaron en `wifi_power_original.json`, junto al .exe. Menos jitter/delay, algo mas de bateria. Se ajusta en *Configurar cliente*. **Sin probar en la Ally real** (si falla solo deja un AVISO en el log). |
| `PS3RP_FOCO_INPUT` | `1` | Durante el streaming la app abre una ventana propia casi invisible (alpha 1/255, transparente al toque) y la mantiene en primer plano. **Necesario en Modo Juego de Armoury Crate**: ahi el mando solo le llega al proceso con la ventana al frente y, con ffplay al frente, la app leia todo en cero. `0` = comportamiento anterior (solo sirve en Modo Escritorio). |
| `PS3RP_PLAYER` | `gstreamer` | Reproductor. `gstreamer` usa la carpeta `gstreamer\` junto al .exe (runtime MSVC 1.26.11 recortado a 20 plugins, ~178 MB; no se instala nada) con `d3d11h264dec` (GPU), `sync=false` y colas que tiran lo atrasado: sin el retraso variable de ffplay al arrancar. `ffplay` = el de antes. Si falta la carpeta, cae a ffplay solo. |
| `PS3RP_FFPLAY` | *(vacio: busca junto al .exe)* | Ruta a otro `ffplay.exe` |
| `PS3RP_DEBUG` | `0` | `1` = log detallado (botones por cambio, stats de Hz) |

A diferencia de la Deck, **el brillo se pasa directo en 0-100** (WMI ya
trabaja en porcentaje), no en unidades crudas del backlight.

## Configurar servidor y cliente desde el menu (2026-09-11)

El menu tiene ahora 4 tarjetas (2x2), no 2: ademas de Streaming/Solo control,
estan **Configurar servidor** y **Configurar cliente** - porteo 1:1 de las
mismas pantallas de la Deck, mismo protocolo UDP (puerto 9200) contra
`config_listener.ps1` del lado del servidor, asi que no hace falta nada nuevo
ahi para que funcione tambien desde la Ally.

- **Configurar servidor**: elige el modo de captura de la PC (720p/1080p
  MJPEG, o los crudos sin comprimir) y confirma la IP de esta Ally, todo por
  red. Boton para mandar solo la IP sin tocar el modo, por si cambia.
- **Configurar cliente**: las variables de la tabla de arriba (menos
  `PS3RP_FFPLAY` y `PS3RP_DEBUG`, que se dejan como variables de entorno
  nada mas), guardadas en `ally_config.json` junto al .exe. Se cargan con el
  mismo patron "solo si no esta puesta" que la Deck: una variable de entorno
  puesta a mano (acceso directo/`.bat`) sigue ganando sobre lo guardado aca.

**Interfaz en mosaicos con icono y transicion deslizante (2026-09-20).** El menu
y sus pantallas usan el mismo estilo que el cliente Android y la Deck
(`src/ui_pygame.py`): mosaicos redondeados con icono, una tira de estado del
servidor arriba del menu, y una sola ventana donde abrir una pantalla la desliza
de derecha a izquierda y volver la desliza de izquierda a derecha (0.32 s). Los
iconos estan en `iconos/` (PNG; ver "Recompilar").

Navegable por completo con el mando: la cruceta mueve el foco entre mosaicos, A
activa (en un texto o numero abre un cuadro para escribirlo; Enter en teclado),
B vuelve. En **Configurar cliente**, L1 / R1 = valor anterior / siguiente (en los
numeros, -1 / +1), X restaura los defaults (sin guardar todavia) e Y guarda. En
**Configurar servidor** los atajos son los de siempre de la Ally: A aplica (sobre
un modo), X consulta, Y manda la IP, L1 reinicia el servidor y R1 lo apaga; tocar
un modo solo lo elige. **Sin probar contra hardware real** (mismo estado que el
resto de este cliente - ver "Lo que falta verificar"); la interfaz se reviso
renderizada fuera de pantalla a 1280x720 y 1920x1080.

## Diferencias de arquitectura contra la Deck (y por que)

- **Un solo proceso, no varios.** La Deck orquesta con bash cuatro piezas
  (`start_client_stream.sh` + `client_menu.py` + `client_control_ui.py` +
  `input_client_v3.py`) como procesos separados. Aca todo vive en un .exe
  (`main_client.py`) porque el pedido era un unico ejecutable. El envio de
  input corre en un hilo de fondo SOLO en modo streaming (ahi no hay ninguna
  ventana propia compitiendo por SDL); en modo control, lectura de mando +
  envio UDP + dibujo van en el MISMO hilo/loop para no tener dos hilos
  tocando SDL/pygame a la vez (mas detalle en el comentario de
  `ejecutar_modo_control()` en el codigo).
- **UI en pygame, no tkinter.** El Python "embeddable" de python.org (el que
  se uso para compilar sin necesitar el instalador MSI, que fallaba por la
  sesion remota) no trae Tcl/Tk. Pygame ya era una dependencia dura del
  proyecto (lee el mando) y no depende de Tcl/Tk, asi que el menu y la
  ventana de control se dibujan con pygame directamente.
- **Mapeo de mando: uno solo (XInput), no dos.** La Deck distingue mando
  "nativo" vs "virtual de Steam Input" segun `lizard_mode`; eso no existe en
  Windows. `gamepad_common.py` asume que el mando de la Ally se ve como
  XInput estandar (10-11 botones, layout tipo Xbox 360) - es el mapeo que la
  Deck YA usa para su caso "virtual", asi que esta mas que probado en ESE
  contexto, pero no en la Ally.
- **Brillo por WMI, no por sysfs.** `brightness_win.py` usa
  `WmiMonitorBrightnessMethods` (lo mismo que usa el control de brillo nativo
  de Windows en laptops) en vez de escribir un archivo. Se llama por
  subprocess a PowerShell para no meter dependencias COM pesadas en el build.

## Lo que NO se porteo (a proposito)

Los ajustes de latencia mas finos del script de la Deck (`OPCIONES.md` /
`start_client_stream.sh`) son especificos de su GPU/compositor
(gamescope + Mesa: `vblank_mode`, `MESA_VK_WSI_PRESENT_MODE`, los umbrales
exactos de `PS3RP_FIFO`/`PS3RP_VQ_*`). En la Ally la ventana la maneja
DWM/Windows, no gamescope - esos numeros no significan lo mismo y copiarlos
tal cual seria puro cargo-cult. Este cliente sale con los ajustes de ffplay
que SI son genericos (`-fflags nobuffer -flags low_delay -framedrop
-sync audio`, `fifo_size=1500` paquetes) como punto de partida, pero **hay
que remedir en la Ally real** siguiendo el mismo metodo que ya esta
documentado en `OPCIONES.md` de la Deck (activar `-loglevel info` en ffplay y
mirar `vq`/`aq`/`A-V`).

Tampoco se porteo el watchdog de "video atascado" que reinicia ffplay solo -
se puede agregar despues si hace falta en la practica.

## Probado ya contra la Ally real (2026-09-11)

Primera sesion con la Ally en la red. Esto es lo que se encontro y arreglo
midiendo de verdad, no teorizando - vale la pena leerlo antes de tocar el
cliente, porque varias trampas no son obvias:

- **El mando NO se mapea por indices crudos.** La Ally expone **16 botones**
  (un XInput estandar expone 11), asi que las tablas heredadas de la Deck no
  correspondian: solo la A caia en su lugar por casualidad. Ahora se usa la
  API de **SDL_GameController**, que trae el mapeo normalizado por
  dispositivo. En el log queda `mapeo=gamecontroller` o `mapeo=crudo`.
- **La cruceta va por el hat.** SDL reconoce el mando pero sus botones
  `DPAD_*` devuelven cero siempre; el hat del joystick crudo si funciona, y
  se usa como respaldo.
- **El mando se lee SOLO desde el hilo principal.** Hubo un hilo de fondo
  para el input durante el streaming: mandaba sus ~105 paquetes/s con todos
  los botones en cero, porque en Windows SDL no actualiza el estado del
  joystick fuera del hilo principal.
- **ffplay no debe heredar `SDL_VIDEODRIVER=dummy`.** Este proceso lo pone
  para leer el mando sin abrir ventana; ffplay dibuja con SDL, asi que al
  heredarlo decodificaba el video perfecto y no dibujaba nada (proceso vivo,
  sin ventana). Se le pasa un entorno limpio.
- **Nada que tarde puede vivir en el bucle de input.** Leer el brillo lanza
  un proceso de PowerShell (300-600 ms) y se hacia una vez por segundo
  DENTRO del bucle: congelaba el input medio segundo por segundo. Se sentia
  como retraso, pulsaciones perdidas y "el cursor se mueve solo" (el ESP32
  sigue reenviando el ultimo estado recibido). Ahora va en un hilo aparte.
- **`SDL_JOYSTICK_RAWINPUT=0` es obligatorio para streaming.** Sin ventana
  real (driver dummy), SDL entregaba los EJES (gatillos) perfectos pero
  NINGUN boton digital - confirmado capturando el trafico real durante
  streaming. El backend RawInput de SDL para botones necesita foco/ventana
  foreground en Windows; los ejes se leen via XInputGetState y no les
  importa. Se fuerza XInput puro. Tiene que ir a NIVEL DE MODULO, antes de
  la primera llamada a `pygame.joystick.init()` (el menu ya la hace) - el
  hint solo se lee la primera vez que se inicializa el joystick.
- **El archivo de config se lee con `utf-8-sig`.** Si se edita desde
  PowerShell o el Bloc de notas queda con BOM, y `json.load` reventaba en
  silencio: la app usaba todos los valores por default sin avisar.

Ritmo medido despues de todo esto, en modo control: ~570 vueltas/s del
bucle, ~108 envios/s al ESP32, leer el mando cuesta 0.1 ms. Con
`PS3RP_DEBUG=1` queda una linea `[ritmo]` en el log cada 5s con esos
numeros.

## Lo que falta verificar

1. **Latencia real end-to-end del video.** Ningun numero de `OPCIONES.md` de
   la Deck aplica tal cual aca (ver arriba): la Deck tiene meses de ajuste
   fino de Mesa/gamescope que no existe en Windows/DWM. Hay que medir de
   cero.
2. **Brillo via WMI.** Funciona, pero cada lectura cuesta un proceso de
   PowerShell. Si alguna vez hace falta leerlo seguido, conviene buscar la
   via especifica de ASUS (Armoury Crate) en vez de WMI generico.
3. **El acorde del boton PS (`SELECT+R1`).** Sigue sin confirmarse si en la
   Ally hace falta o si START llega entero por fuera de Steam.
4. **Microcortes de USB del ESP32.** Se vio `ready=0` intermitente y el
   contador `fallidos` creciendo en el heartbeat. Es del lado del ESP32/PS3,
   no del cliente, pero conviene vigilarlo.

## Recompilar tras un cambio

El toolchain de build quedo instalado en este mismo server (no hace falta
reinstalar nada):

```powershell
cd C:\ps3rp-build\src
# copiar aca los .py actualizados (main_client.py, ui_pygame.py, gamepad_common.py,
# server_udp.py, brightness_win.py, wifi_power.py) y la carpeta iconos\ de este repo
# (rog-ally-client\iconos), despues:
C:\ps3rp-build\python\python.exe -m PyInstaller --noconfirm --onefile --windowed `
    --name "RemotePlay_Ally" `
    --distpath "C:\ps3rp-build\dist" `
    --workpath "C:\ps3rp-build\pyibuild" `
    --specpath "C:\ps3rp-build" `
    --add-data "C:\ps3rp-build\src\iconos;iconos" `
    main_client.py
```

`--add-data` empaqueta los iconos dentro del .exe (2026-09-20). Ademas, la app
los busca en una carpeta `iconos\` junto al .exe: copiarla ahi tambien es un
respaldo por si el empaquetado fallara (sin iconos la interfaz sigue funcionando,
solo que sin dibujitos). `ui_pygame.py` no hay que pasarlo aparte: PyInstaller lo
detecta por el `import`.

El .exe nuevo queda en `C:\ps3rp-build\dist\RemotePlay_Ally.exe`; copiarlo
a esta carpeta (`ROG Ally Windows Client\`) para reemplazar el viejo.

Nota: se instalo Python via el paquete "embeddable" (zip) en vez del
instalador normal porque el instalador MSI fallaba con error 1601 /
`0x80070005` al correr desde una sesion SSH no interactiva (el servicio de
Windows Installer no se puede acceder desde esa sesion). Si se recompila
desde una sesion de escritorio normal, un Python instalado normal (con Tcl/Tk
incluido) tambien serviria, pero en ese caso convendria evaluar volver a
tkinter en vez de pygame para la UI - o dejarlo como esta, que ya funciona.
