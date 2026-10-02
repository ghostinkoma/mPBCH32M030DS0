/*
 * mpb_font5x7 — 5×7 ドットの ASCII フォント (列ごと 1 バイト, bit0 = 上)。0x7F = ° (度)
 */
#ifndef MPB_FONT5X7_H
#define MPB_FONT5X7_H

#include <stdint.h>

extern const uint8_t mpb_font5x7[96][5];

/* 文字 → グリフ (範囲外は '?') */
static inline const uint8_t *Mpb_Font5x7(char c)
{
    uint8_t u = (uint8_t)c;
    if (u < 0x20u || u > 0x7Fu) u = '?';
    return mpb_font5x7[u - 0x20u];
}

#endif /* MPB_FONT5X7_H */
