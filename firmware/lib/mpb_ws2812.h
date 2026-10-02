/*
 * mpb_ws2812 — WS2812B / SK6812 (RGB / RGBW) シリアル LED
 *
 * 既定のデータ端子: PC2 (モジュール J2-2 UART_RX)。UART ログ (TX = PC1) と併用できるが,
 * UART からの書き込み要求は受けられなくなる (スケッチの Makefile で EXTRA_CFLAGS += -DMPB_UART_BOOT=0)。
 * 他の端子も使える (Mpb_Ws2812_Init の port/pin)。3.3V 出力なので, LED を 5V で使うときは先頭 1 個を
 * 3.3〜4V 程度で給電するか, レベル変換 (74AHCT1G125 など) を入れると確実。
 *
 * 送信は SysTick (HCLK) で 1 ビット 1.25µs を刻むビットバング (RAM 上で実行)。
 * 送信中 (LED 1 個 30µs, 8 個で 0.24ms) だけ割込みを止める。モーター PWM と過電流遮断はハードなので止まらない。
 * 色を変えたら Mpb_Ws2812_Show() で「送信予約」し, Mpb_Ws2812_Task() が変化のあったときだけ送る (待ちなし)。
 * 明るさは CIE 1931 L* (Mpb_Cie) で人の目に等間隔になるよう換算できる。
 *
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_WS2812_H
#define MPB_WS2812_H

#include <stdint.h>
#include "mpb.h"

#ifndef MPB_WS2812_MAX
#define MPB_WS2812_MAX 32u                  /* 最大 LED 数 (RAM 4 バイト/個) */
#endif
#if MPB_WS2812_MAX > 600
#error "MPB_WS2812_MAX は 600 まで (送信中は割込みを止めるため, ウォッチドッグ 29ms に収める)"
#endif

typedef enum { MPB_WS_GRB = 0, MPB_WS_RGB, MPB_WS_GRBW, MPB_WS_RGBW } Mpb_WsOrder;

void    Mpb_Ws2812_Init(GPIO_TypeDef *port, uint16_t pin, uint8_t count, Mpb_WsOrder order);
void    Mpb_Ws2812_Set(uint8_t i, uint8_t r, uint8_t g, uint8_t b);
void    Mpb_Ws2812_SetW(uint8_t i, uint8_t r, uint8_t g, uint8_t b, uint8_t w);
void    Mpb_Ws2812_Fill(uint8_t r, uint8_t g, uint8_t b);
void    Mpb_Ws2812_SetLevel(uint8_t i, uint32_t rgb_max, uint16_t lx100);   /* 色 0xRRGGBB を L* (×100) で減光 */
void    Mpb_Ws2812_Hsv(uint8_t i, uint16_t hue, uint8_t sat, uint16_t lx100); /* hue 0〜359 */
void    Mpb_Ws2812_Show(void);               /* 送信予約 */
void    Mpb_Ws2812_Task(void);               /* loop から毎回: 予約があり, 前回から 300µs 以上なら送る */
uint8_t Mpb_Ws2812_Count(void);

#endif /* MPB_WS2812_H */
