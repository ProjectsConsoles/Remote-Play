// Prueba minima: confirmar que el puerto USB nativo/OTG del ESP32-S3 funciona
// como dispositivo HID de verdad (no solo como puerto serie).
//
// Que hace: mueve el cursor del mouse 5px a la derecha y 5px a la izquierda,
// una vez por segundo, mientras el ESP32-S3 este conectado por su puerto USB
// NATIVO (no el de programacion/COM) a la Deck o PC.
//
// Requisito en el IDE antes de subir: Herramientas > USB Mode > "USB-OTG (TinyUSB)"
// (con el modo default "Hardware CDC and JTAG" esto NO va a funcionar).
//
// Si despues de subir el cursor del mouse se mueve solo, confirma que el modo
// USB-OTG/TinyUSB anda y ya podemos pasar al descriptor completo del DS3.

#include "USB.h"
#include "USBHIDMouse.h"

USBHIDMouse Mouse;

void setup() {
  Mouse.begin();
  USB.begin();
}

void loop() {
  Mouse.move(5, 0);
  delay(1000);
  Mouse.move(-5, 0);
  delay(1000);
}
