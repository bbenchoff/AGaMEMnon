#ifndef AGAMEMNON_AG32_I2C_H
#define AGAMEMNON_AG32_I2C_H

#include "ag32_sysctl.h"

typedef struct {
    volatile uint32_t PRERLO;      /* 0x00 prescaler low */
    volatile uint32_t PRERHI;      /* 0x04 prescaler high */
    volatile uint32_t CTR;         /* 0x08 control */
    union {
        volatile uint32_t TXR;     /* 0x0c transmit */
        volatile const uint32_t RXR; /* 0x0c receive */
    };
    union {
        volatile uint32_t CR;      /* 0x10 command */
        volatile const uint32_t SR; /* 0x10 status */
    };
} ag32_i2c_t;

#define AG32_I2C0 ((ag32_i2c_t *)(uintptr_t)AG32_I2C0_BASE)
#define AG32_I2C1 ((ag32_i2c_t *)(uintptr_t)AG32_I2C1_BASE)

#define AG32_I2C_CTR_EN    (1u << 7)
#define AG32_I2C_CTR_IEN   (1u << 6)
#define AG32_I2C_CR_STA    (1u << 7)
#define AG32_I2C_CR_STO    (1u << 6)
#define AG32_I2C_CR_RD     (1u << 5)
#define AG32_I2C_CR_WR     (1u << 4)
#define AG32_I2C_CR_NACK   (1u << 3)
#define AG32_I2C_CR_IACK   (1u << 0)
#define AG32_I2C_SR_RXNACK (1u << 7)
#define AG32_I2C_SR_BUSY   (1u << 6)
#define AG32_I2C_SR_AL     (1u << 5)
#define AG32_I2C_SR_TIP    (1u << 1)
#define AG32_I2C_SR_IF     (1u << 0)

static inline unsigned ag32_i2c_index(const ag32_i2c_t *i2c) {
    return (unsigned)(((uintptr_t)i2c - AG32_I2C0_BASE) / 0x1000u);
}

/*
 * Program the PRER prescaler for the requested SCL rate. pbus_hz is trusted, not
 * measured, and I2C0's own reference clock has never been measured on silicon.
 * Do not pass a datasheet maximum: that scaled UART0's baud by ~17x on this
 * bench. Borrowing ag32_uart_ref_hz_measured() is a cross-domain assumption
 * (SPI0's reference measured ~258 MHz against UART0's ~14.47 MHz), so record
 * what you assumed and verify SCL with a scope. See ag32_sysctl.h.
 */
static inline int ag32_i2c_init(ag32_i2c_t *i2c, uint32_t pbus_hz,
                                uint32_t scl_hz) {
    if (!scl_hz || pbus_hz < 5u * scl_hz)
        return -1;
    unsigned index = ag32_i2c_index(i2c);
    if (index >= AG32_I2C_COUNT)
        return -1;
    ag32_apb_enable(AG32_APB_I2C(index));
    ag32_apb_reset(AG32_APB_I2C(index));
    i2c->CTR = 0;
    uint32_t prescale = pbus_hz / (5u * scl_hz) - 1u;
    if (prescale > 0xffffu)
        return -1;
    i2c->PRERLO = prescale & 0xffu;
    i2c->PRERHI = prescale >> 8;
    i2c->CTR = AG32_I2C_CTR_EN;
    return 0;
}

static inline int ag32_i2c_wait(ag32_i2c_t *i2c, uint32_t timeout) {
    while (i2c->SR & AG32_I2C_SR_TIP) {
        if (!timeout--)
            return -1;
    }
    if (i2c->SR & AG32_I2C_SR_AL)
        return -2;
    return (i2c->SR & AG32_I2C_SR_RXNACK) ? -3 : 0;
}

static inline int ag32_i2c_start(ag32_i2c_t *i2c, uint8_t address,
                                 int read, uint32_t timeout) {
    i2c->TXR = ((uint32_t)address << 1) | (read ? 1u : 0u);
    i2c->CR = AG32_I2C_CR_STA | AG32_I2C_CR_WR;
    return ag32_i2c_wait(i2c, timeout);
}

static inline int ag32_i2c_write(ag32_i2c_t *i2c, uint8_t value,
                                 int stop, uint32_t timeout) {
    i2c->TXR = value;
    i2c->CR = AG32_I2C_CR_WR | (stop ? AG32_I2C_CR_STO : 0u);
    return ag32_i2c_wait(i2c, timeout);
}

static inline int ag32_i2c_read(ag32_i2c_t *i2c, uint8_t *value,
                                int last, uint32_t timeout) {
    i2c->CR = AG32_I2C_CR_RD |
              (last ? (AG32_I2C_CR_NACK | AG32_I2C_CR_STO) : 0u);
    int result = ag32_i2c_wait(i2c, timeout);
    if (!result)
        *value = (uint8_t)i2c->RXR;
    return result;
}

#endif
