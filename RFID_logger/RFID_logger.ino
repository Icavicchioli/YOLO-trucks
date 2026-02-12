/*
  RFID Logger MVP - Arduino Mega + 2 x MFRC522

  Wiring (Arduino Mega):
  Shared SPI lines (both readers):
    - SCK  -> D52
    - MISO -> D50
    - MOSI -> D51
    - GND  -> GND
    - 3.3V -> 3.3V

  Reader A (INGRESS):
    - SDA/SS -> D5
    - RST    -> D7

  Reader B (EGRESS):
    - SDA/SS -> D6
    - RST    -> D8

  Serial output format (115200):
    INGRESS,<UID_HEX>
    EGRESS,<UID_HEX>

  Notes:
  - RC522 is 3.3V only.
  - Prefer level shifting from Mega 5V outputs to RC522 3.3V inputs.
*/

#include <SPI.h>
#include <MFRC522.h>

constexpr byte SS_INGRESS = 5;
constexpr byte RST_INGRESS = 7;
constexpr byte SS_EGRESS = 6;
constexpr byte RST_EGRESS = 8;

constexpr unsigned long DUPLICATE_BLOCK_MS = 1200;

MFRC522 readerIngress(SS_INGRESS, RST_INGRESS);
MFRC522 readerEgress(SS_EGRESS, RST_EGRESS);

String lastIngressUid = "";
String lastEgressUid = "";
unsigned long lastIngressTs = 0;
unsigned long lastEgressTs = 0;

String uidToHex(const MFRC522::Uid &uid) {
  String out = "";
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) out += "0";
    out += String(uid.uidByte[i], HEX);
  }
  out.toUpperCase();
  return out;
}

void haltReader(MFRC522 &reader) {
  reader.PICC_HaltA();
  reader.PCD_StopCrypto1();
}

void pollReader(MFRC522 &reader, const char *eventName, String &lastUid, unsigned long &lastTs) {
  if (!reader.PICC_IsNewCardPresent()) return;
  if (!reader.PICC_ReadCardSerial()) return;

  String uid = uidToHex(reader.uid);
  unsigned long now = millis();

  if (uid != lastUid || (now - lastTs) > DUPLICATE_BLOCK_MS) {
    Serial.print(eventName);
    Serial.print(",");
    Serial.println(uid);
    lastUid = uid;
    lastTs = now;
  }

  haltReader(reader);
}

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    ; // Wait for serial on boards that require it.
  }

  SPI.begin();
  readerIngress.PCD_Init();
  readerEgress.PCD_Init();

  Serial.println("RFID_LOGGER_READY");
}

void loop() {
  pollReader(readerIngress, "INGRESS", lastIngressUid, lastIngressTs);
  pollReader(readerEgress, "EGRESS", lastEgressUid, lastEgressTs);
}
