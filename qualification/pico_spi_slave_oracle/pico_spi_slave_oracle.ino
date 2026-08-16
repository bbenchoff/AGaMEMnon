/*
 * Fixed-response SPI mode-0 slave oracle for the wired L48 qualification rig.
 *
 * AG32 -> Pico: SCK PIN_12/GP0, CSN PIN_13/GP3, MOSI PIN_14/GP5
 * Pico -> AG32: MISO/IO1 GP7/PIN_17
 *
 * The arbitrary wiring does not match an RP2350 hardware-SPI pin group, so a
 * PIO state machine observes the eight command clocks plus the controller's
 * one-clock TX/RX phase seam, then shifts the fixed response 12 34 56 78
 * MSB-first. GP7 is input
 * outside that response window.  Each completed transaction prints DONE and
 * rearms the same response.  This is a lab oracle, not general SPI firmware.
 */

#include <Arduino.h>
#include <hardware/pio.h>
#include <hardware/pio_instructions.h>

static constexpr uint SCK_PIN = 0;
static constexpr uint CS_PIN = 3;
static constexpr uint MOSI_PIN = 5;
static constexpr uint MISO_PIN = 7;
static constexpr uint32_t RESPONSE = 0x12345678u;
static constexpr uint32_t RESPONSE_BIT_REVERSED = 0x1e6a2c48u;

static PIO pio = pio0;
static uint sm;
static uint offset;
static uint16_t instructions[17];
static pio_program program = {instructions, 17, -1};

static void build_program() {
  instructions[0] = pio_encode_set(pio_pindirs, 0);       // release MISO
  instructions[1] = pio_encode_wait_gpio(false, CS_PIN);  // CS asserted
  instructions[2] = pio_encode_set(pio_x, 8);             // command + phase seam
  instructions[3] = pio_encode_wait_gpio(true, SCK_PIN);
  instructions[4] = pio_encode_wait_gpio(false, SCK_PIN);
  instructions[5] = pio_encode_jmp_x_dec(3);
  instructions[6] = pio_encode_pull(false, true);          // response word
  instructions[7] = pio_encode_set(pio_pindirs, 1);       // drive MISO
  instructions[8] = pio_encode_set(pio_x, 31);            // 32 response bits
  instructions[9] = pio_encode_out(pio_pins, 1);          // present before rise
  instructions[10] = pio_encode_wait_gpio(true, SCK_PIN);
  instructions[11] = pio_encode_wait_gpio(false, SCK_PIN);
  instructions[12] = pio_encode_jmp_x_dec(9);
  instructions[13] = pio_encode_wait_gpio(true, CS_PIN);   // transaction ended
  instructions[14] = pio_encode_set(pio_pindirs, 0);      // release MISO
  instructions[15] = pio_encode_irq_set(false, 0);
  instructions[16] = pio_encode_jmp(0);
}

void setup() {
  Serial.begin(115200);
  delay(1500);

  const uint pins[] = {SCK_PIN, CS_PIN, MOSI_PIN, MISO_PIN};
  for (uint pin : pins) {
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_disable_pulls(pin);
  }

  build_program();
  sm = pio_claim_unused_sm(pio, true);
  offset = (uint)pio_add_program(pio, &program);
  pio_gpio_init(pio, MISO_PIN);

  pio_sm_config config = pio_get_default_sm_config();
  sm_config_set_out_pins(&config, MISO_PIN, 1);
  sm_config_set_set_pins(&config, MISO_PIN, 1);
  /* OUT shifts right from bit 0; preload the bit-reversed logical word so the
   * wire still sees RESPONSE bit 31 first. */
  sm_config_set_out_shift(&config, true, false, 32);
  sm_config_set_wrap(&config, offset, offset + program.length - 1);
  pio_sm_init(pio, sm, offset, &config);
  pio_sm_set_consecutive_pindirs(pio, sm, MISO_PIN, 1, false);
  pio_interrupt_clear(pio, 0);
  pio_sm_put_blocking(pio, sm, RESPONSE_BIT_REVERSED);
  pio_sm_set_enabled(pio, sm, true);

  Serial.println("PICO_SPI_ORACLE ready response=12345678 skip=9 mode=0");
}

void loop() {
  if (pio_interrupt_get(pio, 0)) {
    pio_interrupt_clear(pio, 0);
    pio_sm_put_blocking(pio, sm, RESPONSE_BIT_REVERSED);
    Serial.println("DONE response=12345678");
  }
}
