// (2026-08-28) Sketch de diagnostico: descriptor DS3 reducido al MINIMO -
// SOLO el reporte de Input (ID 1, 48 bytes: botones+ejes+presion), SIN
// ningun bloque de Output ni Feature (a diferencia de ds3_wifi_debug_test.ino
// y ds3_controller.ino, que tienen ademas Output ID1 + Feature reports
// 0x01/0x02/0xEE/0xEF/F1/F2/F4/F5/F7/F8). Objetivo: aislar si esos bloques
// extra son la causa de que hid.ready() de siempre false y sendInputReport()
// falle el 100% de las veces (confirmado en AMBOS archivos completos, en
// Linux, incluso con datos reales de un boton fisico sostenido y despues de
// un power-cycle completo). USBHIDMouse (sin Output/Feature, un solo reporte
// Input) SI logra mandar datos con exito en esta misma placa - este test
// aisla si la diferencia es justamente la presencia de Output/Feature.
//
// Si ESTE sketch SI logra ready()=1 y sendInputReport() con exito: confirma
// que el problema es tener Output/Feature reports junto con el Input en el
// mismo descriptor - hay que investigar por que y como evitarlo sin perder
// esa funcionalidad (los feature reports 0xF2/0xF4/etc son necesarios para
// que el PS3 real valide el dispositivo, asi que no se pueden sacar del
// firmware final - pero al menos confirma la causa exacta).
//
// Si este sketch TAMBIEN falla igual: el problema es otra cosa (candidatos:
// algo del multi-report-ID en si aunque sean solo Input, o algo de como se
// llama a SendReport con el buffer de 48 bytes).

#include "USB.h"
#include "USBHID.h"

static const uint8_t DS3_INPUT_ONLY_DESCRIPTOR[] = {
  0x05, 0x01, 0x09, 0x04, 0xA1, 0x01, 0xA1, 0x02, 0x85, 0x01, 0x75, 0x08, 0x95, 0x01, 0x15, 0x00, 0x26, 0xFF, 0x00,
  0x81, 0x03, 0x75, 0x01, 0x95, 0x13, 0x15, 0x00, 0x25, 0x01, 0x35, 0x00, 0x45, 0x01, 0x05, 0x09, 0x19, 0x01, 0x29,
  0x13, 0x81, 0x02, 0x75, 0x01, 0x95, 0x0D, 0x06, 0x00, 0xFF, 0x81, 0x03, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x05, 0x01,
  0x09, 0x01, 0xA1, 0x00, 0x75, 0x08, 0x95, 0x04, 0x35, 0x00, 0x46, 0xFF, 0x00, 0x09, 0x30, 0x09, 0x31, 0x09, 0x32,
  0x09, 0x35, 0x81, 0x02, 0xC0, 0x05, 0x01, 0x75, 0x08, 0x95, 0x27, 0x09, 0x01, 0x81, 0x02,
  0xC0,
  0xC0,
};

class DS3InputOnly : public USBHIDDevice {
public:
  DS3InputOnly() : hid() {
    static bool initialized = false;
    if (!initialized) {
      initialized = true;
      hid.addDevice(this, sizeof(DS3_INPUT_ONLY_DESCRIPTOR));
    }
  }

  void begin() {
    hid.begin();
  }

  uint16_t _onGetDescriptor(uint8_t *dst) override {
    memcpy(dst, DS3_INPUT_ONLY_DESCRIPTOR, sizeof(DS3_INPUT_ONLY_DESCRIPTOR));
    return sizeof(DS3_INPUT_ONLY_DESCRIPTOR);
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

DS3InputOnly ds3;

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
    // Alterna dpad izquierda cada segundo (cambio de valor garantizado).
    static bool left = false;
    left = !left;
    if (left) {
      report[1] |= (1 << 7);
      report[17] = 255;
    }
    ds3.sendInputReport(report);
  }
}
