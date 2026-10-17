// Wiring finder: I2C scan + LCD test, analog readings, digital activity, ultrasonic pin search.
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("=== DIAG START ===");
  Wire.begin();
  int lcdAddr = 0;
  Serial.print("I2C:");
  for (byte a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { Serial.print(" 0x"); Serial.print(a, HEX); if (!lcdAddr && (a == 0x27 || a == 0x3F || (a >= 0x20 && a <= 0x27) || (a >= 0x38 && a <= 0x3F))) lcdAddr = a; }
  }
  Serial.println();
  if (lcdAddr) {
    LiquidCrystal_I2C lcd(lcdAddr, 16, 2);
    lcd.init(); lcd.backlight();
    lcd.setCursor(0, 0); lcd.print("LCD OK  0x"); lcd.print(lcdAddr, HEX);
    lcd.setCursor(0, 1); lcd.print("finding wiring..");
  }
  Serial.print("LCD_ADDR "); Serial.println(lcdAddr, HEX);

  for (int p = 2; p <= 13; p++) pinMode(p, INPUT);
  // passive: count edges on each digital pin for 3 s
  int last[14], edges[14];
  for (int p = 2; p <= 13; p++) { last[p] = digitalRead(p); edges[p] = 0; }
  unsigned long t0 = millis();
  while (millis() - t0 < 3000) for (int p = 2; p <= 13; p++) { int v = digitalRead(p); if (v != last[p]) { edges[p]++; last[p] = v; } }
  Serial.print("DIGITAL idle/edges:");
  for (int p = 2; p <= 13; p++) { Serial.print(" D"); Serial.print(p); Serial.print('='); Serial.print(last[p]); Serial.print('/'); Serial.print(edges[p]); }
  Serial.println();
  // with pullups (finds open-collector flow sensor + buzzer modules)
  Serial.print("PULLUP idle:");
  for (int p = 2; p <= 13; p++) { pinMode(p, INPUT_PULLUP); delay(2); Serial.print(" D"); Serial.print(p); Serial.print('='); Serial.print(digitalRead(p)); pinMode(p, INPUT); }
  Serial.println();
  Serial.print("ANALOG:");
  const int ap[6] = {A0, A1, A2, A3, A4, A5};
  for (int i = 0; i < 6; i++) { long s = 0; for (int k = 0; k < 16; k++) s += analogRead(ap[i]); Serial.print(" A"); Serial.print(i); Serial.print('='); Serial.print(s / 16); }
  Serial.println();
  // active ultrasonic search: 10 us pulse on each candidate TRIG, look for an echo on every other pin
  Serial.print("SONAR:");
  int found = 0;
  for (int trig = 2; trig <= 13 && !found; trig++) {
    for (int echo = 2; echo <= 13; echo++) {
      if (echo == trig || last[echo] == 1) continue;
      pinMode(trig, OUTPUT);
      digitalWrite(trig, LOW); delayMicroseconds(4);
      digitalWrite(trig, HIGH); delayMicroseconds(10); digitalWrite(trig, LOW);
      unsigned long us = pulseIn(echo, HIGH, 30000UL);
      pinMode(trig, INPUT);
      if (us > 100) { Serial.print(" trig=D"); Serial.print(trig); Serial.print(" echo=D"); Serial.print(echo); Serial.print(" cm="); Serial.print(us * 0.0343 / 2, 1); found = 1; break; }
      delay(5);
    }
  }
  if (!found) Serial.print(" none");
  Serial.println();
  Serial.println("=== DIAG END ===");
}

void loop() { delay(6000); setup(); }
