// (2026-08-28) Segundo sketch de diagnostico, continuacion de
// ds3_input_only_test.ino (que confirmo hid.ready()=true con Input SOLO, sin
// Output ni Feature). Este agrega de vuelta el bloque Feature del reporte ID
// 1 (48 bytes, igual que el DS3 real) pero SIGUE sin ningun bloque Output y
// sin los IDs adicionales (0x02/0xEE/0xEF/F1/F2/F4/F5/F7/F8). Objetivo:
// aislar si es el Output el que rompe ready(), o el Feature, o ambos.
//
// LED: rojo = ready()=false, verde = ready()=true (igual que el sketch
// anterior, revisar a simple vista sin necesitar WiFi/log).

#include "USB.h"
#include "USBHID.h"

// Igual al descriptor real (148 bytes) pero SIN el bloque Output de 8 bytes
// (75 08 95 30 09 01 91 02) y SIN los bloques sibling de 0x02/0xEE/0xEF.
static const uint8_t DS3_INPUT_FEATURE_DESCRIPTOR[] = {
  0x05, 0x01, 0x09, 0x04, 0xA1, 0x01, 0xA1, 0x02, 0x85, 0x01, 0x75, 0x08, 0x95, 0x01, 0x15, 0x00, 0x26, 0xFF, 0x00,
  0x81, 0x03, 0x75, 0x01, 0x95, 0x13, 0x15, 0x00, 0x25, 0x01, 0x35, 0x00, 0x45, 0x01, 0x05, 0x09, 0x19, 0x01, 0x29,
  0x13, 0x81, 0x02, 0x75, 0x01, 0x95, 0x0D, 0x06, 0x00, 0xFF, 0x81, 0x03, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x05, 0x01,
  0x09, 0x01, 0xA1, 0x00, 0x75, 0x08, 0x95, 0x04, 0x35, 0x00, 0x46, 0xFF, 0x00, 0x09, 0x30, 0x09, 0x31, 0x09, 0x32,
  0x09, 0x35, 0x81, 0x02, 0xC0, 0x05, 0x01, 0x75, 0x08, 0x95, 0x27, 0x09, 0x01, 0x81, 0x02,
  // (sin bloque Output aca)
  0x75, 0x08, 0x95, 0x30, 0x09, 0x01, 0xB1, 0x02,  // Feature, report ID 1, 48 bytes
  0xC0,
  0xC0,
};

class DS3InputFeature : public USBHIDDevice {
public:
  DS3InputFeature() : hid() {
    static bool initialized = false;
    if (!initialized) {
      initialized = true;
      hid.addDevice(this, sizeof(DS3_INPUT_FEATURE_DESCRIPTOR));
    }
  }

  void begin() {
    hid.begin();
  }

  uint16_t _onGetDescriptor(uint8_t *dst) override {
    memcpy(dst, DS3_INPUT_FEATURE_DESCRIPTOR, sizeof(DS3_INPUT_FEATURE_DESCRIPTOR));
    return sizeof(DS3_INPUT_FEATURE_DESCRIPTOR);
  }

  uint16_t _onGetFeature(uint8_t report_id, uint8_t *buffer, uint16_t len) override {
    if (report_id == 0x01) {
      uint16_t n = (len < 48) ? len : 48;
      memset(buffer, 0, n);
      return n;
    }
    return 0;
  }

  bool sendInputReport(const uint8_t *data48) {
    return hid.SendReport(0x01, data48, 48);
  }

  bool isReady() {
    return hid.ready();
  }

protected:
  USBHID hid;
};

DS3InputFeature ds3;

#define RGB_LED_PIN 48

void setup() {
  Serial.begin(115200);
  neopixelWrite(RGB_LED_PIN, 32, 0, 0);

  USB.VID(0x054C);
  USB.PID(0x0268);
  USB.manufacturerName("Sony");
  USB.productName("PLAYSTATION(R)3 Controller");
  USB.serialNumber("0");
  USB.usbClass(0x00);
  USB.usbSubClass(0x00);
  USB.usbProtocol(0x00);
  USB.usbAttributes(0x80);

  ds3.begin();
  USB.begin();
}

unsigned long lastSend = 0;
bool wasReady = false;

void loop() {
  static unsigned long bootDoneAt = 0;
  if (bootDoneAt == 0) {
    bootDoneAt = millis();
  }
  unsigned long now = millis() - bootDoneAt;

  if (now - lastSend >= 1000) {
    lastSend = now;
    bool ready = ds3.isReady();
    if (ready != wasReady) {
      wasReady = ready;
      neopixelWrite(RGB_LED_PIN, ready ? 0 : 32, ready ? 32 : 0, 0);
    }
    uint8_t report[48] = { 0 };
    report[5] = report[6] = report[7] = report[8] = 128;
    static bool left = false;
    left = !left;
    if (left) {
      report[1] |= (1 << 7);
      report[17] = 255;
    }
    ds3.sendInputReport(report);
  }
}
