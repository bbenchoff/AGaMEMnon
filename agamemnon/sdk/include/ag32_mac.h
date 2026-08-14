#ifndef AGAMEMNON_AG32_MAC_H
#define AGAMEMNON_AG32_MAC_H

/*
 * Open AG32 Ethernet MAC (MAC0) driver, written from the published register
 * map. A 10/100 MAC with an MDIO station-management interface, transmit and
 * receive descriptor rings, and a 64-bit multicast hash filter. This driver
 * provides reset, station-address programming, MDIO PHY access, descriptor
 * ring setup and simple TX/RX; no vendor code is copied.
 *
 * Moving real traffic requires an external PHY, absent from the qualification
 * bench, so this is a driver-only (hardware-unqualified) block.
 */

#include <stdint.h>

#include "ag32_device.h"
#include "ag32_sysctl.h"

typedef struct {
    volatile uint32_t CTRL;    /* 0x00 control                            */
    volatile uint32_t STAT;    /* 0x04 status (write-1-to-clear)          */
    volatile uint32_t MACMSB;  /* 0x08 station address, upper 16 bits     */
    volatile uint32_t MACLSB;  /* 0x0c station address, lower 32 bits     */
    volatile uint32_t MDIO;    /* 0x10 MDIO command/status                */
    volatile uint32_t TXBASE;  /* 0x14 transmit descriptor table base     */
    volatile uint32_t RXBASE;  /* 0x18 receive descriptor table base      */
    uint32_t reserved_1c;
    volatile uint32_t HTMSB;   /* 0x20 hash table, upper 32 bits          */
    volatile uint32_t HTLSB;   /* 0x24 hash table, lower 32 bits          */
} ag32_mac_t;

#define AG32_MAC0 ((ag32_mac_t *)(uintptr_t)AG32_MAC0_BASE)

/* CTRL */
#define AG32_MAC_CTRL_TX_EN     (1u << 0)
#define AG32_MAC_CTRL_RX_EN     (1u << 1)
#define AG32_MAC_CTRL_TX_INTEN  (1u << 2)
#define AG32_MAC_CTRL_RX_INTEN  (1u << 3)
#define AG32_MAC_CTRL_FULLDPX   (1u << 4)  /* 0 half, 1 full duplex     */
#define AG32_MAC_CTRL_PROMISC   (1u << 5)
#define AG32_MAC_CTRL_RESET     (1u << 6)  /* self-clearing             */
#define AG32_MAC_CTRL_SPEED100  (1u << 7)  /* 0 = 10M, 1 = 100M         */
#define AG32_MAC_CTRL_PHY_INTEN (1u << 10)
#define AG32_MAC_CTRL_MCAST_EN  (1u << 11)
#define AG32_MAC_CTRL_RMII      (1u << 16)

/* STAT (write the bit back to clear it) */
#define AG32_MAC_STAT_RX_ERR    (1u << 0)
#define AG32_MAC_STAT_TX_ERR    (1u << 1)
#define AG32_MAC_STAT_RX_INT    (1u << 2)
#define AG32_MAC_STAT_TX_INT    (1u << 3)
#define AG32_MAC_STAT_RX_AHBERR (1u << 4)
#define AG32_MAC_STAT_TX_AHBERR (1u << 5)
#define AG32_MAC_STAT_TOO_SMALL (1u << 6)
#define AG32_MAC_STAT_INV_ADDR  (1u << 7)
#define AG32_MAC_STAT_PHY_CHG   (1u << 8)
#define AG32_MAC_STAT_CLEAR_ALL 0x1ffu

/* MDIO */
#define AG32_MAC_MDIO_WRITE     (1u << 0)
#define AG32_MAC_MDIO_READ      (1u << 1)
#define AG32_MAC_MDIO_LINK_FAIL (1u << 2)  /* read-only                 */
#define AG32_MAC_MDIO_BUSY      (1u << 3)  /* read-only                 */
#define AG32_MAC_MDIO_REG(r)    (((uint32_t)(r) & 0x1fu) << 6)
#define AG32_MAC_MDIO_PHY(p)    (((uint32_t)(p) & 0x1fu) << 11)
#define AG32_MAC_MDIO_DATA(d)   (((uint32_t)(d) & 0xffffu) << 16)
#define AG32_MAC_MDIO_MDCSC(s)  (((uint32_t)(s) & 3u) << 4) /* clock scaler */

/* Descriptor control-word fields (both rings). */
#define AG32_MAC_DESC_LENGTH    0x7ffu
#define AG32_MAC_DESC_EN        (1u << 11) /* owned by MAC when set     */
#define AG32_MAC_DESC_WRAP      (1u << 12) /* last descriptor in ring   */
#define AG32_MAC_DESC_INTEN     (1u << 13)

typedef struct {
    volatile uint32_t CTRL;   /* length + EN/WRAP/INTEN + status bits    */
    volatile uint32_t ADDR;   /* buffer address (4-byte aligned)         */
} ag32_mac_desc_t;

static inline void ag32_mac_configure(ag32_mac_t *mac, uint32_t ctrl) {
    ag32_ahb_enable(AG32_AHB_MAC0);
    mac->CTRL = ctrl;
}

static inline int ag32_mac_reset(ag32_mac_t *mac, uint32_t timeout) {
    ag32_ahb_enable(AG32_AHB_MAC0);
    mac->CTRL |= AG32_MAC_CTRL_RESET;
    while (mac->CTRL & AG32_MAC_CTRL_RESET) {
        if (!timeout--)
            return -1;
    }
    return 0;
}

/* addr[0] is the first byte on the wire; store it in the top of MACMSB. */
static inline void ag32_mac_set_address(ag32_mac_t *mac, const uint8_t addr[6]) {
    mac->MACMSB = ((uint32_t)addr[0] << 8) | (uint32_t)addr[1];
    mac->MACLSB = ((uint32_t)addr[2] << 24) | ((uint32_t)addr[3] << 16) |
                  ((uint32_t)addr[4] << 8) | (uint32_t)addr[5];
}

static inline void ag32_mac_set_rings(ag32_mac_t *mac, const void *tx_base,
                                      const void *rx_base) {
    mac->TXBASE = (uint32_t)(uintptr_t)tx_base;
    mac->RXBASE = (uint32_t)(uintptr_t)rx_base;
}

static inline int ag32_mac_mdio_wait(ag32_mac_t *mac, uint32_t timeout) {
    while (mac->MDIO & AG32_MAC_MDIO_BUSY) {
        if (!timeout--)
            return -1;
    }
    return 0;
}

static inline int ag32_mac_mdio_write(ag32_mac_t *mac, unsigned phy, unsigned reg,
                                      uint16_t value, uint32_t timeout) {
    if (ag32_mac_mdio_wait(mac, timeout))
        return -1;
    mac->MDIO = AG32_MAC_MDIO_DATA(value) | AG32_MAC_MDIO_PHY(phy) |
                AG32_MAC_MDIO_REG(reg) | AG32_MAC_MDIO_WRITE;
    return ag32_mac_mdio_wait(mac, timeout);
}

static inline int ag32_mac_mdio_read(ag32_mac_t *mac, unsigned phy, unsigned reg,
                                     uint16_t *value, uint32_t timeout) {
    if (ag32_mac_mdio_wait(mac, timeout))
        return -1;
    mac->MDIO = AG32_MAC_MDIO_PHY(phy) | AG32_MAC_MDIO_REG(reg) |
                AG32_MAC_MDIO_READ;
    if (ag32_mac_mdio_wait(mac, timeout))
        return -1;
    *value = (uint16_t)(mac->MDIO >> 16);
    return 0;
}

static inline void ag32_mac_start(ag32_mac_t *mac, int tx, int rx) {
    if (tx) mac->CTRL |= AG32_MAC_CTRL_TX_EN;
    if (rx) mac->CTRL |= AG32_MAC_CTRL_RX_EN;
}

static inline uint32_t ag32_mac_status(const ag32_mac_t *mac) { return mac->STAT; }
static inline void ag32_mac_clear_status(ag32_mac_t *mac, uint32_t bits) {
    mac->STAT = bits;
}

/* Hand a filled TX descriptor to the MAC: length + ownership (+ optional wrap). */
static inline void ag32_mac_desc_prepare_tx(ag32_mac_desc_t *desc, void *buffer,
                                            unsigned length, int wrap) {
    desc->ADDR = (uint32_t)(uintptr_t)buffer;
    desc->CTRL = (length & AG32_MAC_DESC_LENGTH) | AG32_MAC_DESC_EN |
                 (wrap ? AG32_MAC_DESC_WRAP : 0u);
}

/* Arm an RX descriptor to receive one frame into buffer. */
static inline void ag32_mac_desc_prepare_rx(ag32_mac_desc_t *desc, void *buffer,
                                            int wrap) {
    desc->ADDR = (uint32_t)(uintptr_t)buffer;
    desc->CTRL = AG32_MAC_DESC_EN | (wrap ? AG32_MAC_DESC_WRAP : 0u);
}

static inline int ag32_mac_desc_owned_by_mac(const ag32_mac_desc_t *desc) {
    return (desc->CTRL & AG32_MAC_DESC_EN) ? 1 : 0;
}

static inline unsigned ag32_mac_desc_length(const ag32_mac_desc_t *desc) {
    return desc->CTRL & AG32_MAC_DESC_LENGTH;
}

#endif /* AGAMEMNON_AG32_MAC_H */
