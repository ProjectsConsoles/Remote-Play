// Sketch de diagnostico (2026-08-27): copia de ds3_controller.ino con TODO lo
// de WiFi/UDP/debugLog sacado - solo emula el DS3 por USB, reporte neutro
// (todo en reposo) cada 8ms, sin leer ningun input real. Objetivo: aislar si
// el rechazo del PS3 real ("USB desconocido") es por contencion WiFi/lwIP
// contra TinyUSB durante la enumeracion, o si es puramente un problema de
// descriptor/protocolo (en cuyo caso el PS3 lo va a seguir rechazando igual
// aca, sin WiFi de por medio). No hace falta que funcione como control util -
// solo mirar si el PS3 lo reconoce como "control conectado" o no.
//
// Mismos requisitos de subida que ds3_controller.ino: Board "ESP32S3 Dev
// Module", USB Mode "USB-OTG (TinyUSB)", truco BOOT+RESET para subir,
// conectar por el puerto USB nativo (no el de programacion/COM).

#include "USB.h"
#include "USBHID.h"

// ---------------------------------------------------------------------------
// Descriptor HID del DualShock 3 - identico al de ds3_controller.ino (ver ahi
// el detalle de procedencia/motivo de cada bloque, no repetido aca).
// ---------------------------------------------------------------------------
static const uint8_t DS3_REPORT_DESCRIPTOR[] = {
  0x05, 0x01, 0x09, 0x04, 0xA1, 0x01, 0xA1, 0x02, 0x85, 0x01, 0x75, 0x08, 0x95, 0x01, 0x15, 0x00, 0x26, 0xFF, 0x00,
  0x81, 0x03, 0x75, 0x01, 0x95, 0x13, 0x15, 0x00, 0x25, 0x01, 0x35, 0x00, 0x45, 0x01, 0x05, 0x09, 0x19, 0x01, 0x29,
  0x13, 0x81, 0x02, 0x75, 0x01, 0x95, 0x0D, 0x06, 0x00, 0xFF, 0x81, 0x03, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x05, 0x01,
  0x09, 0x01, 0xA1, 0x00, 0x75, 0x08, 0x95, 0x04, 0x35, 0x00, 0x46, 0xFF, 0x00, 0x09, 0x30, 0x09, 0x31, 0x09, 0x32,
  0x09, 0x35, 0x81, 0x02, 0xC0, 0x05, 0x01, 0x75, 0x08, 0x95, 0x27, 0x09, 0x01, 0x81, 0x02, 0x75, 0x08, 0x95, 0x30,
  0x09, 0x01, 0x91, 0x02, 0x75, 0x08, 0x95, 0x30, 0x09, 0x01, 0xB1, 0x02, 0xC0, 0xA1, 0x02, 0x85, 0x02, 0x75, 0x08,
  0x95, 0x30, 0x09, 0x01, 0xB1, 0x02, 0xC0, 0xA1, 0x02, 0x85, 0xEE, 0x75, 0x08, 0x95, 0x30, 0x09, 0x01, 0xB1, 0x02,
  0xC0, 0xA1, 0x02, 0x85, 0xEF, 0x75, 0x08, 0x95, 0x30, 0x09, 0x01, 0xB1, 0x02, 0xC0,
  0xA1, 0x02, 0x85, 0xF2, 0x75, 0x08, 0x95, 0x10, 0x09, 0x01, 0xB1, 0x02, 0xC0,
  // Feature report 0xF4 (agregado 2026-08-27): quirk clasico de SIXAXIS/DS3 -
  // el control no manda reportes de Input "en serio" hasta que el host le
  // hace SET_FEATURE(0xF4) con un payload de 4 bytes (el famoso
  // {0x42,0x0c,0x00,0x00} documentado en hid-sony.c y en practicamente todo
  // driver de Sixaxis). Sin declarar este report ID, TinyUSB hace STALL del
  // SET_FEATURE antes de que llegue a _onSetFeature() - mismo problema que
  // tuvo 0xF2 al principio. No hace falta interpretar el payload: alcanza con
  // que el descriptor lo declare para que el host no se quede bloqueado.
  0xA1, 0x02, 0x85, 0xF4, 0x75, 0x08, 0x95, 0x04, 0x09, 0x01, 0xB1, 0x02, 0xC0,
  0xC0,
};

class DS3Controller : public USBHIDDevice {
public:
  DS3Controller() : hid() {
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
    Serial.printf("GET_DESCRIPTOR (HID Report), %u bytes\n", (unsigned)sizeof(DS3_REPORT_DESCRIPTOR));
    memcpy(dst, DS3_REPORT_DESCRIPTOR, sizeof(DS3_REPORT_DESCRIPTOR));
    return sizeof(DS3_REPORT_DESCRIPTOR);
  }

  uint16_t _onGetFeature(uint8_t report_id, uint8_t *buffer, uint16_t len) override {
    Serial.printf("GET_FEATURE id=0x%02X len=%u\n", report_id, len);
    if (report_id == 0x01 || report_id == 0x02 || report_id == 0xEE || report_id == 0xEF) {
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
    Serial.printf("SET_FEATURE id=0x%02X len=%u\n", report_id, len);
  }

  void _onOutput(uint8_t report_id, const uint8_t *buffer, uint16_t len) override {
    Serial.printf("OUTPUT id=0x%02X len=%u\n", report_id, len);
  }

  bool sendInputReport(const uint8_t *data48) {
    return hid.SendReport(0x01, data48, 48);
  }

protected:
  USBHID hid;
};

DS3Controller ds3;

void setup() {
  Serial.begin(115200);

  USB.VID(0x054C);
  USB.PID(0x0268);
  USB.manufacturerName("Sony Computer Entertainment Inc.");
  USB.productName("PLAYSTATION(R)3 Controller");
  USB.serialNumber("SN00000000");
  USB.usbClass(0x00);
  USB.usbSubClass(0x00);
  USB.usbProtocol(0x00);

  ds3.begin();
  USB.begin();
  Serial.println("USB DS3 (sin WiFi) iniciado");
}

unsigned long lastSend = 0;
unsigned long lastToggle = 0;
bool dpadRightPressed = false;

// Confirmacion visual sin necesitar WiFi/Deck: cada 2s alterna D-pad derecha
// presionado/soltado (bit DS3_RIGHT = bit 5 del primer byte de botones,
// offset 1 del reporte de 48 - ver enum DS3Bit en ds3_controller.ino). Si el
// PS3 lo reconoce, el cursor de la XMB se deberia mover solo cada 2s.
// Igual que con un DS3 real (aun ya emparejado por Bluetooth), el PS3 suele
// necesitar un toque del boton PS para "activar" el control en la sesion
// actual - conectarlo por USB solo no alcanza siempre. Se simula un toque
// unico de PS (apretado 3s-3.5s despues de arrancar, soltado despues) antes
// de empezar con el toggle de D-pad derecha, para probar esa hipotesis en la
// misma corrida.
void loop() {
  unsigned long now = millis();

  bool psPressed = (now >= 3000 && now < 3500);

  if (now >= 5000 && now - lastToggle >= 2000) {
    lastToggle = now;
    dpadRightPressed = !dpadRightPressed;
  }

  if (now - lastSend >= 8) {
    lastSend = now;
    uint8_t report[48] = { 0 };
    report[5] = report[6] = report[7] = report[8] = 128;  // sticks centrados
    if (psPressed) {
      report[3] |= (1 << 0);  // DS3_PS (bit 16 del bitfield -> byte offset 3, bit 0)
    }
    if (dpadRightPressed) {
      report[1] |= (1 << 5);  // DS3_RIGHT
      report[15] = 255;       // offset de presion analogica de RIGHT (ver DS3_PRESSURE_OFFSET en ds3_controller.ino)
    }
    ds3.sendInputReport(report);
  }
}
