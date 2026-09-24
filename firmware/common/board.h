/*
 * mPBCH32M030DS0 ボード定義 (ブートローダ / アプリ共通)
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照
 */
#ifndef MPB_BOARD_H
#define MPB_BOARD_H

#include "ch32m030.h"

/* ---- フラッシュ配置 (64KB) --------------------------------------------------
 * 0x08000000 - 0x08004FFF : ブートローダ (20KB, WCH IAP 互換)
 * 0x08005000 - 0x0800FF7F : アプリケーション (44KB - 128B)
 * 0x0800FF80 - 0x0800FFFF : ブート要求フラグページ (末尾 4 バイトにマジック値)
 */
#define MPB_APP_ADDR        0x08005000u
#define MPB_APP_OFFSET      0x00005000u
#define MPB_FLAG_ADDR       (0x08010000u - 4u)
#define MPB_FLAG_MAGIC      0x5aa55aa5u

/* USB: WCH IAP 互換 (VID 0x1A86 / PID 0x55E0, ベンダークラス, EP2 バルク)
 * bcdDevice の上位バイトで区別する: 0xB0 = ブートローダ, 0xA0 = アプリ */
#define MPB_BCD_BOOTLOADER  0xB001
#define MPB_BCD_APP         0xA001

/* ---- ピン ---------------------------------------------------------------- */
/* USER/BOOT ボタン: PC4 (Low = 押下, 外部 10k プルアップ) */
#define MPB_BOOTKEY_PORT    GPIOC
#define MPB_BOOTKEY_PIN     GPIO_Pin_4
#define MPB_BOOTKEY_RCC     RCC_PB2Periph_GPIOC
/* 状態 LED: PC4 (USER/BOOT と共用, Low = 点灯)。+3V3 - LED - 1k - PC4 なのでオープンドレインで駆動する
 * (ボタン押下で Low になっても短絡しない) */
#define MPB_LED_PORT        GPIOC
#define MPB_LED_PIN         GPIO_Pin_4
#define MPB_LED_RCC         RCC_PB2Periph_GPIOC
#define MPB_LED_ON          Bit_RESET
#define MPB_LED_OFF         Bit_SET
/* USB-PD 給電パス許可: PC3 (High = U5 LM74700 有効, 外部 100k プルダウン) */
#define MPB_PDEN_PORT       GPIOC
#define MPB_PDEN_PIN        GPIO_Pin_3
/* UART: USART1 リマップ1 (TX = PC1, RX = PC2)。PC0 は RST ピン */
#define MPB_UART_REMAP      GPIO_PartialRemap1_USART1
#define MPB_UART_BAUD       460800u

/* ---- 割り込み属性 --------------------------------------------------------
 * MounRiver (WCH GCC) では WCH 独自の高速割り込み、
 * 汎用 GCC (Ubuntu riscv64-unknown-elf / xPack) では標準の machine 割り込みを使う。 */
#ifdef USE_STD_IRQ_ATTR
#define MPB_IRQ __attribute__((interrupt("machine")))
#else
#define MPB_IRQ __attribute__((interrupt("WCH-Interrupt-fast")))
#endif

#endif /* MPB_BOARD_H */
