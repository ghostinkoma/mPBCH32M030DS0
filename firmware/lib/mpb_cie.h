/*
 * mpb_cie — CIE 1931 L* (明度) カーブ: 人の目に等間隔に見える明るさ → PWM duty
 *
 *   L* ≤ 8 : Y = L* / 903.3             (暗部の直線)
 *   L* > 8 : Y = ((L* + 16) / 116)^3    (べき乗)
 *   duty = maxval × Y  (整数演算のみ)
 * L* は 1/100 単位 (0〜10000) で渡す。ghostinkoma/Ch32LightBox の cie.h と同じ式。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_CIE_H
#define MPB_CIE_H

#include <stdint.h>

static inline uint32_t Mpb_Cie(uint32_t lx100, uint32_t maxval)
{
    uint32_t d;

    if (lx100 > 10000u) lx100 = 10000u;
    if (lx100 <= 800u)
    {
        d = (uint32_t)((uint64_t)maxval * lx100 / 90330u);                       /* /903.3 (×100) */
    }
    else
    {
        uint64_t t = (uint64_t)(lx100 + 1600u);                                    /* (L*+16) ×100 */
        d = (uint32_t)((uint64_t)maxval * t * t * t / 1560896000000ull);           /* (116×100)^3 */
    }
    return d > maxval ? maxval : d;
}

/* 段階 i (0〜levels) → L* 等間隔 → duty */
static inline uint32_t Mpb_CieLevel(uint32_t i, uint32_t levels, uint32_t maxval)
{
    return Mpb_Cie(levels ? 10000u * i / levels : 0u, maxval);
}

#endif /* MPB_CIE_H */
