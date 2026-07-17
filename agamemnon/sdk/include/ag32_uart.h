#ifndef AGAMEMNON_AG32_UART_H
#define AGAMEMNON_AG32_UART_H

#include "ag32_sysctl.h"

typedef struct {
    volatile uint32_t DR;          /* 0x000 data */
    volatile uint32_t RSR_ECR;     /* 0x004 receive status / error clear */
    uint32_t reserved0[4];         /* 0x008..0x014 */
    volatile const uint32_t FR;    /* 0x018 flags */
    uint32_t reserved1[2];         /* 0x01c..0x020 */
    volatile uint32_t IBRD;        /* 0x024 integer baud divisor */
    volatile uint32_t FBRD;        /* 0x028 fractional baud divisor */
    volatile uint32_t LCR_H;       /* 0x02c line control */
    volatile uint32_t CR;          /* 0x030 control */
    volatile uint32_t IFLS;        /* 0x034 interrupt FIFO levels */
    volatile uint32_t IMSC;        /* 0x038 interrupt mask */
    volatile const uint32_t RIS;   /* 0x03c raw interrupt status */
    volatile const uint32_t MIS;   /* 0x040 masked interrupt status */
    volatile uint32_t ICR;         /* 0x044 interrupt clear */
    volatile uint32_t DMACR;       /* 0x048 DMA control */
} ag32_uart_t;

#define AG32_UART0 ((ag32_uart_t *)(uintptr_t)AG32_UART0_BASE)
#define AG32_UART1 ((ag32_uart_t *)(uintptr_t)AG32_UART1_BASE)
#define AG32_UART2 ((ag32_uart_t *)(uintptr_t)AG32_UART2_BASE)
#define AG32_UART3 ((ag32_uart_t *)(uintptr_t)AG32_UART3_BASE)
#define AG32_UART4 ((ag32_uart_t *)(uintptr_t)AG32_UART4_BASE)

#define AG32_UART_FR_CTS   (1u << 0)
#define AG32_UART_FR_BUSY  (1u << 3)
#define AG32_UART_FR_RXFE  (1u << 4)
#define AG32_UART_FR_TXFF  (1u << 5)
#define AG32_UART_FR_RXFF  (1u << 6)
#define AG32_UART_FR_TXFE  (1u << 7)

#define AG32_UART_LCR_BRK  (1u << 0)
#define AG32_UART_LCR_PEN  (1u << 1)
#define AG32_UART_LCR_EPS  (1u << 2)
#define AG32_UART_LCR_STP2 (1u << 3)
#define AG32_UART_LCR_FEN  (1u << 4)
#define AG32_UART_LCR_WLEN_5 (0u << 5)
#define AG32_UART_LCR_WLEN_6 (1u << 5)
#define AG32_UART_LCR_WLEN_7 (2u << 5)
#define AG32_UART_LCR_WLEN_8 (3u << 5)

#define AG32_UART_CR_UARTEN (1u << 0)
#define AG32_UART_CR_LBE    (1u << 7)
#define AG32_UART_CR_TXE    (1u << 8)
#define AG32_UART_CR_RXE    (1u << 9)
#define AG32_UART_CR_RTSEN  (1u << 14)
#define AG32_UART_CR_CTSEN  (1u << 15)

#define AG32_UART_DMA_RX    (1u << 0)
#define AG32_UART_DMA_TX    (1u << 1)
#define AG32_UART_DMAONERR  (1u << 2)

static inline unsigned ag32_uart_index(const ag32_uart_t *uart) {
    return (unsigned)(((uintptr_t)uart - AG32_UART0_BASE) / 0x1000u);
}

/* Configure 8-N-1. uart_clock_hz is the peripheral input clock after PBUS division. */
static inline int ag32_uart_init(ag32_uart_t *uart, uint32_t uart_clock_hz,
                                 uint32_t baud) {
    if (!baud || uart_clock_hz < 16u * baud)
        return -1;
    unsigned index = ag32_uart_index(uart);
    if (index >= AG32_UART_COUNT)
        return -1;
    ag32_apb_enable(AG32_APB_UART(index));
    ag32_apb_reset(AG32_APB_UART(index));
    uart->CR = 0;
    /* baud divisor * 64 = UARTCLK * 4 / baud, rounded to nearest. */
    /* AG32 clocks are below 1 GHz, so this stays 32-bit and needs no libgcc. */
    if (uart_clock_hz > (0xffffffffu - baud / 2u) / 4u)
        return -1;
    uint32_t divisor64 = (uart_clock_hz * 4u + baud / 2u) / baud;
    uint32_t integer = divisor64 >> 6;
    if (!integer || integer > 0xffffu)
        return -1;
    uart->IBRD = integer;
    uart->FBRD = divisor64 & 0x3fu;
    /* A LCR_H write latches IBRD/FBRD in this controller. */
    uart->LCR_H = AG32_UART_LCR_WLEN_8 | AG32_UART_LCR_FEN;
    uart->ICR = 0x7ffu;
    uart->CR = AG32_UART_CR_RXE | AG32_UART_CR_TXE | AG32_UART_CR_UARTEN;
    return 0;
}

static inline int ag32_uart_putc(ag32_uart_t *uart, uint8_t value,
                                  uint32_t timeout) {
    while (uart->FR & AG32_UART_FR_TXFF) {
        if (!timeout--)
            return -1;
    }
    uart->DR = value;
    return 0;
}

static inline int ag32_uart_getc(ag32_uart_t *uart, uint8_t *value,
                                  uint32_t timeout) {
    while (uart->FR & AG32_UART_FR_RXFE) {
        if (!timeout--)
            return -1;
    }
    uint32_t data = uart->DR;
    if (data & 0x0f00u) {
        uart->RSR_ECR = 0;
        return -2;
    }
    *value = (uint8_t)data;
    return 0;
}

static inline void ag32_uart_flush(ag32_uart_t *uart) {
    while ((uart->FR & (AG32_UART_FR_BUSY | AG32_UART_FR_TXFE)) != AG32_UART_FR_TXFE) { }
}

#endif
