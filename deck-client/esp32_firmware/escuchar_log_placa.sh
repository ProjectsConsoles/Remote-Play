#!/usr/bin/env bash
# Escucha el log remoto del ESP32-S3 (broadcast UDP al puerto 9001).
#
# El Monitor Serie de esta placa nunca funciono (ver la bitacora), asi que
# debugLog() manda cada linea por WiFi. Esto es lo que se usa para ver que le
# esta pidiendo un host - fue lo que destrabo el problema con el PS3, y sirve
# igual para cualquier otra consola.
#
#   ./escuchar_log_placa.sh              # hasta Ctrl+C
#   ./escuchar_log_placa.sh 60           # 60 segundos y sale
#
# Que mirar segun lo que aparezca:
#   - nada de nada           -> la placa no arranco o no conecto al WiFi
#                               (casi siempre alimentacion insuficiente)
#   - solo lineas [hb]       -> la placa vive, pero el host no le pide nada:
#                               no la esta enumerando como DS3
#   - GET_FEATURE/SET_FEATURE-> el host SI la reconocio y esta hablando con
#                               ella; el problema esta mas adelante
SEGS="${1:-0}"
echo "Escuchando el log de la placa en UDP 9001 (Ctrl+C para salir)..."
exec python3 -u -c "
import socket, sys, time
segs = float(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 9001))
t0 = time.time()
while True:
    if segs and time.time() - t0 > segs:
        break
    s.settimeout(1.0)
    try:
        d, a = s.recvfrom(2048)
    except socket.timeout:
        continue
    print(time.strftime('[%H:%M:%S] ') + d.decode('utf-8', 'replace').rstrip())
" "$SEGS"
