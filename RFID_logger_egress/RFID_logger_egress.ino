/*
  RFID Logger (Single Reader) - EGRESS
  NodeMCU LoLin V3 (ESP8266) + 1 x MFRC522 (RC522)

  Wiring (NodeMCU LoLin V3):
    - SCK  -> D5  (GPIO14)
    - MISO -> D6  (GPIO12)
    - MOSI -> D7  (GPIO13)
    - SS   -> D8  (GPIO15)  <- CS / SDA for RC522 (recommended)
    - RST  -> D3  (GPIO0)   <- reset line (can also use D4 but ensure proper boot state)
    - 3.3V -> 3V3 (stable regulator recommended)
    - GND  -> GND

  Notes:
    - Uses hardware SPI. Do not remap SCK/MOSI/MISO.
    - SS must be D8 (GPIO15) if you want the common wiring that avoids SPI/boot issues.
*/

#include <SPI.h>
#include <MFRC522.h>

// Use NodeMCU Dx labels for clarity
constexpr uint8_t SS_PIN  = D8; // SDA/SS -> D8 (GPIO15)
constexpr uint8_t RST_PIN = D3; // RST   -> D3 (GPIO0)

constexpr const char *EVENT_NAME = "EGRESS";
constexpr unsigned long DUPLICATE_BLOCK_MS = 1200;

#ifndef RFID_DEBUG
#define RFID_DEBUG 0
#endif

MFRC522 reader(SS_PIN, RST_PIN);

String uidToHex(const MFRC522::Uid &uid) {
  String out = "";
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) out += "0";
    out += String(uid.uidByte[i], HEX);
  }
  out.toUpperCase();
  return out;
}

void haltReader(MFRC522 &r) {
  r.PICC_HaltA();
  r.PCD_StopCrypto1();
}

void printReaderStatus(MFRC522 &r, bool &okFlag) {
  byte version = r.PCD_ReadRegister(MFRC522::VersionReg);
  okFlag = !(version == 0x00 || version == 0xFF);

  Serial.print("RC522 VersionReg=0x");
  if (version < 0x10) Serial.print("0");
  Serial.print(version, HEX);
  Serial.print(" -> ");
  Serial.println(okFlag ? "OK" : "NO_REPLY");
}

void setup() {
  Serial.begin(9600);
  delay(300);

  // Initialize SPI (hardware SPI pins on NodeMCU are fixed: D5/D6/D7)
  SPI.begin();                      // SCK = D5, MISO = D6, MOSI = D7
  SPI.setDataMode(SPI_MODE0);
  SPI.setFrequency(4000000);        // 4 MHz (adjust if needed)

  pinMode(SS_PIN, OUTPUT);
  digitalWrite(SS_PIN, HIGH); // deselect RC522
  pinMode(RST_PIN, OUTPUT);

  // Hardware reset of RC522
  Serial.print("Resetting RC522... ");
  digitalWrite(RST_PIN, LOW);
  delay(120);
  digitalWrite(RST_PIN, HIGH);
  delay(120);

  reader.PCD_Init();
  reader.PCD_AntennaOn();
  reader.PCD_SetAntennaGain(MFRC522::RxGain_max);

  bool readerOk = false;
  printReaderStatus(reader, readerOk);

  if (!readerOk) {
    Serial.println("RFID_LOGGER_NO_READER");
  } else {
    Serial.println("RFID_LOGGER_READY");
  }
}

String lastUid = "";
unsigned long lastTs = 0;

void loop() {
  // If reader not responding, skip polling (but we didn't keep persistent flag here)
  // Standard flow:
  if (!reader.PICC_IsNewCardPresent()) return;
  if (!reader.PICC_ReadCardSerial()) {
    if (RFID_DEBUG) Serial.println("READ_FAIL");
    return;
  }

  String uid = uidToHex(reader.uid);
  unsigned long now = millis();

  if (uid != lastUid || (now - lastTs) > DUPLICATE_BLOCK_MS) {
    Serial.print(EVENT_NAME);
    Serial.print(",");
    Serial.println(uid);
    lastUid = uid;
    lastTs = now;
  }

  haltReader(reader);
  delay(5);
}