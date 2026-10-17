// Bit-banged I2C scan on A4/A5 in both orientations (finds swapped SDA/SCL wires).
int SDA_P, SCL_P;
void hi(int p){ pinMode(p, INPUT); }            // released: pull-up on the LCD backpack lifts it
void lo(int p){ pinMode(p, OUTPUT); digitalWrite(p, LOW); }
void d(){ delayMicroseconds(10); }
void start(){ hi(SDA_P); hi(SCL_P); d(); lo(SDA_P); d(); lo(SCL_P); d(); }
void stop(){ lo(SDA_P); d(); hi(SCL_P); d(); hi(SDA_P); d(); }
bool writeByte(uint8_t b){
  for (int i = 7; i >= 0; i--) { if (b & (1 << i)) hi(SDA_P); else lo(SDA_P); d(); hi(SCL_P); d(); lo(SCL_P); d(); }
  hi(SDA_P); d(); hi(SCL_P); d(); bool ack = digitalRead(SDA_P) == LOW; lo(SCL_P); d();
  return ack;
}
void scan(int sda, int scl, const char* name){
  SDA_P = sda; SCL_P = scl;
  Serial.print(name); Serial.print(" idle SDA="); hi(sda); hi(scl); delay(2);
  Serial.print(digitalRead(sda)); Serial.print(" SCL="); Serial.print(digitalRead(scl)); Serial.print(" found:");
  int n = 0;
  for (uint8_t a = 1; a < 127; a++) { start(); bool ack = writeByte(a << 1); stop(); if (ack) { Serial.print(" 0x"); Serial.print(a, HEX); n++; } }
  if (!n) Serial.print(" none");
  Serial.println();
}
void setup(){ Serial.begin(115200); }
void loop(){
  scan(A4, A5, "normal  (SDA=A4 SCL=A5)");
  scan(A5, A4, "swapped (SDA=A5 SCL=A4)");
  Serial.println("---");
  delay(3000);
}
