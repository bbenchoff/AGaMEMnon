#ifndef AGAMEMNON_AG32_BOARD_L48_H
#define AGAMEMNON_AG32_BOARD_L48_H

#include "ag32.h"

/* Vendor-default MCU peripheral routes. Custom fabric images may change them. */
#define AG32_BOARD_LED1_GPIO_BIT 1u
#define AG32_BOARD_LED2_GPIO_BIT 2u
#define AG32_BOARD_LED3_GPIO_BIT 3u
#define AG32_BOARD_LED4_GPIO_BIT 4u
#define AG32_BOARD_LED1_PACKAGE_PIN 34u
#define AG32_BOARD_LED2_PACKAGE_PIN 33u
#define AG32_BOARD_LED3_PACKAGE_PIN 32u
#define AG32_BOARD_LED4_PACKAGE_PIN 31u

/* Direct programmable-fabric LED pads qualified by AGaMEMnon. */
#define AG32_FABRIC_LED1_PACKAGE_PIN 25u
#define AG32_FABRIC_LED2_PACKAGE_PIN 26u
#define AG32_FABRIC_LED3_PACKAGE_PIN 27u
#define AG32_FABRIC_LED4_PACKAGE_PIN 28u

#endif
