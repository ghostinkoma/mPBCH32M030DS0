/*
 * mpb_tm1640 — TM1640 の 2 色 8×8 マトリクスモジュールを数珠つなぎ (ghostinkoma/TM1640MatrixChain の移植)
 *
 * 結線: SCLK を全モジュールで共有し, DIN をモジュールごとに 1 本ずつ (TM1640MatrixChain と同じ)。
 *   全モジュールへ同じクロックで同時に送るので, 枚数が増えても送信時間は変わらない (1 画面 ≈ 0.7ms)。
 *   1 モジュール = 赤 8 列 + 緑 8 列 = 16 バイト (アドレス 0xC0〜, 自動インクリメント)。
 * 既定の端子 (config.h で MPB_UART_BOOT 0 にして PC2 を空ける):
 *   SCLK = PA5 (J1-14), DIN0 = PA6 (J1-16), DIN1 = PA7, DIN2 = PC2 (J2-2), DIN3 = PC4 (J1-4)
 *   PC4 は USER ボタン + 状態 LED と共用なのでオープンドレイン (10k プルアップ) で駆動する。送信中は LED がちらつく。
 *   PA5〜PA7 はホール入力の 4.7k プルアップ + 1k/1nF の RC 付き: JP2〜JP4 を 2-3 にして出力として使う。
 *   RC があるので既定の半周期は 2µs (速い基板なら half_us = 1)。モジュールは 5V 給電でも
 *   3.3V の High をほぼ受ける (TM1640 の VIH = 0.7·VDD = 3.5V なので, 確実にするなら 4.7k を 5V へ)。
 *
 *   static Mpb_Matrix mx;
 *   Mpb_Tm1640Cfg c = {0};          // 既定の端子で 4 枚
 *   c.n = 4;
 *   Mpb_Tm1640_Init(&c, &mx);
 *   Mpb_Matrix_Marquee(&mx, "HELLO ", MPB_MX_ORANGE, 40);
 *   loop: Mpb_Tm1640_Task();
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_TM1640_H
#define MPB_TM1640_H

#include <stdint.h>
#include "mpb.h"
#include "mpb_matrix.h"

#define MPB_TM1640_MAX 8u

typedef struct {
    GPIO_TypeDef *sclk_port;                 /* NULL = PA5 */
    uint16_t sclk_pin;
    GPIO_TypeDef *din_port[MPB_TM1640_MAX];  /* NULL = 既定 (PA6, PA7, PC2, PC4) */
    uint16_t din_pin[MPB_TM1640_MAX];
    uint8_t  n;                              /* モジュールの枚数 (1〜8) */
    uint8_t  duty;                           /* 明るさ 0〜7 (1/16 … 14/16), 既定 0 は 1/16 */
    uint8_t  half_us;                        /* クロックの半周期 [µs] (0 = 2) */
} Mpb_Tm1640Cfg;

void    Mpb_Tm1640_Init(const Mpb_Tm1640Cfg *cfg, Mpb_Matrix *m);    /* m->w = 8 × 枚数 にする */
void    Mpb_Tm1640_SetDuty(uint8_t duty);                            /* 0〜7 (次の送信で反映) */
void    Mpb_Tm1640_Flush(void);              /* 今すぐ全モジュールへ送る (≈ 0.7ms, 割込みは止めない) */
uint8_t Mpb_Tm1640_Task(void);               /* 流す + 変わっていれば送る。1 = 送った */

#endif /* MPB_TM1640_H */
