// Firmware ESP32-S3: emula un DualShock 3 por USB cableado y recibe el
// estado del control de la Steam Deck por UDP (mismo formato que ya manda
// input_client_v3.py del lado Deck, sin tocar ese script).
//
// Requisitos en el IDE antes de subir:
//  - Herramientas > Board: "ESP32S3 Dev Module"
//  - Herramientas > USB Mode: "USB-OTG (TinyUSB)"
//  - Libreria "ArduinoJson" (Benoit Blanchon, v7.x) instalada via Gestor de Librerias
//  - Conectar por el puerto USB NATIVO de la placa (no el de programacion/COM)
//  - Truco para subir: mantener BOOT, tocar RESET, soltar RESET, soltar BOOT,
//    recien ahi Subir (el auto-reset no entra solo por USB nativo en esta placa)
//
// ESTADO (2026-08-28): reconstruido desde cero sobre el esqueleto de
// `ds3_raw_tinyusb_udp_test.ino` (CONFIRMADO funcionando de punta a punta:
// WiFi conectado + UDP real + JSON + tud_hid_report() entregando datos
// reales en jstest) en vez de partir de una version anterior de este mismo
// archivo que, pese a usar la misma API de TinyUSB directa (sin USBHID/
// USBHIDDevice), dejaba de mandar datos con el mapeo COMPLETO de botones/
// ejes - la causa exacta de esa diferencia quedo sin identificar (se
// descartaron por separado, cada uno sin problema: WiFi solo, UDP+JSON con
// un campo, debugLog() dentro de los callbacks TinyUSB, e incluso
// debugLog() completamente deshabilitado - ninguno por separado reproducia
// la falla, pero la version vieja de este archivo con TODOS esos elementos
// juntos + el mapeo completo de 21 campos JSON + buildInputReport() de 17
// botones SI fallaba). Ante la duda, se prefirio reconstruir sobre la base
// confirmada en vez de seguir restando piezas a la version rota.
//
// IMPORTANTE: NO agregar "#include <USBHID.h>" a este archivo - eso
// compilaria y linkearia USBHID.cpp, que define tud_hid_descriptor_report_cb/
// tud_hid_get_report_cb/tud_hid_set_report_cb como simbolos fuertes (no
// weak) y chocaria con las versiones de aca abajo. Ver memoria del proyecto
// para el detalle completo de por que se abandono USBHID/USBHIDDevice.

#include "USB.h"
#include "esp32-hal-tinyusb.h"
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoJson.h>
#include <stdarg.h>
#include <Preferences.h>
// Header privado de TinyUSB: hace falta para registrar un driver de clase
// propio (XID del Xbox clasico, ver el bloque "MODO XBOX CLASICO" mas abajo).
#include "device/usbd_pvt.h"

// ---------------------------------------------------------------------------
// Configuracion de red - EDITAR antes de subir
// ---------------------------------------------------------------------------
const char *WIFI_SSID = "TU_RED_WIFI_2.4GHZ";  // el ESP32-S3-WROOM-1 solo tiene radio 2.4GHz
const char *WIFI_PASSWORD = "TU_CONTRASENA_WIFI";
const uint16_t UDP_PORT = 9000;  // debe coincidir con --port de input_client_v3.py

#define RGB_LED_PIN 48
#define BOOT_BUTTON_PIN 0  // el mismo boton BOOT de la placa, GPIO0 - solo se lee en RUNTIME, nunca al resetear (ver nota abajo)

// ---------------------------------------------------------------------------
// SELECTOR DE CONSOLA (2026-09-12): PS2/OPL necesita la clase USB de
// DEVICE en 0xE0 (ver nota grande junto a USB.usbClass mas abajo), pero
// PS3 y Xbox 360 (con hiddriver360) necesitan la clase generica 0x00 - ya
// no hay un solo ajuste que sirva para las tres consolas. Se elige con el
// boton BOOT (GPIO0, el mismo que ya existe en la placa para entrar al
// bootloader - NO se agrega hardware nuevo) y queda guardado en flash.
//
// GESTO: mantener BOOT presionado ~1.5s EN CUALQUIER MOMENTO mientras el
// firmware ya esta corriendo (nunca al encender/resetear - GPIO0 es un pin
// de strapping, si esta en LOW justo en ese instante el chip entra al
// bootloader de fabrica en vez de correr este programa). Al pasar el 1.5s
// el LED empieza a ciclar de color cada ~700ms; se suelta el boton en el
// color deseado para confirmar, y la placa se reinicia sola para aplicar
// el modo nuevo limpio (USB.begin() no se puede reconfigurar sin reiniciar).
// ---------------------------------------------------------------------------
// MODO_XBOX_CLASICO (2026-09-19): el Xbox ORIGINAL (2001) no habla HID sino XID
// (clase USB 0x58), asi que su modo arma otros descriptores y otro driver USB.
enum ModoConsola : uint8_t { MODO_PS3 = 0, MODO_PS2 = 1, MODO_XBOX360 = 2, MODO_XBOX_CLASICO = 3 };
const uint8_t NUM_MODOS = 4;

// Reporte de entrada XID (Xbox clasico), definido aca arriba a proposito: ver el
// bloque "MODO XBOX CLASICO" mas abajo.
struct __attribute__((packed)) XidInReport {
  uint8_t reportId;      // 0
  uint8_t length;        // 0x14
  uint16_t buttons;      // bits: up1 down2 left4 right8 start10 back20 L3 40 R3 80
  uint8_t analog[8];     // A B X Y Black White LT RT (0-255)
  int16_t lx, ly, rx, ry;
};
static_assert(sizeof(XidInReport) == 20, "el reporte XID debe medir 20 bytes");
Preferences prefsModo;
ModoConsola modoActual = MODO_PS3;

const char *nombreModo(ModoConsola m) {
  switch (m) {
    case MODO_PS2:     return "PS2/OPL";
    case MODO_XBOX360: return "Xbox360";
    case MODO_XBOX_CLASICO: return "XboxClasico";
    default:           return "PS3";
  }
}

// Mismo brillo (32) que ya usaba el LED de wifi-conectado, solo cambia el color.
void colorParaModo(ModoConsola m, uint8_t &r, uint8_t &g, uint8_t &b) {
  switch (m) {
    case MODO_PS2:     r = 0;  g = 0;  b = 32; break;  // azul
    case MODO_XBOX360: r = 20; g = 0;  b = 32; break;  // morado
    case MODO_XBOX_CLASICO: r = 0; g = 32; b = 0; break;  // verde
    default:           r = 32; g = 22; b = 0;  break;  // amarillo (PS3)
  }
}

void cargarModoGuardado() {
  prefsModo.begin("ds3cfg", true);
  uint8_t guardado = prefsModo.getUChar("modo", MODO_PS3);
  // Un valor fuera de rango (flash vieja o corrupta) cae al modo de siempre.
  modoActual = (guardado < NUM_MODOS) ? (ModoConsola)guardado : MODO_PS3;
  prefsModo.end();
}

void guardarModo(ModoConsola m) {
  prefsModo.begin("ds3cfg", false);
  prefsModo.putUChar("modo", (uint8_t)m);
  prefsModo.end();
}

// Se llama desde loop() en cada vuelta. Solo actua si el boton BOOT (GPIO0)
// se mantiene presionado - en uso normal (boton suelto) es una lectura de
// pin y nada mas, no le cuesta nada al ritmo del loop.
void revisarSelectorModo() {
  static unsigned long presionadoDesde = 0;
  static bool enSeleccion = false;
  static ModoConsola candidato = MODO_PS3;
  static unsigned long ultimoCambio = 0;

  bool presionado = (digitalRead(BOOT_BUTTON_PIN) == LOW);

  if (!enSeleccion) {
    if (presionado) {
      if (presionadoDesde == 0) presionadoDesde = millis();
      if (millis() - presionadoDesde > 1500) {
        enSeleccion = true;
        candidato = modoActual;
        ultimoCambio = millis();
        uint8_t r, g, b;
        colorParaModo(candidato, r, g, b);
        neopixelWrite(RGB_LED_PIN, r, g, b);
        debugLog("[modo] entrando a seleccion, empieza en %s\n", nombreModo(candidato));
      }
    } else {
      presionadoDesde = 0;
    }
    return;
  }

  if (presionado) {
    if (millis() - ultimoCambio > 700) {
      candidato = (ModoConsola)((candidato + 1) % NUM_MODOS);
      ultimoCambio = millis();
      uint8_t r, g, b;
      colorParaModo(candidato, r, g, b);
      neopixelWrite(RGB_LED_PIN, r, g, b);
      debugLog("[modo] candidato=%s\n", nombreModo(candidato));
    }
  } else {
    modoActual = candidato;
    guardarModo(modoActual);
    debugLog("[modo] guardado modo=%s, reiniciando para aplicarlo\n", nombreModo(modoActual));
    delay(300);
    ESP.restart();
  }
}

// ---------------------------------------------------------------------------
// Descriptor HID del DualShock 3 - EXACTO al de un DS3 real (148 bytes),
// dump obtenido con ioctl(HIDIOCGRDESC) de un DS3 fisico (2026-08-28).
// ---------------------------------------------------------------------------
// Log remoto por WiFi (broadcast UDP al puerto 9001). El Monitor Serie por USB
// esta roto en esta placa (ver notas del proyecto), asi que esta es la unica
// via de telemetria cuando el ESP32 esta conectado al PS3 y lejos de la Deck.
// Verlo desde la Deck con:  socat -u UDP-RECV:9001 -
const uint16_t DEBUG_LOG_PORT = 9001;
WiFiUDP debugUdp;
IPAddress debugBroadcastIP;

void debugLog(const char *fmt, ...) {
  char buf[256];
  int prefixLen = snprintf(buf, sizeof(buf), "[%8lu] ", millis());
  va_list args;
  va_start(args, fmt);
  vsnprintf(buf + prefixLen, sizeof(buf) - prefixLen, fmt, args);
  va_end(args);
  Serial.print(buf);
  if (WiFi.status() == WL_CONNECTED) {
    debugUdp.beginPacket(debugBroadcastIP, DEBUG_LOG_PORT);
    debugUdp.print(buf);
    debugUdp.endPacket();
  }
}

static const uint8_t DS3_REPORT_DESCRIPTOR[] = {
  0x05, 0x01, 0x09, 0x04, 0xA1, 0x01, 0xA1, 0x02, 0x85, 0x01, 0x75, 0x08, 0x95, 0x01, 0x15, 0x00, 0x26, 0xFF, 0x00,
  0x81, 0x03, 0x75, 0x01, 0x95, 0x13, 0x15, 0x00, 0x25, 0x01, 0x35, 0x00, 0x45, 0x01, 0x05, 0x09, 0x19, 0x01, 0x29,
  0x13, 0x81, 0x02, 0x75, 0x01, 0x95, 0x0D, 0x06, 0x00, 0xFF, 0x81, 0x03, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x05, 0x01,
  0x09, 0x01, 0xA1, 0x00, 0x75, 0x08, 0x95, 0x04, 0x35, 0x00, 0x46, 0xFF, 0x00, 0x09, 0x30, 0x09, 0x31, 0x09, 0x32,
  0x09, 0x35, 0x81, 0x02, 0xC0, 0x05, 0x01, 0x75, 0x08, 0x95, 0x27, 0x09, 0x01, 0x81, 0x02, 0x75, 0x08, 0x95, 0x30,
  0x09, 0x01, 0x91, 0x02, 0x75, 0x08, 0x95, 0x30, 0x09, 0x01, 0xB1, 0x02, 0xC0, 0xA1, 0x02, 0x85, 0x02, 0x75, 0x08,
  0x95, 0x30, 0x09, 0x01, 0xB1, 0x02, 0xC0, 0xA1, 0x02, 0x85, 0xEE, 0x75, 0x08, 0x95, 0x30, 0x09, 0x01, 0xB1, 0x02,
  0xC0, 0xA1, 0x02, 0x85, 0xEF, 0x75, 0x08, 0x95, 0x30, 0x09, 0x01, 0xB1, 0x02, 0xC0,
  0xC0,
};

static uint8_t ds3_itf_num = 0xFF;

extern "C" uint16_t ds3_hid_load_descriptor(uint8_t *dst, uint8_t *itf) {
  uint8_t str_index = tinyusb_add_string_descriptor("PLAYSTATION(R)3 Controller");
  uint8_t ep_in = tinyusb_get_free_in_endpoint();
  uint8_t ep_out = tinyusb_get_free_out_endpoint();
  if (ep_in == 0 || ep_out == 0) {
    return 0;
  }
  uint8_t descriptor[TUD_HID_INOUT_DESC_LEN] = {
    TUD_HID_INOUT_DESCRIPTOR(*itf, str_index, HID_ITF_PROTOCOL_NONE, sizeof(DS3_REPORT_DESCRIPTOR), ep_out, (uint8_t)(0x80 | ep_in), 64, 1)
  };
  ds3_itf_num = *itf;
  *itf += 1;
  memcpy(dst, descriptor, TUD_HID_INOUT_DESC_LEN);
  return TUD_HID_INOUT_DESC_LEN;
}

extern "C" const uint8_t *tud_hid_descriptor_report_cb(uint8_t instance) {
  (void)instance;
  debugLog("[usb] host pidio el REPORT DESCRIPTOR (instance=%d)\n", (int)instance);
  return DS3_REPORT_DESCRIPTOR;
}

// ---------------------------------------------------------------------------
// Ciclo de vida USB (2026-09-12): agregado para diagnosticar un host que deja
// tud_hid_ready()=0 para siempre sin que el dispositivo se entere de por que
// (medido contra una Xbox 360 con hiddriver360 - mismo sintoma de fondo que
// el menu de OPL nunca resuelto: se atasca con ciertos hosts, PS3/Windows
// nunca). Sin esto no habia forma de ver si el host hace enumeracion,
// suspende, o directamente nunca completa el mount.
// ---------------------------------------------------------------------------
extern "C" void tud_mount_cb(void) { debugLog("[usb] MOUNT (enumeracion completa)\n"); }
extern "C" void tud_umount_cb(void) { debugLog("[usb] UMOUNT (se desconecto/reseteo)\n"); }
extern "C" void tud_suspend_cb(bool remote_wakeup_en) {
  debugLog("[usb] SUSPEND remote_wakeup=%d\n", (int)remote_wakeup_en);
}
extern "C" void tud_resume_cb(void) { debugLog("[usb] RESUME\n"); }

// ---------------------------------------------------------------------------
// Respuestas REALES de un DualShock 3 fisico a cada feature report, dumpeadas
// con ioctl(HIDIOCGFEATURE) sobre /dev/hidrawN (ver
// esp32_firmware/reference/ds3_real_feature_reports.txt). Antes se devolvian
// puros ceros y el PS3 se plantaba justo despues de GET_FEATURE 0xF7 sin
// llegar nunca a hacer poll del endpoint de Input.
// El primer byte del dump (el report ID en el formato hidraw) se descarta:
// el buffer que llega a tud_hid_get_report_cb NO incluye el report ID.
// NOTA: 0xF2 lleva el MAC real de ESTE DS3 y 0xF5 el del PS3 con el que esta
// vinculado - por eso el ESP32 no deberia usarse a la vez que ese DS3 real.
static const uint8_t FEAT_01[] = {
  0x01, 0x04, 0x00, 0x06, 0x0C, 0x01, 0x02, 0x18, 0x18, 0x18, 0x18, 0x09,
  0x0A, 0x10, 0x11, 0x12, 0x13, 0x00, 0x00, 0x00, 0x00, 0x04, 0x00, 0x02,
  0x02, 0x02, 0x02, 0x00, 0x00, 0x00, 0x04, 0x04, 0x04, 0x04, 0x00, 0x00,
  0x03, 0x00, 0x01, 0x02, 0x00, 0x00, 0x17, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00,
};
static const uint8_t FEAT_02[] = {
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00,
};
static const uint8_t FEAT_EE[] = {
  0xEE, 0x02, 0x00, 0x06, 0xEE, 0x10, 0x00, 0x00, 0x00, 0x00, 0x12, 0x02,
  0xEF, 0x01, 0xF2, 0x00, 0x00, 0x02, 0x02, 0x02, 0x00, 0x03, 0x00, 0x00,
  0x02, 0x00, 0x00, 0x02, 0x62, 0x01, 0x02, 0x01, 0x5E, 0x00, 0x32, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00,
};
static const uint8_t FEAT_EF[] = {
  0xEF, 0x04, 0x00, 0x06, 0x03, 0x01, 0xB0, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x02, 0x72, 0x02, 0x71, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00,
};
static const uint8_t FEAT_F2[] = {
  0xFF, 0xFF, 0x00, 0x60, 0x38, 0x0E, 0x1E, 0x91, 0x21, 0x00, 0x03, 0x50,
  0x81, 0xD8, 0x01, 0x8A, 0x02, 0x72, 0x02, 0x71, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00,
};
static const uint8_t FEAT_F5[] = {
  0x00, 0xF8, 0x2F, 0xA8, 0x4E, 0x75, 0x75, 0x91, 0x21, 0x00, 0x03, 0x50,
  0x81, 0xD8, 0x01, 0x8A, 0x02, 0x72, 0x02, 0x71, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00,
};
static const uint8_t FEAT_F7[] = {
  0x00, 0xEF, 0x02, 0xF2, 0x01, 0xEE, 0xFF, 0x10, 0x12, 0x00, 0x03, 0x50,
  0x81, 0xD8, 0x01, 0x8A, 0x02, 0x72, 0x02, 0x71, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00,
};
static const uint8_t FEAT_F8[] = {
  0x01, 0x00, 0x00, 0xF2, 0x01, 0xEE, 0xFF, 0x10, 0x12, 0x00, 0x03, 0x50,
  0x81, 0xD8, 0x01, 0x8A, 0x02, 0x72, 0x02, 0x71, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00,
};

// firstByte = el byte 0 REAL que devuelve el DS3 fisico. TinyUSB antepone
// automaticamente el report ID en esa posicion (hid_device.c: report_buf[0] =
// report id, y a nuestro callback le pasa report_buf+1), pero el DS3 real
// pone ahi 0x00/0x01 segun el report - solo 0xF2 coincide con su propio id.
// Se corrige escribiendo buffer[-1] en el callback (ver nota ahi).
struct FeatEntry { uint8_t id; const uint8_t *data; uint16_t len; uint8_t firstByte; };
static const FeatEntry FEAT_TABLE[] = {
  { 0x01, FEAT_01, sizeof(FEAT_01), 0x00 },
  { 0x02, FEAT_02, sizeof(FEAT_02), 0x00 },
  { 0xEE, FEAT_EE, sizeof(FEAT_EE), 0x00 },
  { 0xEF, FEAT_EF, sizeof(FEAT_EF), 0x00 },
  { 0xF2, FEAT_F2, sizeof(FEAT_F2), 0xF2 },
  { 0xF5, FEAT_F5, sizeof(FEAT_F5), 0x01 },
  { 0xF7, FEAT_F7, sizeof(FEAT_F7), 0x01 },
  { 0xF8, FEAT_F8, sizeof(FEAT_F8), 0x00 },
};


// Eco de feature reports: el PS3 real hace SET_FEATURE (escribe config,
// ej. 0xEF/0xF5) y despues GET_FEATURE del MISMO id esperando leer de vuelta
// lo que el mismo escribio (no simplemente ceros) - se confirmo en el log
// que se traba justo ahi (SET 0xEF -> GET 0xEF x2 -> loop infinito de GET
// 0xEF) cuando antes devolviamos puros ceros. Guardamos lo ultimo escrito
// por report_id y lo devolvemos tal cual en el siguiente GET de ese id.
static uint8_t featureStore[256][64];
static uint16_t featureStoreLen[256];
static bool featureStoreValid[256];
// Byte 0 real de cada report (ver nota en FEAT_TABLE). 0xFF = usar el default
// de TinyUSB (el propio report ID), para ids que no dumpeamos del DS3 real.
static uint8_t featureFirstByte[256];

// Inicializa el store con los valores REALES del DS3 (FEAT_TABLE de arriba),
// para que el primer GET de cada id ya devuelva algo valido aunque el PS3 no
// haya hecho un SET previo. Un SET posterior lo pisa (comportamiento de eco).
static void initFeatureStoreFromRealDS3() {
  for (unsigned i = 0; i < sizeof(FEAT_TABLE) / sizeof(FEAT_TABLE[0]); i++) {
    uint8_t id = FEAT_TABLE[i].id;
    uint16_t n = FEAT_TABLE[i].len;
    if (n > 64) n = 64;
    memset(featureStore[id], 0, 64);
    memcpy(featureStore[id], FEAT_TABLE[i].data, n);
    // Siempre 64: el PS3 pide wLength=63 y hay que poder devolver ese largo
    // completo o se queda reintentando el mismo id en loop.
    featureStoreLen[id] = 64;
    featureStoreValid[id] = true;
    featureFirstByte[id] = FEAT_TABLE[i].firstByte;
  }
}

extern "C" uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type, uint8_t *buffer, uint16_t reqlen) {
  (void)instance;
  debugLog("GET_FEATURE id=0x%02X type=%d len=%u\n", report_id, (int)report_type, reqlen);

  if (featureStoreValid[report_id]) {
    // TinyUSB ya escribio el report ID en buffer[-1] (hid_device.c hace
    // report_buf[0] = report id y nos pasa report_buf+1). El DS3 real pone
    // otro valor ahi, asi que lo sobreescribimos para replicarlo byte a byte.
    // Seguro porque report_id != 0 garantiza que ese prefijo existe.
    if (report_id != 0) {
      buffer[-1] = featureFirstByte[report_id];
    }
    uint16_t n = (reqlen < featureStoreLen[report_id]) ? reqlen : featureStoreLen[report_id];
    memcpy(buffer, featureStore[report_id], n);
    return n;
  }

  uint16_t n = reqlen;
  memset(buffer, 0, n);
  return n;
}

// El PS3 manda su OUTPUT report (LEDs y vibracion) unas 50 veces por segundo.
// Logear cada uno era ~50 broadcasts UDP por segundo: el log quedaba ilegible y
// la radio transmitiendo sin parar. Los FEATURE (que son los de la enumeracion,
// los que de verdad importan para diagnosticar) se siguen logeando todos; de
// los OUTPUT solo se logean los primeros y despues se cuentan nomas, y la
// cuenta sale en el heartbeat.
unsigned long outputReports = 0;

extern "C" void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type, uint8_t const *buffer, uint16_t bufsize) {
  (void)instance;
  if (report_type == HID_REPORT_TYPE_OUTPUT || report_type == HID_REPORT_TYPE_INVALID) {
    outputReports++;
    if (outputReports <= 3) {
      debugLog("OUTPUT id=0x%02X type=%d len=%u (los siguientes solo se cuentan)\n",
               report_id, (int)report_type, bufsize);
    }
  } else {
    debugLog("SET_FEATURE id=0x%02X type=%d len=%u\n", report_id, (int)report_type, bufsize);
  }
  uint16_t n = (bufsize < 64) ? bufsize : 64;
  memcpy(featureStore[report_id], buffer, n);
  featureStoreLen[report_id] = n;
  featureStoreValid[report_id] = true;
}

// ---------------------------------------------------------------------------
// Mapeo de botones DS3 (identico al de las versiones anteriores)
// ---------------------------------------------------------------------------
enum DS3Bit {
  DS3_SELECT = 0,
  DS3_L3,
  DS3_R3,
  DS3_START,
  DS3_UP,
  DS3_RIGHT,
  DS3_DOWN,
  DS3_LEFT,
  DS3_L2,
  DS3_R2,
  DS3_L1,
  DS3_R1,
  DS3_TRIANGLE,
  DS3_CIRCLE,
  DS3_CROSS,
  DS3_SQUARE,
  DS3_PS
};

// Offsets de los 12 bytes de presion (botones analogicos del DS3) DENTRO del
// payload de 48 bytes, o sea SIN contar el Report ID: tud_hid_report(0x01, ...)
// lo antepone el mismo, asi que out48[0] es el byte de relleno que en la
// documentacion del DS3 (que cuenta el ID como byte 0) figura como byte 1.
// De ahi que todo el mapa quede corrido un lugar respecto de esa
// documentacion: botones en los bytes doc 2-4 = out48[1..3], sticks en doc 6-9
// = out48[5..8], y presiones en doc 14-25 = **out48[13..24]**.
//
// CORRECCION 2026-08-29: aca decia 14..25 (los numeros de la documentacion
// copiados tal cual, sin restar el ID) y por eso cada boton dejaba su presion
// en la casilla del SIGUIENTE. Sintoma exacto que llevo a encontrarlo: en el
// XMB todos los botones bien, pero dentro de un juego "volteados" - el XMB
// mira solo los bits digitales (out48[1..3], que si estaban bien) mientras que
// los juegos leen ademas la presion analogica. Con el corrimiento, la presion
// del CIRCULO caia en la casilla de la CRUZ (el circulo hacia lo de la cruz) y
// la de la CRUZ en la del CUADRADO (la cruz "no respondia"); L2 aterrizaba en
// R2. El orden de los 12 bytes es: Up, Right, Down, Left, L2, R2, L1, R1,
// Triangle, Circle, Cross, Square.
//
// Los ceros son los botones sin presion (SELECT, L3, R3, START y PS): no se
// escriben nunca en buildInputReport(), el 0 es solo relleno de la tabla.
static const uint8_t DS3_PRESSURE_OFFSET[17] = {
  0, 0, 0, 0,
  13, 14, 15, 16,
  17, 18, 19, 20,
  21, 22, 23, 24,
  0,
};

WiFiUDP udp;
char udpBuffer[1024];

struct ControllerState {
  bool cross = false, circle = false, square = false, triangle = false;
  bool l1 = false, r1 = false, l2_click = false, r2_click = false;
  bool select_ = false, start_ = false, l3 = false, r3 = false, ps = false;
  int8_t dpad_x = 0, dpad_y = 0;
  float lstick_x = 0, lstick_y = 0, rstick_x = 0, rstick_y = 0;
  float l2_analog = -1.0f, r2_analog = -1.0f;
} state;

// CAUSA RAIZ del bug historico "el mapeo completo nunca mandaba datos"
// (2026-08-28): input_client_v3.py serializa los botones como ENTEROS
// ("A": 1, porque pygame get_button() devuelve int), pero el operador `|` de
// ArduinoJson es ESTRICTO DE TIPO: `buttons["A"] | false` ve un int donde
// espera un bool, no coincide, y devuelve el default `false`. Resultado: el
// estado nunca cambiaba y buildInputReport() armaba siempre un reporte en
// cero - se enviaba bien por USB, pero sin datos, asi que ningun host veia
// nada. Este helper acepta bool, int o float indistintamente.
static bool jsonBool(JsonVariantConst v) {
  if (v.is<bool>()) return v.as<bool>();
  if (v.is<int>()) return v.as<int>() != 0;
  if (v.is<float>()) return v.as<float>() != 0.0f;
  return false;
}

unsigned long parseOk = 0;
unsigned long parseErr = 0;

// 2026-09-22: comando remoto para elegir el modo desde el menu de colores en vez de
// mantener BOOT en la placa. Paquete de un solo campo, {"set_modo": 0-3}, distinto del
// JSON de control (buttons/axes/dpad) que llega a 120Hz. Mismo mecanismo que el gesto de
// BOOT: guarda en flash y reinicia (el modo USB no se puede recargar sin reiniciar), asi
// que el control se desconecta de la consola ~1-2s, igual que si se desconectara el cable.
void aplicarModoRemoto(uint8_t nuevo) {
  if (nuevo >= NUM_MODOS) {
    debugLog("[modo] set_modo remoto fuera de rango: %u\n", (unsigned)nuevo);
    return;
  }
  modoActual = (ModoConsola)nuevo;
  guardarModo(modoActual);
  debugLog("[modo] set_modo remoto -> %s, reiniciando para aplicarlo\n", nombreModo(modoActual));
  delay(300);
  ESP.restart();
}

void updateStateFromJson(const uint8_t *data, size_t len) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, data, len);
  if (err) {
    parseErr++;
    if (parseErr <= 3) {
      debugLog("[json] ERROR de parseo: %s (len=%u)\n", err.c_str(), (unsigned)len);
    }
    return;
  }
  parseOk++;

  if (!doc["set_modo"].isNull()) {
    aplicarModoRemoto(doc["set_modo"].as<uint8_t>());
    return;  // ESP.restart() no vuelve; por las dudas, no seguir leyendo el resto como control
  }

  JsonObject buttons = doc["buttons"];
  state.cross = jsonBool(buttons["A"]);
  state.circle = jsonBool(buttons["B"]);
  state.square = jsonBool(buttons["X"]);
  state.triangle = jsonBool(buttons["Y"]);
  state.l1 = jsonBool(buttons["L1"]);
  state.r1 = jsonBool(buttons["R1"]);
  state.l2_click = jsonBool(buttons["L2_CLICK"]);
  state.r2_click = jsonBool(buttons["R2_CLICK"]);
  state.select_ = jsonBool(buttons["SELECT"]);
  state.start_ = jsonBool(buttons["START"]);
  state.l3 = jsonBool(buttons["L3_CLICK"]);
  state.r3 = jsonBool(buttons["R3_CLICK"]);
  state.ps = jsonBool(buttons["STEAM"]);

  JsonObject axes = doc["axes"];
  state.lstick_x = axes["LSTICK_X"] | 0.0f;
  state.lstick_y = axes["LSTICK_Y"] | 0.0f;
  state.rstick_x = axes["RSTICK_X"] | 0.0f;
  state.rstick_y = axes["RSTICK_Y"] | 0.0f;
  state.l2_analog = axes["L2_ANALOG"] | -1.0f;
  state.r2_analog = axes["R2_ANALOG"] | -1.0f;

  JsonObject dpad = doc["dpad"];
  state.dpad_x = dpad["x"] | 0;
  state.dpad_y = dpad["y"] | 0;

  // Traza puntual: avisa cuando el boton A (=Cross) realmente cambia de valor
  // tras el parseo, para separar "el JSON no se entiende" de "el JSON se
  // entiende pero el reporte no lo refleja".
  static bool lastCross = false;
  if (state.cross != lastCross) {
    lastCross = state.cross;
    debugLog("[json] state.cross -> %d\n", (int)state.cross);
  }
}

// Zona muerta de los sticks. La Deck tiene una deriva pequena pero constante
// en reposo (se midio LSTICK_X=-0.02 con el stick sin tocar) y el DS3 no
// aplica ninguna zona muerta propia, asi que ese desvio minimo alcanzaba para
// que el menu del PS3 se moviera solo hacia un lado. Solo aplica a los sticks
// (NO a los gatillos L2/R2, que descansan legitimamente en -1.0).
const float STICK_DEADZONE = 0.12f;

inline float applyDeadzone(float v) {
  if (v > -STICK_DEADZONE && v < STICK_DEADZONE) {
    return 0.0f;
  }
  // Reescalar el tramo restante a 0..1 para no perder recorrido util ni dar
  // un salto brusco justo al salir de la zona muerta.
  float sign = (v < 0) ? -1.0f : 1.0f;
  float mag = (v < 0) ? -v : v;
  return sign * ((mag - STICK_DEADZONE) / (1.0f - STICK_DEADZONE));
}

inline uint8_t axisToByte(float v) {
  // El +0.5f redondea en vez de truncar: sin el, v=0.0 daba 127 y el centro
  // exacto de un DS3 es 128 (medio paso corrido hacia el negativo en los 4
  // ejes). Los extremos siguen dando 0 y 255 gracias al clamp de abajo.
  int val = (int)((v + 1.0f) * 127.5f + 0.5f);
  if (val < 0) {
    val = 0;
  }
  if (val > 255) {
    val = 255;
  }
  return (uint8_t)val;
}

void setBit(uint32_t &bits, uint8_t bit, bool value) {
  if (value) {
    bits |= (1UL << bit);
  } else {
    bits &= ~(1UL << bit);
  }
}


// ---------------------------------------------------------------------------
// Boton PS por combinacion START + SELECT
// ---------------------------------------------------------------------------
// El boton STEAM de la Deck lo intercepta el propio cliente de Steam y nunca
// llega a pygame, asi que no sirve como fuente para el boton PS. En su lugar
// se usa START+SELECT juntos. Al ser un mapeo directo (PS sostenido mientras
// ambos esten presionados), el comportamiento corto/largo sale gratis: un
// toque abre el XMB y mantenerlos presionados dispara el menu largo del PS3.
//
// Ventana de guarda: es imposible presionar ambos botones en el mismo
// instante, asi que sin proteccion se colaria un START (o SELECT) suelto al
// PS3 durante los milisegundos intermedios - y un START suelto pausa el
// juego. Por eso START/SELECT individuales se retienen COMBO_GUARD_MS antes
// de mandarse; si el otro llega dentro de esa ventana, era el combo y ninguno
// de los dos se envia. Solo afecta a botones de menu, no al juego en si.
const unsigned long COMBO_GUARD_MS = 80;

// Salidas efectivas. IMPORTANTE: applyPsCombo() NO debe modificar
// state.start_/state.select_/state.ps. Hacerlo fue un bug real (2026-08-28):
// esta funcion corre cada 8ms pero los paquetes UDP llegan cada ~16ms, asi
// que en la segunda pasada leia el `false` que ella misma habia escrito,
// interpretaba que el boton se solto y reiniciaba el contador de la ventana
// de guarda indefinidamente -> START/SELECT sueltos NUNCA llegaban a pasar.
bool effStart = false;
bool effSelect = false;
bool effPs = false;

void applyPsCombo() {
  static unsigned long singleSince = 0;  // cuando empezo a haber exactamente uno
  static bool comboLatched = false;      // hubo combo: suprimir hasta soltar ambos

  const bool start = state.start_;   // solo lectura, nunca se escriben
  const bool select = state.select_;
  const unsigned long now = millis();
  const bool combo = start && select;

  if (combo) {
    comboLatched = true;
    singleSince = 0;
  } else if (!start && !select) {
    comboLatched = false;
    singleSince = 0;
  } else if (singleSince == 0) {
    singleSince = now;
  }

  effPs = state.ps || combo;

  if (comboLatched) {
    // Mientras dure el combo (y hasta soltar ambos), no dejar pasar
    // START/SELECT por separado, ni siquiera de cola al soltar.
    effStart = false;
    effSelect = false;
    return;
  }

  // Un solo boton presionado: retenerlo hasta que pase la ventana de guarda,
  // por si el otro llega tarde y en realidad era el combo. Pasada la ventana,
  // el boton fluye normal mientras siga presionado.
  const bool guard = (singleSince != 0 && (now - singleSince) < COMBO_GUARD_MS);
  effStart = start && !guard;
  effSelect = select && !guard;
}

void buildInputReport(uint8_t *out48) {
  memset(out48, 0, 48);

  uint32_t bits = 0;
  setBit(bits, DS3_SELECT, effSelect);
  setBit(bits, DS3_L3, state.l3);
  setBit(bits, DS3_R3, state.r3);
  setBit(bits, DS3_START, effStart);
  setBit(bits, DS3_UP, state.dpad_y > 0);
  setBit(bits, DS3_RIGHT, state.dpad_x > 0);
  setBit(bits, DS3_DOWN, state.dpad_y < 0);
  setBit(bits, DS3_LEFT, state.dpad_x < 0);
  setBit(bits, DS3_L2, state.l2_click);
  setBit(bits, DS3_R2, state.r2_click);
  setBit(bits, DS3_L1, state.l1);
  setBit(bits, DS3_R1, state.r1);
  setBit(bits, DS3_TRIANGLE, state.triangle);
  setBit(bits, DS3_CIRCLE, state.circle);
  setBit(bits, DS3_CROSS, state.cross);
  setBit(bits, DS3_SQUARE, state.square);
  setBit(bits, DS3_PS, effPs);

  out48[1] = (bits >> 0) & 0xFF;
  out48[2] = (bits >> 8) & 0xFF;
  out48[3] = (bits >> 16) & 0xFF;

  out48[5] = axisToByte(applyDeadzone(state.lstick_x));
  out48[6] = axisToByte(applyDeadzone(state.lstick_y));
  out48[7] = axisToByte(applyDeadzone(state.rstick_x));
  out48[8] = axisToByte(applyDeadzone(state.rstick_y));

  out48[DS3_PRESSURE_OFFSET[DS3_UP]] = state.dpad_y > 0 ? 255 : 0;
  out48[DS3_PRESSURE_OFFSET[DS3_RIGHT]] = state.dpad_x > 0 ? 255 : 0;
  out48[DS3_PRESSURE_OFFSET[DS3_DOWN]] = state.dpad_y < 0 ? 255 : 0;
  out48[DS3_PRESSURE_OFFSET[DS3_LEFT]] = state.dpad_x < 0 ? 255 : 0;
  out48[DS3_PRESSURE_OFFSET[DS3_L2]] = axisToByte(state.l2_analog);
  out48[DS3_PRESSURE_OFFSET[DS3_R2]] = axisToByte(state.r2_analog);
  out48[DS3_PRESSURE_OFFSET[DS3_L1]] = state.l1 ? 255 : 0;
  out48[DS3_PRESSURE_OFFSET[DS3_R1]] = state.r1 ? 255 : 0;
  out48[DS3_PRESSURE_OFFSET[DS3_TRIANGLE]] = state.triangle ? 255 : 0;
  out48[DS3_PRESSURE_OFFSET[DS3_CIRCLE]] = state.circle ? 255 : 0;
  out48[DS3_PRESSURE_OFFSET[DS3_CROSS]] = state.cross ? 255 : 0;
  out48[DS3_PRESSURE_OFFSET[DS3_SQUARE]] = state.square ? 255 : 0;
}

// ===========================================================================
// MODO XBOX CLASICO (2026-09-19) - control del Xbox ORIGINAL (2001) por XID
// ===========================================================================
// NO ES HID. El Xbox original solo reconoce la clase USB 0x58/0x42 ("XID"):
//  - Device: bcdUSB 0x0110, clase 0/0/0. Un unico interface 0x58/0x42/0x00 con
//    2 endpoints interrupt de 32 bytes, bInterval 4 (IN 0x82 / OUT 0x02 en el
//    control real; aca se usa un endpoint "duplex" con el mismo numero).
//  - La consola pregunta por peticiones VENDOR dirigidas al interface (bmRequestType
//    0xC1): 0x06/0x4200 = descriptor XID (16 B) y 0x01/0x0100 y 0x01/0x0200 =
//    capacidades de entrada (20 B) y de salida (6 B).
//  - Reporte de entrada de 20 bytes por el endpoint IN; rumble de 6 bytes por
//    el OUT (o por SET_REPORT 0x21/0x09, wValue 0x0200, en el control).
// Fuentes: xboxdevwiki.net/Xbox_Input_Devices y xqemu/hw/xbox/xid.c (los bytes de
// los descriptores/capacidades salen de ahi; NO probado contra una consola real
// al momento de escribir esto).
//
// COMO ENGANCHA EN ARDUINO-ESP32 2.0.13 (TinyUSB 0.15):
//  - tinyusb_enable_interface(USB_INTERFACE_CUSTOM, ...) mete nuestro descriptor.
//  - Sin un driver que "reclame" el interface 0x58, TinyUSB aborta la enumeracion
//    (TU_ASSERT): por eso se sobreescribe usbd_app_driver_get_cb() (weak en la
//    lib) y se abren los endpoints con usbd_open_edpt_pair().
//  - Las peticiones VENDOR van SIEMPRE a tud_vendor_control_xfer_cb (sin importar
//    el destinatario); el core las delega al gancho weak
//    tinyusb_vendor_control_request_cb(), que se sobreescribe aca.
// Todo esto solo actua con modoActual == MODO_XBOX_CLASICO: en los otros modos
// usbd_app_driver_get_cb devuelve 0 drivers y el gancho vendor devuelve false, o
// sea el mismo comportamiento de antes.

static const uint8_t XID_DESC[16] = {
  0x10, 0x42,        // bLength, bDescriptorType (XID)
  0x00, 0x01,        // bcdXid 0x0100
  0x01,              // bType: gamepad
  0x02,              // bSubType: 0x02 = Controller S (0x01 = Duke)
  0x14, 0x06,        // max input report 20 B, max output report 6 B
  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF  // 4 PID alternativos (ninguno)
};
// Capacidades: el mismo formato del reporte con todos los campos validos en 0xFF.
// [0]=report id, [1]=largo, [3] es el byte reservado del reporte.
static const uint8_t XID_CAPS_IN[20] = {
  0x00, 0x14, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF
};
static const uint8_t XID_CAPS_OUT[6] = { 0x00, 0x06, 0xFF, 0xFF, 0xFF, 0xFF };

static uint8_t xid_ep_in = 0, xid_ep_out = 0;
static uint8_t xid_out_buf[32];
static uint8_t xid_in_buf[32];
static uint8_t xid_ctrl_buf[32];
static XidInReport xid_ultimo;                 // ultimo reporte armado (GET_REPORT)
static uint16_t xid_motor_izq = 0, xid_motor_der = 0;
unsigned long xidEnviados = 0, xidFallidos = 0, xidOcupado = 0, xidSalidas = 0, xidVendor = 0;

// Descriptor del interface: 9 (interface) + 7 (EP IN) + 7 (EP OUT) = 23 bytes.
extern "C" uint16_t xid_load_descriptor(uint8_t *dst, uint8_t *itf) {
  uint8_t ep = tinyusb_get_free_duplex_endpoint();
  if (ep == 0) {
    return 0;
  }
  const uint8_t d[23] = {
    9, 4, *itf, 0, 2, 0x58, 0x42, 0x00, 0,
    7, 5, (uint8_t)(0x80 | ep), 0x03, 0x20, 0x00, 4,
    7, 5, ep, 0x03, 0x20, 0x00, 4
  };
  *itf += 1;
  memcpy(dst, d, sizeof(d));
  return sizeof(d);
}

// Rumble: [0]=0, [1]=6, [2..3] motor izquierdo, [4..5] motor derecho (16 bits LE).
static void xidProcesarSalida(const uint8_t *d, uint32_t n) {
  if (n < 6 || d[1] != 6) {
    return;
  }
  xid_motor_izq = (uint16_t)(d[2] | (d[3] << 8));
  xid_motor_der = (uint16_t)(d[4] | (d[5] << 8));
  xidSalidas++;
  if (xidSalidas <= 5) {
    debugLog("[xid] rumble izq=%u der=%u (paquete %lu)\n", xid_motor_izq, xid_motor_der, xidSalidas);
  }
}

static void xid_drv_init(void) {}
static void xid_drv_reset(uint8_t rhport) {
  (void)rhport;
  xid_ep_in = 0;
  xid_ep_out = 0;
}

static uint16_t xid_drv_open(uint8_t rhport, tusb_desc_interface_t const *desc_itf, uint16_t max_len) {
  if (desc_itf->bInterfaceClass != 0x58 || desc_itf->bInterfaceSubClass != 0x42) {
    return 0;  // no es nuestro
  }
  const uint16_t drv_len = sizeof(tusb_desc_interface_t) + desc_itf->bNumEndpoints * sizeof(tusb_desc_endpoint_t);
  if (max_len < drv_len) {
    return 0;
  }
  uint8_t const *p_desc = tu_desc_next(desc_itf);
  if (!usbd_open_edpt_pair(rhport, p_desc, desc_itf->bNumEndpoints, TUSB_XFER_INTERRUPT, &xid_ep_out, &xid_ep_in)) {
    return 0;
  }
  debugLog("[xid] interface abierta: EP IN=0x%02X OUT=0x%02X\n", xid_ep_in, xid_ep_out);
  // Dejar el endpoint OUT listo para recibir el rumble.
  usbd_edpt_xfer(rhport, xid_ep_out, xid_out_buf, sizeof(xid_out_buf));
  return drv_len;
}

// Peticiones de CLASE al interface (las VENDOR van al gancho de mas abajo):
// GET_REPORT (0xA1/0x01) devuelve el ultimo estado; SET_REPORT (0x21/0x09) trae el rumble.
static bool xid_drv_control_xfer(uint8_t rhport, uint8_t stage, tusb_control_request_t const *req) {
  if (req->bmRequestType_bit.type != TUSB_REQ_TYPE_CLASS) {
    return false;
  }
  const bool entrada = (req->bmRequestType_bit.direction == TUSB_DIR_IN);
  if (stage == CONTROL_STAGE_SETUP) {
    if (entrada && req->bRequest == 0x01) {
      uint16_t n = req->wLength < sizeof(xid_ultimo) ? req->wLength : sizeof(xid_ultimo);
      return tud_control_xfer(rhport, req, (void *)&xid_ultimo, n);
    }
    if (!entrada && req->bRequest == 0x09) {
      uint16_t n = req->wLength < sizeof(xid_ctrl_buf) ? req->wLength : sizeof(xid_ctrl_buf);
      return tud_control_xfer(rhport, req, xid_ctrl_buf, n);
    }
    return false;
  }
  if (stage == CONTROL_STAGE_ACK && !entrada && req->bRequest == 0x09) {
    xidProcesarSalida(xid_ctrl_buf, req->wLength);
  }
  return true;
}

static bool xid_drv_xfer_cb(uint8_t rhport, uint8_t ep_addr, xfer_result_t result, uint32_t xferred_bytes) {
  if (ep_addr == xid_ep_out) {
    if (result == XFER_RESULT_SUCCESS) {
      xidProcesarSalida(xid_out_buf, xferred_bytes);
    }
    usbd_edpt_xfer(rhport, xid_ep_out, xid_out_buf, sizeof(xid_out_buf));  // rearmar
  }
  return true;
}

static const usbd_class_driver_t xid_driver = {
#if CFG_TUSB_DEBUG >= 2
  "XID",
#endif
  xid_drv_init, xid_drv_reset, xid_drv_open, xid_drv_control_xfer, xid_drv_xfer_cb, NULL
};

extern "C" const usbd_class_driver_t *usbd_app_driver_get_cb(uint8_t *driver_count) {
  if (modoActual == MODO_XBOX_CLASICO) {
    *driver_count = 1;
    return &xid_driver;
  }
  *driver_count = 0;
  return NULL;
}

// Peticiones VENDOR de la consola (descriptor XID y capacidades).
extern "C" bool tinyusb_vendor_control_request_cb(uint8_t rhport, uint8_t stage, tusb_control_request_t const *req) {
  if (modoActual != MODO_XBOX_CLASICO) {
    return false;
  }
  if (stage != CONTROL_STAGE_SETUP) {
    return true;  // las etapas DATA/ACK de un IN no piden nada mas
  }
  if (req->bmRequestType_bit.direction != TUSB_DIR_IN) {
    return false;
  }
  xidVendor++;
  if (xidVendor <= 12) {
    debugLog("[xid] peticion vendor bReq=0x%02X wValue=0x%04X wIndex=%u wLen=%u\n",
             req->bRequest, req->wValue, req->wIndex, req->wLength);
  }
  const uint8_t *datos = NULL;
  uint16_t largo = 0;
  if (req->bRequest == 0x06 && req->wValue == 0x4200) {
    datos = XID_DESC;
    largo = sizeof(XID_DESC);
  } else if (req->bRequest == 0x01 && req->wValue == 0x0100) {
    datos = XID_CAPS_IN;
    largo = sizeof(XID_CAPS_IN);
  } else if (req->bRequest == 0x01 && req->wValue == 0x0200) {
    datos = XID_CAPS_OUT;
    largo = sizeof(XID_CAPS_OUT);
  } else {
    return false;
  }
  if (req->wLength < largo) {
    largo = req->wLength;
  }
  return tud_control_xfer(rhport, req, (void *)datos, largo);
}

// Gatillo analogico (-1..1, reposo en -1) a 0-255; si solo llega el "click" digital, 255.
static uint8_t xidGatillo(float analogico, bool click) {
  int v = (int)((analogico + 1.0f) * 127.5f + 0.5f);
  if (v < 0) v = 0;
  if (v > 255) v = 255;
  if (click && v == 0) v = 255;
  return (uint8_t)v;
}

// Stick (-1..1) a int16 con la misma zona muerta que el modo DS3.
static int16_t xidStick(float v) {
  int32_t x = (int32_t)(applyDeadzone(v) * 32767.0f);
  if (x > 32767) x = 32767;
  if (x < -32767) x = -32767;
  return (int16_t)x;
}

// Traduce el estado que ya manda la Deck/Ally (nombres de DS3) al reporte XID.
// Mapeo: A/B/X/Y directos; L1 = White y R1 = Black (nombres de los botones del
// Xbox original); L2/R2 = gatillos; SELECT = Back. Sin el acorde de PS (no existe
// en el Xbox). El eje Y se invierte: en SDL arriba es negativo y en XID positivo.
static void buildXboxReport(XidInReport *r) {
  memset(r, 0, sizeof(*r));
  r->length = 0x14;
  uint8_t b = 0;
  if (state.dpad_y > 0) b |= 0x01;
  if (state.dpad_y < 0) b |= 0x02;
  if (state.dpad_x < 0) b |= 0x04;
  if (state.dpad_x > 0) b |= 0x08;
  if (state.start_) b |= 0x10;
  if (state.select_) b |= 0x20;
  if (state.l3) b |= 0x40;
  if (state.r3) b |= 0x80;
  r->buttons = b;
  r->analog[0] = state.cross ? 255 : 0;      // A
  r->analog[1] = state.circle ? 255 : 0;     // B
  r->analog[2] = state.square ? 255 : 0;     // X
  r->analog[3] = state.triangle ? 255 : 0;   // Y
  r->analog[4] = state.r1 ? 255 : 0;         // Black
  r->analog[5] = state.l1 ? 255 : 0;         // White
  r->analog[6] = xidGatillo(state.l2_analog, state.l2_click);
  r->analog[7] = xidGatillo(state.r2_analog, state.r2_click);
  r->lx = xidStick(state.lstick_x);
  r->ly = xidStick(-state.lstick_y);
  r->rx = xidStick(state.rstick_x);
  r->ry = xidStick(-state.rstick_y);
}

static void xidEnviarEstado() {
  buildXboxReport(&xid_ultimo);
  if (xid_ep_in == 0 || !tud_ready()) {
    xidFallidos++;
    return;
  }
  if (usbd_edpt_busy(0, xid_ep_in)) {
    xidOcupado++;  // el reporte anterior sigue esperando que la consola lo lea
    return;
  }
  if (!usbd_edpt_claim(0, xid_ep_in)) {
    xidOcupado++;
    return;
  }
  memcpy(xid_in_buf, &xid_ultimo, sizeof(xid_ultimo));
  if (usbd_edpt_xfer(0, xid_ep_in, xid_in_buf, sizeof(xid_ultimo))) {
    xidEnviados++;
  } else {
    usbd_edpt_release(0, xid_ep_in);
    xidFallidos++;
  }
}

// Ajustes USB de este modo (se llama desde setup() en lugar de la parte DS3).
static void configurarUsbXboxClasico() {
  USB.VID(0x045E);   // Microsoft
  USB.PID(0x0289);   // Xbox Controller S (bSubType 0x02 en XID_DESC)
  USB.usbVersion(0x0110);
  USB.firmwareVersion(0x0100);
  USB.usbClass(0x00);
  USB.usbSubClass(0x00);
  USB.usbProtocol(0x00);
  USB.usbAttributes(0x80);
  USB.usbPower(100);
  USB.manufacturerName("Microsoft");
  USB.productName("Xbox Controller S");
  USB.serialNumber("0");
  tinyusb_enable_interface(USB_INTERFACE_CUSTOM, 23, xid_load_descriptor);
  debugLog("[setup] modo XBOX CLASICO: interface XID 0x58/0x42, USB 1.10\n");
}

void setup() {
  Serial.begin(115200);
  neopixelWrite(RGB_LED_PIN, 32, 0, 0);

  pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);
  cargarModoGuardado();
  debugLog("[setup] modo consola = %s\n", nombreModo(modoActual));

  WiFi.mode(WIFI_STA);

  // APAGAR EL AHORRO DE ENERGIA DEL WIFI. Sin esto son 30-100ms de retraso en
  // CADA paquete de input, y no es teoria: medido desde la Deck el 2026-08-29
  // con `ping -c 40 -i 0.1 192.168.0.40` estando esta placa con el firmware
  // anterior, los tiempos salian alternados 5ms / 100ms (con picos de 200 y
  // 310ms), o sea min 3, promedio 79, max 310.
  //
  // POR QUE PASA: por default el ESP32 en modo estacion duerme la radio entre
  // beacons del router (100ms tipico). Mientras duerme, el router NO le manda
  // nada: le guarda los paquetes y se los entrega recien en el proximo beacon.
  // Como esta placa solo RECIBE (nunca contesta nada por UDP), se pasa dormida
  // casi todo el tiempo, asi que a casi todos los paquetes de input les toca
  // esperar el beacon. Ese retraso se suma DIRECTO al lag boton->PS3, y encima
  // con jitter, que es lo que hace que se sienta "gomoso" en un juego aunque
  // en el menu del XMB casi ni se note.
  //
  // Costo: la radio queda siempre prendida, ~100mA mas de consumo. Alimentada
  // desde el USB del PS3 (500mA) no es problema.
  //
  // Ojo con la nota vieja: en la bitacora quedo escrito que este ping "en
  // realidad daba 3-9ms y no hacia falta tocar setSleep()". Esa medicion fue
  // con pocos paquetes seguidos - manda el patron alternado de arriba, que
  // solo se ve pidiendo varias decenas.
  //
  // Se llama DOS veces a proposito: algunas versiones del core ignoran la
  // primera si todavia no arranco la interfaz, y la segunda (ya conectado)
  // siempre pega. getSleep() en el log de arranque dice cual quedo valiendo:
  // tiene que decir sleep=0.
  WiFi.setSleep(false);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long wifiStart = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - wifiStart < 15000) {
    delay(200);
  }
  WiFi.setSleep(false);
  udp.begin(UDP_PORT);
  {
    IPAddress ip = WiFi.localIP();
    debugBroadcastIP = IPAddress(ip[0], ip[1], ip[2], 255);
  }
  {
    uint8_t r, g, b;
    colorParaModo(modoActual, r, g, b);
    neopixelWrite(RGB_LED_PIN, r, g, b);
  }
  // Trazas de arranque: el WiFi corre en su propia tarea de FreeRTOS, asi que
  // el ESP32 puede responder ping aunque setup()/loop() esten colgados. Estas
  // lineas dicen exactamente hasta donde llega el arranque.
  debugLog("[setup] wifi ok, ip=%s sleep=%d\n", WiFi.localIP().toString().c_str(), (int)WiFi.getSleep());

  if (modoActual == MODO_XBOX_CLASICO) {
    configurarUsbXboxClasico();
  } else {
  USB.VID(0x054C);
  USB.PID(0x0268);
  USB.manufacturerName("Sony");
  USB.productName("PLAYSTATION(R)3 Controller");
  USB.serialNumber("0");
  // Clase de dispositivo USB "Wireless Controller" (0xE0/0x01/0x01), no la
  // clase HID generica (2026-09-11, soporte PS2/OPL). Un DS3 real usa esta
  // clase RARA a nivel de DEVICE descriptor (no de interfaz) incluso
  // conectado por cable, porque el mismo chip tambien habla Bluetooth. La
  // PS3 no es estricta con esto y aceptaba el emulador igual con clase
  // generica (0x00/0x00/0x00, "definida en la interfaz"), pero el driver de
  // OPL (Open PS2 Loader) para PS2 SI la revisa explicitamente antes de
  // reconocer el mando - ver USB_CLASS_WIRELESS_CONTROLLER/
  // USB_SUBCLASS_RF_CONTROLLER/USB_PROTOCOL_BLUETOOTH_PROG en
  // include/ds34common.h del repo de OPL (ps2homebrew/Open-PS2-Loader).
  // Poner los valores reales no deberia romper nada del lado del PS3: es
  // MAS fiel al DS3 autentico, no menos.
  // XBOX360 (2026-09-12) CONFIRMADO: con hiddriver.xex realmente cargado
  // (el bug real era el launch.ini equivocado, ver
  // [[xbox360_hiddriver_setup]]), la Xbox 360 SI necesita la clase
  // generica 0x00 (como un DS3 real) - con 0xE0 nunca negociaba. Como
  // OPL/PS2 necesita 0xE0 y PS3/Xbox360 necesitan 0x00, ya no hay un solo
  // valor que sirva para las tres consolas - se elige con el selector de
  // modo (boton BOOT, ver arriba) y se guarda en flash.
  if (modoActual == MODO_PS2) {
    USB.usbClass(0xE0);
    USB.usbSubClass(0x01);
    USB.usbProtocol(0x01);
  } else {
    USB.usbClass(0x00);
    USB.usbSubClass(0x00);
    USB.usbProtocol(0x00);
  }
  USB.usbAttributes(0x80);

  initFeatureStoreFromRealDS3();
  debugLog("[setup] feature store listo\n");

  tinyusb_enable_interface(USB_INTERFACE_HID, TUD_HID_INOUT_DESC_LEN, ds3_hid_load_descriptor);
  }  // fin de la rama DS3 (PS3 / PS2 / Xbox 360)
  debugLog("[setup] llamando USB.begin()\n");
  USB.begin();
  debugLog("[setup] USB.begin() retorno - setup completo\n");
}

unsigned long lastSend = 0;
unsigned long lastHeartbeat = 0;

// Contadores de diagnostico. El "Hilo A" (ds3_controller.ino no mandaba datos
// reales ni en Linux, con el mapeo completo de 17 botones) nunca se aislo del
// todo; se investigaba cuando se encontro que la causa raiz real del bloqueo
// del PS3 estaba en otro lado (feature reports en cero, ya resuelto). Estos
// contadores dicen de una si el problema, de reaparecer, esta en la recepcion
// UDP o en el envio USB, sin volver a comentar codigo a ciegas.
unsigned long packetsReceived = 0;
unsigned long packetsStale = 0;
unsigned long reportsSent = 0;
unsigned long reportsFailed = 0;

// ---------------------------------------------------------------------------
// RECUPERACION DEL USB CUANDO EL PS3 SUELTA EL MANDO
// ---------------------------------------------------------------------------
// SINTOMA MEDIDO (2026-08-29): jugando un rato, el PS3 deja de ver el mando y
// no vuelve solo. El heartbeat lo muestra sin lugar a dudas:
//
//   [1585458] [hb] udp=170339 ... enviados=223205 fallidos=9537  ready=0
//   [1590459] [hb] udp=170932 ... enviados=223205 fallidos=10278 ready=0
//
// 26 minutos de uptime (la placa NO se reinicio), WiFi bien, el UDP de la Deck
// entrando perfecto y sin un solo error de JSON - pero `enviados` congelado y
// `fallidos` subiendo 148 por segundo, con ready=0. O sea que el problema es
// puramente el lado USB: el host dejo de atender el endpoint y tud_hid_report()
// falla para siempre. Hasta ahora la unica salida era desenchufar y volver a
// enchufar el cable a mano.
//
// QUE HACE ESTO. Si ready lleva USB_ATASCADO_MS en cero (y alguna vez estuvo
// en uno, para no pelearse con la enumeracion inicial), se reinicia la placa
// entera con ESP.restart() - cuesta ~4s de WiFi y arranca todo de cero.
//
// ANTES (hasta 2026-09-11) se probaba primero una reconexion suave
// (tud_disconnect()+tud_connect(), soltando y volviendo a poner el pull-up
// de D+ sin reiniciar nada) y solo se llegaba al restart tras dos intentos
// fallidos - pensado para el caso del PS3 original, donde eso alcanzaba
// igual que desenchufar el cable. Confirmado contra hardware real en el
// caso de PS2/OPL (mismo dia, con el usuario conectando y flasheando en
// vivo): la reconexion suave NUNCA sacaba al firmware del atasco - hacia
// falta el restart completo si o si. Eso sugiere que el atasco no es solo
// la senalizacion USB (pull-up), sino algo mas profundo del stack TinyUSB
// que un reconnect no limpia. Se salta directo al restart: recupera mas
// rapido (sin gastar los intentos suaves ni la espera entre ellos) y cubre
// los dos casos.
// PROBADO Y DESCARTADO (2026-09-11, con el umbral viejo de 3000/6000 y dos
// intentos suaves): subir este umbral a 20000/15000 no cambio el sintoma de
// OPL ("funciona unos segundos y ya no, no se recupera solo") - por eso se
// descarto el umbral como causa. La causa de fondo de por que se atasca
// tud_hid_ready() en el menu de OPL sigue sin identificarse; lo que cambio
// aca es COMO se recupera una vez atascado, no por que se atasca.
const unsigned long USB_ATASCADO_MS = 3000;
unsigned long ultimoReady = 0;
bool huboReadyAlgunaVez = false;

// Un DS3 real manda su Input report cada ~8ms. Ese sigue siendo el ritmo de
// fondo, pero ya no es el unico momento en que se manda: ver ENVIO POR CAMBIO
// mas abajo.
const unsigned long SEND_INTERVAL_MS = 8;

// Piso de separacion entre dos reportes seguidos cuando el disparo es por
// cambio de estado. El PS3 pide el endpoint de interrupcion cada 1ms
// (bInterval=1 en TUD_HID_INOUT_DESCRIPTOR), asi que 2ms sobra y de paso evita
// que un cliente que algun dia mande mas rapido inunde el bus.
const unsigned long MIN_SEND_INTERVAL_MS = 2;

void loop() {
  static bool firstLoop = true;
  if (firstLoop) {
    firstLoop = false;
    debugLog("[loop] primera vuelta\n");
  }

  revisarSelectorModo();

  // -------------------------------------------------------------------------
  // VACIAR LA COLA UDP ENTERA Y QUEDARSE CON EL ULTIMO PAQUETE
  // -------------------------------------------------------------------------
  // Antes se atendia UN paquete por vuelta de loop(). Ahi hay un modo de falla
  // clasico: si en algun momento entran mas paquetes de los que se sacan (una
  // rafaga de wifi que llega junta, lwIP entregando en bloque, cualquier pausa
  // del loop), la cola de recepcion se llena de estado VIEJO y el firmware se
  // pone a reproducir el pasado - cada vuelta aplica un paquete mas viejo que
  // el anterior y el retraso crece sin techo, sin que se pierda un solo
  // paquete ni aparezca error en ningun lado. Se siente exactamente como
  // "input lag que empeora mientras jugas".
  //
  // Aca cada paquete es el ESTADO COMPLETO del mando, no un evento: el ultimo
  // que llego ya contiene todo, los anteriores no aportan nada. Asi que se
  // drena todo lo que haya encolado y se parsea solo el ultimo.
  //
  // packetsStale cuenta los que se descartaron por viejos. Si ese numero crece
  // en el heartbeat, HABIA cola (o sea, se estaba acumulando lag aca); si
  // queda en 0, la recepcion nunca se atraso y el retraso esta en otro lado.
  int drained = 0;
  int lastLen = 0;
  int packetSize;
  while ((packetSize = udp.parsePacket()) > 0) {
    if (packetSize >= (int)sizeof(udpBuffer)) {
      // No entra en el buffer: no se lee, la proxima parsePacket() lo tira.
      continue;
    }
    int len = udp.read(udpBuffer, sizeof(udpBuffer) - 1);
    if (len > 0) {
      udpBuffer[len] = '\0';
      lastLen = len;
      packetsReceived++;
      drained++;
    }
  }

  bool estadoNuevo = false;
  if (lastLen > 0) {
    if (drained > 1) packetsStale += (drained - 1);
    updateStateFromJson((const uint8_t *)udpBuffer, lastLen);
    estadoNuevo = true;
  }

  // -------------------------------------------------------------------------
  // ENVIO POR CAMBIO + LATIDO DE FONDO
  // -------------------------------------------------------------------------
  // El timer de 8ms solo sumaba espera: un paquete que llegaba justo despues
  // de un envio se quedaba guardado hasta 8ms (4ms de promedio) antes de salir
  // al PS3. Ahora, apenas entra estado nuevo se manda el reporte, y el timer
  // queda como LATIDO para cuando no llega nada - el PS3 espera que un DS3
  // hable seguido, no solo cuando cambia algo.
  //
  // applyPsCombo() pasa a correr mas seguido (hasta 120 veces por segundo en
  // vez de 125): no le afecta, porque mide con millis() y no escribe sobre
  // state (ver la advertencia grande en su definicion, sigue vigente).
  unsigned long now = millis();
  bool porCambio = estadoNuevo && (now - lastSend >= MIN_SEND_INTERVAL_MS);
  bool porLatido = (now - lastSend >= SEND_INTERVAL_MS);
  if (modoActual == MODO_XBOX_CLASICO) {
    if (porCambio || porLatido) {
      lastSend = now;
      xidEnviarEstado();
    }
  } else if (porCambio || porLatido) {
    lastSend = now;
    applyPsCombo();
    if (tud_hid_ready()) {
      uint8_t report[48];
      buildInputReport(report);
      if (tud_hid_report(0x01, report, 48)) {
        reportsSent++;
      } else {
        reportsFailed++;
      }
    } else {
      reportsFailed++;
    }
  }

  // Vigilancia del USB (ver la nota larga de arriba).
  if (tud_hid_ready()) {
    ultimoReady = now;
    huboReadyAlgunaVez = true;
  } else if (huboReadyAlgunaVez && ultimoReady != 0
             && (now - ultimoReady) > USB_ATASCADO_MS) {
    debugLog("[usb] ready=0 hace %lu ms: reiniciando la placa\n", now - ultimoReady);
    delay(50);
    ESP.restart();
  }

  if (now - lastHeartbeat >= 5000) {
    lastHeartbeat = now;
    uint8_t probe[48];
    buildInputReport(probe);
    debugLog("[hb] udp=%lu viejos=%lu jsonOk=%lu jsonErr=%lu enviados=%lu fallidos=%lu out=%lu ready=%d rep=[%02X %02X %02X] cross=%d\n",
             packetsReceived, packetsStale, parseOk, parseErr, reportsSent, reportsFailed,
             outputReports,
             (int)tud_hid_ready(), probe[1], probe[2], probe[3], (int)state.cross);
    if (modoActual == MODO_XBOX_CLASICO) {
      debugLog("[hb-xid] montado=%d ep_in=0x%02X enviados=%lu fallidos=%lu ocupado=%lu rumble=%lu vendor=%lu\n",
               (int)tud_mounted(), xid_ep_in, xidEnviados, xidFallidos, xidOcupado, xidSalidas, xidVendor);
    }
  }
}
