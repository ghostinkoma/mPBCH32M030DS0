/*
 * mpb_rgbw — パワー段 (MOSFET) で駆動する RGBW 4ch LED の調光エンジン (CIE 1931)
 *
 * LED テープ (12V/24V, RGBW 共通アノード) の + を VBUS, R/G/B/W の − を OUT0〜OUT3 へつなぎ,
 * 各レッグのローサイドだけで PWM する (Mpb_Bridge_LegLow, 16bit, 0〜100%)。HB3 を使うので use_tim2 = 1。
 *
 * 明るさは 2 段で決める:
 *   マスター明るさ  … L* (×100, 0〜10000)。フェード付き。CIE 1931 で人の目に等間隔
 *   色             … ① 線形の混合比 (Mpb_Rgbw_SetColor: 各 0〜1000) → duty = CIE(マスター) × 比
 *                     ② チャネルごとの L* (Mpb_Rgbw_SetLevels: WS2812 の 0〜255 など) → duty = CIE(値 × マスター)
 *   どちらも最後に CIE 1931 L* → 輝度 で duty にするので, 暗いところまで目に自然に変わる。
 * Mpb_Rgbw_Task() が 1ms ごとにフェードを進めて出力する (待ちなし)。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_RGBW_H
#define MPB_RGBW_H

#include <stdint.h>
#include "mpb_bridge.h"

void     Mpb_Rgbw_Init(const uint8_t legs[4], uint8_t nch);    /* nch = 3 (RGB) / 4 (RGBW)。legs: 各色の出力 0〜3 */
void     Mpb_Rgbw_SetMaster(uint16_t lx100, uint32_t fade_ms); /* マスター明るさ (L* ×100) */
uint16_t Mpb_Rgbw_Master(void);                                /* 現在 (フェード途中) のマスター */
uint8_t  Mpb_Rgbw_Fading(void);
void     Mpb_Rgbw_SetColor(uint16_t r, uint16_t g, uint16_t b, uint16_t w);   /* 線形の混合比 0〜1000 */
void     Mpb_Rgbw_SetLevels(uint8_t r, uint8_t g, uint8_t b, uint8_t w);      /* チャネルごとの L* (0〜255) */
void     Mpb_Rgbw_SetHsv(uint16_t hue, uint16_t sat1000, uint16_t white1000);  /* 色相 0〜359, 彩度, 白の混合 */
void     Mpb_Rgbw_Task(void);
uint16_t Mpb_Rgbw_DutyQ16(uint8_t ch);                         /* 出力中の duty (0〜65535) */

/* 色相・彩度 → 線形の RGB 比 (0〜1000)。単体でも使える */
void     Mpb_Hsv2Rgb(uint16_t hue, uint16_t sat1000, uint16_t *r, uint16_t *g, uint16_t *b);

#endif /* MPB_RGBW_H */
