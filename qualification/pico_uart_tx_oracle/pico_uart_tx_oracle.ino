/* Commanded UART transmitter for the wired L48 qualification rig.
 * RP2350 GP7 drives AG32 L48 PIN_17. Send a decimal baud over USB CDC;
 * after a settling delay the oracle transmits FF 55 41 00 repeated 16 times.
 */

#include <Arduino.h>
#include <hardware/clocks.h>
#include <hardware/pio.h>
#include <hardware/pio_instructions.h>

static constexpr uint TX_PIN = 7;
static constexpr uint8_t PATTERN[] = {0xff, 0x55, 0x41, 0x00};

static const uint16_t uart_tx_instructions[] = {
  pio_encode_pull(false, true),
  pio_encode_set(pio_x, 7),
  (uint16_t)(pio_encode_set(pio_pins, 0) | pio_encode_delay(7)),
  (uint16_t)(pio_encode_out(pio_pins, 1) | pio_encode_delay(6)),
  pio_encode_jmp_x_dec(3),
  (uint16_t)(pio_encode_set(pio_pins, 1) | pio_encode_delay(7)),
};

static const pio_program uart_tx_program = {
  uart_tx_instructions,
  6,
  -1,
};

static PIO uart_pio = pio0;
static uint uart_sm;
static uint uart_offset;

static void uart_tx_begin(uint32_t baud) {
  pio_sm_set_enabled(uart_pio, uart_sm, false);
  pio_sm_clear_fifos(uart_pio, uart_sm);
  pio_sm_restart(uart_pio, uart_sm);
  pio_sm_config config = pio_get_default_sm_config();
  sm_config_set_wrap(&config, uart_offset, uart_offset + 5);
  sm_config_set_out_pins(&config, TX_PIN, 1);
  sm_config_set_set_pins(&config, TX_PIN, 1);
  sm_config_set_out_shift(&config, true, false, 32);
  sm_config_set_clkdiv(&config,
                       (float)clock_get_hz(clk_sys) / (8.0f * (float)baud));
  pio_gpio_init(uart_pio, TX_PIN);
  pio_sm_set_consecutive_pindirs(uart_pio, uart_sm, TX_PIN, 1, true);
  pio_sm_init(uart_pio, uart_sm, uart_offset, &config);
  pio_sm_set_pins_with_mask(uart_pio, uart_sm, 1u << TX_PIN, 1u << TX_PIN);
  pio_sm_set_enabled(uart_pio, uart_sm, true);
}

void setup() {
  Serial.begin(115200);
  uart_sm = pio_claim_unused_sm(uart_pio, true);
  uart_offset = pio_add_program(uart_pio, &uart_tx_program);
  delay(1000);
  Serial.println("PICO_UART_TX_ORACLE ready");
}

void loop() {
  if (!Serial.available()) return;
  uint32_t baud = Serial.parseInt();
  while (Serial.available()) Serial.read();
  if (baud < 300 || baud > 1000000) {
    Serial.println("ERR baud");
    return;
  }

  uart_tx_begin(baud);
  delay(250);
  for (unsigned repeat = 0; repeat < 16; ++repeat)
    for (uint8_t value : PATTERN)
      pio_sm_put_blocking(uart_pio, uart_sm, value);
  while (!pio_sm_is_tx_fifo_empty(uart_pio, uart_sm)) tight_loop_contents();
  delayMicroseconds((10000000u + baud - 1u) / baud);
  Serial.print("SENT baud=");
  Serial.print(baud);
  Serial.println(" bytes=64 data=ff554100x16");
}
