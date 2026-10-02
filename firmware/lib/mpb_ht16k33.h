/*
 * mpb_ht16k33 — HT16K33(A) の 8×8 マトリクスモジュールを I2C で数珠つなぎ (待ちなし)
 *
 * 各モジュールのアドレスを A0〜A2 のジャンパで 0x70, 0x71, 0x72, … と連番にして同じ I2C バスへ。
 * 8 枚 (0x70〜0x77) まで。OLED や I2C センサと同じバス (SDA = PA14, SCL = PA15) に置ける。
 * モジュール 0 (先頭アドレス) が左端。描画は Mpb_Matrix (mpb_matrix.h) で行う。
 * Mpb_Ht16k33_Task() は 1 回に 1 転送 (1 モジュール 17 バイト) ずつ進め, 変わったモジュールだけ送る。
 *
 * モジュールによって LED のつなぎ方が違うので map で選ぶ:
 *   MPB_HT_PLAIN     行 y = アドレス 2y, 列 x = bit x
 *   MPB_HT_ADAFRUIT  Adafruit 8x8 バックパック (列が 1 ビットずれている: bit = (x + 7) & 7)
 *   MPB_HT_BICOLOR   Adafruit 2 色 8x8: 行 y の緑 = アドレス 2y, 赤 = 2y + 1
 *   | MPB_HT_COLROW   アドレス = 列, ビット = 行 (行と列を入れ替えて配線したモジュール)
 *   | MPB_HT_FLIPX / MPB_HT_FLIPY  左右 / 上下反転 (モジュールを逆さまに付けたとき)
 *
 *   static Mpb_Matrix mx;
 *   Mpb_I2c_Init(400000);
 *   Mpb_Ht16k33_Init(0x70, 4, MPB_HT_ADAFRUIT, &mx);
 *   Mpb_Matrix_Marquee(&mx, "HELLO ", MPB_MX_RED, 40);
 *   loop: Mpb_Ht16k33_Task();
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_HT16K33_H
#define MPB_HT16K33_H

#include <stdint.h>
#include "mpb_matrix.h"

#define MPB_HT16K33_MAX 8u

enum {
    MPB_HT_PLAIN = 0, MPB_HT_ADAFRUIT = 1, MPB_HT_BICOLOR = 2,
    MPB_HT_COLROW = 0x10, MPB_HT_FLIPX = 0x20, MPB_HT_FLIPY = 0x40
};

void    Mpb_Ht16k33_Init(uint8_t first_addr7, uint8_t n, uint8_t map, Mpb_Matrix *m);   /* m->w = 8 × 枚数 */
void    Mpb_Ht16k33_Brightness(uint8_t b);   /* 0〜15 */
void    Mpb_Ht16k33_Blink(uint8_t mode);     /* 0 = 点灯, 1 = 2Hz, 2 = 1Hz, 3 = 0.5Hz */
uint8_t Mpb_Ht16k33_Task(void);              /* 1 = まだ送るものがある */
uint8_t Mpb_Ht16k33_Online(void);            /* 応答したモジュールのビット (bit i = モジュール i) */

#endif /* MPB_HT16K33_H */
