// (2026-08-28) Sketch de diagnostico: bypasea POR COMPLETO el wrapper
// Arduino USBHID/USBHIDDevice (libraries/USB/src/USBHID.cpp del core), que
// se confirmo en esta sesion como la causa de que hid.ready() quede
// permanentemente atascado en false apenas el descriptor HID tiene CUALQUIER
// Feature report (probado con LED rojo/verde en 3 sketches previos,
// reproducido igual en core 3.3.11 y 2.0.13 - no es un problema de version
// del core). En vez de USBHID::SendReport()/USBHIDDevice::_onGetFeature(),
// este sketch llama directo a la API de TinyUSB (tud_hid_n_ready(),
// tud_hid_n_report()) e implementa el mismo los callbacks weak/obligatorios
// (tud_hid_descriptor_report_cb, tud_hid_get_report_cb,
// tud_hid_set_report_cb) sin la capa intermedia de USBHID.cpp
// (tinyusb_get_device_by_report_id() y su restriccion de "solo report IDs
// parseados del descriptor"). Es el mismo enfoque que usa la implementacion
// de referencia `droidshock3` en Android/Linux via FunctionFS (confirmada
// funcionando contra un PS3 real) - responder directo a nivel bajo, sin
// restriccion de una capa intermedia.
//
// IMPORTANTE: NO incluir "USBHID.h" en este sketch - eso compilaria y
// linkearia USBHID.cpp, que ya define tud_hid_descriptor_report_cb/
// tud_hid_get_report_cb/tud_hid_set_report_cb como simbolos FUERTES (no
// weak) -> error de simbolo duplicado con las versiones de este sketch.
//
// LED: rojo = tud_hid_ready()==false, verde = true (mismo patron que los
// sketches de diagnostico anteriores, para iterar rapido sin depender de
// WiFi/log).

#include "USB.h"
#include "esp32-hal-tinyusb.h"

// Descriptor EXACTO del DS3 real (148 bytes), dump obtenido con
// ioctl(HIDIOCGRDESC) de un DS3 fisico conectado por USB a la Deck
// (2026-08-28, ver memoria del proyecto). A diferencia de los sketches
// anteriores, NO hace falta declarar F1/F2/F4/F5/F7/F8 aparte para que nos
// lleguen los pedidos - con esta implementacion "cruda" (sin la capa
// USBHID.cpp que restringe el ruteo a IDs declarados/parseados),
// tud_hid_get_report_cb/tud_hid_set_report_cb ya reciben CUALQUIER
// report_id que pida el host, este o no declarado en el descriptor -
// exactamente igual que como responde el DS3 real (que tampoco declara
// 0xF2 en su propio descriptor, confirmado en el dump).
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

// --- Callbacks TinyUSB, implementados directo (sin USBHID.cpp) ---

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
  // 0x01, 0x02, 0xEE, 0xEF y cualquier otro report_id: devolver ceros. No
  // hace falta filtrar por ID conocido - a diferencia de USBHID.cpp, aca no
  // hay restriccion de "solo lo declarado", asi que respondemos CUALQUIER
  // GET_FEATURE que llegue en vez de dejarlo silenciosamente sin log.
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
  // Rumble/LED (Output) y SET_FEATURE (ej. 0xF4) llegan aca. Por ahora solo
  // se ignoran - suficiente para esta prueba de diagnostico.
}

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

  tinyusb_enable_interface(USB_INTERFACE_HID, TUD_HID_INOUT_DESC_LEN, ds3_hid_load_descriptor);
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
    bool ready = tud_hid_ready();
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
    if (ready) {
      tud_hid_report(0x01, report, 48);
    }
  }
}
