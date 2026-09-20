# Cliente Android

Cliente para tabletas/teléfonos Android con mando Bluetooth (pensado para una
Samsung + GameSir G8+). Hace lo mismo que los clientes de la Deck y la Ally:

- recibe el MPEG-TS (H.264 + Opus) por UDP y lo muestra a pantalla completa
  con el decodificador de **hardware** (`MediaCodec`);
- manda el estado del mando al ESP32-S3 por UDP (JSON, 120 Hz);
- configura el servidor Windows en remoto (UDP 9200: consultar, aplicar modo,
  apagar) y los ajustes del cliente.

> **Estado:** compila y las pruebas unitarias pasan (demultiplexor probado con
> un `.ts` real de ffmpeg y el JSON del mando contra el contrato del firmware).
> **Todavía no se ha probado en una tableta real.**

Sin bibliotecas externas: el demultiplexor MPEG-TS (`TsDemuxer.kt`) es propio.
Los cuadros y el audio se entregan al decodificador apenas llegan, sin reloj de
sincronía (igual que el modo GStreamer de la Deck): si el decodificador no tiene
sitio para un cuadro, se tira y se espera al siguiente IDR en vez de acumular
retraso.

## Uso

1. En el servidor, **Configurar servidor** (en la app): la IP de la tableta se
   detecta sola; elige el modo (el recomendado es `1280x720 MJPEG`) y
   **Aplicar**. Si el servidor estaba transmitiendo, se reinicia con la config
   nueva.
2. **Configurar cliente**: IP del ESP32 (por defecto `192.168.0.40`, puerto 9000).
3. **Streaming** (video + audio + mando) o **Solo control** (la tableta es solo
   el mando, con el brillo al mínimo).

En el menú principal, una línea de estado avisa si el servidor está apagado, sin
transmitir o transmitiendo a otra IP.

### Controles

| Mando | Envía |
|---|---|
| A B X Y, L1 R1, L3 R3, SELECT, START | igual que en la Deck |
| Gatillos L2/R2 | analógicos (más un "click" digital al pasar de 30 %) |
| Cruceta | cruceta (HAT o teclas) |
| Botón Guía/Home | botón PS (`STEAM`) |
| SELECT + R1 (configurable) | botón PS, como en la Deck y la Ally |

- **Salir del streaming:** L1 + R1 + SELECT + START a la vez (o Atrás del sistema).
- **Tocar la pantalla** durante el streaming muestra/oculta las estadísticas
  (paquetes/s, cuadros dentro/fuera/tirados, errores del decodificador, Hz del
  mando, botones y sticks en vivo). Es lo primero que hay que mirar si algo falla.
- Los menús se navegan con el mando: cruceta/stick para mover el foco, A para
  activar, B para volver.

### Ajustes del cliente

IP y puerto del ESP32, puerto de video (5000), ajuste de imagen (barras
negras / estirar / llenar recortando), frecuencia del mando (60–250 Hz), acorde
del botón PS, zona muerta de los sticks y segundos sin video antes de cerrar.

## Compilar

Hace falta el JDK que trae Android Studio, el SDK de Android (API 35) y Gradle 8.13
(el proyecto no incluye el *wrapper*). Desde `android-client/`:

```sh
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"
gradle testDebugUnitTest   # 18 pruebas: demultiplexor y estado del mando
gradle assembleDebug       # -> app/build/outputs/apk/debug/app-debug.apk
```

También se puede abrir la carpeta `android-client/` con Android Studio y darle Run.

Instalar en la tableta (depuración USB o inalámbrica activada):

```sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Si no hay imagen

1. Toca la pantalla y mira las estadísticas: `red` debe mostrar paquetes/s. Si
   está en 0, el servidor no está mandando a esta IP → **Configurar servidor → Aplicar**.
2. Con paquetes pero `video 0 fps`: revisa `ts video pid` (debe ser 256) y
   `err` / `ultimo error` del decodificador.
3. Sin audio pero con imagen: las estadísticas dicen `audio NO disponible` si el
   decodificador Opus del sistema falló al iniciar.
4. Mando sin efecto: en las estadísticas los `botones`/`sticks` deben moverse al
   tocar el mando; si no, el mando no está en modo Android/Xbox. Si se mueven pero
   la consola no responde, mira `mando ... enviados` y la IP del ESP32.

## Estructura

| Archivo | Qué hace |
|---|---|
| `TsDemuxer.kt` | Demultiplexor MPEG-TS (PAT/PMT, PES de video de longitud 0, Opus) |
| `VideoPlayer.kt` / `AudioPlayer.kt` | `MediaCodec` H.264 → `Surface`; Opus → `AudioTrack` de baja latencia |
| `StreamReceiver.kt` | Socket UDP de recepción |
| `GamepadInput.kt` / `GamepadState.kt` | Eventos de Android → estado del mando y su JSON |
| `InputSender.kt` | Manda el JSON al ESP32 a la frecuencia configurada |
| `Net.kt` | Cliente del protocolo UDP 9200 del servidor |
| `StreamActivity.kt` y las demás `*Activity.kt` | Pantallas |
