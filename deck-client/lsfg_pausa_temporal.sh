#!/bin/bash
# ============================================================
#  lsfg_pausa_temporal.sh
# ============================================================
#  Baja el "multiplier" (generacion de cuadros) de un perfil de lsfg-vk
#  a 1 durante unos segundos y lo regresa solo, EDITANDO el conf.toml en
#  caliente (lsfg-vk soporta recargar multiplier/flow_scale/performance_mode
#  sin reiniciar el proceso que envuelve).
#
#  Para que: el watchdog de start_client_stream.sh detecta rafagas breves
#  de cuadros del servidor (cambio de consola/juego) que no llenan las
#  colas de ffplay pero descuadran a Lossless Scaling. Antes la unica
#  salida era reiniciar ffplay (parpadeo de ventana); esto evita el
#  parpadeo apagando la generacion de cuadros un momento en vez de tocar
#  ffplay para nada.
#
#  Uso: lsfg_pausa_temporal.sh <perfil> <archivo_conf.toml> [segundos_pausa]
#  Sale con 0 si bajo el multiplier (y ya dejo programada la restauracion
#  en segundo plano dentro de este mismo proceso). Sale con 1 si no
#  encontro el perfil/archivo, o si el multiplier ya era 1 o menos (nada
#  que apagar) - quien llama deberia caer de vuelta a reiniciar ffplay en
#  ese caso.
# ============================================================
set -u

PERFIL="${1:?falta el perfil (exe = \"...\" del conf.toml)}"
CONF="${2:?falta la ruta del conf.toml}"
PAUSA="${3:-4}"

[ -f "$CONF" ] || exit 1

leer_multiplier() {
    awk -v perfil="$PERFIL" '
        /^\[\[game\]\]/ { enBloque = 0 }
        $0 == "exe = \"" perfil "\"" { enBloque = 1 }
        enBloque && /^multiplier = / {
            val = $0
            gsub(/[^0-9]/, "", val)
            print val
            exit
        }
    ' "$CONF"
}

escribir_multiplier() {
    local valor="$1"
    local tmp="$CONF.tmp.$$"
    awk -v perfil="$PERFIL" -v valor="$valor" '
        /^\[\[game\]\]/ { enBloque = 0 }
        $0 == "exe = \"" perfil "\"" { enBloque = 1 }
        enBloque && /^multiplier = / { print "multiplier = " valor; next }
        { print }
    ' "$CONF" > "$tmp" && mv "$tmp" "$CONF"
}

ORIGINAL=$(leer_multiplier)
[ -n "$ORIGINAL" ] || exit 1
[ "$ORIGINAL" -gt 1 ] || exit 1

escribir_multiplier 1
sleep "$PAUSA"
escribir_multiplier "$ORIGINAL"
