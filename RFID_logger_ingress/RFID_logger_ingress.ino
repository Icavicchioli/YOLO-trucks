/*
  RFID Logger (Single Reader) - INGRESS
  Arduino Nano + 1 x MFRC522 (RC522)

  Wiring (Arduino Nano):
    - SCK  -> D13  [level shift 5V->3.3V]
    - MISO -> D12  [direct]
    - MOSI -> D11  [level shift 5V->3.3V]
    - SS   -> D10  [level shift 5V->3.3V]
    - RST  -> D9   [level shift 5V->3.3V]
    - 3.3V -> 3.3V (stable regulator recommended)
    - GND  -> GND

  Serial output (115200):
    INGRESS,<UID_HEX>

  Note:
  - Avoid MOSFET bidirectional shifters (e.g., HW-221 BSS138) on SPI; use unidirectional shifting
    (CD4504B / 74LVC / fast resistor dividers like 1k series + 2k to GND).
*/

#include <SPI.h>
#include <MFRC522.h>

constexpr byte SS_PIN = 10;
constexpr byte RST_PIN = 9;
constexpr const char *EVENT_NAME = "INGRESS";

constexpr unsigned long DUPLICATE_BLOCK_MS = 1200;
constexpr byte SPI_CLOCK_DIV = SPI_CLOCK_DIV16;

#ifndef RFID_DEBUG
#define RFID_DEBUG 0
#endif

MFRC522 reader(SS_PIN, RST_PIN);

String lastUid = "";
unsigned long lastTs = 0;
bool readerOk = false;

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
  Serial.begin(115200);
  delay(300);

  SPI.begin();
  SPI.setDataMode(SPI_MODE0);
  SPI.setClockDivider(SPI_CLOCK_DIV);

  pinMode(SS_PIN, OUTPUT);
  digitalWrite(SS_PIN, HIGH);
  pinMode(RST_PIN, OUTPUT);

  Serial.print("Resetting RC522... ");
  digitalWrite(RST_PIN, LOW);
  delay(120);
  digitalWrite(RST_PIN, HIGH);
  delay(120);

  reader.PCD_Init();
  reader.PCD_AntennaOn();
  reader.PCD_SetAntennaGain(MFRC522::RxGain_max);
  printReaderStatus(reader, readerOk);

  Serial.println("RFID_LOGGER_READY");
}

void loop() {
  if (!readerOk) return;

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

