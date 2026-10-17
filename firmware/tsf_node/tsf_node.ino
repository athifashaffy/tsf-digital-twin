/*
  tsf_node.ino — Arduino UNO R4 WiFi acquisition node for the TSF lab rig
  ───────────────────────────────────────────────────────────────────────
  Talks to DATA Server/live_server.py:
    POST /ingest         {"ultrasonic_cm","water_level_pct","flow_lpm","turb_ntu"}
    GET  /buzzer_status  {"buzzer":0|1}

  Pin map (fixes two conflicts in the thesis Appendix A wiring):
    D2  YF-S201 signal       — D4 is NOT interrupt-capable on the UNO R4
    D5  HC-SR04 TRIG
    D6  HC-SR04 ECHO
    D7  IR receiver OUT      (optional, USE_IR)
    D8  Buzzer (+)           (active buzzer; passive also works with tone())
    D9  Water-sensor strip VCC (powered only while reading, slows corrosion)
    A0  SEN0189 turbidity board OUT — A4 is the I2C SDA line used by the LCD
    A1  Water-sensor strip S
    SDA/SCL  16x2 I2C LCD (address 0x27, sometimes 0x3F)

  Libraries: LiquidCrystal_I2C, (optional) IRremote 4.x. WiFiS3 ships with the board package.
*/

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <WiFiS3.h>
#include <EEPROM.h>

#define USE_IR 0            // set to 1 if IRremote is installed and the receiver is wired
#if USE_IR
#include <IRremote.hpp>
#endif

// ── Network ──────────────────────────────────────────────────────────────────
// Set over USB serial (115200 baud), saved in EEPROM so it survives power-off:
//   WIFI:<name>|<password>      e.g. WIFI:HomeNet|secret123
//   SERVER:<ip>:<port>          e.g. SERVER:192.168.1.20:8502
//   STATUS                      prints the saved settings
//   SCAN                        lists the WiFi networks the board can see
struct Config { uint32_t magic; char ssid[33]; char pass[65]; char server[40]; uint16_t port; };
const uint32_t CFG_MAGIC = 0x54534631;   // "TSF1"
Config cfg;

// ── Pins ─────────────────────────────────────────────────────────────────────
const int FLOW_PIN   = 2;
const int TRIG_PIN   = 5;
const int ECHO_PIN   = 6;
const int IR_PIN     = 7;
const int BUZZER_PIN = 8;
const int STRIP_PWR  = 9;
const int TURB_PIN   = A0;
const int STRIP_PIN  = A1;

// ── Rig geometry and calibration (measure these on your rig) ─────────────────
const float SENSOR_TO_FLOOR_CM = 40.0;   // HC-SR04 face to tank floor
const float FLOW_HZ_PER_LPM    = 7.5;    // YF-S201 nominal: f(Hz) = 7.5 × Q(L/min)
const int   STRIP_DRY_RAW      = 0;      // strip reading in air
const int   STRIP_FULL_RAW     = 520;    // strip reading fully submerged

// Turbidity: voltage → NTU pairs from your own kaolin standards, clear water first.
// Placeholder values follow the DFRobot SEN0189 curve; replace after calibrating.
const int   TURB_POINTS = 5;
const float TURB_V[TURB_POINTS]   = {4.20, 4.05, 3.70, 3.10, 2.50};
const float TURB_NTU[TURB_POINTS] = {0,    50,   200,  500,  1000};

// ── Timing ───────────────────────────────────────────────────────────────────
const unsigned long SAMPLE_MS = 1000;    // matches the ~1 s rows in sensor_data.csv
const unsigned long BUZZ_MS   = 2000;

LiquidCrystal_I2C* lcd = nullptr;     // created once the I2C scan finds the backpack
unsigned long lastWifiTry = 0;
volatile unsigned long pulseCount = 0;
unsigned long lastSample = 0, lastBuzz = 0;
bool buzzerOn = false, muted = false;

void flowISR() { pulseCount++; }

// ── Sensors ──────────────────────────────────────────────────────────────────
float readDistanceCm() {
  // median of 5 pings rejects single echoes off ripples or the tank wall
  float v[5];
  for (int i = 0; i < 5; i++) {
    digitalWrite(TRIG_PIN, LOW);  delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);
    unsigned long us = pulseIn(ECHO_PIN, HIGH, 25000UL);
    v[i] = us ? us * 0.0343f / 2.0f : -1;
    delay(30);
  }
  for (int i = 1; i < 5; i++) {               // insertion sort
    float k = v[i]; int j = i - 1;
    while (j >= 0 && v[j] > k) { v[j + 1] = v[j]; j--; }
    v[j + 1] = k;
  }
  return v[2];                                 // −1 means no echo
}

float readFlowLpm(unsigned long elapsedMs) {
  noInterrupts();
  unsigned long n = pulseCount;
  pulseCount = 0;
  interrupts();
  float hz = n * 1000.0f / elapsedMs;
  return hz / FLOW_HZ_PER_LPM;
}

float readTurbidityNtu() {
  long sum = 0;
  for (int i = 0; i < 20; i++) { sum += analogRead(TURB_PIN); delay(2); }
  float volts = (sum / 20.0f) * 5.0f / 1023.0f;
  if (volts >= TURB_V[0]) return TURB_NTU[0];
  for (int i = 1; i < TURB_POINTS; i++) {
    if (volts >= TURB_V[i]) {
      float t = (TURB_V[i - 1] - volts) / (TURB_V[i - 1] - TURB_V[i]);
      return TURB_NTU[i - 1] + t * (TURB_NTU[i] - TURB_NTU[i - 1]);
    }
  }
  return TURB_NTU[TURB_POINTS - 1];
}

float readStripPct() {
  digitalWrite(STRIP_PWR, HIGH);
  delay(10);
  int raw = analogRead(STRIP_PIN);
  digitalWrite(STRIP_PWR, LOW);
  float pct = 100.0f * (raw - STRIP_DRY_RAW) / (float)(STRIP_FULL_RAW - STRIP_DRY_RAW);
  return constrain(pct, 0, 100);
}

// ── Network ──────────────────────────────────────────────────────────────────
void loadConfig() {
  EEPROM.get(0, cfg);
  if (cfg.magic != CFG_MAGIC) { memset(&cfg, 0, sizeof(cfg)); cfg.magic = CFG_MAGIC; cfg.port = 8502; }
}

void saveConfig() { EEPROM.put(0, cfg); }

void handleSerial() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.startsWith("WIFI:")) {
    String v = line.substring(5); int bar = v.indexOf('|');
    String ss = bar < 0 ? v : v.substring(0, bar), pw = bar < 0 ? "" : v.substring(bar + 1);
    ss.toCharArray(cfg.ssid, sizeof(cfg.ssid)); pw.toCharArray(cfg.pass, sizeof(cfg.pass));
    saveConfig(); WiFi.disconnect(); lastWifiTry = 0;
    Serial.print("OK wifi="); Serial.println(cfg.ssid);
  } else if (line.startsWith("SERVER:")) {
    String v = line.substring(7); int colon = v.lastIndexOf(':');
    String ip = colon < 0 ? v : v.substring(0, colon);
    if (colon >= 0) cfg.port = v.substring(colon + 1).toInt();
    ip.toCharArray(cfg.server, sizeof(cfg.server)); saveConfig();
    Serial.print("OK server="); Serial.print(cfg.server); Serial.print(':'); Serial.println(cfg.port);
  } else if (line == "SCAN") {
    Serial.print("wifi module fw "); Serial.print(WiFi.firmwareVersion()); Serial.print(" status "); Serial.println(WiFi.status());
    WiFi.disconnect(); delay(500);
    int n = WiFi.scanNetworks();
    Serial.print("networks: "); Serial.println(n);
    for (int i = 0; i < n; i++) { Serial.print("  "); Serial.print(WiFi.SSID(i)); Serial.print("  rssi="); Serial.println(WiFi.RSSI(i)); }
  } else if (line == "STATUS") {
    Serial.print("wifi="); Serial.print(cfg.ssid); Serial.print(" connected="); Serial.print(WiFi.status() == WL_CONNECTED);
    Serial.print(" ip="); Serial.print(WiFi.localIP()); Serial.print(" server="); Serial.print(cfg.server);
    Serial.print(':'); Serial.print(cfg.port); Serial.print(" lcd="); Serial.println(lcd ? "yes" : "no");
  }
}

void ensureWiFi() {
  if (!cfg.ssid[0] || WiFi.status() == WL_CONNECTED) return;
  if (lastWifiTry && millis() - lastWifiTry < 30000) return;   // retry every 30 s, keep the display live
  lastWifiTry = millis();
  if (cfg.pass[0]) WiFi.begin(cfg.ssid, cfg.pass); else WiFi.begin(cfg.ssid);
}

void lcdLine(int row, const String& text) {
  if (!lcd) return;
  String t = text; while (t.length() < 16) t += ' ';
  lcd->setCursor(0, row); lcd->print(t.substring(0, 16));
}

void initLcd() {
  Wire.begin();
  const byte cands[] = {0x27, 0x3F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x3E};
  for (byte a : cands) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      lcd = new LiquidCrystal_I2C(a, 16, 2);
      lcd->init(); lcd->backlight();
      Serial.print("LCD at 0x"); Serial.println(a, HEX);
      return;
    }
  }
  Serial.println("LCD not found on SDA/SCL");
}

bool postReading(float distCm, float pct, float lpm, float ntu) {
  if (!cfg.server[0] || WiFi.status() != WL_CONNECTED) return false;
  WiFiClient c;
  if (!c.connect(cfg.server, cfg.port)) return false;
  String body = String("{\"ultrasonic_cm\":") + String(distCm, 1) +
                ",\"water_level_pct\":" + String(pct, 0) +
                ",\"flow_lpm\":" + String(lpm, 2) +
                ",\"turb_ntu\":" + String(ntu, 1) + "}";
  c.print("POST /ingest HTTP/1.1\r\nHost: "); c.print(cfg.server);
  c.print("\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: ");
  c.print(body.length()); c.print("\r\n\r\n"); c.print(body);
  unsigned long t0 = millis();
  while (c.connected() && !c.available() && millis() - t0 < 1500) delay(5);
  String status = c.readStringUntil('\n');
  c.stop();
  return status.indexOf("200") > 0;
}

void pollBuzzer() {
  if (!cfg.server[0] || WiFi.status() != WL_CONNECTED) return;
  WiFiClient c;
  if (!c.connect(cfg.server, cfg.port)) return;
  c.print("GET /buzzer_status HTTP/1.1\r\nHost: "); c.print(cfg.server);
  c.print("\r\nConnection: close\r\n\r\n");
  unsigned long t0 = millis();
  String resp;
  while ((c.connected() || c.available()) && millis() - t0 < 1500) {
    while (c.available()) resp += (char)c.read();
  }
  c.stop();
  buzzerOn = resp.indexOf("\"buzzer\":1") >= 0;
  if (!buzzerOn) muted = false;                // re-arm mute for the next alert
}

// ── Main ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(STRIP_PWR, OUTPUT);
  pinMode(FLOW_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), flowISR, FALLING);
  loadConfig();
  initLcd();
  lcdLine(0, "TSF monitor");
  lcdLine(1, cfg.ssid[0] ? String("WiFi ") + cfg.ssid : "No WiFi set");
#if USE_IR
  IrReceiver.begin(IR_PIN, DISABLE_LED_FEEDBACK);
#endif
  ensureWiFi();
  lastSample = millis();
}

void loop() {
  unsigned long now = millis();
  handleSerial();

#if USE_IR
  if (IrReceiver.decode()) { muted = true; IrReceiver.resume(); }   // any key mutes
#endif

  if (now - lastSample >= SAMPLE_MS) {
    float lpm  = readFlowLpm(now - lastSample);
    lastSample = now;
    float dist = readDistanceCm();
    float pct  = readStripPct();
    float ntu  = readTurbidityNtu();
    float level = dist > 0 ? SENSOR_TO_FLOOR_CM - dist : -1;

    ensureWiFi();
    bool ok = postReading(dist > 0 ? dist : 0, pct, lpm, ntu);

    String net = WiFi.status() != WL_CONNECTED ? "NoNet" : (ok ? "Sent" : "SrvX");
    lcdLine(0, (level >= 0 ? "L" + String(level, 1) + "cm" : String("L --")) + " F" + String(lpm, 1));
    lcdLine(1, "T" + String(ntu, 0) + " " + (buzzerOn ? String("ALERT") : net) + " W" + String(pct, 0) + "%");

    Serial.print(dist); Serial.print(','); Serial.print(pct); Serial.print(',');
    Serial.print(lpm);  Serial.print(','); Serial.print(ntu); Serial.println(ok ? ",sent" : ",FAIL");
  }

  if (now - lastBuzz >= BUZZ_MS) { lastBuzz = now; pollBuzzer(); }
  digitalWrite(BUZZER_PIN, (buzzerOn && !muted) ? HIGH : LOW);
}
