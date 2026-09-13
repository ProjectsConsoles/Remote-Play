#!/bin/bash
# ============================================================
# PS3 Remote Play - Cliente completo (Steam Deck)
#   video + audio (ffplay)  +  control remoto (input_client_v3.py)
# ============================================================
# Lanza las dos mitades del sistema en una sola entrada de Steam:
#   - Recibe y muestra el stream de video+audio que manda la PC.
#   - Manda el estado del control de la Deck por UDP al ESP32-S3, que lo
#     reinyecta al PS3 emulando un DualShock 3 por USB cableado.
# El control corre en segundo plano y se cierra solo al salir del video.
#
# Un solo proceso ffplay recibe el stream unificado
# (MPEG-TS con video+audio juntos) por un solo puerto.
# El lado del servidor (start_server_stream.bat, en el share de
# la PC) hace el mux; ver ese archivo para la sintonia de latencia
# del lado de la captura/encode.
#
# Requiere ffplay instalado (via flatpak org.freedesktop.Platform.ffmpeg-full
# o el paquete de tu distro).
#
# Pensado para agregarse a Steam como "juego no-Steam" y lanzarse
# desde el Modo Juego (Gaming Mode). -fs lo abre en pantalla
# completa. Para cerrarlo en Modo Juego: Boton Steam -> menu de
# acceso rapido -> pestaña de energia -> "Cerrar aplicacion".
# ============================================================

PORT=5000
LOG="$HOME/ps3rp_client.log"

# SCRIPT_DIR se necesita ARRIBA de las variables PS3RP_* (mas abajo tenia su
# propia definicion, duplicada, justo antes de INPUT_SCRIPT/MENU_SCRIPT/etc -
# se quito esa copia). Hace falta aca temprano para poder cargar
# client_config.env ANTES de que las lineas ${PS3RP_X:-default} lean esas
# variables.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# client_config.env (2026-09-11): lo escribe la pantalla "Configurar cliente"
# del menu de la Deck (client_settings.py). Son las MISMAS variables PS3RP_*
# de siempre, para no inventar un mecanismo de configuracion aparte - solo
# les da un lugar donde vivir entre lanzamientos sin tener que escribirlas a
# mano en las opciones de lanzamiento de Steam cada vez.
#
# PRIORIDAD: si Steam ya trae la variable puesta en sus opciones de
# lanzamiento (%command%), esta carga NO LA PISA - bash ya la trae en el
# entorno antes de que este script arranque, y las lineas de abajo son
# `export` normales, que si sobreescribirian. Por eso el archivo se genera
# con el patron "solo si no esta puesta" (`: "${VAR:=valor}"`), no con
# `export VAR=valor` a secas.
if [ -f "$SCRIPT_DIR/client_config.env" ]; then
    source "$SCRIPT_DIR/client_config.env"
fi

# Lossless Scaling / frame generation via lsfg-vk (2026-09-11): normalmente
# esto se prende escribiendo "~/lsfg %command%" a mano en las Opciones de
# Lanzamiento de Steam, envolviendo TODO el comando desde afuera - pero eso
# no se puede prender/apagar desde la pantalla "Configurar cliente" porque
# para cuando este script arranca, Steam ya decidio si envolverlo o no. En
# vez de eso, el envoltorio se mueve PARA ADENTRO: si PS3RP_LSFG=1 (puesto
# por client_config.env, igual que las demas variables), este script se
# re-ejecuta a si mismo A TRAVES de ~/lsfg. El guard PS3RP_LSFG_ENVUELTO
# evita que, ya envuelto, el propio ~/lsfg vuelva a lanzar bash con este
# script y se re-envuelva para siempre.
if [ "${PS3RP_LSFG:-0}" = "1" ] && [ -z "$PS3RP_LSFG_ENVUELTO" ]; then
    if [ -x "$HOME/lsfg" ]; then
        export PS3RP_LSFG_ENVUELTO=1
        # Ruta absoluta via SCRIPT_DIR (no "$0"): si Steam algun dia invoca
        # este script con una ruta relativa o distinta a BASH_SOURCE, "$0"
        # podria no ser un camino valido una vez que ~/lsfg haga su propio
        # "exec $@" desde el home del usuario.
        exec "$HOME/lsfg" "$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")" "$@"
    else
        echo "PS3RP_LSFG=1 pero no existe (o no es ejecutable) $HOME/lsfg - sigo sin el." >> "$LOG"
    fi
fi

# ------------------------------------------------------------
# Control remoto (input) - se lanza junto con el video
# ------------------------------------------------------------
# input_client_v3.py lee el control fisico de la Deck y manda su estado por
# UDP al ESP32-S3, que lo reinyecta al PS3 emulando un DualShock 3 por USB.
# Se lanza aca en segundo plano para que "juego = video + control" sea una
# sola entrada en Steam, y se mata al salir (ver trap mas abajo).
#
# Se puede sobreescribir sin editar el script:
#   PS3RP_ESP32_IP=192.168.0.55 ./start_client_stream.sh
#   PS3RP_INPUT=0 ./start_client_stream.sh    # solo video, sin control
ESP32_IP="${PS3RP_ESP32_IP:-192.168.0.40}"
ESP32_PORT="${PS3RP_ESP32_PORT:-9000}"
# 120 Hz por default (antes 60): el firmware del ESP32 manda su reporte HID cada
# 8ms (125Hz), asi que mandandole a 60Hz se regalaban hasta ~16ms de espera pura
# en cada pulsacion. Se venia pasando a mano con `PS3RP_INPUT_RATE=120 %command%`
# en las opciones de lanzamiento de Steam - medido asi el 2026-08-29 en el log:
# 118.9 Hz efectivos, sin errores. Ahora es el default para no depender de que
# esa linea este puesta (la ultima corrida del log salio en 60 Hz justamente
# porque faltaba). Volver atras: PS3RP_INPUT_RATE=60.
INPUT_RATE="${PS3RP_INPUT_RATE:-120}"
ENABLE_INPUT="${PS3RP_INPUT:-1}"

# ------------------------------------------------------------
# Perillas de latencia (para medir, sin editar el script)
# ------------------------------------------------------------
#   PS3RP_VSYNC=1   ./start_client_stream.sh   # volver a vsync (default 0)
#   PS3RP_NOAUDIO=1 ./start_client_stream.sh   # video sin audio (diagnostico)
#   PS3RP_AUDIO_MS=30 ./start_client_stream.sh # achicar buffer de audio (gana ~13ms, ver abajo)
#   PS3RP_SYNC=video ./start_client_stream.sh  # reloj maestro = video (MIDE PEOR, ver abajo)
#   PS3RP_PRESENT=fifo ./start_client_stream.sh # modo de presentacion Vulkan (default: mailbox)
#   PS3RP_STATS=1   ./start_client_stream.sh   # medir las colas internas de ffplay
#   PS3RP_FIFO=130000 ./start_client_stream.sh # volver al buffer UDP viejo (ver abajo)
#   PS3RP_WATCHDOG=0 ./start_client_stream.sh  # no reiniciar ffplay solo (ver abajo)
#   PS3RP_VQ_MAX=200 PS3RP_VQ_SECS=30 ...      # hacerlo mas conservador todavia
#   PS3RP_PS_COMBO="SELECT+L1+R1" ...          # que acorde hace de boton PS
#                                              # (default SELECT+R1; "none" lo apaga)
# Ver la explicacion larga de cada una junto a la linea de ffplay.
VSYNC="${PS3RP_VSYNC:-0}"
NOAUDIO="${PS3RP_NOAUDIO:-0}"
AUDIO_MS="${PS3RP_AUDIO_MS:-}"   # vacio = no tocar el buffer de audio (default)
SYNC="${PS3RP_SYNC:-audio}"      # reloj maestro = audio (default de ffplay); ver la nota larga
PRESENT="${PS3RP_PRESENT:-mailbox}"  # modo de presentacion Vulkan; ver la nota del vsync
STATS="${PS3RP_STATS:-0}"        # 1 = medir las colas internas de ffplay (ver nota abajo)
# Cada cuantos segundos dejar UNA linea de estadisticas en el log aunque no se
# haya pedido el modo medicion. Sin esto el log no sirve para diagnosticar nada
# despues del hecho: el watchdog CONSUME la linea de stats pero no la escribia,
# asi que las corridas quedaban sin rastro de A-V ni de vq. 30 s son 120 lineas
# por hora, nada. PS3RP_STATS_EVERY=0 lo apaga.
STATS_EVERY="${PS3RP_STATS_EVERY:-30}"
FIFO="${PS3RP_FIFO:-1500}"        # buffer UDP en PAQUETES de 188 bytes (no en bytes; ver nota larga)
# Watchdog del atasco de video. Ver la nota larga junto al lazo de ffplay.
WATCHDOG="${PS3RP_WATCHDOG:-1}"  # 0 = no reiniciar ffplay solo, nunca
VQ_MAX="${PS3RP_VQ_MAX:-100}"    # KB de video encolado a partir de los cuales se sospecha
VQ_SECS="${PS3RP_VQ_SECS:-10}"   # segundos seguidos por encima del tope antes de actuar
VQ_ESPERA="${PS3RP_VQ_ESPERA:-90}"  # segundos de veda despues de un reinicio, para no realimentarse
# Salto en fd= (cuadros descartados por ffplay) que dispara una reaccion DE
# GOLPE, sin esperar vqsecs (2026-09-13, ver la nota larga junto al lazo de
# ffplay: rafagas de cuadros del servidor - cambio de consola/juego, pantalla
# negra de HDMI - no llenan vq ni aq (ffplay las absorbe bien solo), pero
# descuadran a Lossless Scaling (~/lsfg), que necesita ritmo parejo para
# interpolar y se queda "trabado" de una forma que ningun contador de ffplay
# mide directo. fd SI salta de golpe en esas rafagas (confirmado en vivo:
# fd=52 con vq=0KB/aq=0KB durante el problema).
FD_SALTO="${PS3RP_FD_SALTO:-6}"

# AJUSTE SIN PARPADEO (2026-09-13): reiniciar ffplay arregla el atasco de
# lsfg pero cierra y vuelve a abrir la ventana - "se ve muy mal" (reportado
# el mismo dia). lsfg-vk permite recargar "multiplier"/flow_scale/
# performance_mode EN CALIENTE via su conf.toml, sin reiniciar el proceso
# que envuelve - asi que si esta corriendo bajo ~/lsfg (PS3RP_LSFG=1),
# apagamos la generacion de cuadros (multiplier=1) unos segundos en vez de
# tocar ffplay para nada. $LSFG_PROCESS ya viene puesto por el propio
# ~/lsfg del usuario (ver ese archivo) - es el nombre del perfil dentro del
# conf.toml, no algo que este proyecto invente. Si no esta corriendo bajo
# lsfg, o no se encuentra el perfil/archivo, se cae de vuelta al reinicio
# de ffplay de siempre (ver reiniciarFfplay en el watchdog).
LSFG_CONF="${PS3RP_LSFG_CONF:-$HOME/.config/lsfg-vk/conf.toml}"
LSFG_PAUSA="${PS3RP_LSFG_PAUSA:-4}"
LSFG_PAUSA_SCRIPT="$SCRIPT_DIR/lsfg_pausa_temporal.sh"
# Veda ENTRE disparos del ajuste de lsfg (2026-09-13, distinta de "espera"/
# VQ_ESPERA de arriba - esas gobiernan el reinicio de ffplay, que aca ya no
# pasa). Medido en vivo contra el juego ICO (bastante mas inestable que
# otros): la mayoria de las rafagas reales quedan MUY separadas (91 a 485s),
# pero un mismo evento a veces genera dos saltos de fd seguidos ~16s
# despues del primero - con la veda vieja de 15s (compartida con el
# reinicio de ffplay) esos pares disparaban dos veces. 25s los trata como
# un solo evento sin tapar rafagas de verdad distintas (todas las medidas
# quedaron muy por encima de eso).
LSFG_VEDA="${PS3RP_LSFG_VEDA:-25}"

VENV_PY="$SCRIPT_DIR/ps3rp-env/bin/python3"
INPUT_SCRIPT="$SCRIPT_DIR/input_client_v3.py"
MENU_SCRIPT="$SCRIPT_DIR/client_menu.py"
CONTROL_UI="$SCRIPT_DIR/client_control_ui.py"
INPUT_PID=""
CONTROL_UI_PID=""

# Al salir (cierre normal, Ctrl+C, o "Cerrar aplicacion" desde Modo Juego)
# matar el cliente de input para no dejarlo colgado mandando UDP. Sin esto,
# instancias viejas se acumulan y varias mandan estados contradictorios al
# ESP32 a la vez (ya paso: los botones parecian no responder).
cleanup() {
    trap - EXIT INT TERM HUP   # evitar re-entrar si llega otra señal
    if [ -n "$INPUT_PID" ] && kill -0 "$INPUT_PID" 2>/dev/null; then
        kill -TERM "$INPUT_PID" 2>/dev/null
        # Darle un momento para cerrar solo; si no, forzar.
        for _ in 1 2 3 4 5; do
            kill -0 "$INPUT_PID" 2>/dev/null || break
            sleep 0.2
        done
        kill -KILL "$INPUT_PID" 2>/dev/null
    fi
    # Red de seguridad: si el proceso quedo huerfano (ej. el shell recibio
    # SIGKILL y no llego a correr este trap la vez anterior), barrer
    # cualquier instancia que haya quedado dando vueltas. Es seguro porque
    # solo deberia existir la que lanza este script.
    pkill -f "input_client_v3.py" 2>/dev/null

    # La ventana del modo control, si quedo abierta (ej. Steam mando SIGTERM
    # con la ventana todavia en pantalla).
    if [ -n "$CONTROL_UI_PID" ] && kill -0 "$CONTROL_UI_PID" 2>/dev/null; then
        kill -TERM "$CONTROL_UI_PID" 2>/dev/null
    fi
    pkill -f "client_control_ui.py" 2>/dev/null

    # Matar tambien ffplay. Parece redundante (normalmente el script solo
    # termina PORQUE ffplay se cerro), pero no lo es: si ffplay se queda
    # esperando un stream que nunca llega, nunca abre ventana, y el usuario
    # no tiene como cerrarlo salvo "Detener" desde Steam. Ahi Steam le pega
    # al shell, y sin esto ffplay quedaba huerfano ocupando el puerto 5000
    # para siempre - el siguiente lanzamiento moria con "Address already in
    # use" sin decir nada y Steam seguia marcando el juego "En ejecucion".
    # Ese era el sintoma de "ya no me lanza" (2026-08-28).
    pkill -x ffplay 2>/dev/null

    # Devolver el brillo si el modo control lo bajo. Va aqui y no solo al
    # final del modo control a proposito: si Steam mata el script con una
    # señal, este trap es lo unico que corre, y sin esto la Deck se
    # quedaria con la pantalla apagada despues de salir.
    restore_screen

    [ -n "$WATCHDOG_FLAG" ] && rm -f "$WATCHDOG_FLAG"
    return 0
}
# Al recibir una señal hay que limpiar Y salir; con un solo trap para todo,
# el manejador volvia y el script seguia corriendo como si nada.
on_signal() {
    cleanup
    exit 143   # 128 + SIGTERM, lo que Steam espera de un juego cerrado
}
trap cleanup EXIT
trap on_signal INT TERM HUP

# ------------------------------------------------------------
#  Brillo de la pantalla (lo usa el modo "solo control")
# ------------------------------------------------------------
# El backlight de la Deck es escribible por el grupo "deck" SIN sudo
# (verificado el 2026-09-06: /sys/class/backlight/amdgpu_bl0/brightness
# es rw-rw-r-- root:deck, maximo 65535). O sea que esto no necesita
# contrasena, ni polkit, ni brightnessctl - que ademas no esta instalado.
#
# NO se baja a 0 por default: con la pantalla completamente negra en Modo
# Juego no hay forma de distinguir "el modo control esta andando" de "se
# colgo". El 1% queda apenas visible y ahorra bateria igual. Para apagarla
# del todo: PS3RP_BRILLO=0.
#
# Si Steam vuelve a subir el brillo solo (tiene su propio control del
# mismo sysfs), esto no pelea con el: escribe una vez y ya.
BACKLIGHT_DIR="${PS3RP_BACKLIGHT:-/sys/class/backlight/amdgpu_bl0}"
BRILLO_DESTINO="${PS3RP_BRILLO:-}"   # vacio = 1% del maximo
BRILLO_PREVIO=""

dim_screen() {
    local archivo="$BACKLIGHT_DIR/brightness"
    local archivo_max="$BACKLIGHT_DIR/max_brightness"
    if [ ! -w "$archivo" ]; then
        echo "AVISO: no puedo escribir $archivo; la pantalla queda como esta." | tee -a "$LOG"
        return 0
    fi
    BRILLO_PREVIO=$(cat "$archivo" 2>/dev/null)
    local max destino
    max=$(cat "$archivo_max" 2>/dev/null || echo 65535)
    if [ -n "$BRILLO_DESTINO" ]; then
        destino="$BRILLO_DESTINO"
    else
        destino=$(( max / 100 ))
    fi
    if echo "$destino" > "$archivo" 2>/dev/null; then
        echo "[brillo] $BRILLO_PREVIO -> $destino (max $max)" >> "$LOG"
    else
        echo "AVISO: fallo al bajar el brillo." | tee -a "$LOG"
        BRILLO_PREVIO=""
    fi
}

# Desarma el modo control sin terminar el script: mata su ventana y su cliente
# de input, y devuelve el brillo. Es lo que permite volver al selector en vez
# de cerrar la aplicacion (pedido del usuario, 2026-09-06).
#
# Deja INPUT_PID y CONTROL_UI_PID vacios a proposito, para que el trap de
# salida no vuelva a intentar matar unos PIDs que ya no existen (y que para
# entonces podrian pertenecer a otro proceso distinto).
detener_control() {
    if [ -n "$CONTROL_UI_PID" ] && kill -0 "$CONTROL_UI_PID" 2>/dev/null; then
        kill -TERM "$CONTROL_UI_PID" 2>/dev/null
    fi
    CONTROL_UI_PID=""

    if [ -n "$INPUT_PID" ] && kill -0 "$INPUT_PID" 2>/dev/null; then
        kill -TERM "$INPUT_PID" 2>/dev/null
        for _ in 1 2 3 4 5; do
            kill -0 "$INPUT_PID" 2>/dev/null || break
            sleep 0.2
        done
        kill -KILL "$INPUT_PID" 2>/dev/null
    fi
    # Red de seguridad, igual que en cleanup: si quedo alguna instancia
    # huerfana, dos clientes mandando estados contradictorios al ESP32 hacen
    # que los botones parezcan no responder.
    pkill -f "input_client_v3.py" 2>/dev/null
    INPUT_PID=""

    restore_screen
}

restore_screen() {
    [ -n "$BRILLO_PREVIO" ] || return 0
    local archivo="$BACKLIGHT_DIR/brightness"
    if [ -w "$archivo" ]; then
        echo "$BRILLO_PREVIO" > "$archivo" 2>/dev/null
        echo "[brillo] restaurado a $BRILLO_PREVIO" >> "$LOG"
    fi
    BRILLO_PREVIO=""   # que no se repita si cleanup corre dos veces
}

# Chequeo de la latencia de red hasta el ESP32. Corre en segundo plano (no
# retrasa el arranque del video) y deja UNA linea en el log.
#
# Por que esta esto: el 2026-08-29, con todo el resto ya afinado, el input lag
# que quedaba era en buena parte esto y no se veia por ningun lado. El ahorro
# de energia del WiFi del ESP32 hace que el router le GUARDE los paquetes hasta
# el proximo beacon: medido, los tiempos salian alternados ~5ms / ~100ms, con
# picos de 310ms. Un ping suelto de 3 o 4 paquetes NO lo muestra (de hecho una
# vez se descarto la hipotesis justamente por eso); hay que pedir varias
# decenas para ver el patron. Por eso conviene que lo mida el script solo, en
# cada corrida, en vez de acordarse de medirlo a mano.
#
# El arreglo vive en el firmware (WiFi.setSleep(false) en ds3_controller.ino).
# Si este aviso aparece, la placa esta corriendo un firmware viejo o el
# setSleep no pego: hay que reflashear.
check_esp32_latency() {
    local linea avg
    linea=$(ping -c 25 -i 0.2 -W 1 "$ESP32_IP" 2>/dev/null | grep "rtt min/avg/max")
    if [ -z "$linea" ]; then
        echo "[red] no se pudo medir la latencia al ESP32 ($ESP32_IP)." >> "$LOG"
        return
    fi
    # rtt min/avg/max/mdev = 3.4/78.6/310.1/34.8 ms  ->  el avg es el 2do campo
    avg=$(echo "$linea" | sed 's|.*= ||; s| ms||' | cut -d/ -f2)
    echo "[red] latencia al ESP32: $linea" >> "$LOG"
    if [ -n "$avg" ] && [ "${avg%%.*}" -ge 20 ] 2>/dev/null; then
        echo "[red] AVISO: ${avg}ms de promedio es MUCHO para wifi local (deberia dar <10ms)." >> "$LOG"
        echo "[red]   Eso se suma entero al lag boton->PS3. Casi siempre es el ahorro" >> "$LOG"
        echo "[red]   de energia del wifi del ESP32: reflashear ds3_controller.ino, que" >> "$LOG"
        echo "[red]   ya trae WiFi.setSleep(false). En el log de arranque de la placa" >> "$LOG"
        echo "[red]   tiene que decir sleep=0." >> "$LOG"
    fi
}

start_input_client() {
    if [ "$ENABLE_INPUT" != "1" ]; then
        echo "Control remoto deshabilitado (PS3RP_INPUT=0)." | tee -a "$LOG"
        return
    fi
    if [ ! -x "$VENV_PY" ] || [ ! -f "$INPUT_SCRIPT" ]; then
        echo "AVISO: no encontre el venv o input_client_v3.py; va solo el video." | tee -a "$LOG"
        return
    fi

    # input_client_v3.py asume lizard_mode DESACTIVADO (mapeo nativo de la
    # Deck). En Modo Juego el propio cliente de Steam ya lo desactiva, asi
    # que normalmente no hay nada que hacer. Desde Modo Escritorio si hace
    # falta, pero requiere root: se intenta sin pedir contrasena (-n) y si no
    # se puede, solo se avisa - nunca abortar el lanzamiento por esto, que
    # dejaria al usuario sin video tambien.
    local lizard="/sys/module/hid_steam/parameters/lizard_mode"
    if [ -r "$lizard" ] && [ "$(cat "$lizard")" = "Y" ]; then
        if ! sudo -n sh -c "echo 0 > $lizard" 2>/dev/null; then
            echo "AVISO: lizard_mode activo y no se pudo desactivar sin contrasena." | tee -a "$LOG"
            echo "  Si los botones no responden, correr en una terminal:" | tee -a "$LOG"
            echo "  echo 0 | sudo tee $lizard" | tee -a "$LOG"
        fi
    fi

    # Matar instancias previas colgadas antes de arrancar la nuestra.
    pkill -f "input_client_v3.py" 2>/dev/null

    echo "Control remoto -> $ESP32_IP:$ESP32_PORT a $INPUT_RATE Hz" | tee -a "$LOG"
    # -u (sin buffer): al redirigir la salida a un archivo, python la buferea en
    # bloques de 8K, asi que lineas clave como "Mando conectado: ..." o las de
    # [stats] no aparecian NUNCA en el log (solo al cerrar, si es que cerraba
    # limpio). Justo las que hacen falta para diagnosticar en Modo Juego, donde
    # no hay terminal a la vista.
    "$VENV_PY" -u "$INPUT_SCRIPT" --host "$ESP32_IP" --port "$ESP32_PORT" \
        --rate "$INPUT_RATE" >> "$LOG" 2>&1 &
    INPUT_PID=$!

    check_esp32_latency &
}

# ------------------------------------------------------------
#  Menu de arranque: streaming o solo control
# ------------------------------------------------------------
# Va DESPUES de definir start_input_client() y ANTES de todo lo que es
# especifico del video, porque el modo control se salta esa parte entera.
#
# PS3RP_MODO se puede fijar para saltarse el menu (util para dejar dos
# accesos directos distintos en Steam): "streaming" o "control".
#
# Regla de oro de este bloque: si el menu falla POR LO QUE SEA, se sigue
# en streaming. Nunca dejar al usuario sin nada por culpa de la ventanita.
# EL BUCLE (2026-09-06). "Salir" del modo control devuelve aca, al selector,
# en vez de cerrar la aplicacion. Del bucle se sale de dos formas: eligiendo
# streaming (se rompe y sigue el resto del script), o cancelando el menu con B
# / Escape, que ahora es la manera de cerrar la aplicacion entera.
while true; do

MODO="${PS3RP_MODO:-}"
if [ -z "$MODO" ]; then
    if [ -x "$VENV_PY" ] && [ -f "$MENU_SCRIPT" ]; then
        # No se toma la salida en crudo A PROPOSITO. Cualquier libreria que
        # el menu importe puede escupir algo en stdout (pygame saluda con dos
        # lineas, y eso ya rompio esto una vez: la eleccion llegaba con el
        # saludo pegado, no coincidia con "control" y arrancaba streaming).
        # Filtrando por las respuestas validas, da igual lo que se cuele.
        MENU_SALIDA=$("$VENV_PY" "$MENU_SCRIPT" 2>>"$LOG")
        MENU_RC=$?
        MODO=$(printf '%s\n' "$MENU_SALIDA" \
               | tr -d '\r' \
               | grep -E '^(streaming|control)$' \
               | tail -n 1)
        case "$MENU_RC" in
            0)
               if [ -z "$MODO" ]; then
                   echo "AVISO: el menu no devolvio un modo valido; sigo en streaming." | tee -a "$LOG"
                   echo "  devolvio: $MENU_SALIDA" >> "$LOG"
                   MODO="streaming"
               fi
               ;;
            1) echo "Menu cancelado; no se lanza nada." | tee -a "$LOG"; exit 0 ;;
            *) echo "AVISO: el menu no abrio; sigo en streaming." | tee -a "$LOG"
               MODO="streaming" ;;
        esac
    else
        echo "AVISO: no encontre client_menu.py; sigo en streaming." | tee -a "$LOG"
        MODO="streaming"
    fi
fi
[ -n "$MODO" ] || MODO="streaming"

if [ "$MODO" = "control" ]; then
    echo "--- $(date) --- modo SOLO CONTROL" >> "$LOG"
    echo "Modo solo control: la Deck es nada mas el mando."

    start_input_client
    if [ -z "$INPUT_PID" ]; then
        echo "ERROR: no arranco el cliente de input; no tiene sentido seguir." | tee -a "$LOG"
        exit 1
    fi

    # LA VENTANA NO ES DECORACION (2026-09-06). Sin NINGUNA ventana, Modo
    # Juego se queda mostrando la pantalla de lanzamiento con el boton
    # "Cancelar" para siempre: Steam espera que la aplicacion muestre algo y
    # da por hecho que todavia esta arrancando. Con la ventana, el juego se
    # da por arrancado y todo se comporta normal.
    if [ -x "$VENV_PY" ] && [ -f "$CONTROL_UI" ]; then
        "$VENV_PY" -u "$CONTROL_UI" --pid "$INPUT_PID" \
            --host "$ESP32_IP" --port "$ESP32_PORT" \
            --backlight "$BACKLIGHT_DIR" >> "$LOG" 2>&1 &
        CONTROL_UI_PID=$!
    else
        echo "AVISO: no encontre client_control_ui.py; sin ventana." | tee -a "$LOG"
    fi

    # Atenuar DESPUES de que la ventana este a la vista, no antes: asi da
    # tiempo de leer que arranco bien, en vez de ver una pantalla negra de
    # entrada y quedarse con la duda de si prendio.
    sleep 2
    dim_screen

    echo "Listo. Toca Salir para volver al menu, o Steam -> Detener juego."

    # Bloquear hasta que se cierre la ventana. Este script tiene que seguir
    # vivo por dos razones: Steam da el "juego" por cerrado cuando muere el
    # proceso que lanzo, y el trap de salida es lo que devuelve el brillo.
    if [ -n "$CONTROL_UI_PID" ]; then
        wait "$CONTROL_UI_PID"
        if [ "$?" = "2" ]; then
            echo "AVISO: la ventana de control no abrio; espero sin ventana." | tee -a "$LOG"
            wait "$INPUT_PID"
        fi
    else
        wait "$INPUT_PID"
    fi

    # Se cerro la ventana: bajar el modo control entero (ventana + cliente de
    # input + brillo) antes de volver al menu. Si no se matara el cliente de
    # input aqui, al elegir streaming despues habria DOS mandando al ESP32.
    detener_control

    # Con el modo fijado por variable de entorno no hay menu al que volver:
    # reentrar seria un bucle infinito sin salida.
    if [ -n "${PS3RP_MODO:-}" ]; then
        echo "Modo control terminado (PS3RP_MODO fijo, no hay menu)." | tee -a "$LOG"
        exit 0
    fi

    continue
fi

# Streaming: salir del bucle y seguir con el resto del script.
break
done

# ------------------------------------------------------------
#  De aqui para abajo: modo streaming (lo de siempre)
# ------------------------------------------------------------

# Si quedo un ffplay colgado de un lanzamiento anterior, todavia tiene
# tomado el puerto UDP y el nuevo muere al instante con "Address already in
# use" - sin ventana y sin que nadie lo vea. Barrerlo antes de empezar.
if command -v ss >/dev/null && ss -lun 2>/dev/null | grep -q ":$PORT "; then
    echo "Habia un cliente anterior colgado en el puerto $PORT; cerrandolo." | tee -a "$LOG"
    pkill -x ffplay 2>/dev/null
    sleep 1
fi

echo "Esperando stream de video+audio en puerto $PORT..."
echo "Ctrl+C para cerrar."
echo ""

# En Modo Juego no hay terminal visible, asi que ffplay tira sus
# warnings/errores (ej. "circular buffer overrun" si la wifi pierde
# paquetes, o mensajes de desfase de audio) a este log en vez de
# perderse. -loglevel warning + -nostats evita que se llene de la
# linea de estadisticas de cada frame (fps=/bitrate=/etc), que no
# sirve para diagnosticar cortes y solo ensucia el archivo.
echo "--- $(date) ---" >> "$LOG"
# Cuantas lineas tenia el log antes de esta corrida, para poder revisar despues
# SOLO lo que escribio ffplay ahora (ver el chequeo del modo de presentacion al
# final del script).
LOG_LINES_BEFORE=$(wc -l < "$LOG" 2>/dev/null || echo 0)

# Arrancar el control ANTES del video: ffplay es el proceso que bloquea hasta
# que se cierra la ventana, asi que cualquier cosa que vaya despues no correria
# hasta el final.
start_input_client

# -fflags nobuffer -flags low_delay -framedrop -probesize 32
#   -analyzeduration 0 : minimizan el buffering/probing interno de
#   ffplay para no sumar latencia extra de lectura/decode.
#
# -f mpegts : evita que ffplay tenga que probar el contenedor con un
#   probesize tan chico (podria no detectarlo).
#
# ?fifo_size=...&overrun_nonfatal=1 : buffer circular de recepcion del socket
#   UDP. Sin nada de esto, rafagas/jitter normales de la wifi tiraban paquetes
#   y se veia como tartamudeo (cuadros que se congelan y saltan).
#
#   *** CORRECCION IMPORTANTE (2026-08-29): LA UNIDAD NO ES BYTES. ***
#   Todo lo que se venia razonando aca abajo (y en la bitacora) daba por hecho
#   que fifo_size era un tope en BYTES. Es falso, y esta verificado contra el
#   propio ffmpeg de esta Deck:
#
#       $ ffmpeg -h protocol=udp
#       -fifo_size <int>  set the UDP receiving circular buffer size,
#                         expressed as a NUMBER OF PACKETS WITH SIZE OF
#                         188 BYTES  (default 28672)
#
#   O sea que hay que multiplicar por 188. Los valores que se venian usando
#   eran, en realidad:
#       1000000 -> 188 MB
#        200000 ->  37 MB
#        130000 ->  24 MB   <- el que estaba puesto hasta hoy
#   contra un default de ffmpeg de 28672 paquetes = 5.4 MB. Es decir que cada
#   vez que se "bajaba el fifo_size para quitar latencia" en realidad se lo
#   estaba dejando 4 a 35 veces MAS GRANDE que el default. Por eso bajarlo de
#   1000000 a 200000 no bajo el retraso de forma proporcional y la prueba
#   quedo como "no confirma la hipotesis": los dos valores eran enormes.
#
#   POR QUE ESTO IMPORTA PARA EL LAG (y no solo para el tartamudeo). Este
#   buffer no es un retardo por si mismo: solo retiene datos si el lector va
#   mas lento que la red. El problema es el ARRANQUE. Cuando ffplay abre el
#   socket, el servidor ya viene mandando; mientras ffplay hace el probe, abre
#   el decodificador y crea la ventana (~1s), los datos que llegan se van
#   apilando aca. Despues ffplay se pone a leer, llena sus propias colas
#   internas (se frena a los 25 cuadros por stream) y DEJA DE LEER - y todo lo
#   que quedo apilado en este buffer se queda apilado para siempre, porque de
#   ahi en mas entra exactamente lo mismo que sale. Queda como una linea de
#   retardo fija de la que ffplay nunca se recupera: no crece, no se drena, y
#   se siente exactamente como el "lag fijo que no se va" del video.
#   (Es el mismo mecanismo que ya estaba anotado mas abajo en la nota de
#   -sync: "la cola no la crea el audio, la crea el arranque".)
#
#   Con 24 MB de colchon, ese apilamiento de arranque cabe entero. Con un
#   buffer chico, lo que sobra se descarta en el arranque (se ven uno o dos
#   "Circular buffer overrun" en el log durante el primer segundo, inofensivos
#   gracias a overrun_nonfatal=1) y el retardo fijo queda acotado al tamano
#   del buffer.
#
#   PERO OJO - ESTO NO ES DONDE ESTA EL LAG, Y HAY QUE DECIRLO. El razonamiento
#   de arriba sobre el apilamiento de arranque suena bien pero NO se sostiene
#   con la medicion: si hubiera datos apilados en este buffer, el hilo lector
#   de ffplay se los llevaria enseguida a sus colas internas y se verian como
#   vq/aq altos (ver la nota de PS3RP_STATS mas abajo). Medido, vq queda en 0 y
#   aq en 2 KB: las colas estan VACIAS, o sea que ffplay va al dia y no hay
#   ninguna linea de retardo escondida aca. Este bloque queda como correccion
#   de unidades y para que nadie vuelva a "bajar el fifo_size para quitar
#   latencia" creyendo que son bytes - no como el arreglo del input lag.
#
#   DONDE SI IMPORTA, Y ES LO QUE PASA AL CAMBIAR DE JUEGO (2026-08-29): en
#   regimen normal este buffer esta vacio y da igual cuanto mida - por eso
#   bajarlo no cambio nada. Pero cuando el stream se CORTA un instante (el PS3
#   renegocia el modo de video al entrar o salir de un juego, o hay una rafaga
#   de wifi), los datos se siguen apilando aca mientras ffplay no puede
#   consumir. Al volver la senal, ffplay recibe todo ese atraso de una. El
#   video atrasado se tira con -framedrop, pero EL AUDIO NO SE PUEDE TIRAR: se
#   reproduce entero, tarde, y como el reloj maestro es el de audio, el video
#   queda anclado a ese atraso. Medido despues: se drena solo, pero tarda ~5
#   minutos (la tabla esta junto al lazo de ffplay, mas abajo) - de ahi el
#   sintoma que reporto el usuario, "al cambiar de juego crece el lag, se calma
#   si apago y reabro el cliente".
#
#   Por eso el tope tiene que ser CHICO: lo que no entra se descarta durante el
#   corte (con overrun_nonfatal=1 solo deja un aviso en el log) en vez de
#   entregarse tarde y quedar clavado como retraso permanente.
#
#   VALOR: 1500 paquetes = 282 KB, ~0.44s a la tasa actual (~5.1 Mbps = 5M de
#   video + 96k de audio, o sea ~638 KB/s). O sea que un corte no puede dejar
#   mas de ~0.44s de atraso pegado, contra los ~1.5s que permitian los 5000 de
#   antes y los ~39s de los 130000 originales. El piso salio de medir: contra
#   un stream local de 720p60/5M, con 500 paquetes aparecen "Circular buffer
#   overrun" y mas errores de h264; con 2000 ya no. 1500 deja margen sobre ese
#   piso sin regalar medio segundo de colchon.
#
#   MEDIDO DESPUES: acotar el fifo AYUDA pero no alcanza - el atasco igual se
#   forma (llego a 142 KB de vq con este tope de 1500). Por eso ademas esta el
#   watchdog, ver la nota junto al lazo de ffplay. Y ojo con el campo que se
#   mira: aq NO sirve para esto. 180 ms de audio a 96 kbps son ~2 KB, que se
#   pierden en el redondeo de la linea de stats; el atasco solo se ve en vq.
#   Formula si cambia el bitrate del server:
#       paquetes = segundos_de_colchon * bitrate_total_bps / 8 / 188
#
#   PS3RP_FIFO=130000 ./start_client_stream.sh vuelve al valor viejo sin
#   editar nada, por si algun dia reaparece el tartamudeo por rafagas.
#
# -sync : cual reloj manda. Default de este script: AUDIO (que es tambien
#   el default de ffplay).
#
#   REVERTIDO CON MEDICION (2026-08-29, tercera vuelta). El dia anterior se
#   habia puesto -sync video por default razonando que "ffplay muestra cada
#   frame cuando el reloj de AUDIO lo alcanza, asi que el video se retrasa lo
#   que tarde el audio". Suena bien y ES FALSO EN LA PRACTICA: medido contra
#   el stream vivo del PS3, -sync video AGREGA entre 150 y 340 ms de retraso
#   fijo. Es la mayor parte del "medio segundo" que se seguia sintiendo.
#
#   LA MEDICION (con -loglevel info, o sea PS3RP_STATS=1; vq = KB de video
#   encolado sin decodificar, ~1.6 ms por KB a 5 Mbps):
#     -sync video, Modo Juego (log de las 12:10):  vq = 205..248 KB  (~340 ms)
#     -sync video, Escritorio:                     vq =  83..111 KB  (~150 ms)
#     -sync audio, Escritorio:                     vq =   0 KB  fd=8
#   Con audio de maestro la cola se vacia SOLA en el primer segundo (fd sube a
#   8 = tiro 8 cuadros atrasados una vez y quedo al dia) y de ahi en adelante
#   vq queda clavado en 0 y A-V en -0.005. Con video de maestro la cola se
#   forma y NO SE VA NUNCA.
#
#   POR QUE. La cola no la crea el audio: la crea el arranque. Mientras ffplay
#   levanta su ventana el hilo principal se queda pegado un rato (en el log de
#   Modo Juego se ve: "Spent 195.947 ms translating SPIR-V (slow!)" mas el
#   swapchain de gamescope creado, destruido y vuelto a crear por el -fs). El
#   video que sigue llegando por UDP en ese rato se apila. El hilo de audio de
#   SDL, en cambio, NUNCA se detiene: es su propio hilo, sigue consumiendo y su
#   reloj sigue avanzando con el tiempo real. O sea que al salir del tiron el
#   video quedo ~300 ms atrasado y el audio quedo al dia. Y ahi:
#     - con maestro AUDIO: el video esta atrasado respecto del maestro, se
#       activa -framedrop, tira los cuadros viejos y se pone al dia. Fin.
#     - con maestro VIDEO: el maestro ES el video atrasado, asi que nada lo
#       obliga a alcanzar el presente; -framedrop no dispara nunca (compara
#       contra el propio reloj de video, la diferencia sale positiva). Peor
#       todavia: ffplay resamplea el AUDIO para arrastrarlo a ese atraso.
#       Por eso "el audio se oye bien" - se oye bien PORQUE tambien lo
#       atrasaron. El tiron de arranque queda convertido en retraso
#       permanente de toda la reproduccion.
#
#   O SEA: el hallazgo viejo de que "con PS3RP_NOAUDIO=1 el lag baja" era real
#   pero la conclusion no. -an no ayudaba por quitar el audio; ayudaba porque
#   sin audio el arranque es mucho mas liviano. Y -sync video no era "la misma
#   ganancia conservando el sonido": era lo contrario.
#
#   Para volver a probar el reloj de video: PS3RP_SYNC=video. Antes de creerle
#   a lo que se sienta, lanzar con PS3RP_STATS=1 y mirar vq: si queda parado en
#   un numero distinto de cero, eso son milisegundos de lag puro y no hay
#   perilla del lado del Deck que los arregle.

# -hwaccel vaapi -vf hwdownload,format=nv12 : decodifica H.264 con el
#   bloque de video dedicado de la GPU (VCN) en vez de por software.
#   Medido en este Deck con un clip de prueba local: decode por
#   software = 100% de un nucleo de CPU; con esto = ~27%. Esto es lo
#   que de verdad soluciona (o al menos deja mucho mas margen ante) el
#   retraso/entrecortado de audio en Modo Juego que se veia antes -
#   con tanto margen de CPU libre, aunque Modo Juego le baje clocks a
#   esta "app" el decode no se atrasa del tiempo real.
#
#   OJO con el orden: usar -hwaccel vaapi SOLO (sin -vf hwdownload) es
#   lo que crashea. Este build de ffplay arma el renderer de ventana
#   con Vulkan/libplacebo, y sin hwdownload, ffplay intenta reusar ese
#   mismo device Vulkan como origen para derivar el frames-context de
#   VAAPI (para mostrar el frame decodificado sin copia) - esa
#   derivacion no esta soportada aca ("Derive vaapi from vulkan not
#   supported") y en vez de fallar limpio, revienta con buffer
#   overflow/abort apenas llega un frame real. Agregar
#   -vf hwdownload,format=nv12 hace que el frame decodificado en VAAPI
#   se baje a memoria normal ANTES de llegarle al renderer, asi nunca
#   se necesita esa derivacion - el mismo mensaje "Derive vaapi from
#   vulkan..." puede seguir apareciendo en el log pero ahi queda como
#   warning inofensivo, no crashea. No lo saques pensando que "ya no
#   hace falta".
#
# NO subas -probesize/-analyzeduration pensando en el desfase de
# audio: se probo (2026-08-23) y no cambia nada. El desfase de audio
# NO es del lado del Deck (paso IGUAL en ventana que en fullscreen,
# y con estos valores subidos a 1MB/1s) - la causa real era la
# conversion a start_server_stream.exe con ps2exe, del lado de la PC.
# Ver [[server-side-exe-audio-bug]] en la memoria del proyecto. Este
# script nunca fue el problema, no lo sigas tocando por esto.

# Quitarle a ffplay el overlay de Steam.
#
# Cuando esto se lanza como acceso directo de Steam, Steam le inyecta al
# proceso su overlay: LD_PRELOAD=.../gameoverlayrenderer.so mas la capa
# implicita de Vulkan steamoverlay_x86_64. env -u LD_PRELOAD saca el .so
# preloaded y las dos variables DISABLE_VK_LAYER_* son la forma oficial de
# apagar esas capas. Se aplica solo a este comando.
#
# HONESTIDAD SOBRE POR QUE ESTA ESTO: se agrego el 2026-08-28 sospechando
# que el overlay era lo que impedia que naciera la ventana de ffplay. NO
# era: se reprodujo el mismo sintoma con estas variables ya puestas. La
# causa real era que no llegaba stream decodificable (ver abajo). Se deja
# porque un reproductor de video no gana nada con el overlay encima y
# quita una variable de en medio, pero no lo cuentes como "el arreglo".
# Apagar el vsync de la PRESENTACION (tres variables, una por capa).
#   ffplay crea su renderer SDL con PRESENTVSYNC clavado en el codigo, asi que
#   cada SDL_RenderPresent() se queda esperando el vblank. En Modo Juego eso
#   pesa mas que en Escritorio: el log muestra que la ventana de ffplay termina
#   en un swapchain de gamescope de 4 imagenes ("imageCount: 4"), o sea hasta 3
#   frames ya decodificados haciendo cola para salir.
#
#   CORRECCION MEDIDA (2026-08-29): aca decia antes que SDL_RENDER_VSYNC=0
#   alcanzaba, "porque SDL2 consulta ese hint dentro de SDL_CreateRenderer".
#   En esta Deck es FALSO, y por el mismo motivo que ya habia mordido con el
#   teclado en pantalla: el ffplay de SteamOS no enlaza contra SDL2 real sino
#   contra sdl2-compat sobre SDL3, y sdl2-compat traduce el flag PRESENTVSYNC
#   de SDL2 a un SDL_SetRenderVSync() de SDL3 SIN mirar la variable de entorno.
#   Medido con ctypes contra la misma libSDL2-2.0.so.0 que carga ffplay,
#   replicando su llamada (ACCELERATED|PRESENTVSYNC):
#     sin la variable / =0 / =1  -> PRESENTVSYNC "SI" en los tres casos
#     presentaciones reales por segundo -> 32.5 / 32.5 / 32.3, identicas
#   O sea que la variable sola no hacia NADA. Se deja puesta porque no estorba
#   (y por si algun dia ffplay enlaza SDL2 de verdad), pero no la cuentes como
#   el arreglo.
#
#   Lo que SI mide distinto es apagarlo por debajo de SDL, a nivel Mesa:
#     vblank_mode=0  ->  32.5 sube a 60.3 presentaciones/s
#   Se duplico: con swap interval 1 cada frame esperaba DOS refrescos (el vsync
#   de GL mas el throttle del compositor) = ~33ms de presentacion en vez de
#   ~16. Ese frame de mas es latencia pura y se paga en CADA cuadro.
#   MESA_VK_WSI_PRESENT_MODE es lo mismo para el camino Vulkan, que es el que se
#   usa en Modo Juego (de ahi los "[Gamescope WSI] Creating swapchain" del log):
#   el modo FIFO es justo la cola de hasta 3 frames de arriba. En Escritorio no
#   midio diferencia extra (ahi el camino es GL), y no hace daño.
#
#   CORRECCION MEDIDA (2026-08-29, segunda vuelta): se habia puesto
#   MESA_VK_WSI_PRESENT_MODE=immediate y NO SERVIA DE NADA. El log de Modo Juego
#   lo dice literal, en las cuatro corridas de la tarde:
#     [Gamescope WSI] Creating swapchain ... provided minImageCount: 4
#     Unsupported MESA_VK_WSI_PRESENT_MODE value!
#     [Gamescope WSI] Created swapchain ... imageCount: 4
#   O sea: Mesa pidio IMMEDIATE, la superficie de gamescope NO lo ofrece
#   ("Unsupported" lo imprime Mesa cuando el modo pedido no esta en la lista de
#   modos soportados de esa superficie, no cuando el texto esta mal escrito), y
#   el swapchain quedo en FIFO con 4 imagenes = exactamente la cola de hasta 3
#   cuadros que se queria sacar. gamescope solo expone IMMEDIATE cuando el
#   tearing esta habilitado para ese juego (menu de acceso rapido -> Rendimiento
#   -> vista avanzada -> "Permitir tearing"); sin eso, el unico modo sin cola que
#   queda es MAILBOX (presenta siempre el ultimo cuadro y descarta los viejos,
#   sin tearing porque igual sincroniza al vblank).
#
#   Por eso el default paso a MAILBOX. Como no se puede saber desde Escritorio
#   que modos expone la superficie de gamescope, el script AVISA solo: si al
#   terminar aparecio la linea "Unsupported ..." en esta corrida, lo dice en
#   claro al final (ver el bloque despues de ffplay). Si mailbox tambien sale
#   rechazado, la unica via es prender el tearing en el menu de Steam y probar
#   PS3RP_PRESENT=immediate.
#
#   Las tres se apagan juntas con PS3RP_VSYNC=1 si se ve peor (tirones o
#   tearing). Ojo: gamescope igual compone, asi que tearing visible no deberia
#   haber.
#
# PS3RP_NOAUDIO=1 -> agrega -an. Es SOLO para medir, no para jugar:
#   sirve para partir el presupuesto de latencia en dos. Con el audio puesto,
#   el reloj maestro es el de audio y el video se muestra cuando ese reloj lo
#   alcanza; con -an el maestro pasa a ser el propio video.
#
#   OJO CON COMO SE LEE EL RESULTADO (corregido 2026-08-29, ver la nota larga
#   de -sync mas arriba): aca decia que "si con -an el lag baja, el culpable es
#   la cadena de audio". Se probo y bajaba, y esa conclusion resulto EQUIVOCADA.
#   Quitar el audio tambien aliviana el arranque de ffplay, que es donde de
#   verdad se formaba el atasco. La forma correcta de sacarle informacion a
#   esta perilla es mirar vq con PS3RP_STATS=1, no solo "como se siente":
#     vq parado en un numero > 0  -> hay cola encolada, es atasco de arranque
#     vq en 0 y aun asi se siente -> el retraso es captura+encode+red+pantalla
#   Si el audio se destapara como culpable de verdad, se ataca en el origen
#   (-audio_buffer_size del lado del servidor), no aca.
# PULSE_LATENCY_MSEC / PIPEWIRE_LATENCY (agregado 2026-08-29): tamano del
#   buffer de SALIDA de audio que ffplay le pide al servidor de sonido. Con el
#   reloj de audio de maestro, cada cuadro de video se muestra cuando ese reloj
#   lo alcanza, y el reloj va tan atrasado como el buffer de salida - asi que
#   un buffer grande retrasa TAMBIEN el video.
#
#   La Deck corre PipeWire 1.6.4 con capa de compatibilidad PulseAudio, y
#   ffplay enlaza contra libSDL2. SDL lee PULSE_LATENCY_MSEC en su backend de
#   pulse (lo convierte a tlength del buffer); PIPEWIRE_LATENCY es el
#   equivalente por si SDL termina usando el backend nativo de pipewire, y se
#   expresa en cuadros/tasa - por eso la multiplicacion por 48 (48 kHz).
#   Poner las dos no hace dano: la que no aplique se ignora.
#
#   SIGUE APAGADA POR DEFECTO, PERO EL MOTIVO CAMBIO (2026-08-29): cuando se
#   probo PS3RP_AUDIO_MS=30 el usuario reporto que el audio se DESINCRONIZABA.
#   Eso fue con -sync video puesto, y con ese reloj tiene toda la logica: el
#   video estaba anclado ~300 ms tarde y clavado ahi, asi que adelantar el
#   audio 13 ms lo despegaba de la imagen. Con el maestro de vuelta en audio,
#   el video SIGUE al audio y no se puede despegar. Medido de nuevo hoy contra
#   el stream vivo, ya con -sync audio:
#     sin la variable:        A-V = -0.005   vq = 0 KB
#     PS3RP_AUDIO_MS=30:      A-V = -0.018   vq = 3..20 KB
#   O sea, 13 ms de diferencia y el audio pegado al video en los dos casos: no
#   desincroniza. La ganancia tambien es de 13 ms, o sea casi nada al lado de
#   los 340 ms que se acaban de recuperar con el reloj, y no vale la pena
#   arriesgar clicks por eso. Queda como perilla, no como default; si algun dia
#   hace falta exprimir los ultimos milisegundos, esta es y ya se sabe que es
#   segura con el reloj de audio.
AUDIO_ENV=()
if [ -n "$AUDIO_MS" ]; then
    AUDIO_ENV=(PULSE_LATENCY_MSEC="$AUDIO_MS" PIPEWIRE_LATENCY="$((AUDIO_MS * 48))/48000")
    echo "Buffer de salida de audio forzado a ${AUDIO_MS}ms." | tee -a "$LOG"
fi

# Ver la nota larga de arriba: la de SDL es la que se comprobo inutil sola, las
# dos de Mesa son las que miden distinto. Solo se agregan al apagar el vsync;
# con PS3RP_VSYNC=1 el comportamiento vuelve a ser el de siempre.
VSYNC_ENV=(SDL_RENDER_VSYNC="$VSYNC")
if [ "$VSYNC" = "0" ]; then
    VSYNC_ENV+=(vblank_mode=0 MESA_VK_WSI_PRESENT_MODE="$PRESENT")
    echo "Modo de presentacion Vulkan pedido: $PRESENT" | tee -a "$LOG"
fi

FFPLAY_SYNC_ARGS=()
if [ -n "$SYNC" ]; then
    FFPLAY_SYNC_ARGS=(-sync "$SYNC")
    echo "Reloj maestro forzado a: $SYNC" | tee -a "$LOG"
fi

# PS3RP_STATS=1 -> quita -nostats y sube el loglevel a info, que es el nivel al
#   que ffplay imprime su linea de estado. Es la unica forma de MEDIR desde la
#   Deck cuanto video hay parado esperando turno:
#
#     3.45 M-V: 0.012 fd= 0 aq=  23KB vq= 400KB sq= 0B f=0/0
#
#   vq = cuantos KB de video hay encolados sin decodificar. A los 5 Mbps que
#   manda el servidor, 100KB son ~160ms de retraso puro; 300KB son ~480ms. O
#   sea que ese numero se traduce DIRECTO a milisegundos de lag:
#       ms = KB * 8 * 1000 / 5000   (~1.6ms por KB)
#   aq es lo mismo para el audio (a 96k, ~83ms por KB), M-V es la diferencia
#   entre el reloj maestro y el video, y fd la cuenta de cuadros descartados.
#
#   PARA QUE SIRVE: distingue las dos causas posibles de un lag FIJO, que se
#   sienten igual pero se arreglan distinto:
#     - vq alto y estable -> hay un atasco parado en la cola de ffplay. Ojo con
#       la nota vieja que decia que "parejo, no crece" descarta encolamiento:
#       NO lo descarta. Una cola constante es justo eso, un colchon que se
#       formo al arrancar y ya nunca se drena, porque entran y salen 60 cuadros
#       por segundo. Con -sync video nada lo obliga a alcanzar el presente. El
#       arreglo es volver al reloj de audio (que es el default: ahi -framedrop
#       tira los cuadros atrasados y la cola se vacia sola en el primer
#       segundo). NO sirve PS3RP_SYNC=ext, aunque el reloj externo tenga una
#       aceleracion a 1.01x justo para esto: solo se activa cuando las DOS
#       colas pasan de 10 paquetes, y aca la de audio anda en ~6 (aq de 1-2 KB
#       a 96 kbps son ~256 bytes por cuadro AAC), asi que nunca dispara.
#     - vq casi en cero -> no hay cola: el retraso se genera antes (captura,
#       encode, wifi) o despues (presentacion), y hay que medir del lado del
#       servidor.
#
#   Solo para medir: deja el log mucho mas verboso (una linea por segundo mas
#   los mensajes de nivel info del arranque).
# El watchdog LEE la linea de stats, asi que la necesita encendida aunque el
# usuario no haya pedido el modo medicion. La diferencia entre los dos casos no
# esta aca sino en stamp(): con STATS=0 esas lineas se usan y se DESCARTAN sin
# escribirlas al log, para no llenarlo de una linea por segundo.
FFPLAY_LOG_ARGS=(-loglevel warning -nostats)
if [ "$STATS" = "1" ] || [ "$WATCHDOG" = "1" ]; then
    FFPLAY_LOG_ARGS=(-loglevel info)
fi
if [ "$STATS" = "1" ]; then
    echo "MODO MEDICION: stats de ffplay activadas (1 linea/s en el log)." | tee -a "$LOG"
fi

FFPLAY_AUDIO_ARGS=()
if [ "$NOAUDIO" = "1" ]; then
    FFPLAY_AUDIO_ARGS=(-an)
    echo "MODO MEDICION: video sin audio (-an)." | tee -a "$LOG"
fi

# Evitar que salga el teclado en pantalla al lanzar en Modo Juego
# (SDL_ENABLE_SCREEN_KEYBOARD=0, arriba en el env de ffplay).
#
# El ffplay de SteamOS no enlaza contra SDL2 de verdad: /usr/lib/libSDL2-2.0.so.0
# es sdl2-compat corriendo encima de SDL3. sdl2-compat tiene que preservar la
# semantica de SDL2, donde la entrada de texto esta ACTIVA por defecto - medido
# aca: SDL_IsTextInputActive() da True apenas se crea la ventana, sin que ffplay
# pida nada. Y SDL3 detecta la Deck por la variable de entorno "SteamDeck", que
# Steam le pone a todo lo que lanza desde Modo Juego; ahi el backend x11 declara
# soporte de teclado en pantalla y, como la entrada de texto ya esta activa, lo
# ABRE solo. Por eso solo pasa en Modo Juego y no en Escritorio.
#
# Medido con ctypes contra la misma libSDL2-2.0.so.0 que carga ffplay:
#   SteamDeck=1, sin el hint  -> HasScreenKeyboardSupport True, IsScreenKeyboardShown True
#   SteamDeck=1, con el hint 0 -> HasScreenKeyboardSupport True, IsScreenKeyboardShown False
#
# No hay opcion de ffplay para esto (no es cosa de ffmpeg sino de SDL), asi que
# el hint por entorno es la unica via sin recompilar. Es solo para este proceso.

# Ponerle la hora a cada linea que escupe ffplay. Sin esto el log es
# indistinguible entre dos cosas que se ven IGUAL pero significan lo opuesto:
#   - un arranque normal (una rafaga de "non-existing PPS 0 referenced" en el
#     primer segundo, mientras se espera el primer keyframe del server), y
#   - perdida de paquetes de wifi EN MEDIO de la partida, que es lo que se
#     siente como tirones y lag que se acumula.
# Contar errores por corrida (lo que se hacia hasta ahora) no alcanza: las dos
# dan numeros parecidos. Con la hora, la pregunta se responde de un vistazo.
# gawk viene en SteamOS; si por lo que sea no esta, el log sale como antes.
stamp() {
    if command -v gawk >/dev/null 2>&1; then
        # RS="[\r\n]": ffplay escribe su linea de estadisticas con retorno de
        # carro (\r) y sin salto de linea, para irla pisando en la terminal. Sin
        # esto el log entero seria UNA sola linea kilometrica. Y como esa linea
        # se reescribe ~60 veces por segundo, se deja pasar solo una por segundo
        # (systime() tiene resolucion de 1s, que alcanza: lo que interesa es la
        # tendencia de las colas, no cada cuadro).
        #
        # Ademas, este mismo gawk es el WATCHDOG (ver la nota larga junto al
        # lazo de ffplay): ya esta parseando la linea de stats, asi que mirar vq
        # aca sale gratis y no hace falta otro proceso leyendo el log.
        #   - muestras > espera : ignorar el arranque, y despues de un reinicio
        #     callarse un buen rato. Cada muestra es 1 segundo, asi que "espera"
        #     son segundos. NO es cosmetico: el reinicio corta el stream, y ese
        #     corte genera un atasco nuevo - sin veda el watchdog se realimenta
        #     y reinicia sin parar (paso, ver la nota del lazo).
        #   - seguidas >= vqsecs : exigir que el atasco PERSISTA. Un pico suelto
        #     de vq es una rafaga de wifi que se drena sola; lo que buscamos es
        #     la meseta que ya no baja nunca.
        #   - salto en fd= : dispara DE GOLPE, sin esperar que persista (ver
        #     PS3RP_FD_SALTO arriba) - una rafaga de cuadros del servidor deja
        #     vq/aq en 0 (ffplay la absorbe bien solo) pero descuadra a
        #     Lossless Scaling, y esa rafaga es instantanea, no una meseta.
        #   - con stats != 1 la linea se consume pero NO se escribe al log.
        gawk -v stats="$STATS" -v wd="$WATCHDOG" -v vqmax="$VQ_MAX" \
             -v vqsecs="$VQ_SECS" -v flag="$WATCHDOG_FLAG" -v espera="$ESPERA" \
             -v cada="$STATS_EVERY" -v fdsalto="$FD_SALTO" \
             -v lsfgon="${PS3RP_LSFG:-0}" -v lsfgperfil="${LSFG_PROCESS:-}" \
             -v lsfgconf="$LSFG_CONF" -v lsfgscript="$LSFG_PAUSA_SCRIPT" \
             -v lsfgpausa="$LSFG_PAUSA" -v lsfgveda="$LSFG_VEDA" '
              BEGIN {
                  RS = "[\r\n]"; last = 0; muestras = 0; seguidas = 0; ultimaStat = 0; fdAnterior = -1
                  ultimoLsfg = -999999
                  # Chequeo UNA vez al arrancar, no en cada muestra: si esto
                  # corre bajo ~/lsfg de verdad (lsfgperfil viene puesto) y el
                  # ajustador existe, preferimos el ajuste sin parpadeo sobre
                  # reiniciar ffplay para el disparador de fd.
                  lsfgDisponible = (lsfgon == "1" && lsfgperfil != "" && system("test -x \"" lsfgscript "\"") == 0)
              }
              function reiniciarFfplay(motivo) {
                  printf("%s [watchdog] %s Reiniciando ffplay.\n", strftime("[%H:%M:%S]"), motivo)
                  fflush()
                  print "" > flag
                  close(flag)
                  system("pkill -x ffplay")
                  seguidas = 0
                  muestras = 0
                  fdAnterior = -1
              }
              function bajarLsfgTemporal(motivo,   t2) {
                  t2 = systime()
                  if (t2 - ultimoLsfg < lsfgveda + 0) {
                      # Veda propia (2026-09-13, distinta de "espera"): un
                      # mismo evento a veces genera dos saltos de fd seguidos
                      # ~16s aparte (medido en vivo con ICO) - esto los trata
                      # como uno solo en vez de bajar el multiplier dos veces.
                      printf("%s [watchdog] %s (en veda de lsfg, %ds desde el ultimo ajuste - se ignora, mismo evento).\n",
                             strftime("[%H:%M:%S]"), motivo, t2 - ultimoLsfg)
                      fflush()
                      return
                  }
                  ultimoLsfg = t2
                  printf("%s [watchdog] %s Bajando generacion de cuadros de lsfg %ss (perfil %s) en vez de reiniciar ffplay.\n",
                         strftime("[%H:%M:%S]"), motivo, lsfgpausa, lsfgperfil)
                  fflush()
                  system("\"" lsfgscript "\" \"" lsfgperfil "\" \"" lsfgconf "\" " lsfgpausa " >/dev/null 2>&1 &")
                  seguidas = 0
                  muestras = 0
                  fdAnterior = -1
              }
              {
                  if ($0 == "") next
                  esStats = ($0 ~ /aq=.*vq=/)
                  if (esStats) {
                      t = systime()
                      if (t == last) next
                      last = t
                      muestras++
                      disparado = 0
                      if (wd == "1" && muestras > espera + 0 && match($0, /vq=[ ]*([0-9]+)KB/, m)) {
                          if (m[1] + 0 >= vqmax + 0) seguidas++
                          else seguidas = 0
                          if (seguidas >= vqsecs + 0) {
                              reiniciarFfplay(sprintf("vq lleva %d s en %s KB (tope %s): el video quedo atrasado y tardaria minutos en drenarse.", seguidas, m[1], vqmax))
                              disparado = 1
                          }
                      }
                      if (!disparado && wd == "1" && muestras > espera + 0 && match($0, /fd=[ ]*([0-9]+)/, mf)) {
                          fdActual = mf[1] + 0
                          if (fdAnterior >= 0 && (fdActual - fdAnterior) >= fdsalto + 0) {
                              motivo = sprintf("fd salto de %d a %d (+%d en 1s): rafaga del servidor.", fdAnterior, fdActual, fdActual - fdAnterior)
                              if (lsfgDisponible) bajarLsfgTemporal(motivo)
                              else reiniciarFfplay(motivo " Descuadro a Lossless Scaling.")
                              disparado = 1
                          }
                          fdAnterior = fdActual
                      }
                      # Sin modo medicion igual se deja UNA cada "cada"
                      # segundos, para que la corrida quede con rastro de la
                      # tendencia de A-V y vq. Es lo que hace la diferencia
                      # entre diagnosticar despues y pedirle al usuario que
                      # vuelva a reproducir el problema.
                      if (stats != "1") {
                          if (cada + 0 <= 0) next
                          if (t - ultimaStat < cada + 0) next
                          ultimaStat = t
                      }
                  }
                  print strftime("[%H:%M:%S]"), $0
                  fflush()
              }'
    else
        # Sin gawk no hay watchdog posible (es quien lee vq). Se avisa una vez
        # al arrancar, mas arriba, y el video sigue funcionando igual.
        tr "\r" "\n"
    fi
}

# ---------------------------------------------------------------------------
# WATCHDOG DEL ATASCO DE VIDEO
# ---------------------------------------------------------------------------
# Por que ffplay se lanza dentro de un lazo y no una sola vez.
#
# MEDIDO EL 2026-08-29, no supuesto. El usuario reporto que al salir de un juego
# y volver a entrar, el lag de la imagen empeoraba y solo se calmaba cerrando y
# reabriendo el cliente. Con PS3RP_STATS=1 quedo el momento exacto en el log:
#
#   [20:57:51]  A-V: -0.036  fd=22  aq=0KB  vq=  40KB    <- normal
#   [20:57:56]  A-V: +0.016  fd=24  aq=0KB  vq= 112KB    <- el salto
#   [20:58:01]  A-V: +0.017  fd=24  aq=0KB  vq= 142KB
#   ... y se queda en 110-144 KB por el resto de la corrida
#
# vq salta de golpe. A 5 Mbps son ~130 ms extra de video encolado.
#
# SE DRENA SOLO, PERO TARDA UNA ETERNIDAD - por eso hace falta el watchdog y no
# alcanza con esperar. Promedio de vq por minuto en esa misma corrida:
#
#   20:56  49 KB   <- regimen normal (nunca paso de 69)
#   20:57 142 KB   <- el cambio de juego
#   20:58 128 KB
#   20:59 124 KB
#   21:00 112 KB
#   21:01  91 KB
#   21:02  58 KB
#   21:03  35 KB
#   21:04  22 KB   <- recien aca vuelve a la normalidad
#
# O sea CINCO MINUTOS de partida con hasta 200 ms de mas encima, cada vez que se
# entra o se sale de un juego. El usuario lo describio como "se fue
# estabilizando"; el numero dice cuanto tarda en estabilizarse.
#
# POR QUE NO SE ARREGLA SOLO. Cuando el PS3 renegocia el modo de video (entrar o
# salir de un juego) el stream se corta un instante; mientras tanto los datos se
# apilan y al volver la senal ffplay los recibe todos juntos. Ahi el audio y el
# video quedan atrasados POR IGUAL, asi que entre ellos siguen sincronizados:
# fijate que A-V se queda en ~0.017 y que fd (cuadros tirados) se congela en 24.
# -framedrop compara cada cuadro contra el reloj MAESTRO, que es el de audio, y
# el de audio tambien va tarde - o sea que para ffplay no hay nada atrasado que
# tirar. El unico que sabe que se perdio tiempo contra la realidad es el que
# esta jugando. Por eso no hay perilla de ffplay que lo arregle: hay que
# reiniciarlo, que es justo lo que el usuario hacia a mano.
#
# QUE HACE ESTO. stamp() vigila vq; si pasa VQ_MAX (90 KB) durante VQ_SECS (6)
# segundos SEGUIDOS, mata ffplay y deja una marca. Este lazo la ve y lo vuelve a
# lanzar. Es ~1 segundo de pantalla negra en vez de que el usuario salga del
# juego y vuelva a entrar. EL CLIENTE DE INPUT NO SE TOCA: sigue corriendo en
# segundo plano, asi que el control nunca se corta durante el reinicio.
#
# LOS UMBRALES SE CORRIGIERON EN CALIENTE (2026-08-29). La primera version
# usaba 90 KB / 6 s y se realimentaba: el log mostro dos disparos seguidos,
#
#   [21:09:02] [watchdog] vq lleva 6 s en 296 KB ... Reiniciando ffplay.
#   [21:09:38] [watchdog] vq lleva 6 s en  91 KB ... Reiniciando ffplay.
#
# El segundo es un falso positivo: 91 KB es un kilobyte por encima del tope, y
# es el vq NORMAL de los segundos que siguen a un reinicio. Ahi esta el circulo
# vicioso que hay que tener presente si algun dia se vuelven a tocar estos
# numeros: EL REINICIO CORTA EL STREAM, Y ESE CORTE GENERA UN ATASCO NUEVO. Sin
# freno, el watchdog se dispara a si mismo para siempre. Y no era inofensivo:
# cada reinicio destruye y recrea la ventana de ffplay, el foco rebota y Steam
# Input deja mudo el pad virtual, asi que al usuario se le "desconectaba" el
# control del ESP32 justo al cambiar de juego.
#
# Numeros actuales, todos de la medicion: en regimen vq anda en 29-69 KB, justo
# despues de un reinicio ronda los 90, y atascado de verdad va de 110 a 152 (y
# llego a 296). Por eso 100 KB: arriba del transitorio del reinicio y abajo de
# la meseta real. 10 segundos seguidos descartan la rafaga de wifi.
#
# LA VEDA ES LO QUE DE VERDAD ROMPE EL BUCLE, no el umbral: despues de cada
# reinicio el watchdog se calla VQ_ESPERA segundos (90) antes de poder volver a
# actuar. Aunque el umbral se quede corto alguna vez, el bucle no puede pasar.
#
# TOPE DE REINICIOS. Si algo esta mal de verdad (el server caido, la wifi
# muerta) reiniciar en bucle solo empeora las cosas y tapa el problema real. A
# partir del 5to reinicio en 2 minutos el watchdog se apaga solo por el resto de
# la corrida y lo dice en el log.
#
# Apagarlo del todo: PS3RP_WATCHDOG=0. Ajustarlo: PS3RP_VQ_MAX, PS3RP_VQ_SECS.
WATCHDOG_FLAG=$(mktemp -u)
REINICIOS=0
VENTANA_T0=$(date +%s)
# Muestras (=segundos) que el watchdog deja pasar antes de poder actuar. Al
# arrancar alcanza con saltear el arranque de ffplay; despues de un reinicio hay
# que callarlo mucho mas, porque el propio reinicio deja el vq alto un rato.
ESPERA=15

if [ "$WATCHDOG" = "1" ] && ! command -v gawk >/dev/null 2>&1; then
    echo "AVISO: no hay gawk, el watchdog del video queda inactivo." | tee -a "$LOG"
    WATCHDOG=0
fi

while true; do
    RC_FILE=$(mktemp)
    rm -f "$WATCHDOG_FLAG"
    ( env -u LD_PRELOAD \
        DISABLE_VK_LAYER_VALVE_steam_overlay_1=1 \
        DISABLE_VK_LAYER_VALVE_steam_fossilize_1=1 \
        "${VSYNC_ENV[@]}" \
        SDL_ENABLE_SCREEN_KEYBOARD=0 \
        "${AUDIO_ENV[@]}" \
        ffplay -fs -fflags nobuffer -flags low_delay -framedrop \
        "${FFPLAY_AUDIO_ARGS[@]}" "${FFPLAY_SYNC_ARGS[@]}" \
        -probesize 32 -analyzeduration 0 \
        -hwaccel vaapi -vf 'hwdownload,format=nv12' \
        "${FFPLAY_LOG_ARGS[@]}" \
        -f mpegts "udp://@:$PORT?fifo_size=$FIFO&overrun_nonfatal=1" \
        2>&1; echo $? > "$RC_FILE" ) | stamp | tee -a "$LOG" &
    wait $!

    # Guardar como salio ffplay, no como salio tee. Sin esto el codigo de salida
    # real se pierde en la tuberia (y PIPESTATUS tampoco sirve aca, porque la
    # tuberia se lanzo en segundo plano), asi que ffplay escribe su codigo a un
    # archivo temporal. Una muerte silenciosa de ffplay - justo lo que costo
    # diagnosticar el 2026-08-28 - ya no pasa desapercibida.
    FFPLAY_RC=$(cat "$RC_FILE" 2>/dev/null)
    rm -f "$RC_FILE"
    echo "ffplay termino con codigo $FFPLAY_RC" >> "$LOG"

    # Sin marca, ffplay se cerro porque el usuario salio: no relanzar.
    [ -f "$WATCHDOG_FLAG" ] || break
    rm -f "$WATCHDOG_FLAG"

    AHORA=$(date +%s)
    if [ $((AHORA - VENTANA_T0)) -gt 120 ]; then
        REINICIOS=0
        VENTANA_T0=$AHORA
    fi
    REINICIOS=$((REINICIOS + 1))
    if [ "$REINICIOS" -ge 5 ]; then
        echo "AVISO: 5 reinicios del video en menos de 2 minutos. El watchdog se apaga" | tee -a "$LOG"
        echo "  por el resto de la corrida: si el atasco vuelve tan seguido, el problema" | tee -a "$LOG"
        echo "  no es una cola atascada sino algo mas de fondo (server caido, wifi, etc)." | tee -a "$LOG"
        WATCHDOG=0
    fi
    ESPERA="$VQ_ESPERA"
    echo "Reiniciando el video (reinicio #$REINICIOS; watchdog en veda ${ESPERA}s)..." | tee -a "$LOG"
done

# Aviso si gamescope rechazo el modo de presentacion pedido. Sin esto la linea
# "Unsupported MESA_VK_WSI_PRESENT_MODE value!" queda enterrada entre los
# mensajes de arranque del WSI y se puede pasar por alto durante dias creyendo
# que el vsync quedo apagado cuando no (paso: todo el ajuste de "immediate" del
# 2026-08-29 fue letra muerta por esto). Se mira SOLO lo que se agrego al log en
# esta corrida, contando desde la linea donde estaba antes de arrancar.
if [ "$VSYNC" = "0" ] && [ -n "$LOG_LINES_BEFORE" ]; then
    if tail -n "+$((LOG_LINES_BEFORE + 1))" "$LOG" 2>/dev/null \
        | grep -q "Unsupported MESA_VK_WSI_PRESENT_MODE"; then
        echo "AVISO: gamescope RECHAZO el modo de presentacion '$PRESENT'." | tee -a "$LOG"
        echo "  El swapchain quedo en FIFO (cola de hasta 3 cuadros = ~50ms de lag)." | tee -a "$LOG"
        echo "  Probar PS3RP_PRESENT=mailbox, o habilitar 'Permitir tearing' en el" | tee -a "$LOG"
        echo "  menu de acceso rapido (Rendimiento -> avanzado) y usar =immediate." | tee -a "$LOG"
    else
        echo "Modo de presentacion '$PRESENT' aceptado (sin rechazo en el log)." >> "$LOG"
    fi
fi
