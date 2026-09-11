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
| `PS3RP_FFPLAY` | *(vacio: busca junto al .exe)* | Ruta a otro `ffplay.exe` |
| `PS3RP_DEBUG` | `0` | `1` = log detallado (botones por cambio, stats de Hz) |

A diferencia de la Deck, **el brillo se pasa directo en 0-100** (WMI ya
trabaja en porcentaje), no en unidades crudas del backlight.

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

## Lo que falta verificar (no se pudo probar sin la Ally)

1. **Mapeo de botones/ejes.** `gamepad_common.py` asume que SDL ve el mando de
   la Ally exactamente como un XInput/Xbox 360 estandar. Correr con
   `PS3RP_DEBUG=1`, entrar en modo control, apretar cada boton y mirar
   `ps3rp_ally_client.log` (o el indicador en pantalla) contra lo que
   deberia ser. Si algo sale mal mapeado, se ajusta en
   `gamepad_common.BUTTON_NAMES` / `AXIS_NAMES`.
2. **Brillo via WMI.** Puede que el driver de pantalla de la Ally no exponga
   `WmiMonitorBrightnessMethods` (pasa en algunos paneles). Si la barra sale
   deshabilitada con "no disponible via WMI", hay que buscar la alternativa
   especifica de ASUS (Armoury Crate expone su propio control; puede que
   haga falta llamar a su SDK/CLI en vez de WMI generico).
3. **Latencia real end-to-end.** Ningun numero de `OPCIONES.md` de la Deck
   aplica tal cual aca (ver arriba). Hay que medir de cero.
4. **Pantalla completa (`-fs`) con el compositor de Windows.** No se sabe si
   tapa la barra de tareas limpio o si hace falta `PS3RP_FULLSCREEN=0` +
   maximizar a mano en la practica.
5. **El acorde del boton PS (`SELECT+R1`).** En la Deck existe porque Steam
   Input intercepta START antes de llegar a pygame. Si en la Ally se lanza
   por fuera de Steam, es posible que START llegue entero y el acorde ni
   haga falta - probar primero si START solo ya funciona como boton PS antes
   de asumir que hace falta el acorde.

## Recompilar tras un cambio

El toolchain de build quedo instalado en este mismo server (no hace falta
reinstalar nada):

```powershell
cd C:\ps3rp-build\src
# copiar aca los .py actualizados, despues:
C:\ps3rp-build\python\python.exe -m PyInstaller --noconfirm --onefile --windowed `
    --name "RemotePlay_Ally" `
    --distpath "C:\ps3rp-build\dist" `
    --workpath "C:\ps3rp-build\pyibuild" `
    --specpath "C:\ps3rp-build" `
    main_client.py
```

El .exe nuevo queda en `C:\ps3rp-build\dist\RemotePlay_Ally.exe`; copiarlo
a esta carpeta (`ROG Ally Windows Client\`) para reemplazar el viejo.

Nota: se instalo Python via el paquete "embeddable" (zip) en vez del
instalador normal porque el instalador MSI fallaba con error 1601 /
`0x80070005` al correr desde una sesion SSH no interactiva (el servicio de
Windows Installer no se puede acceder desde esa sesion). Si se recompila
desde una sesion de escritorio normal, un Python instalado normal (con Tcl/Tk
incluido) tambien serviria, pero en ese caso convendria evaluar volver a
tkinter en vez de pygame para la UI - o dejarlo como esta, que ya funciona.
