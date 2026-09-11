// Sketch de diagnostico: SOLO WiFi + UDP + Serial, sin USB HID (USB.h/USBHID).
// Objetivo: descartar si el stack USB-OTG (TinyUSB) de ds3_controller.ino
// interfiere con la recepcion de paquetes UDP (el ping SI llega al ESP32 en
// esa configuracion, pero ningun paquete UDP explicito llega nunca a
// udp.parsePacket() - ver conversacion). Este sketch usa el mismo SSID/
// password/puerto para poder comparar en igualdad de condiciones.
//
// Requisitos en el IDE antes de subir:
//  - Herramientas > Board: "ESP32S3 Dev Module"
//  - Herramientas > USB Mode: da igual, este sketch no usa USB nativo custom -
//    dejar en "Hardware CDC and JTAG" (el default) para que el auto-reset al
//    subir funcione solo, sin el truco BOOT+RESET.
//  - Conectar por el puerto "COM" (el mismo que se uso para ver el Monitor
//    Serie de ds3_controller.ino).

#include <WiFi.h>
#include <WiFiUdp.h>

const char *WIFI_SSID = "TU_RED_WIFI_2.4GHZ";
const char *WIFI_PASSWORD = "TU_CONTRASENA_WIFI";
const uint16_t UDP_PORT = 9000;

WiFiUDP udp;
char udpBuffer[512];
unsigned long packetsReceived = 0;
unsigned long lastHeartbeat = 0;

void setup() {
  Serial.begin(115200);
  delay(1000);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Conectando WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nWiFi OK, IP: %s\n", WiFi.localIP().toString().c_str());

  bool ok = udp.begin(UDP_PORT);
  Serial.printf("udp.begin(%u) devolvio: %s\n", UDP_PORT, ok ? "true" : "false");
}

void loop() {
  int packetSize = udp.parsePacket();
  if (packetSize > 0) {
    int len = udp.read(udpBuffer, sizeof(udpBuffer) - 1);
    if (len > 0) {
      udpBuffer[len] = '\0';
      packetsReceived++;
      Serial.printf("UDP #%lu de %s:%u, %d bytes: %s\n", packetsReceived,
                     udp.remoteIP().toString().c_str(), udp.remotePort(), len, udpBuffer);
    }
  }

  unsigned long now = millis();
  if (now - lastHeartbeat >= 2000) {
    lastHeartbeat = now;
    Serial.printf("[heartbeat] wifi=%d paquetes recibidos=%lu\n", WiFi.status(), packetsReceived);
  }
}
