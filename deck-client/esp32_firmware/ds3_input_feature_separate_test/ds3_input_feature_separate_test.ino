// (2026-08-28) Tercer sketch de diagnostico. Confirmado hasta aca:
// - Input SOLO (sin Output/Feature) -> hid.ready()=true (ds3_input_only_test.ino)
// - Input + Feature MEZCLADOS bajo el mismo bloque/ID 1 -> hid.ready()=false
//   (ds3_input_feature_test.ino) - esto es EXACTAMENTE como esta estructurado
//   el descriptor del DS3 REAL (confirmado por dump real via HIDIOCGRDESC).
//
// Este test prueba si separar el Feature del ID 1 en su PROPIO bloque
// sibling (igual patron que ya usan 0x02/0xEE/0xEF: "A1 02 85 01 ... B1 02
// C0" aparte, en vez de compartir la misma coleccion que el Input) evita el
// bug, aunque esto YA NO coincide byte a byte con el descriptor del hardware
// real - no importa, ningun host valida la ESTRUCTURA de colecciones, solo
// el report_id numerico al pedir GET_FEATURE via control transfer.
//
// LED: rojo = ready()=false, verde = ready()=true.

#include "USB.h"
#include "USBHID.h"

static const uint8_t DS3_DESCRIPTOR[] = {
  // --- Input, ID 1, SOLO (igual a ds3_input_only_test.ino) ---
  0x05, 0x01, 0x09, 0x04, 0xA1, 0x01, 0xA1, 0x02, 0x85, 0x01, 0x75, 0x08, 0x95, 0x01, 0x15, 0x00, 0x26, 0xFF, 0x00,
  0x81, 0x03, 0x75, 0x01, 0x95, 0x13, 0x15, 0x00, 0x25, 0x01, 0x35, 0x00, 0x45, 0x01, 0x05, 0x09, 0x19, 0x01, 0x29,
  0x13, 0x81, 0x02, 0x75, 0x01, 0x95, 0x0D, 0x06, 0x00, 0xFF, 0x81, 0x03, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x05, 0x01,
  0x09, 0x01, 0xA1, 0x00, 0x75, 0x08, 0x95, 0x04, 0x35, 0x00, 0x46, 0xFF, 0x00, 0x09, 0x30, 0x09, 0x31, 0x09, 0x32,
  0x09, 0x35, 0x81, 0x02, 0xC0, 0x05, 0x01, 0x75, 0x08, 0x95, 0x27, 0x09, 0x01, 0x81, 0x02,
  0xC0,  // cierra la coleccion "A1 02" del Input id1
  // --- Feature, ID 1, en bloque SIBLING SEPARADO (mismo patron que 0x02/0xEE/0xEF) ---
  0xA1, 0x02, 0x85, 0x01, 0x75, 0x08, 0x95, 0x30, 0x09, 0x01, 0xB1, 0x02, 0xC0,
  0xC0,  // cierra la coleccion Application
};

class DS3Sep : public USBHIDDevice {
public:
  DS3Sep() : hid() {
    static bool initialized = false;
    if (!initialized) {
      initialized = true;
      hid.addDevice(this, sizeof(DS3_DESCRIPTOR));
    }
  }

  void begin() {
    hid.begin();
  }

  uint16_t _onGetDescriptor(uint8_t *dst) override {
    memcpy(dst, DS3_DESCRIPTOR, sizeof(DS3_DESCRIPTOR));
    return sizeof(DS3_DESCRIPTOR);
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

DS3Sep ds3;

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
