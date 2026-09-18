@echo off
REM ============================================================
REM  PS3 Remote Play - Servidor de video + audio (Windows + Nvidia)
REM ============================================================
REM  Captura la PS3 desde la capturadora HDMI ("USB Video" +
REM  audio digital), codifica el video en H.264 con NVENC y el
REM  audio en AAC, y transmite AMBOS muxeados en un solo stream
REM  MPEG-TS por UN puerto UDP a la Steam Deck (coincide con lo
REM  que espera start_client_stream.sh del lado del Deck).
REM
REM  Toda la sintonia de abajo (tune ull, delay 0, audio_buffer_size,
REM  etc.) es para minimizar el input lag boton->pantalla, que es lo
REM  que mas importa para poder jugar. Ver notas puntuales en cada
REM  bloque antes de tocar valores.
REM
REM  Cada corrida deja un log en la carpeta "logs" de al lado.
REM  Para leerlo sin bucear: doble clic en revisar_log.bat.
REM ============================================================

REM ------------------------------------------------------------
REM  PERILLA: modo de captura  (0 = MJPEG normal, 1 = SIN COMPRIMIR)
REM ------------------------------------------------------------
REM  Cambiar el 0 por un 1 en la linea "set MODO_CRUDO=" de abajo, o
REM  lanzar este .bat con el argumento "crudo" (por ejemplo desde un
REM  acceso directo:  start_server_stream.bat crudo). Volver a 0 lo
REM  deja exactamente como estaba, no hay nada mas que revertir.
REM
REM  QUE PRUEBA (2026-09-06): si el MJPEG de la capturadora es lo que
REM  pone el piso de latencia que queda. La duda concreta es cuanto
REM  bufferea el chip para comprimir: si guarda 1-2 cuadros enteros
REM  antes de soltarlos serian 16-33 ms escondidos que el modo crudo
REM  se ahorraria. Eso no se puede saber leyendo fichas, solo probando.
REM
REM  LO QUE YA SE SABE (medido con listar_modos.bat el 2026-09-06; el
REM  listado completo quedo en listar_modos_log.txt, al lado):
REM    - Sin comprimir (yuyv422) esta capturadora SOLO llega a 60 fps
REM      en 720x480 y 640x480. De ahi para arriba cae a 10-30 fps.
REM    - Todas sus combinaciones piden entre 37 y 46 MB/s sin importar
REM      la resolucion, y ese es justo el techo del USB 2.0 (~40 MB/s).
REM      O sea: el limite es el CABLE, no el chip ni el sensor.
REM
REM  POR QUE PODRIA SALIR PEOR (por eso es una prueba y no un cambio):
REM  un cuadro 720x480 crudo pesa 691 KB contra los 80-250 KB de un
REM  720p en MJPEG. Son ~5x mas bytes por el mismo cable lento: ~17 ms
REM  de transferencia contra ~3.5 ms. Se ganan los 2-5 ms del decode
REM  MJPEG en esta PC y se pierden ~13 ms en el USB, ademas de bajar
REM  de 720p a 480p (el PS3 saca 720p, se va a notar en la imagen).
REM
REM  COMO LEER EL RESULTADO: jugar unos minutos con cada modo.
REM    - Si el modo crudo NO se siente mejor -> el MJPEG no era el
REM      problema, y NO hace falta comprar la capturadora MS2130: el
REM      piso de latencia esta en otro lado.
REM    - Si se siente notoriamente mejor a pesar de los bytes de mas
REM      -> la MS2130 (USB 3.0, crudo a 1080p60) se justifica sola.
REM
REM  El bitrate se deja en 5M A PROPOSITO aunque 480p necesite menos:
REM  asi lo unico que cambia entre las dos corridas es el camino de
REM  captura y la comparacion es limpia.
REM  PS3RP_GUI=1 lo pone la interfaz grafica antes de lanzar esto.
REM  Su unico efecto es saltarse los "pause" de los mensajes de
REM  error: la interfaz corre este .bat con la ventana OCULTA, y un
REM  pause ahi seria un proceso esperando una tecla que nadie puede
REM  presionar - quedaria colgado para siempre y sin nada en
REM  pantalla que lo delate. Abierto a mano el .bat pausa como
REM  siempre.

set MODO_CRUDO=0

REM  De donde sale el modo, en orden de prioridad:
REM    1) la variable de entorno PS3RP_MODO - es lo que usa la
REM       interfaz grafica (start_server_gui.ps1) para pasar la
REM       eleccion sin tener que editar ni parsear nada;
REM    2) el argumento "crudo" (o la perilla MODO_CRUDO de arriba),
REM       que se mantienen porque ya estaban y siguen funcionando;
REM    3) si no hay nada, mjpeg720, que es el modo probado.
if /i "%~1"=="crudo" set MODO_CRUDO=1

if not defined PS3RP_MODO (
  if "%MODO_CRUDO%"=="1" (set "PS3RP_MODO=crudo480") else (set "PS3RP_MODO=mjpeg720")
)

REM  Tabla de modos. Cada uno define cuatro cosas: como se le pide el
REM  video a la capturadora (CAPTURA), si hay que marcar el 16:9 a
REM  mano (ASPECTO), y el bitrate y el bufsize del encoder.
REM
REM  El bufsize se mueve JUNTO con el bitrate a proposito: son ~3
REM  cuadros de VBV en los dos casos (bitrate / 60 fps x 3). Dejarlo
REM  clavado en 250k con 8 Mbps daria un colchon mas chico en tiempo
REM  y rafagas mas nerviosas.
set "CAPTURA="
REM  RTBUF por defecto para los modos MJPEG/crudo480/640 de siempre (ver
REM  la nota grande de rtbufsize mas abajo, ajustada para esos). crudo720
REM  la pisa con un valor propio (frames sin comprimir a 720p pesan
REM  ~1.8MB cada uno - 512k no alcanza ni para uno solo).
set "RTBUF=512k"

if /i "%PS3RP_MODO%"=="mjpeg720" (
  set "CAPTURA=-video_size 1280x720 -framerate 60 -vcodec mjpeg"
  set "ASPECTO="
  set "VBITRATE=5M"
  set "VBUF=250k"
  set "MODO_TXT=1280x720 MJPEG - normal, el modo probado"
)

if /i "%PS3RP_MODO%"=="mjpeg1080" (
  set "CAPTURA=-video_size 1920x1080 -framerate 60 -vcodec mjpeg"
  set "ASPECTO="
  set "VBITRATE=8M"
  set "VBUF=400k"
  set "MODO_TXT=1920x1080 MJPEG - mas nitido, mas carga de wifi"
)

if /i "%PS3RP_MODO%"=="crudo480" (
  set "CAPTURA=-video_size 720x480 -framerate 60 -pixel_format yuyv422"
  set "ASPECTO=-aspect 16:9"
  set "VBITRATE=5M"
  set "VBUF=250k"
  set "MODO_TXT=720x480 SIN COMPRIMIR - prueba de latencia"
)

if /i "%PS3RP_MODO%"=="crudo640" (
  set "CAPTURA=-video_size 640x480 -framerate 60 -pixel_format yuyv422"
  set "ASPECTO=-aspect 16:9"
  set "VBITRATE=5M"
  set "VBUF=250k"
  set "MODO_TXT=640x480 SIN COMPRIMIR - prueba de latencia"
)

REM  crudo720 (2026-09-17): la capturadora "Hagibis" nueva SI sostiene
REM  1280x720 sin comprimir a 60fps por USB (confirmado con una prueba
REM  de 12s: 59fps, 1 solo aviso de buffer lleno) - la vieja topaba en
REM  480p sin comprimir. Frame crudo de 720p pesa ~1.8MB, por eso el
REM  RTBUF propio de 8M (con 512k ni entraba un cuadro completo).
if /i "%PS3RP_MODO%"=="crudo720" (
  set "CAPTURA=-video_size 1280x720 -framerate 60 -pixel_format yuyv422"
  set "ASPECTO="
  set "VBITRATE=5M"
  set "VBUF=250k"
  set "RTBUF=8M"
  set "MODO_TXT=1280x720 SIN COMPRIMIR - requiere capturadora que lo soporte"
)

if not defined CAPTURA (
  echo.
  echo   ERROR: modo de captura desconocido: "%PS3RP_MODO%"
  echo   Los validos son: mjpeg720, mjpeg1080, crudo480, crudo640, crudo720
  echo.
  if not defined PS3RP_GUI pause
  exit /b 1
)

REM  El "-aspect 16:9" del modo crudo NO reescala nada y no cuesta
REM  CPU: solo marca en el stream que el cuadro se ve en 16:9. Hace
REM  falta porque 720x480 no es 16:9 de por si, y sin eso la Deck lo
REM  mostraria achatado. Si en el modo crudo la imagen sale deformada
REM  al REVES (estirada a lo ancho), significa que la capturadora ya
REM  manda barras negras en vez de achatar: quitar ese -aspect 16:9.

REM ------------------------------------------------------------
REM  IP de la Steam Deck - se pregunta al arrancar
REM ------------------------------------------------------------
REM  El video va EMPUJADO de esta PC hacia la Deck: la Deck solo se
REM  sienta a escuchar en udp://@:5000 y acepta de quien sea, asi
REM  que nunca necesita saber la IP de esta PC. La unica IP que
REM  tiene que estar bien es la de la Deck, y vive aqui.
REM
REM  Antes estaba clavada como 192.168.0.141. El problema: si la
REM  Deck cambia de IP (por ejemplo al pasarse de la red de 2.4GHz
REM  a la de 5GHz), ffmpeg sigue disparando a la IP vieja, NO da
REM  ningun error - manda UDP feliz a un destino que no existe - y
REM  del lado del Deck solo se ve pantalla negra. Paso el
REM  2026-08-28 y costo un rato darse cuenta, porque el cliente
REM  arranca bien y no se queja. Por eso ahora se pregunta.
REM
REM  La ultima IP usada queda guardada en deck_ip.txt (al lado de
REM  este .bat) y se ofrece como default: Enter la acepta.
REM
REM  Para ver la IP actual de la Deck, en una terminal del Deck:
REM      ip -4 addr show wlan0
REM
REM  OJO: este .bat DEBE guardarse con saltos de linea CRLF. El
REM  bloque de abajo usa una etiqueta (:pedir_ip) con goto, y
REM  cmd.exe se pierde saltando a etiquetas si el archivo tiene
REM  solo LF (asi estaba antes de agregar esto).
set DECK_PORT=5000
set IP_FILE=%~dp0deck_ip.txt

REM  Default: la ultima IP guardada, o la de siempre la primera vez.
set DECK_IP_DEF=192.168.0.141
if exist "%IP_FILE%" set /p DECK_IP_DEF=<"%IP_FILE%"

:pedir_ip
echo.

REM  Si PS3RP_IP viene puesta desde afuera (la interfaz grafica), se
REM  usa esa y NO se pregunta nada. Igual pasa por la validacion de
REM  abajo, asi que una IP mal escrita no se cuela por este atajo;
REM  si falla, se limpia la variable y cae al prompt de siempre.
if defined PS3RP_IP (
  set "DECK_IP=%PS3RP_IP%"
  goto validar_ip
)

set "NUEVA_IP="
set /p NUEVA_IP=  IP de la Steam Deck [%DECK_IP_DEF%], o Enter para usar esa: 
if "%NUEVA_IP%"=="" (set "DECK_IP=%DECK_IP_DEF%") else (set "DECK_IP=%NUEVA_IP%")

:validar_ip

REM  Validacion minima: 4 grupos de digitos separados por puntos.
REM  No valida rangos (256.1.1.1 pasa) - solo atrapa dedazos como
REM  una IP a medias o con una letra, que si no se notarian hasta
REM  ver la pantalla negra otra vez.
echo(%DECK_IP%| findstr /r /c:"^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$" >nul
if errorlevel 1 (
  echo   "%DECK_IP%" no parece una IP. Intenta de nuevo.
  set "PS3RP_IP="
  goto pedir_ip
)

REM  Guardar para la proxima. Se escribe CON salto de linea al final
REM  (por eso `echo` y no `<nul set /p`, que era lo de antes):
REM  `set /p x=<archivo` lee hasta el salto de linea, y si el archivo
REM  no lo tiene se come el ultimo caracter - la IP volveria como
REM  192.168.0.14 en vez de 192.168.0.141, pasaria la validacion de
REM  abajo igual (siguen siendo 4 grupos de digitos) y otra vez
REM  pantalla negra sin ningun error. El salto NO se cuela en la
REM  variable: es justo lo que set /p usa para saber donde termina.
>"%IP_FILE%" echo(%DECK_IP%

echo.
echo  Mandando video a %DECK_IP%:%DECK_PORT%
echo.

REM  Usa el FFmpeg que viene junto a este .bat (carpeta
REM  ffmpeg-9.0.1-full_build\bin), no depende del PATH del sistema.
REM  (El PATH del sistema puede no reflejarse en una sesion de cmd/
REM  Explorer ya abierta aunque lo hayas configurado bien.)
set FFMPEG=%~dp0ffmpeg-9.0.1-full_build\bin\ffmpeg.exe

REM ------------------------------------------------------------
REM  Nombres de la capturadora - ya no van clavados
REM ------------------------------------------------------------
REM  Antes esto decia, tal cual:
REM      -i video="USB Video":audio="Interfaz de sonido digital (USB Digital Audio)"
REM
REM  El problema (paso el 2026-08-29): Windows le cambia el nombre a
REM  la interfaz de audio de la capturadora si se enchufa en OTRO
REM  puerto USB - le mete un numero adelante y queda como
REM  "Interfaz de sonido digital (2- USB Digital Audio)". El nombre
REM  clavado deja de existir, y ffmpeg ni arranca:
REM      Could not find audio only device with name [Interfaz de
REM      sonido digital (USB Digital Audio)] among source devices
REM      of type audio.
REM      Error opening input files: I/O error
REM
REM  Ahora el nombre se busca cada vez, por PEDAZO ("USB Video",
REM  "USB Digital Audio"), que es lo que sobrevive al "2- ".
REM
REM  La busqueda la hace detectar_dispositivos.ps1 (al lado de este
REM  .bat) y no este mismo .bat a proposito: los nombres traen
REM  espacios, comillas y parentesis, y sacarlos de la salida de
REM  ffmpeg con for /f en cmd es un campo minado. El .ps1 los deja
REM  en dos archivos de texto y aqui se leen con "set /p", que es la
REM  misma manera en que ya se lee deck_ip.txt mas arriba.
set "F_VIDEO=%TEMP%\ps3rp_video.txt"
set "F_AUDIO=%TEMP%\ps3rp_audio.txt"
set "F_LISTA=%TEMP%\ps3rp_dshow.txt"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0detectar_dispositivos.ps1" >nul 2>&1

REM  Si el .ps1 no encontro algo, no escribe su archivo (y borra el
REM  de la corrida anterior), asi que la variable queda sin definir.
set "VIDEO_DEV="
set "AUDIO_DEV="
if exist "%F_VIDEO%" set /p VIDEO_DEV=<"%F_VIDEO%"
if exist "%F_AUDIO%" set /p AUDIO_DEV=<"%F_AUDIO%"

if not defined VIDEO_DEV goto sin_dispositivo
if not defined AUDIO_DEV goto sin_dispositivo

echo  Capturadora video: %VIDEO_DEV%
echo  Capturadora audio: %AUDIO_DEV%
echo.

REM ------------------------------------------------------------
REM  Log de la corrida
REM ------------------------------------------------------------
REM  QUE PREGUNTA RESPONDE (2026-08-29, cuarta vuelta): si la
REM  capturadora MJPEG a 720p60 le esta GANANDO a esta PC. Si el
REM  MJPEG no se decodifica a tiempo, los cuadros se apilan en el
REM  buffer de dshow ANTES de llegar a NVENC - serian cientos de ms
REM  de lag que ningun ajuste del lado del Deck puede tocar, porque
REM  se generan aca. En el log eso se ve de dos formas:
REM    - fps= por debajo de 60 en la linea de estado, o speed= por
REM      debajo de 1x;
REM    - el aviso de ffmpeg "real-time buffer [...] too full or near
REM      too full [...] frame dropped!", que es dshow diciendo
REM      literalmente que se le llena la cola.
REM  Si el log sale limpio (60 fps clavados, sin ese aviso), la
REM  captura NO es el cuello de botella y hay que medir el piso de
REM  la capturadora en si (ver README/notas: ffplay directo contra
REM  el dispositivo, sin red ni NVENC, y foto contra la TV).
REM
REM  SON DOS ARCHIVOS, Y HACEN FALTA LOS DOS. Se probo (medido aqui
REM  mismo el 2026-08-29 con un ffmpeg de prueba) que NO alcanza con
REM  uno solo:
REM
REM  1) ffmpeg-<fecha>.log  <- FFREPORT
REM     FFREPORT es el "tee" que cmd no tiene: equivale a pasarle
REM     -report, o sea que escribe el log a un archivo y ADEMAS lo
REM     sigue mostrando en esta ventana (no se pierde nada de lo que
REM     ya se veia, como los errores de dispositivo del arranque).
REM     Aqui es donde caen los avisos, incluido el que importa:
REM     "real-time buffer ... full ... frame dropped!".
REM     level=32 es "info" a proposito: el default del report es
REM     debug (48) y con NVENC + dshow a 60fps escribe por cuadro,
REM     dejando un archivo inmanejable.
REM
REM     LO QUE NO TIENE: la linea de estado periodica. Comprobado:
REM     en el report solo aparece UN fps=, el del resumen final. Las
REM     lineas de progreso van directo a la consola sin pasar por el
REM     log, asi que con esto solo NO se puede ver si los fps se
REM     caen a mitad de la partida - que es justo la pregunta.
REM
REM  2) progreso-<fecha>.log  <- -progress
REM     Esto si escribe un bloque cada -stats_period con los numeros
REM     en formato clave=valor: fps, speed, dup_frames, drop_frames.
REM     Es la serie temporal que contesta la pregunta.
REM     Ojo: -progress TRUNCA el archivo en cada corrida (por eso el
REM     nombre lleva la fecha, para no pisar el de la corrida
REM     anterior; -progress no expande %%t como FFREPORT, hay que
REM     armarle el nombre).
REM
REM  Los dos archivos de una misma corrida comparten la fecha en el
REM  nombre, asi que se emparejan de un vistazo. Se acumulan: borrar
REM  la carpeta "logs" de vez en cuando.
REM
REM  El pushd evita el unico punto delicado: FFREPORT separa sus
REM  opciones con ":", asi que una ruta de Windows con "C:\" adentro
REM  habria que escaparla. Parados en la carpeta de logs, el nombre
REM  queda relativo y no hay ningun ":" que escapar.
REM
REM  -stats_period 2 : un bloque cada 2s en vez de cada 0.5s. Cuatro
REM  veces menos archivo y alcanza de sobra para ver una caida de
REM  fps. (Tambien espacia la linea de estado en pantalla.)
if not exist "%~dp0logs" mkdir "%~dp0logs"

REM  Fecha-hora para el nombre de los dos archivos. Se le pide a
REM  PowerShell (del que este script ya depende para detectar la
REM  capturadora) en vez de a %%DATE%%/%%TIME%%, que cambian de
REM  formato segun la configuracion regional de Windows y dejarian
REM  nombres con barras o espacios.
set "STAMP="
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set STAMP=%%i
if not defined STAMP set STAMP=sinfecha

set FFREPORT=file=ffmpeg-%STAMP%.log:level=32
echo  Logs de esta corrida, en %~dp0logs\
echo    ffmpeg-%STAMP%.log     - avisos y errores
echo    progreso-%STAMP%.log   - fps, speed, cuadros tirados
echo  Para leerlos sin bucear: revisar_log.bat
echo.
echo  Modo de captura: %MODO_TXT%
echo.
pushd "%~dp0logs"

REM  AUDIO: Opus de baja latencia en vez de AAC (2026-09-18). ffplay usa el
REM  audio de reloj maestro, asi que todo retraso del audio se lo hereda el
REM  video (la Deck mostraba vq=30-70 KB de video esperando al audio). AAC
REM  retiene ~40 ms (frame de 1024 + relleno del codificador); Opus con
REM  frame_duration 10 y lowdelay, ~15 ms. Para volver: -c:a aac -b:a 96k.
REM  PRUEBA (2026-09-18): -audio_buffer_size 50->20 y Opus frame_duration 10->5.
REM    Con Opus el delay bajo mucho, o sea que la cadena de audio (de la que
REM    depende el video por -sync audio) sigue mandando. El 20 ya se probo el
REM    2026-08-29 y se sintio peor, pero fue ANTES de quitar las retenciones del
REM    muxer y de pasar a Opus. Si truena el audio o empeora: volver a 50 y 10
REM    (valores buenos confirmados).
"%FFMPEG%" ^
  -stats_period 2 -progress progreso-%STAMP%.log ^
  -f dshow %CAPTURA% ^
  -use_wallclock_as_timestamps 1 ^
  -audio_buffer_size 20 -rtbufsize %RTBUF% ^
  -i video="%VIDEO_DEV%":audio="%AUDIO_DEV%" ^
  -vf format=nv12 %ASPECTO% ^
  -c:v h264_nvenc -preset p1 -tune ull -zerolatency 1 -rc cbr -b:v %VBITRATE% -maxrate %VBITRATE% -bufsize %VBUF% ^
  -g 30 -bf 0 -rc-lookahead 0 -delay 0 ^
  -af aresample=async=1000 ^
  -c:a libopus -application lowdelay -frame_duration 5 -b:a 96k -ar 48000 -ac 2 ^
  -f mpegts -muxdelay 0 -muxpreload 0 -flush_packets 1 -max_interleave_delta 0 -pes_payload_size 0 ^
  udp://%DECK_IP%:%DECK_PORT%?pkt_size=1316

REM  Guardar el codigo de salida ANTES del popd: popd lo pisa, y sin
REM  esto el .bat siempre reportaria exito aunque ffmpeg reventara.
set RC=%ERRORLEVEL%
popd

REM  Aqui termina el trabajo. El exit /b es obligatorio: sin el,
REM  cuando ffmpeg corta, cmd sigue leyendo el archivo y se meteria
REM  solo en el bloque :sin_dispositivo del final.
exit /b %RC%

REM  AJUSTE (2026-08-29): captura NATIVA a 1280x720 en vez de capturar
REM    1080p y reescalar con la CPU. Medido con medir_latencia.bat: la
REM    capturadora ofrece "vcodec=mjpeg min s=1280x720 fps=10 max s=1280x720
REM    fps=60.0002", o sea 720p60 directo. Antes se pedia 1920x1080 y se
REM    bajaba con "-vf scale=1280:720" - eso obligaba a la capturadora a
REM    comprimir en MJPEG un cuadro del doble de pixeles, mandarlo entero
REM    por USB2 (que es el cuello de botella de este aparato) y recien ahi
REM    la CPU lo decodificaba y lo encogia. Pidiendolo ya en 720p se ahorra
REM    ~la mitad del tiempo de transferencia por USB y el reescalado entero,
REM    y el resultado final es identico (el stream ya salia en 720p).
REM    Por eso el -vf quedo solo en "format=nv12": el scale ya no hace falta.
REM    OJO: el mismo listado mostro que sin comprimir (yuyv422) esta
REM    capturadora ("USB Video", la vieja) tope a 10 fps en 1080p y 25 fps
REM    en 720p - por eso MJPEG no era opcional ahi, aunque su compresion/
REM    descompresion sea justo lo que le pone piso a la latencia.
REM
REM    MATIZ (2026-09-06, listar_modos.bat): "no es opcional" valia para
REM    720p CON ESA capturadora, pero el listado completo mostro que SI
REM    habia crudo a 60 fps en 720x480 y 640x480 - de ahi crudo480/crudo640.
REM
REM    CAMBIA POR CAPTURADORA (2026-09-17): la "Hagibis" nueva SI sostiene
REM    1280x720 sin comprimir a 60fps (confirmado, ver modo crudo720 en la
REM    tabla de arriba) - la limitacion de 25fps@720p era de la capturadora
REM    vieja, no una limitacion de USB en general. Si cambias de
REM    capturadora otra vez, volve a correr listar_modos_capturadora.bat
REM    (al lado de este .bat) contra el nombre nuevo antes de asumir que
REM    crudo720 sigue sirviendo.

REM 
REM  -rtbufsize 512k : tope del buffer de captura en tiempo real de
REM    dshow, o sea la cola de cuadros que ffmpeg deja acumular ENTRE
REM    la capturadora y el encoder. El default de ffmpeg son 3041280
REM    bytes (~2.9 MB). A 720p60 en MJPEG un cuadro pesa entre 80 y
REM    250 KB segun lo cargada que este la escena, asi que ese default
REM    son entre 12 y 35 CUADROS de cola: 200 a 580 ms de retraso que
REM    se generan aca y que ninguna perilla del lado del Deck puede
REM    tocar.
REM 
REM    Y no se llena parejo: se llena cuando la PC no le gana a la
REM    capturadora, que es justo lo que pasa al entrar a un JUEGO
REM    (escena complicada -> el MJPEG pesa mas -> tarda mas en
REM    decodificarse -> la cola crece y se queda arriba). Encaja con el
REM    sintoma de 'hay mas lag cuando abro un juego' que en el XMB, que
REM    es una pantalla casi quieta.
REM 
REM    Si la PC no llega, ahora TIRA cuadros en vez de acumular
REM    retraso, y lo dice en el log: 'real-time buffer ... full ...
REM    frame dropped!'. Que aparezca ese aviso no es el problema, es el
REM    diagnostico - revisar_log.bat lo cuenta.
REM 
REM    HISTORIA DEL VALOR (para no volver a probar a ciegas):
REM      default (2.9 MB) -> 12 a 35 cuadros de cola. Era lo que habia.
REM      512k (~2-5 cuadros) -> el usuario confirmo 'ya mejoro mucho'
REM         en Modo Juego. VALOR CONOCIDO BUENO: si algo sale mal,
REM         volver aca, no al default.
REM      256k (~1-3 cuadros) -> se probo y se sintio IGUAL que 512k, o
REM         sea que en 512k la cola ya no se llenaba. Se volvio a 512k
REM         por ser el valor confirmado. No apretar mas: no rinde.
REM  AJUSTE (2026-08-29): -bufsize bajado de 700k a 250k. bufsize es
REM    el tamano del buffer virtual del rate control (VBV): 700k a
REM    5 Mbps son ~140ms de margen que NVENC se permite gastar en un
REM    solo frame. Ese margen se traduce en rafagas grandes cruzando
REM    la wifi (encolamiento = jitter = lag) y en NALs mas grandes,
REM    que es justo lo que hace que perder UN paquete UDP corrompa
REM    todo el frame (los "non-existing PPS 0" del log del Deck).
REM    250k son ~3 frames a 60fps (5M/60 = ~83k por frame), que es el
REM    rango tipico de baja latencia. Efecto secundario esperado: en
REM    cambios de escena bruscos el bitrate no puede dispararse, asi
REM    que puede verse un pelin mas blando por un instante. Si se ve
REM    notoriamente peor y el lag no bajo, volver a 700k.

REM  PROBADO Y REVERTIDO (2026-08-29): se bajo -audio_buffer_size de 50 a
REM    20 ms y el usuario reporto que el input lag EMPEORO respecto a la
REM    corrida con 50 (imagen y audio se veian/oian bien, pero el lag
REM    volvio). Se devolvio a 50, que es el valor bueno confirmado.
REM    No volver a bajarlo sin una razon nueva.
REM
REM    Y EL RAZONAMIENTO QUE LLEVO A PROBARLO TAMBIEN ERA MALO (corregido el
REM    2026-08-29, mismo dia, mas tarde). Decia: "se midio que el lag de video
REM    ES la cadena de audio, porque con PS3RP_NOAUDIO=1 del lado del Deck el
REM    lag baja notoriamente". La medicion era cierta, la conclusion no.
REM    Midiendo la cola interna de ffplay (PS3RP_STATS=1 en
REM    start_client_stream.sh, campo vq) se vio que el retraso grande se
REM    formaba EN EL ARRANQUE del reproductor del Deck y se quedaba ahi para
REM    siempre: 205-248 KB de video encolado = ~340 ms de lag puro, causados
REM    por haber puesto -sync video del lado del cliente. Con el reloj de
REM    audio de vuelta (el default) esa cola se vacia sola y queda en 0 KB.
REM    Quitar el audio "ayudaba" porque tambien aliviana ese arranque, no
REM    porque el audio frenara al video.
REM    O sea: NO hay razon medida para seguir bajando -audio_buffer_size. El
REM    valor bueno confirmado es 50. Si algun dia se retoma, primero medir vq
REM    del lado del Deck y solo despues venir aca.

REM 
REM  -max_interleave_delta 0 : el muxer de mpegts, por default, NO
REM    escribe un cuadro de video hasta tener un paquete de AUDIO que
REM    lo cubra en el tiempo, para dejar los dos streams bien
REM    intercalados. Con un archivo eso es prolijo; con una
REM    transmision en vivo es retraso puro: el audio de la
REM    capturadora llega en bloques (-audio_buffer_size 50, mas los
REM    1024 samples que junta el AAC), asi que cada cuadro de video se
REM    queda esperando ~25-70 ms EN LA PC antes de salir a la red.
REM    Con 0 se apaga esa espera y cada paquete sale apenas esta listo.
REM 
REM    POR QUE ESTE ES EL SOSPECHOSO BUENO AHORA: la vista previa local
REM    de la capturadora (medir_latencia.bat) se siente inmediata, y esa
REM    vista previa NO pasa por el encoder ni por el muxer ni por la
REM    red. O sea que todo lo que esta entre NVENC y el Deck sigue sin
REM    medirse, y esta espera del muxer vive justo ahi. Tambien encaja
REM    con la vieja observacion de que 'sin audio la imagen es
REM    inmediata': sin audio no hay con quien intercalar, y el muxer
REM    deja de esperar.
REM 
REM    -muxdelay 0 / -muxpreload 0 (que ya estaban) NO cubren esto: son
REM    otra cosa, el retardo de arranque del muxer, no el intercalado.
REM
REM  -pes_payload_size 0 (2026-09-18, PROBAR y medir): el muxer mpegts
REM    junta el AUDIO en paquetes PES de minimo 2930 bytes (default)
REM    antes de escribirlos. A 96 kbps de AAC (~12 KB/s) eso es hasta
REM    ~200 ms de audio retenido en esta PC - y como el cliente usa el
REM    audio de reloj maestro (-sync audio), el video espera a que ese
REM    audio llegue. Con 0 cada paquete de audio sale apenas esta
REM    listo (el video ya salia de a uno por cuadro, no le cambia).
REM    Si el audio suena entrecortado o el video empeora, quitar SOLO
REM    "-pes_payload_size 0" de la linea de -f mpegts: es la unica
REM    diferencia contra el comportamiento anterior.
REM 
REM 
REM  -use_wallclock_as_timestamps 1 : lo que hace que el aresample de
REM    arriba pueda hacer su trabajo.
REM 
REM    aresample=async solo corrige contra las MARCAS DE TIEMPO. Si el
REM    demuxer numera las muestras para armar el PTS en vez de anotar la
REM    hora real de llegada, la linea de tiempo del audio le parece
REM    perfecta - la deriva esta ahi pero es invisible, y el filtro no
REM    corrige nada. Que es exactamente lo que paso: se puso async=1000
REM    y el audio siguio desfasandose igual.
REM 
REM    Con esto cada paquete se marca con la hora a la que llego de
REM    verdad, asi que la deriva del reloj de la capturadora aparece en
REM    los timestamps y el aresample la puede absorber.
REM 
REM    RIESGO A VIGILAR: esto tambien afecta al video. Las marcas pasan
REM    a tener el jitter de llegada, y como la salida es a 60fps fijos,
REM    ffmpeg podria empezar a duplicar o tirar cuadros para cuadrar.
REM    Eso se ve en el log de progreso como dup_frames o drop_frames
REM    distintos de cero (revisar_log.bat los muestra), y en pantalla
REM    como tironeo. Si aparece, se quita esta linea y volvemos a
REM    pensar - el aresample de arriba se puede quedar, no molesta.

REM  -af aresample=async=1000 : arreglo de la DERIVA del audio.
REM 
REM    El sintoma: despues de un rato el audio se va desfasando del
REM    video, y se compone reiniciando el server. Ese 'se compone
REM    reiniciando' es justamente la firma del problema.
REM 
REM    La causa: el reloj de audio de la capturadora no corre exacto a
REM    48000 Hz (ninguno lo hace; se van unas partes por millon). El
REM    encoder AAC no le hace caso a la hora a la que llega cada
REM    bloque: numera las muestras y de ahi saca el PTS. Asi que si el
REM    aparato entrega 48001 muestras por segundo en vez de 48000, cada
REM    segundo el audio se corre un poquito, y ESO SE ACUMULA - no se
REM    nota en un minuto y es obvio en veinte. Reiniciar el server pone
REM    la cuenta de muestras en cero otra vez, por eso 'se arregla'.
REM 
REM    aresample=async=1000 le da permiso al remuestreador para estirar
REM    o encoger hasta 1000 muestras por segundo con tal de que el audio
REM    siga pegado a las marcas de tiempo con las que entro. La deriva
REM    se absorbe sobre la marcha en vez de acumularse.
REM 
REM    No agrega latencia: no guarda nada, solo ajusta el paso. Si
REM    alguna vez se llegara a oir el ajuste (no deberia, son partes por
REM    millon), bajarlo a async=100. Quitarlo del todo devuelve la
REM    deriva.
REM  -audio_buffer_size 50 : la interfaz de audio USB de la
REM    capturadora usaba un buffer de captura grande por default en
REM    DirectShow/Windows, lo que atrasaba el audio respecto al
REM    video. Este flag le pide al driver un buffer chico (en ms)
REM    para bajar esa latencia en el origen. Si el driver del
REM    dispositivo ignora el valor pedido, no hace nada (algunos no
REM    lo respetan) - probado y funciona con esta capturadora.
REM
REM    IMPORTANTE: no intentar arreglar el desfase audio/video con
REM    -itsoffset separando video y audio en dos -i distintos. Ya se
REM    probo: obliga al muxer a esperar el audio (que sigue llegando
REM    tarde de verdad, el offset solo cambia la etiqueta de tiempo)
REM    antes de poder escribir el video, y el input lag empeora en
REM    vez de mejorar. Tampoco forzar -sync video del lado del
REM    cliente como sustituto: eso hace que ffplay reintente
REM    resamplear el audio sin parar contra un hueco que nunca se
REM    cierra, y se escucha cortado. La solucion real es bajar la
REM    latencia real de captura del audio (este flag), no mentir
REM    sobre sus timestamps ni forzar el reloj de reproduccion.
REM
REM  -tune ull -zerolatency 1 -rc-lookahead 0 -delay 0 : evitan que
REM    NVENC acumule frames en buffer interno antes de soltarlos.
REM    Con 60fps eso solo podia sumar decenas/cientos de ms.
REM
REM  -muxdelay 0 -muxpreload 0 -flush_packets 1 : el muxer mpegts
REM    por default puede retener paquetes hasta 0.7s (-muxdelay) para
REM    interleavear streams "prolijo". Sin esto, ese delay se suma
REM    solo, aunque el resto de la cadena este bien afinada.
REM
REM  &connect=0 (agregado 2026-08-23, QUITADO DE NUEVO 2026-08-23 para
REM    prueba A/B) : arreglaba confirmadamente el bug de tener que
REM    reiniciar ESTE server al salir y volver a entrar al cliente
REM    (start_client_stream.sh) - sin esto, ffmpeg conecta el socket
REM    UDP de salida, y mientras el cliente no escucha en el puerto (el
REM    rato entre salir y volver a entrar) Windows le devuelve al
REM    server un ICMP "Destination Unreachable" por paquete, que con el
REM    socket conectado hace fallar el siguiente send() con
REM    WSAECONNRESET y deja el pipeline atascado hasta reiniciar el
REM    proceso. connect=0 evitaba ese connect() para no recibir esos
REM    ICMP.
REM    Se quito de nuevo (sin el "&connect=0" en la URL de abajo) para
REM    probar si es la causa de un sonido con chasquidos/pops que
REM    aparecio despues de agregarlo, presente en Escritorio Y Modo
REM    Juego. Si SIN connect=0 el chasquido desaparece, confirma la
REM    hipotesis (hay que buscar otra forma de arreglar el bug del
REM    reinicio que no cause esto). Si el chasquido sigue igual sin
REM    connect=0, esto se descarta como causa y hay que devolver el
REM    "&connect=0" a la URL (arregla un bug real, confirmado) y seguir
REM    buscando la causa del chasquido en otro lado.
REM
REM  PRUEBA (2026-08-23): bajado de 1920x1080/8M a 1280x720/5M
REM    (scale=1280:720 antes del nv12, -b:v/-maxrate 8M->5M, -bufsize
REM    1M->700k proporcional). Motivo: en ~/ps3rp_client.log del lado
REM    Deck aparecio una corrida con 29 errores seguidos de
REM    "non-existing PPS 0 referenced"/"decode_slice_header
REM    error"/"no frame!" (frames de video corrompidos por perder un
REM    paquete UDP de 188 bytes a mitad de un NAL H.264), mientras
REM    corridas de minutos antes y despues en la misma sesion dieron 0
REM    errores - apunta a una rafaga de interferencia/perdida en la
REM    wifi, no a que el pipeline le quede grande a la CPU. Bajar
REM    resolucion+bitrate real (no solo resolucion, dejando el mismo
REM    -b:v 8M no bajaria nada los bytes/seg que van por la wifi con
REM    -rc cbr) reduce la cantidad de datos por segundo y el tamano
REM    tipico de NAL, asi que perder un paquete puntual corrompe menos
REM    seguido. Si el corte/retraso que crecia con el tiempo no vuelve
REM    a aparecer con esto, confirma la hipotesis. Si vuelve a pasar
REM    igual, esto se puede revertir a 1920x1080/8M/1M (los valores
REM    originales de -video_size/-vf/-b:v/-maxrate/-bufsize arriba) y
REM    hay que seguir buscando del lado de la wifi (interferencia,
REM    canal, trafico de fondo).
REM
REM  PRUEBA (2026-08-23): audio -b:a bajado de 128k a 96k. Con 720p/5M
REM    de video (ver arriba) volvio a haber audio entrecortado
REM    ocasional. 128k->96k ahorra muy poco del total (32kbps de
REM    ~5.13Mbps, <1%), asi que esto SOLO ayuda si el corte es porque
REM    un paquete UDP que le toca justo al audio se pierde (a
REM    diferencia del video, que tiene keyframes cada 0.5s para
REM    recuperarse, un frame AAC perdido se escucha como un click
REM    inmediato) - bajar el bitrate de audio reduce un poco cuantos
REM    paquetes por segundo le tocan al audio, no el ancho de banda
REM    total. Si el corte ocasional sigue igual con esto, el problema
REM    real sigue siendo perdida de paquetes en la wifi en general
REM    (no algo que se arregle bajando mas la calidad de audio) y hay
REM    que atacarlo del lado de la red, no de ffmpeg. Revertir a 128k
REM    si el audio suena notoriamente peor y no ayudo con los cortes.

if not defined PS3RP_GUI pause

REM ------------------------------------------------------------
REM  Salida cuando no aparece la capturadora
REM ------------------------------------------------------------
:sin_dispositivo
echo.
echo ============================================================
echo  ERROR: no se encontro la capturadora
echo ============================================================
if not defined VIDEO_DEV echo   - No hay ningun dispositivo de VIDEO con "USB Video" en el nombre.
if not defined AUDIO_DEV echo   - No hay ningun dispositivo de AUDIO con "Digital Audio" en el nombre.
echo.
if not exist "%F_LISTA%" (
  echo  Ni siquiera se pudo pedir el listado de dispositivos. Revisar
  echo  que detectar_dispositivos.ps1 este en esta misma carpeta
  echo  ^(junto a este .bat^) y que PowerShell corra.
) else (
  echo  Esto es todo lo que Windows ofrece ahora mismo:
  echo.
  type "%F_LISTA%"
)
echo.
echo  Que revisar, en este orden:
echo    1^) Que la capturadora este enchufada. Cambiarla de puerto USB
echo       tambien vale: el nombre puede cambiar, pero esto ya lo
echo       aguanta.
echo    2^) Que no la tenga tomada otro programa: OBS, Discord, el
echo       propio Remote Play, o un ffmpeg que quedo colgado de una
echo       corrida anterior.
echo    3^) Administrador de dispositivos: que no aparezca con el
echo       triangulito amarillo.
echo.
if not defined PS3RP_GUI pause
exit /b 1
