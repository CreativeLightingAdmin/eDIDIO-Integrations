// eDIDIO lighting from an ESP32 / ESP8266 (or Ethernet-equipped Arduino).
//
// Connects over Wi-Fi/TCP to an eDIDIO controller and drives lights from GPIO
// buttons / sensors. This example: a button on GPIO 0 recalls a scene, and a
// PIR/motion sensor on GPIO 4 turns a group on; both send eDIDIO frames built by
// the zero-dependency EdidioFrames encoder.
//
// Boards: ESP32 / ESP8266 (WiFi). For a wired Arduino use the Ethernet library
// and an EthernetClient instead of WiFiClient.

#include <WiFi.h>          // ESP32. For ESP8266 use <ESP8266WiFi.h>
#include "EdidioFrames.h"

const char* WIFI_SSID = "your-ssid";
const char* WIFI_PASS = "your-password";
const char* EDIDIO_HOST = "192.168.1.50";
const uint16_t EDIDIO_PORT = 23;

const int BUTTON_PIN = 0;   // recall scene
const int MOTION_PIN = 4;   // turn a group on

WiFiClient client;
int32_t messageId = 0;
unsigned long lastKeepAlive = 0;

int32_t nextId() { messageId = (messageId + 1) & 0xFFFFFF; return messageId; }

bool ensureConnected() {
  if (client.connected()) return true;
  return client.connect(EDIDIO_HOST, EDIDIO_PORT);
}

void sendFrame(const uint8_t* buf, size_t n) {
  if (n > 0 && ensureConnected()) client.write(buf, n);
}

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(MOTION_PIN, INPUT);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(250); Serial.print("."); }
  Serial.println("\nWiFi connected");
  ensureConnected();
}

void loop() {
  uint8_t buf[64];

  // Button (active low) -> recall scene 3 on line 1.
  static int lastButton = HIGH;
  int button = digitalRead(BUTTON_PIN);
  if (lastButton == HIGH && button == LOW) {
    size_t n = edidio::daliBroadcastScene(buf, sizeof(buf), nextId(), edidio::lineMask(1), 3);
    sendFrame(buf, n);
    Serial.println("scene 3");
  }
  lastButton = button;

  // Motion -> group 0 to full on line 1.
  static int lastMotion = LOW;
  int motion = digitalRead(MOTION_PIN);
  if (lastMotion == LOW && motion == HIGH) {
    size_t n = edidio::daliGroupArcLevel(buf, sizeof(buf), nextId(), edidio::lineMask(1), 0, 254);
    sendFrame(buf, n);
    Serial.println("motion -> group on");
  }
  lastMotion = motion;

  // Keep-alive every 7 s.
  if (millis() - lastKeepAlive > 7000) {
    if (client.connected()) client.write(edidio::KEEP_ALIVE, 2);
    lastKeepAlive = millis();
  }

  delay(20);
}
