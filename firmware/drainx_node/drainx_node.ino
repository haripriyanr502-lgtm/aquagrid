// =====================================================================
//  DrainX Smart Node  v2  -  Arduino Uno
//  Senses drain water level, water quality, recharge-pit state and flow.
//  Decides (with safeties) whether to send water to the recharge pit.
//  Talks to the laptop over USB serial as one JSON line per second.
// =====================================================================
//
//  WIRING SUMMARY (full details in the Hardware Guide)
//  D2  <- Flow sensor YF-S201 signal (yellow)       [interrupt pin]
//  D5  -> (optional) WS2812B LED strip DIN
//  D7  -> Relay CH1  -> 12V pump  (sump -> recharge pit)  = the GATE
//  D8  -> Relay CH2  -> 9V pump   ("rain" for the demo)
//  D9  -> Sump ultrasonic TRIG     D10 <- Sump ultrasonic ECHO
//  D11 -> Pit  ultrasonic TRIG     D12 <- Pit  ultrasonic ECHO
//  A0  <- Turbidity sensor (analog out)
//  A1  <- TDS sensor (analog out)
//  A2  <- Capacitive soil-moisture sensor (in the pit sand)
// =====================================================================

// ---------- OPTIONAL PARTS (1 = installed, 0 = not installed) ----------
#define USE_PIT_SENSOR  1   // second ultrasonic in recharge pit
#define USE_LEDS        0   // WS2812B strip (needs Adafruit NeoPixel library)

#if USE_LEDS
  #include <Adafruit_NeoPixel.h>
  #define LED_PIN   5
  #define LED_COUNT 8
  Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);
#endif

// ---------- PINS ----------
const int FLOW_PIN    = 2;
const int RELAY_GATE  = 7;
const int RELAY_RAIN  = 8;
const int SUMP_TRIG   = 9;
const int SUMP_ECHO   = 10;
const int PIT_TRIG    = 11;
const int PIT_ECHO    = 12;
const int TURB_PIN    = A0;
const int TDS_PIN     = A1;
const int SOIL_PIN    = A2;

// Most cheap relay boards switch ON when their input is LOW.
// If your relay clicks the wrong way round, change this to false.
const bool RELAY_ACTIVE_LOW = true;

// ---------- SETTINGS (most can be changed live with commands) ----------
float sumpEmptyCm   = 25.0;  // sensor -> sump floor when EMPTY          (command CAL)
float sumpFullCm    = 7.0;   // sensor -> water at the OVERFLOW line      (command CALFULL)
float pitEmptyCm    = 25.0;  // sensor -> pit floor when EMPTY           (command CALPIT)
float pitFullCm     = 7.0;   // sensor -> water when pit is FULL         (command CALPITFULL)
float thresholdPct  = 60.0;  // open gate above this sump level   (T:xx)
float hysteresisPct = 10.0;  // close gate below threshold - this
float pitFullPct    = 85.0;  // never fill the pit above this
float minPumpPct    = 8.0;   // never run pump below this (dry-run protection)
int   turbCleanMin  = 600;   // turbidity raw >= this = clear enough (Q:xxx)
float tdsMaxPpm     = 600;   // TDS above this = polluted           (X:xxx)
unsigned long firstFlushMs = 20000; // first 20 s of each rain event -> drain (F:sec)
float pulsesPerLitre = 450.0;       // YF-S201 typical, calibrate      (K:xxx)
int   soilDryRaw    = 560;   // capacitive sensor in DRY sand  (edit after calibrating)
int   soilWetRaw    = 260;   // capacitive sensor in WET sand

// ---------- STATE ----------
enum Mode { AUTO, REQ_OPEN, FORCE_CLOSE };
Mode mode = AUTO;
bool qualityGateEnabled = true;
bool gateOpen = false, rainOn = false;
bool qualityOk = false, firstFlush = false, sumpOk = false;
float levelPct = 0, pitPct = 0, soilPct = 0, tdsPpm = 0, flowLpm = 0;
int   turbRaw = 0, soilRaw = 0;
volatile unsigned long flowPulses = 0;
unsigned long totalPulses = 0;
unsigned long lastSend = 0, lastFlowCalc = 0;
unsigned long eventStart = 0;
bool eventActive = false;
const char* reason = "idle";

void onFlowPulse() { flowPulses++; }

// ---------- HELPERS ----------
void setRelay(int pin, bool on) { digitalWrite(pin, RELAY_ACTIVE_LOW ? !on : on); }

float pingOnce(int trig, int echo) {
  digitalWrite(trig, LOW);  delayMicroseconds(2);
  digitalWrite(trig, HIGH); delayMicroseconds(10);
  digitalWrite(trig, LOW);
  unsigned long d = pulseIn(echo, HIGH, 30000UL);
  if (d == 0) return -1;
  return d * 0.0343 / 2.0;
}

// median of 5 pings: ignores ripples and random spikes
float distanceCm(int trig, int echo) {
  float r[5]; int n = 0;
  for (int i = 0; i < 5; i++) { float d = pingOnce(trig, echo); if (d > 0) r[n++] = d; delay(12); }
  if (n == 0) return -1;
  for (int i = 0; i < n - 1; i++)
    for (int j = i + 1; j < n; j++)
      if (r[j] < r[i]) { float t = r[i]; r[i] = r[j]; r[j] = t; }
  return r[n / 2];
}

int analogAvg(int pin) { long s = 0; for (int i = 0; i < 10; i++) { s += analogRead(pin); delay(2); } return s / 10; }

// DFRobot Gravity TDS conversion, assuming 25 C water
float readTds() {
  float v = analogAvg(TDS_PIN) * 5.0 / 1024.0;
  return (133.42 * v * v * v - 255.86 * v * v + 857.39 * v) * 0.5;
}

const char* modeName() {
  if (mode == REQ_OPEN)    return "REQ_OPEN";
  if (mode == FORCE_CLOSE) return "FORCE_CLOSE";
  return "AUTO";
}

void ack(const String& c) { Serial.print(F("{\"ack\":\"")); Serial.print(c); Serial.println(F("\"}")); }

// ---------- COMMANDS (sent by the laptop, one per line) ----------
//  T:55      threshold 55 %          D:ON   ask gate to open (safeties still apply)
//  D:OFF     force gate closed       D:AUTO automatic decision
//  R:ON/R:OFF rain pump              CAL / CALFULL  calibrate sump empty / full
//  CALPIT / CALPITFULL  calibrate recharge pit empty / full
//  Q:600     turbidity clean limit   X:600  TDS limit (ppm)
//  F:20      first-flush seconds     K:450  flow pulses per litre
//  QG:OFF/QG:ON  disable/enable quality gate (testing only)   RST:L reset litres
void handleCommand(String c) {
  c.trim(); if (c.length() == 0) return;
  if      (c.startsWith("T:"))  { float v = c.substring(2).toFloat(); if (v > 5 && v < 95) thresholdPct = v; }
  else if (c == "D:ON")         mode = REQ_OPEN;
  else if (c == "D:OFF")        mode = FORCE_CLOSE;
  else if (c == "D:AUTO")       mode = AUTO;
  else if (c == "R:ON")         rainOn = true;
  else if (c == "R:OFF")        rainOn = false;
  else if (c == "CAL")          { float d = distanceCm(SUMP_TRIG, SUMP_ECHO); if (d > 0) sumpEmptyCm = d; }
  else if (c == "CALFULL")      { float d = distanceCm(SUMP_TRIG, SUMP_ECHO); if (d > 0) sumpFullCm  = d; }
  else if (c == "CALPIT")       { float d = distanceCm(PIT_TRIG, PIT_ECHO);   if (d > 0) pitEmptyCm  = d; }
  else if (c == "CALPITFULL")   { float d = distanceCm(PIT_TRIG, PIT_ECHO);   if (d > 0) pitFullCm   = d; }
  else if (c.startsWith("Q:"))  turbCleanMin = c.substring(2).toInt();
  else if (c.startsWith("X:"))  tdsMaxPpm    = c.substring(2).toFloat();
  else if (c.startsWith("F:"))  firstFlushMs = (unsigned long)c.substring(2).toInt() * 1000UL;
  else if (c.startsWith("K:"))  { float k = c.substring(2).toFloat(); if (k > 10) pulsesPerLitre = k; }
  else if (c == "QG:OFF")       qualityGateEnabled = false;
  else if (c == "QG:ON")        qualityGateEnabled = true;
  else if (c == "RST:L")        totalPulses = 0;
  else { Serial.print(F("{\"error\":\"unknown command ")); Serial.print(c); Serial.println(F("\"}")); return; }
  ack(c);
}

#if USE_LEDS
void showLeds() {
  uint32_t col;
  if (!qualityOk && levelPct > 15)     col = strip.Color(150, 60, 0);   // brown/orange = dirty water
  else if (levelPct >= thresholdPct)   col = strip.Color(200, 0, 0);    // red = flood risk
  else if (levelPct >= thresholdPct/2) col = strip.Color(200, 150, 0);  // yellow
  else                                 col = strip.Color(0, 160, 40);   // green
  int lit = constrain((int)(levelPct / 100.0 * LED_COUNT + 0.5), 1, LED_COUNT);
  for (int i = 0; i < LED_COUNT; i++) strip.setPixelColor(i, i < lit ? col : 0);
  if (gateOpen) strip.setPixelColor(LED_COUNT - 1, strip.Color(0, 80, 255)); // blue = recharging
  strip.show();
}
#endif

// ---------- SETUP ----------
void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);
  pinMode(SUMP_TRIG, OUTPUT); pinMode(SUMP_ECHO, INPUT);
  pinMode(PIT_TRIG, OUTPUT);  pinMode(PIT_ECHO, INPUT);
  pinMode(RELAY_GATE, OUTPUT); pinMode(RELAY_RAIN, OUTPUT);
  setRelay(RELAY_GATE, false); setRelay(RELAY_RAIN, false);
  pinMode(FLOW_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), onFlowPulse, FALLING);
#if USE_LEDS
  strip.begin(); strip.setBrightness(60); strip.show();
#endif
  Serial.println(F("{\"status\":\"DrainX node online\"}"));
}

// ---------- LOOP ----------
void loop() {
  // 1. commands
  while (Serial.available()) handleCommand(Serial.readStringUntil('\n'));

  // 2. sensors
  float d = distanceCm(SUMP_TRIG, SUMP_ECHO);
  sumpOk = d > 0;
  float sumpSpan = max(sumpEmptyCm - sumpFullCm, 2.0f);
  if (sumpOk) levelPct = constrain((sumpEmptyCm - d) / sumpSpan * 100.0, 0, 100);

#if USE_PIT_SENSOR
  float p = distanceCm(PIT_TRIG, PIT_ECHO);
  float pitSpan = max(pitEmptyCm - pitFullCm, 2.0f);
  if (p > 0) pitPct = constrain((pitEmptyCm - p) / pitSpan * 100.0, 0, 100);
#else
  pitPct = 0;
#endif

  turbRaw = analogAvg(TURB_PIN);
  tdsPpm  = readTds();
  soilRaw = analogAvg(SOIL_PIN);
  soilPct = constrain(map(soilRaw, soilDryRaw, soilWetRaw, 0, 100), 0, 100);

  // flow: litres/minute from pulses counted in the last second
  if (millis() - lastFlowCalc >= 1000) {
    noInterrupts(); unsigned long pulses = flowPulses; flowPulses = 0; interrupts();
    float secs = (millis() - lastFlowCalc) / 1000.0;
    lastFlowCalc = millis();
    totalPulses += pulses;
    flowLpm = (pulses / pulsesPerLitre) / secs * 60.0;
  }

  // 3. rain-event + first-flush tracking
  if (!eventActive && levelPct > 12) { eventActive = true; eventStart = millis(); }
  if (eventActive && levelPct < 5)   { eventActive = false; }
  firstFlush = eventActive && (millis() - eventStart < firstFlushMs);

  // water is "clean" if clear enough AND not too many dissolved solids
  // (probes are only trusted once they are under water: level > 20 %)
  bool probesWet = levelPct > 20;
  qualityOk = !qualityGateEnabled || (probesWet && turbRaw >= turbCleanMin && tdsPpm <= tdsMaxPpm);

  // 4. decision - who wants the gate open?
  bool want;
  if (mode == FORCE_CLOSE)      want = false;
  else if (mode == REQ_OPEN)    want = true;
  else {  // AUTO with hysteresis
    if (!gateOpen && levelPct >= thresholdPct)                       want = true;
    else if (gateOpen && levelPct <= thresholdPct - hysteresisPct)   want = false;
    else                                                             want = gateOpen;
  }

  // 5. safeties ALWAYS win (edge safety: the laptop cannot override these)
  reason = want ? "open" : (mode == FORCE_CLOSE ? "forced_closed" : "below_threshold");
  if (want && !sumpOk)                  { want = false; reason = "sensor_fault"; }
  if (want && levelPct < minPumpPct)    { want = false; reason = "dry_run_protect"; }
  if (want && firstFlush)               { want = false; reason = "first_flush_to_drain"; }
  if (want && !qualityOk)               { want = false; reason = "dirty_water_to_drain"; }
  if (want && pitPct >= pitFullPct)     { want = false; reason = "pit_full"; }
  gateOpen = want;

  if (rainOn && levelPct >= 92) rainOn = false;   // demo safety: don't overflow the model

  setRelay(RELAY_GATE, gateOpen);
  setRelay(RELAY_RAIN, rainOn);
#if USE_LEDS
  showLeds();
#endif

  // 6. report once a second
  if (millis() - lastSend >= 1000) {
    lastSend = millis();
    float litres = totalPulses / pulsesPerLitre;
    Serial.print(F("{\"node\":\"SS-01\""));
    Serial.print(F(",\"level_pct\":"));    Serial.print(levelPct, 1);
    Serial.print(F(",\"pit_pct\":"));      Serial.print(pitPct, 1);
    Serial.print(F(",\"turbidity\":"));    Serial.print(turbRaw);
    Serial.print(F(",\"tds\":"));          Serial.print(tdsPpm, 0);
    Serial.print(F(",\"soil_pct\":"));     Serial.print(soilPct, 0);
    Serial.print(F(",\"soil_raw\":"));     Serial.print(soilRaw);
    Serial.print(F(",\"flow_lpm\":"));     Serial.print(flowLpm, 2);
    Serial.print(F(",\"litres_total\":")); Serial.print(litres, 2);
    Serial.print(F(",\"gate_open\":"));    Serial.print(gateOpen ? F("true") : F("false"));
    Serial.print(F(",\"rain_on\":"));      Serial.print(rainOn ? F("true") : F("false"));
    Serial.print(F(",\"quality_ok\":"));   Serial.print(qualityOk ? F("true") : F("false"));
    Serial.print(F(",\"first_flush\":"));  Serial.print(firstFlush ? F("true") : F("false"));
    Serial.print(F(",\"mode\":\""));       Serial.print(modeName());
    Serial.print(F("\",\"reason\":\""));   Serial.print(reason);
    Serial.print(F("\",\"threshold\":"));  Serial.print(thresholdPct, 0);
    Serial.println(F("}"));
  }
}
