/*
  pin_voltage_test.ino
  Test mínimo para verificar tensión lógica en LOLIN / NodeMCU (ESP8266 / ESP32)

  Qué hace:
    - Imprime por Serial la tensión de VCC (ESP8266) o 3.3V fijo (ESP32)
    - Pone D2 en HIGH → medís con multímetro, tiene que dar ~3.3V
    - Pone D2 en LOW  → medís con multímetro, tiene que dar ~0V
    - Parpadea el LED built-in como señal de vida

  Cómo usar:
    1. Subir el sketch
    2. Abrir Serial Monitor a 115200 baud
    3. Medir con multímetro entre D2 y GND mientras imprime
*/

// ---- ESP8266: lee VCC real del regulador ----
#ifdef ESP8266
  ADC_MODE(ADC_VCC);
#endif

#define TEST_PIN  2   // D2 en D1 Mini / NodeMCU — cambiá si necesitás otro pin
#define LED_BUILTIN_PIN LED_BUILTIN

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(TEST_PIN, OUTPUT);
  pinMode(LED_BUILTIN_PIN, OUTPUT);

  Serial.println("\n=== PIN VOLTAGE TEST ===");

#ifdef ESP8266
  Serial.println("Plataforma: ESP8266");
  float vcc = ESP.getVcc() / 1000.0f;
  Serial.print("VCC medido: ");
  Serial.print(vcc, 3);
  Serial.println(" V  (debería ser ~3.3V)");
#elif defined(ESP32)
  Serial.println("Plataforma: ESP32");
  Serial.println("VCC: 3.3V (fijo en ESP32, verificar con multímetro en pin 3V3)");
#else
  Serial.println("Plataforma: desconocida / AVR");
#endif

  Serial.println("========================");
  Serial.println("Midiendo D2 con multímetro:");
}

void loop() {
  // HIGH
  digitalWrite(TEST_PIN, HIGH);
  digitalWrite(LED_BUILTIN_PIN, LOW);  // LED on (activo bajo en la mayoría)
  Serial.print("D2 = HIGH → medís: ");
  Serial.print(readVccApprox(), 2);
  Serial.println(" V esperado");
  delay(2000);

  // LOW
  digitalWrite(TEST_PIN, LOW);
  digitalWrite(LED_BUILTIN_PIN, HIGH); // LED off
  Serial.println("D2 = LOW  → medís: ~0.00 V esperado");
  delay(2000);
}

// Retorna tensión esperada en HIGH según plataforma
float readVccApprox() {
#ifdef ESP8266
  return ESP.getVcc() / 1000.0f;
#else
  return 3.3f;
#endif
}
