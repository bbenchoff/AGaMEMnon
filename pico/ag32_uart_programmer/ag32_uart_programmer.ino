// Raspberry Pi Pico 2 bridge for the AG32 mask-ROM UART bootloader.
//
// USB CDC accepts a deliberately small ASCII protocol from AGaMEMnon. UART1
// carries the AG32's binary protocol at 460800 8N1, while GPIOs select the boot
// mode and reset the target. Both boards use 3.3-V logic; join ground only,
// not 3V3/VBUS. NRST is open-drain: this firmware drives it low or releases it.
//
// Pico GP20 (UART1 TX) -> AG32 L48 pin 31 UART0_RX
// Pico GP21 (UART1 RX) <- AG32 L48 pin 30 UART0_TX
// Pico GP22             -> AG32 L48 pin 44 BOOT0
// Pico GP26             -> AG32 L48 pin  7 NRST
// Pico GP27             -> AG32 L48 pin 20 PIN_20/BOOT1
// Pico GND              -- AG32 GND

#include <Arduino.h>
#include <hardware/gpio.h>

static const uint8_t TARGET_TX = 20;
static const uint8_t TARGET_RX = 21;
static const uint8_t TARGET_BOOT0 = 22;
static const uint8_t TARGET_NRST = 26;
static const uint8_t TARGET_BOOT1 = 27;
static const uint32_t TARGET_BAUD = 460800;
static const size_t UART_CHUNK = 128;
static const size_t LINE_MAX = 320;

static char line[LINE_MAX];
static size_t lineLength = 0;

static void releaseReset() {
  // Never drive NRST high. The weak Pico pull-up also releases boards whose
  // reset pull-up lived on a now-disconnected debugger.
  digitalWrite(TARGET_NRST, LOW);
  pinMode(TARGET_NRST, INPUT_PULLUP);
}

static void assertReset() {
  digitalWrite(TARGET_NRST, LOW);
  pinMode(TARGET_NRST, OUTPUT);
}

static void selectAndReset(bool bootRom) {
  assertReset();
  digitalWrite(TARGET_BOOT0, bootRom ? HIGH : LOW);
  // BOOT1 must be low for ROM boot. Drive it low only across reset/latching,
  // then release it so normal firmware remains free to use PIN_20.
  digitalWrite(TARGET_BOOT1, LOW);
  pinMode(TARGET_BOOT1, OUTPUT);
  delay(20);
  releaseReset();
  delay(50);
  pinMode(TARGET_BOOT1, INPUT);
}

static void flushTargetRx() {
  while (Serial2.available()) Serial2.read();
}

static int hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static void handleLine(char *input) {
  char *command = strtok(input, " ");
  if (!command) return;

  if (!strcasecmp(command, "PING")) {
    Serial.println("AG32UART v1 tx=20 rx=21 boot0=22 nrst=26 boot1=27 baud=460800");
    return;
  }

  if (!strcasecmp(command, "STATUS")) {
    Serial.print("STATUS rx=");
    Serial.print(digitalRead(TARGET_RX));
    Serial.print(" boot0=");
    Serial.print(digitalRead(TARGET_BOOT0));
    Serial.print(" boot1=");
    Serial.print(digitalRead(TARGET_BOOT1));
    Serial.print(" nrst=");
    Serial.print(digitalRead(TARGET_NRST));
    Serial.print(" queued=");
    Serial.print(Serial2.available());
    Serial.print(" overflow=");
    Serial.println(Serial2.overflow() ? 1 : 0);
    return;
  }

  if (!strcasecmp(command, "SENSE")) {
    // A driven UART TX defeats both weak pulls; a floating GP21 follows them.
    // This can look like a false start bit to the target, so the host should
    // reset back into the selected boot mode after using this diagnostic.
    gpio_pull_up(TARGET_RX);
    delayMicroseconds(100);
    int withPullUp = digitalRead(TARGET_RX);
    gpio_pull_down(TARGET_RX);
    delayMicroseconds(100);
    int withPullDown = digitalRead(TARGET_RX);
    gpio_disable_pulls(TARGET_RX);
    Serial.print("SENSE rx_up=");
    Serial.print(withPullUp);
    Serial.print(" rx_down=");
    Serial.println(withPullDown);
    return;
  }

  if (!strcasecmp(command, "BOOT")) {
    char *mode = strtok(nullptr, " ");
    if (!mode) {
      Serial.println("ERR BOOT requires ENTER or RUN");
      return;
    }
    flushTargetRx();
    if (!strcasecmp(mode, "ENTER")) {
      selectAndReset(true);
    } else if (!strcasecmp(mode, "RUN")) {
      selectAndReset(false);
    } else {
      Serial.println("ERR BOOT requires ENTER or RUN");
      return;
    }
    flushTargetRx();
    Serial.println("OK");
    return;
  }

  if (!strcasecmp(command, "UART")) {
    char *operation = strtok(nullptr, " ");
    if (!operation) {
      Serial.println("ERR UART requires TX, RX, or FLUSH");
      return;
    }
    if (!strcasecmp(operation, "FLUSH")) {
      flushTargetRx();
      Serial.println("OK");
      return;
    }
    if (!strcasecmp(operation, "TX")) {
      char *hex = strtok(nullptr, " ");
      size_t chars = hex ? strlen(hex) : 0;
      if (!chars || (chars & 1) || chars / 2 > UART_CHUNK) {
        Serial.println("ERR UART TX requires 1..128 hex bytes");
        return;
      }
      uint8_t data[UART_CHUNK];
      for (size_t i = 0; i < chars / 2; ++i) {
        int hi = hexNibble(hex[2 * i]);
        int lo = hexNibble(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) {
          Serial.println("ERR invalid hex");
          return;
        }
        data[i] = (uint8_t)((hi << 4) | lo);
      }
      Serial2.write(data, chars / 2);
      Serial2.flush();
      Serial.print("TX ");
      Serial.println(chars / 2);
      return;
    }
    if (!strcasecmp(operation, "RX")) {
      char *countText = strtok(nullptr, " ");
      char *timeoutText = strtok(nullptr, " ");
      long count = countText ? strtol(countText, nullptr, 0) : 0;
      long timeoutMs = timeoutText ? strtol(timeoutText, nullptr, 0) : 0;
      if (count < 1 || count > (long)UART_CHUNK || timeoutMs < 1 || timeoutMs > 30000) {
        Serial.println("ERR UART RX count=1..128 timeout=1..30000ms");
        return;
      }
      uint8_t data[UART_CHUNK];
      size_t received = 0;
      uint32_t start = millis();
      while (received < (size_t)count && millis() - start < (uint32_t)timeoutMs) {
        if (Serial2.available()) data[received++] = (uint8_t)Serial2.read();
      }
      static const char digits[] = "0123456789abcdef";
      Serial.print("RX ");
      for (size_t i = 0; i < received; ++i) {
        Serial.print(digits[data[i] >> 4]);
        Serial.print(digits[data[i] & 15]);
      }
      Serial.println();
      return;
    }
    Serial.println("ERR UART requires TX, RX, or FLUSH");
    return;
  }

  Serial.println("ERR unknown command");
}

void setup() {
  // BOOT0 must never float. Default to normal flash boot before touching reset.
  digitalWrite(TARGET_BOOT0, LOW);
  pinMode(TARGET_BOOT0, OUTPUT);
  pinMode(TARGET_BOOT1, INPUT);
  releaseReset();

  Serial2.setTX(TARGET_TX);
  Serial2.setRX(TARGET_RX);
  // An extended read can return 1024 data bytes immediately after its ACK.
  // Buffer the complete response while the host performs USB command/response
  // round trips, instead of relying on the core's small default UART FIFO.
  Serial2.setFIFOSize(2048);
  Serial2.begin(TARGET_BAUD, SERIAL_8N1);
  Serial.begin(115200);
}

void loop() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      line[lineLength] = '\0';
      handleLine(line);
      lineLength = 0;
    } else if (lineLength + 1 < LINE_MAX) {
      line[lineLength++] = c;
    } else {
      lineLength = 0;
      Serial.println("ERR line too long");
    }
  }
}
