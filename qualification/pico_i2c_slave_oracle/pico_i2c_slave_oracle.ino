/* Open-drain I2C slave oracle for the wired L48 qualification rig.
 * SDA: AG32 PIN_11 / Pico GP1, SCL: AG32 PIN_15 / Pico GP2.
 * Address 0x55 ACKs writes and records one byte; reads return 0x5A.
 */

#include <Arduino.h>
#include <hardware/gpio.h>

static constexpr uint SDA_PIN = 1;
static constexpr uint SCL_PIN = 2;
static constexpr uint8_t ADDRESS = 0x55;
static constexpr uint8_t READ_VALUE = 0x5a;
static constexpr uint32_t EDGE_TIMEOUT_US = 200000;

static void sda_release() {
  gpio_set_dir(SDA_PIN, GPIO_IN);
  gpio_pull_up(SDA_PIN);
}

static void sda_low() {
  gpio_put(SDA_PIN, 0);
  gpio_set_dir(SDA_PIN, GPIO_OUT);
}

static bool wait_level(uint pin, bool level) {
  uint64_t deadline = time_us_64() + EDGE_TIMEOUT_US;
  while ((bool)gpio_get(pin) != level) {
    if (time_us_64() >= deadline) return false;
  }
  return true;
}

static bool wait_start() {
  uint64_t deadline = time_us_64() + 2000000;
  bool previous = gpio_get(SDA_PIN);
  while (time_us_64() < deadline) {
    bool current = gpio_get(SDA_PIN);
    if (previous && !current && gpio_get(SCL_PIN)) return true;
    previous = current;
  }
  return false;
}

static bool read_bit(bool &bit) {
  if (!wait_level(SCL_PIN, false) || !wait_level(SCL_PIN, true)) return false;
  bit = gpio_get(SDA_PIN);
  return true;
}

static bool read_byte(uint8_t &value) {
  value = 0;
  for (unsigned i = 0; i < 8; ++i) {
    bool bit;
    if (!read_bit(bit)) return false;
    value = (uint8_t)((value << 1) | bit);
  }
  return true;
}

static bool send_ack() {
  if (!wait_level(SCL_PIN, false)) return false;
  sda_low();
  if (!wait_level(SCL_PIN, true) || !wait_level(SCL_PIN, false)) return false;
  sda_release();
  return true;
}

static bool send_byte(uint8_t value, bool &master_nack) {
  for (int bit = 7; bit >= 0; --bit) {
    if (value & (1u << bit)) sda_release(); else sda_low();
    if (!wait_level(SCL_PIN, true) || !wait_level(SCL_PIN, false)) return false;
  }
  sda_release();
  if (!wait_level(SCL_PIN, true)) return false;
  master_nack = gpio_get(SDA_PIN);
  return wait_level(SCL_PIN, false);
}

void setup() {
  Serial.begin(115200);
  gpio_init(SDA_PIN);
  gpio_init(SCL_PIN);
  sda_release();
  gpio_set_dir(SCL_PIN, GPIO_IN);
  gpio_pull_up(SCL_PIN);
  delay(1000);
  Serial.println("PICO_I2C_ORACLE ready address=55 read=5A");
}

void loop() {
  sda_release();
  if (!wait_start()) return;

  uint8_t address_byte;
  if (!read_byte(address_byte)) return;
  uint8_t address = address_byte >> 1;
  bool read = address_byte & 1u;
  if (address != ADDRESS) return;
  if (!send_ack()) return;

  if (!read) {
    uint8_t value;
    if (read_byte(value) && send_ack()) {
      Serial.print("WRITE value=");
      if (value < 16) Serial.print('0');
      Serial.println(value, HEX);
    }
  } else {
    bool master_nack;
    if (send_byte(READ_VALUE, master_nack)) {
      Serial.print("READ value=5A master_nack=");
      Serial.println(master_nack ? 1 : 0);
    }
  }
  sda_release();
}
