// (2026-08-28) Igual a ds3_raw_tinyusb_wifi_test.ino (que SI funciono con
// WiFi conectado - LED verde sostenido, datos reales confirmados) pero
// agregando la recepcion UDP real + deserializeJson() de ArduinoJson (igual
// que ds3_controller.ino, que SI dejo de mandar datos con esto agregado).
// Objetivo: aislar si es especificamente el parseo JSON en cada paquete
// recibido lo que rompe tud_hid_ready()/tud_hid_report(), separado de la
// otra sospecha (debugLog() llamado desde dentro de
// tud_hid_get_report_cb/tud_hid_set_report_cb) - este test NO llama
// debugLog desde esos callbacks, solo hace el parseo JSON en loop().
//
// LED: rojo = tud_hid_ready()==false, verde = true.

#include "USB.h"
#include "esp32-hal-tinyusb.h"
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoJson.h>

const char *WIFI_SSID = "TU_RED_WIFI_2.4GHZ";
const char *WIFI_PASSWORD = "TU_CONTRASENA_WIFI";
const uint16_t UDP_PORT = 9000;

WiFiUDP udp;
char udpBuffer[1024];
float lastLstickX = 0;

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
  return DS3_REPORT_DESCRIPTOR;
}

extern "C" uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type, uint8_t *buffer, uint16_t reqlen) {
  (void)instance;
  (void)report_type;
  if (report_id == 0xF2) {
    uint16_t n = (reqlen < 16) ? reqlen : 16;
    memset(buffer, 0, n);
    if (n > 8) {
      static const uint8_t mac[6] = { 0x00, 0x19, 0xC5, 0x12, 0x34, 0x56 };
      memcpy(&buffer[3], mac, 6);
    }
    return n;
  }
  uint16_t n = (reqlen < 48) ? reqlen : 48;
  memset(buffer, 0, n);
  return n;
}

extern "C" void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type, uint8_t const *buffer, uint16_t bufsize) {
  (void)instance;
  (void)report_id;
  (void)report_type;
  (void)buffer;
  (void)bufsize;
}

#define RGB_LED_PIN 48

void setup() {
  Serial.begin(115200);
  neopixelWrite(RGB_LED_PIN, 32, 0, 0);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long wifiStart = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - wifiStart < 15000) {
    delay(200);
  }
  udp.begin(UDP_PORT);
  neopixelWrite(RGB_LED_PIN, 32, 32, 0);

  USB.VID(0x054C);
  USB.PID(0x0268);
  USB.manufacturerName("Sony");
  USB.productName("PLAYSTATION(R)3 Controller");
  USB.serialNumber("0");
  USB.usbClass(0x00);
  USB.usbSubClass(0x00);
  USB.usbProtocol(0x00);
  USB.usbAttributes(0x80);

  tinyusb_enable_interface(USB_INTERFACE_HID, TUD_HID_INOUT_DESC_LEN, ds3_hid_load_descriptor);
  USB.begin();
}

unsigned long lastSend = 0;

void loop() {
  static unsigned long bootDoneAt = 0;
  if (bootDoneAt == 0) {
    bootDoneAt = millis();
  }
  unsigned long now = millis() - bootDoneAt;

  // Recepcion UDP + parseo JSON real, igual que ds3_controller.ino - el
  // valor parseado (LSTICK_X) se usa para decidir el bit de dpad izquierda
  // del reporte, para que quede visible en jstest si algo llega mal.
  int packetSize = udp.parsePacket();
  if (packetSize > 0 && packetSize < (int)sizeof(udpBuffer)) {
    int len = udp.read(udpBuffer, sizeof(udpBuffer) - 1);
    if (len > 0) {
      udpBuffer[len] = '\0';
      JsonDocument doc;
      DeserializationError err = deserializeJson(doc, udpBuffer, len);
      if (!err) {
        JsonObject axes = doc["axes"];
        lastLstickX = axes["LSTICK_X"] | 0.0f;
      }
    }
  }

  if (now - lastSend >= 1000) {
    lastSend = now;
    bool ready = tud_hid_ready();
    neopixelWrite(RGB_LED_PIN, ready ? 0 : 32, ready ? 32 : 0, 0);
    uint8_t report[48] = { 0 };
    report[5] = report[6] = report[7] = report[8] = 128;
    if (lastLstickX < -0.3f) {
      report[1] |= (1 << 7);
      report[17] = 255;
    }
    if (ready) {
      tud_hid_report(0x01, report, 48);
    }
  }
}
