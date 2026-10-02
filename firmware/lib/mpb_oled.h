/*
 * mpb_oled — I2C の OLED (SSD1306 / SH1106, 128×64 / 128×32) にテキストとバーを表示する (待ちなし)
 *
 * 画面全体のフレームバッファ (1KB) は持たず, 文字 (21 桁 × 8 行) と行ごとのバー値だけを持ち,
 * 変わった行 (= OLED の 1 ページ, 8 ドット) だけをその場で描いて送る。RAM は約 300 バイト。
 * 送信は mpb_i2c (I2C1, SDA = PA14 / SCL = PA15) を使い, Mpb_Oled_Task() が 1 回に 1 転送ずつ進める。
 * 他の I2C デバイス (HT16K33, センサ) と同じバスに置ける。
 *
 *   Mpb_I2c_Init(400000);
 *   Mpb_Oled_Init(0x3C, 64, MPB_OLED_SSD1306);
 *   Mpb_Oled_Printf(0, "rpm %5d", rpm);    // 0 行目 (変わったときだけ送られる)
 *   Mpb_Oled_Bar(7, 640);                   // 7 行目を 64% のバーに
 *   loop: Mpb_Oled_Task();
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_OLED_H
#define MPB_OLED_H

#include <stdint.h>

#define MPB_OLED_COLS 21u
#define MPB_OLED_ROWS 8u

typedef enum { MPB_OLED_SSD1306 = 0, MPB_OLED_SH1106 = 1 } Mpb_OledType;

void    Mpb_Oled_Init(uint8_t addr7, uint8_t height, Mpb_OledType type);   /* height = 64 / 32 */
void    Mpb_Oled_Clear(void);
void    Mpb_Oled_Print(uint8_t row, uint8_t col, const char *s);           /* 行の途中から書く (行末まで) */
void    Mpb_Oled_Printf(uint8_t row, const char *fmt, ...);                /* 行全体 (残りは空白) */
void    Mpb_Oled_Bar(uint8_t row, uint16_t permille);                      /* 行をバー表示に (0〜1000) */
void    Mpb_Oled_Invert(uint8_t row, uint8_t on);                          /* 行を白黒反転 */
void    Mpb_Oled_Contrast(uint8_t c);
uint8_t Mpb_Oled_Task(void);         /* 送信を 1 手進める。1 = まだ送るものがある */
uint8_t Mpb_Oled_Ready(void);        /* 初期化が終わった (応答あり) */

#endif /* MPB_OLED_H */
