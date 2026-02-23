/*
  RFID Logger MVP - Arduino Nano + 1 x MFRC522

  Wiring (Arduino Nano):
    - SCK  -> D13
    - MISO -> D12
    - MOSI -> D11
    - SDA/SS -> D10
    - RST    -> D9
    - GND  -> GND
    - 3.3V -> 3.3V

  Serial output format (115200):
    INGRESS,<UID_HEX>

  Notes:
  - RC522 is 3.3V only.
  - Use level shifting from Nano 5V outputs to RC522 3.3V inputs.
*/

#include <SPI.h>
#include <MFRC522.h>

constexpr byte SS_PIN  = 10;
constexpr byte RST_PIN = 9;

constexpr unsigned long DUPLICATE_BLOCK_MS = 1200;

MFRC522 reader(SS_PIN, RST_PIN);

String lastUid = "";
unsigned long lastTs = 0;

String uidToHex(const MFRC522::Uid &uid) {
  String out = "";
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) out += "0";
    out += String(uid.uidByte[i], HEX);
  }
  out.toUpperCase();
  return out;
}

void setup() {
  Serial.begin(115200);
  SPI.begin();
  reader.PCD_Init();
  byte v = reader.PCD_ReadRegister(MFRC522::VersionReg);
  Serial.print("RC522 version: 0x");
  Serial.println(v, HEX);
  Serial.println("RFID_LOGGER_READY");
}

void loop() {
  if (!reader.PICC_IsNewCardPresent()) return;
  if (!reader.PICC_ReadCardSerial()) return;

  String uid = uidToHex(reader.uid);
  unsigned long now = millis();

  if (uid != lastUid || (now - lastTs) > DUPLICATE_BLOCK_MS) {
    Serial.print("INGRESS,");
    Serial.println(uid);
    lastUid = uid;
    lastTs = now;
  }

  reader.PICC_HaltA();
  reader.PCD_StopCrypto1();
}
