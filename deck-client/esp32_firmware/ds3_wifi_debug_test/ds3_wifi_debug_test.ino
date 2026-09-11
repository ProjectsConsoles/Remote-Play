// Sketch de diagnostico (2026-08-27): igual que ds3_no_wifi_test.ino (fix de
// clase de dispositivo 0x00/0x00/0x00, feature report 0xF4 declarado, toque
// de PS + toggle de D-pad derecha para confirmar reconocimiento visual en la
// XMB) pero CON el log remoto por WiFi de vuelta (como en ds3_controller.ino)
// para poder ver GET_DESCRIPTOR/GET_FEATURE/SET_FEATURE en tiempo real desde
// la Deck via `socat -u UDP-RECV:9001 -`, ya que el Monitor Serie por USB no
// esta dando señal en esta placa (sin diagnosticar por que, ver conversacion).
// Si el PS3 vuelve a rechazarlo ("USB desconocido") con este sketch, confirma
// que el WiFi activo durante la enumeracion sigue siendo un problema real
// incluso con el fix de clase ya puesto, y hay que resolver eso antes de
// seguir. Si NO lo rechaza, tenemos logs Y podemos confirmar si se mueve el
// D-pad en la misma corrida.

#include "USB.h"
#include "USBHID.h"
#include <WiFi.h>
#include <WiFiUdp.h>
#include <stdarg.h>

const char *WIFI_SSID = "TU_RED_WIFI_2.4GHZ";
const char *WIFI_PASSWORD = "TU_CONTRASENA_WIFI";

const uint16_t DEBUG_LOG_PORT = 9001;
WiFiUDP debugUdp;
IPAddress debugBroadcastIP;

// Todo lo que pasa ANTES de que el WiFi conecte (arranca recien a los 4s, ver
// loop()) se perdia: Serial no funciona en esta placa (sin diagnosticar por
// que) y el UDP se salteaba por no tener WiFi todavia. Como GET_DESCRIPTOR/
// GET_FEATURE del PS3 pasan en el primer segundo o dos tras conectar - mucho
// antes de que el WiFi termine de asociarse - se acumulan en este buffer y se
// mandan todos juntos en un solo paquete apenas conecta el WiFi.
char earlyLogBuf[1400] = "";
size_t earlyLogLen = 0;
bool wifiEverConnected = false;

void debugLog(const char *fmt, ...) {
  char buf[256];
  va_list args;
  va_start(args, fmt);
  vsnprintf(buf, sizeof(buf), fmt, args);
  va_end(args);
  Serial.print(buf);
  if (WiFi.status() == WL_CONNECTED) {
    debugUdp.beginPacket(debugBroadcastIP, DEBUG_LOG_PORT);
    debugUdp.print(buf);
    debugUdp.endPacket();
  } else if (!wifiEverConnected) {
    size_t n = strlen(buf);
    if (earlyLogLen + n < sizeof(earlyLogBuf) - 1) {
      memcpy(earlyLogBuf + earlyLogLen, buf, n);
      earlyLogLen += n;
      earlyLogBuf[earlyLogLen] = '\0';
    }
  }
}

void flushEarlyLog() {
  wifiEverConnected = true;
  if (earlyLogLen > 0) {
    debugUdp.beginPacket(debugBroadcastIP, DEBUG_LOG_PORT);
    debugUdp.print("--- log de antes de conectar WiFi ---\n");
    debugUdp.print(earlyLogBuf);
    debugUdp.print("--- fin log temprano ---\n");
    debugUdp.endPacket();
  }
}

#define RGB_LED_PIN 48

static const uint8_t DS3_REPORT_DESCRIPTOR[] = {
  0x05,
  0x01,
  0x09,
  0x04,
  0xA1,
  0x01,
  0xA1,
  0x02,
  0x85,
  0x01,
  0x75,
  0x08,
  0x95,
  0x01,
  0x15,
  0x00,
  0x26,
  0xFF,
  0x00,
  0x81,
  0x03,
  0x75,
  0x01,
  0x95,
  0x13,
  0x15,
  0x00,
  0x25,
  0x01,
  0x35,
  0x00,
  0x45,
  0x01,
  0x05,
  0x09,
  0x19,
  0x01,
  0x29,
  0x13,
  0x81,
  0x02,
  0x75,
  0x01,
  0x95,
  0x0D,
  0x06,
  0x00,
  0xFF,
  0x81,
  0x03,
  0x15,
  0x00,
  0x26,
  0xFF,
  0x00,
  0x05,
  0x01,
  0x09,
  0x01,
  0xA1,
  0x00,
  0x75,
  0x08,
  0x95,
  0x04,
  0x35,
  0x00,
  0x46,
  0xFF,
  0x00,
  0x09,
  0x30,
  0x09,
  0x31,
  0x09,
  0x32,
  0x09,
  0x35,
  0x81,
  0x02,
  0xC0,
  0x05,
  0x01,
  0x75,
  0x08,
  0x95,
  0x27,
  0x09,
  0x01,
  0x81,
  0x02,
  0x75,
  0x08,
  0x95,
  0x30,
  0x09,
  0x01,
  0x91,
  0x02,
  0x75,
  0x08,
  0x95,
  0x30,
  0x09,
  0x01,
  0xB1,
  0x02,
  0xC0,
  0xA1,
  0x02,
  0x85,
  0x02,
  0x75,
  0x08,
  0x95,
  0x30,
  0x09,
  0x01,
  0xB1,
  0x02,
  0xC0,
  0xA1,
  0x02,
  0x85,
  0xEE,
  0x75,
  0x08,
  0x95,
  0x30,
  0x09,
  0x01,
  0xB1,
  0x02,
  0xC0,
  0xA1,
  0x02,
  0x85,
  0xEF,
  0x75,
  0x08,
  0x95,
  0x30,
  0x09,
  0x01,
  0xB1,
  0x02,
  0xC0,
  // (2026-08-28) Re-agregados: bloque Feature report 0xF2 (16 bytes body,
  // MAC/info del Sixaxis) y 0xF4 (4 bytes body, el "paquete magico"
  // SET_FEATURE {0x42,0x0c,0x00,0x00} que activa el modo operacional de un
  // DS3 real). Se habian sacado el 2026-08-27 por la hipotesis (ya
  // descartada: se confirmo con USB.onEvent()/ARDUINO_USB_STARTED_EVENT que
  // el PS3 SI completa SET_CONFIGURATION sin importar si estos bloques
  // estan o no) de que el tamaño/estructura del descriptor le hacia
  // descartar el dispositivo antes de tiempo. El wrapper USBHID de
  // arduino-esp32 solo rutea GET_FEATURE/SET_FEATURE a _onGetFeature/
  // _onSetFeature para report IDs DECLARADOS aca (a diferencia del hardware
  // real, que responde a cualquier control transfer sin esa restriccion) -
  // si el PS3 manda SET_FEATURE(0xF4) como primer paso tras montar el USB y
  // el ID no esta declarado, TinyUSB lo descarta ANTES de llegar a nuestro
  // callback, sin dejar rastro en el log - encaja exactamente con "nada en
  // el log, nada en pantalla del PS3, ni error".
  0xA1,
  0x02,
  0x85,
  0xF2,
  0x75,
  0x08,
  0x95,
  0x10,
  0x09,
  0x01,
  0xB1,
  0x02,
  0xC0,
  0xA1,
  0x02,
  0x85,
  0xF4,
  0x75,
  0x08,
  0x95,
  0x04,
  0x09,
  0x01,
  0xB1,
  0x02,
  0xC0,
  // (2026-08-28) Se agregan tambien F1/F5/F7/F8 - el wrapper USBHID de
  // arduino-esp32 (tinyusb_get_device_by_report_id() en USBHID.cpp) descarta
  // CUALQUIER GET_REPORT/SET_REPORT para un report_id no declarado aca ANTES
  // de que llegue a nuestro _onGetFeature/_onSetFeature (via debugLog/UDP) -
  // el unico rastro que deja es un log_d() interno que solo sale por Serial
  // en modo debug (invisible en esta placa, Serial no funciona). Es decir:
  // el PS3 podria estar pidiendo alguno de estos SIN que lo hayamos visto
  // hasta ahora. Se declaran igual que 0x02/0xEE/0xEF (48 bytes body) para
  // que cualquier intento quede visible en el log remoto.
  0xA1,
  0x02,
  0x85,
  0xF1,
  0x75,
  0x08,
  0x95,
  0x30,
  0x09,
  0x01,
  0xB1,
  0x02,
  0xC0,
  0xA1,
  0x02,
  0x85,
  0xF5,
  0x75,
  0x08,
  0x95,
  0x30,
  0x09,
  0x01,
  0xB1,
  0x02,
  0xC0,
  0xA1,
  0x02,
  0x85,
  0xF7,
  0x75,
  0x08,
  0x95,
  0x30,
  0x09,
  0x01,
  0xB1,
  0x02,
  0xC0,
  0xA1,
  0x02,
  0x85,
  0xF8,
  0x75,
  0x08,
  0x95,
  0x30,
  0x09,
  0x01,
  0xB1,
  0x02,
  0xC0,
  0xC0,
};
// NOTA (2026-08-27, historica): se sacaron los bloques de feature report 0xF2 y 0xF4 que
// tenia esta copia (agregados antes para que el driver hid-sony de Linux
// reclamara el input) - eso hizo crecer el descriptor de ~135 a 161 bytes.
// El PS3 real NUNCA pidio GET_DESCRIPTOR (HID Report) en ningun intento hasta
// ahora, con o sin esos bloques - hipotesis: el PS3 podria estar descartando
// el dispositivo por el largo/estructura del descriptor antes de pedirlo, y
// 135 bytes es el tamaño original de droidshock3 (documentado como probado
// contra PS3 real en ese proyecto). Este archivo ya no va a enumerar bien en
// Linux (hid-sony va a fallar con 0xf2 de nuevo) - no importa para esta
// prueba puntual contra el PS3.

// (2026-08-28) Saber si el PS3 completa la enumeracion USB ESTANDAR
// (GET_DESCRIPTOR device/config, SET_ADDRESS, SET_CONFIGURATION) -
// independiente de si despues pide o no el HID Report descriptor.
// _onGetDescriptor/_onGetFeature de USBHIDDevice solo se llaman para
// pedidos especificos de la clase HID; el evento ARDUINO_USB_STARTED_EVENT
// (via USB.onEvent(), que el core ya reenvia desde tud_mount_cb() interno -
// no se puede redefinir tud_mount_cb() aca, el core ya lo define) SOLO se
// dispara tras SET_CONFIGURATION exitoso, asi que confirma si el PS3 llega
// a esa etapa o se queda antes (fallo mas temprano/electrico) - distingue
// las dos hipotesis en juego. IMPORTANTE: el handler de onEvent() corre en
// una tarea con poco stack (ARDUINO_USB_EVENT_TASK_STACK_SIZE) - llamar a
// debugLog() (WiFiUDP/Serial) directo desde ahi ya reseteo el chip antes
// (ver ds3_controller.ino). Solo se marca un flag volatile aca; loop() lo
// lee y logea desde un contexto seguro.
volatile bool tusbStartedEvent = false;
volatile bool tusbStoppedEvent = false;
volatile bool tusbSuspendEvent = false;
volatile bool tusbResumeEvent = false;

void onUsbEvent(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data) {
  (void)arg;
  (void)event_base;
  (void)event_data;
  switch (event_id) {
    case ARDUINO_USB_STARTED_EVENT: tusbStartedEvent = true; break;
    case ARDUINO_USB_STOPPED_EVENT: tusbStoppedEvent = true; break;
    case ARDUINO_USB_SUSPEND_EVENT: tusbSuspendEvent = true; break;
    case ARDUINO_USB_RESUME_EVENT:  tusbResumeEvent = true; break;
    default: break;
  }
}

class DS3Controller : public USBHIDDevice {
public:
  DS3Controller()
    : hid() {
    static bool initialized = false;
    if (!initialized) {
      initialized = true;
      hid.addDevice(this, sizeof(DS3_REPORT_DESCRIPTOR));
    }
  }

  void begin() {
    hid.begin();
  }

  uint16_t _onGetDescriptor(uint8_t *dst) override {
    debugLog("GET_DESCRIPTOR (HID Report), %u bytes\n", (unsigned)sizeof(DS3_REPORT_DESCRIPTOR));
    memcpy(dst, DS3_REPORT_DESCRIPTOR, sizeof(DS3_REPORT_DESCRIPTOR));
    return sizeof(DS3_REPORT_DESCRIPTOR);
  }

  uint16_t _onGetFeature(uint8_t report_id, uint8_t *buffer, uint16_t len) override {
    debugLog("GET_FEATURE id=0x%02X len=%u\n", report_id, len);
    if (report_id == 0x01 || report_id == 0x02 || report_id == 0xEE || report_id == 0xEF
        || report_id == 0xF1 || report_id == 0xF4 || report_id == 0xF5 || report_id == 0xF7 || report_id == 0xF8) {
      uint16_t n = (len < 48) ? len : 48;
      memset(buffer, 0, n);
      return n;
    }
    if (report_id == 0xF2) {
      uint16_t n = (len < 16) ? len : 16;
      memset(buffer, 0, n);
      if (n > 8) {
        static const uint8_t mac[6] = { 0x00, 0x19, 0xC5, 0x12, 0x34, 0x56 };
        memcpy(&buffer[3], mac, 6);
      }
      return n;
    }
    return 0;
  }

  void _onSetFeature(uint8_t report_id, const uint8_t *buffer, uint16_t len) override {
    debugLog("SET_FEATURE id=0x%02X len=%u\n", report_id, len);
  }

  void _onOutput(uint8_t report_id, const uint8_t *buffer, uint16_t len) override {
    debugLog("OUTPUT id=0x%02X len=%u\n", report_id, len);
  }

  bool sendInputReport(const uint8_t *data48) {
    // (2026-08-28) Diagnostico: todos los sendInputReport() estaban
    // fallando (100% failed en el heartbeat), sin saber si era por
    // hid.ready()==false (endpoint nunca listo) o porque SendReport() en si
    // fallaba con el endpoint ya listo. Se loguea el estado de ready()
    // aparte, throttled a 1/seg para no inundar el log (esto se llama cada
    // 8ms).
    static unsigned long lastReadyLog = 0;
    bool wasReady = hid.ready();
    unsigned long nowMs = millis();
    if (nowMs - lastReadyLog >= 1000) {
      lastReadyLog = nowMs;
      debugLog("[hid] ready=%d\n", (int)wasReady);
    }
    return hid.SendReport(0x01, data48, 48);
  }

protected:
  USBHID hid;
};

DS3Controller ds3;

void setup() {
  Serial.begin(115200);
  neopixelWrite(RGB_LED_PIN, 32, 0, 0);

  // CAMBIO (2026-08-27): USB primero, WiFi recien despues de que loop() ya
  // este corriendo unos segundos - al reves del orden usado en
  // ds3_controller.ino. Con WiFi activo DURANTE la enumeracion el PS3 real
  // rechaza el dispositivo (confirmado 3 veces seguidas); la hipotesis ahora
  // es que alcanza con que WiFi/lwIP no este corriendo durante los primeros
  // segundos criticos de enumeracion, no que nunca se prenda. IMPORTANTE: acá
  // NO se bloquea con delay()/while() esperando WiFi como en la version
  // anterior de este mismo sketch - eso dejaba de mandar Input reports
  // durante 4-19s justo despues de USB.begin(), lo cual podia ser otro motivo
  // de rechazo aparte del WiFi. WiFi.begin() se dispara de forma no
  // bloqueante desde loop() (ver abajo), para que sendInputReport() no pare
  // nunca desde el primer ciclo.
  USB.VID(0x054C);
  USB.PID(0x0268);
  USB.manufacturerName("Sony");
  USB.productName("PLAYSTATION(R)3 Controller");
  // El DS3 real no tiene string de serie (iSerial=0), pero el core
  // arduino-esp32 hardcodea iSerialNumber=3 en el device descriptor sin
  // condicion (esp32-hal-tinyusb.c:227) y ademas trata un string vacio como
  // "usa el fallback de MAC del chip" (esp32-hal-tinyusb.c:766-769), que
  // seria AUN mas distinto del real. No se puede igualar esto sin parchear
  // el core instalado (fuera de este repo) - se deja un string corto fijo
  // en vez de MAC o del "SN00000000" original, mejor esfuerzo posible via API publica.
  USB.serialNumber("0");
  USB.usbClass(0x00);
  USB.usbSubClass(0x00);
  USB.usbProtocol(0x00);
  USB.usbAttributes(0x80);
  USB.onEvent(onUsbEvent);

  ds3.begin();
  USB.begin();
}

unsigned long lastSend = 0;
unsigned long lastHeartbeat = 0;
bool wifiStarted = false;
bool wifiWasConnected = false;
bool dpadLeftWasHeld = false;
unsigned long inputReportsSent = 0;
unsigned long inputReportsFailed = 0;

void loop() {
  static unsigned long bootDoneAt = 0;
  if (bootDoneAt == 0) {
    bootDoneAt = millis();
  }
  unsigned long now = millis() - bootDoneAt;

  // WiFi se dispara recien a los 4s, sin bloquear el resto de loop() -
  // sendInputReport() sigue corriendo cada 8ms desde el primer ciclo.
  if (!wifiStarted && now >= 4000) {
    wifiStarted = true;
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
  if (wifiStarted && !wifiWasConnected && WiFi.status() == WL_CONNECTED) {
    wifiWasConnected = true;
    neopixelWrite(RGB_LED_PIN, 0, 32, 0);
    IPAddress localIP = WiFi.localIP();
    debugBroadcastIP = IPAddress(localIP[0], localIP[1], localIP[2], 255);
    flushEarlyLog();
    debugLog("WiFi OK (arrancado despues del USB), IP %s, broadcast %s:%u\n",
             localIP.toString().c_str(), debugBroadcastIP.toString().c_str(), DEBUG_LOG_PORT);
  }

  if (tusbStartedEvent) {
    tusbStartedEvent = false;
    debugLog("[TUSB] STARTED (SET_CONFIGURATION exitoso - USB llego a MOUNTED)\n");
  }
  if (tusbStoppedEvent) {
    tusbStoppedEvent = false;
    debugLog("[TUSB] STOPPED (unmount)\n");
  }
  if (tusbSuspendEvent) {
    tusbSuspendEvent = false;
    debugLog("[TUSB] SUSPEND\n");
  }
  if (tusbResumeEvent) {
    tusbResumeEvent = false;
    debugLog("[TUSB] RESUME\n");
  }

  // (2026-08-28) Antes solo se simulaba UN toque de PS (500ms) a los 3s de
  // arrancar - si el PS3 solo "escucha" el reporte de entrada en alguna
  // ventana que no coincidia con esa unica vez (por ejemplo, recien despues
  // de que el usuario interactue con la XMB, o en un intervalo periodico),
  // nunca lo hubieramos visto. Ahora se repite: 1s presionado, 3s soltado,
  // en loop indefinido durante toda la conexion - le da al PS3 muchas
  // oportunidades de "notar" el boton sin importar en que momento este
  // escuchando.
  unsigned long psPhase = now % 4000;
  bool psPressed = (now >= 3000) && (psPhase < 1000);

  // (2026-08-28) Pedido del usuario: mientras dura el toque de PS simulado,
  // sostener tambien dpad IZQUIERDA (bit 7 de report[1] + presion analogica
  // en report[17], segun el mapeo DS3Bit/DS3_PRESSURE_OFFSET documentado en
  // ds3_controller.ino - DS3_LEFT=indice 7 del bitfield que arranca en
  // report[1]) y prender el LED en azul mientras se sostiene, volviendo al
  // color anterior (verde si ya hay WiFi, rojo si no) al soltar. Sirve como
  // señal visual independiente de nuestro log: si el PS3 SI esta leyendo el
  // input report, deberia verse la flecha izquierda reaccionar en pantalla
  // exactamente cuando el LED esta en azul.
  bool dpadLeftHeld = psPressed;
  if (dpadLeftHeld && !dpadLeftWasHeld) {
    neopixelWrite(RGB_LED_PIN, 0, 0, 32);
  } else if (!dpadLeftHeld && dpadLeftWasHeld) {
    if (wifiWasConnected) {
      neopixelWrite(RGB_LED_PIN, 0, 32, 0);
    } else {
      neopixelWrite(RGB_LED_PIN, 32, 0, 0);
    }
  }
  dpadLeftWasHeld = dpadLeftHeld;

  // (2026-08-28) DIAGNOSTICO TEMPORAL: bajado de 8ms a 1000ms para descartar
  // que el problema sea saturar el endpoint mandando muy rapido desde el
  // arranque - USBHIDMouse (que SI funciona, confirmado) manda 1 vez por
  // segundo. Revertir a 8 una vez descartado/confirmado.
  if (now - lastSend >= 1000) {
    lastSend = now;
    uint8_t report[48] = { 0 };
    report[5] = report[6] = report[7] = report[8] = 128;
    if (psPressed) {
      report[3] |= (1 << 0);
    }
    if (dpadLeftHeld) {
      report[1] |= (1 << 7);
      report[17] = 255;
    }
    inputReportsSent++;
    if (!ds3.sendInputReport(report)) {
      inputReportsFailed++;
    }
  }

  if (now - lastHeartbeat >= 2000) {
    lastHeartbeat = now;
    debugLog(
      "[heartbeat] wifi=%d input_reports sent=%lu failed=%lu\n", WiFi.status(), inputReportsSent, inputReportsFailed
    );
  }
}
