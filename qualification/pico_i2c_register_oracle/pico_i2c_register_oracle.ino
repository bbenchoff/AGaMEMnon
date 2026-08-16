/* Exact open-drain I2C repeated-START oracle for the wired L48 rig.
 * SDA: AG32 PIN_11 / Pico GP1, SCL: AG32 PIN_15 / Pico GP2.
 * Expected transaction at address 0x55:
 *   W 2A A6, repeated START, R -> 5A C3 7E, master ACK/ACK/NACK.
 */

#include <Arduino.h>
#include <hardware/gpio.h>

static constexpr uint SDA_PIN = 1;
static constexpr uint SCL_PIN = 2;
static constexpr uint8_t ADDRESS = 0x55;
static constexpr uint8_t RESPONSE[] = {0x5a, 0xc3, 0x7e};
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

static bool address_phase(bool read) {
  uint8_t value;
  return wait_start() && read_byte(value) &&
         value == (uint8_t)((ADDRESS << 1) | (read ? 1u : 0u)) && send_ack();
}

void setup() {
  Serial.begin(115200);
  gpio_init(SDA_PIN);
  gpio_init(SCL_PIN);
  sda_release();
  gpio_set_dir(SCL_PIN, GPIO_IN);
  gpio_pull_up(SCL_PIN);
  delay(1000);
  Serial.println("PICO_I2C_REGISTER_ORACLE ready address=55");
}

void loop() {
  sda_release();
  uint8_t reg = 0, data = 0;
  bool master_nack[3] = {true, true, false};
  bool ok = address_phase(false) &&
            read_byte(reg) && send_ack() &&
            read_byte(data) && send_ack() &&
            address_phase(true);
  for (unsigned i = 0; ok && i < 3; ++i)
    ok = send_byte(RESPONSE[i], master_nack[i]);
  sda_release();

  if (ok) {
    Serial.print("REG reg="); Serial.print(reg, HEX);
    Serial.print(" data="); Serial.print(data, HEX);
    Serial.print(" nack=");
    for (bool bit : master_nack) Serial.print(bit ? '1' : '0');
    Serial.println();
  }
}
