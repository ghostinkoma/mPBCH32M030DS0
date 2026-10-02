/*
 * mpb_rgbw — RGBW 4ch LED の調光エンジン (CIE 1931)
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_rgbw.h"
#include "mpb_cie.h"

static uint8_t  s_leg[4], s_n;
static uint8_t  s_mode;                     /* 0 = 混合比, 1 = チャネルごとの L* */
static uint16_t s_mix[4];                   /* 混合比 0〜1000 */
static uint8_t  s_lv[4];                    /* チャネルごとの L* 0〜255 */
static uint16_t s_from, s_to, s_now;        /* マスター (L* ×100) */
static uint32_t s_t0, s_dur, s_t_ms;
static uint16_t s_duty[4];
static uint8_t  s_dirty = 1;

void Mpb_Hsv2Rgb(uint16_t hue, uint16_t sat, uint16_t *r, uint16_t *g, uint16_t *b)
{
    uint32_t h = hue % 360u, f = (h % 60u) * 1000u / 60u, v = 1000u;
    uint32_t p, q, t, rr, gg, bb;

    if (sat > 1000u) sat = 1000u;
    p = v * (1000u - sat) / 1000u;
    q = v * (1000u - sat * f / 1000u) / 1000u;
    t = v * (1000u - sat * (1000u - f) / 1000u) / 1000u;
    switch (h / 60u)
    {
    case 0: rr = v; gg = t; bb = p; break;
    case 1: rr = q; gg = v; bb = p; break;
    case 2: rr = p; gg = v; bb = t; break;
    case 3: rr = p; gg = q; bb = v; break;
    case 4: rr = t; gg = p; bb = v; break;
    default: rr = v; gg = p; bb = q; break;
    }
    *r = (uint16_t)rr;
    *g = (uint16_t)gg;
    *b = (uint16_t)bb;
}

void Mpb_Rgbw_Init(const uint8_t legs[4], uint8_t nch)
{
    s_n = (nch == 3u) ? 3u : 4u;
    for (uint8_t i = 0; i < 4; i++)
    {
        s_leg[i] = legs[i];
        s_mix[i] = 1000u;
        s_duty[i] = 0;
    }
    s_now = s_from = s_to = 0;
    s_dur = 0;
    s_mode = 0;
    s_dirty = 1;
}

void Mpb_Rgbw_SetMaster(uint16_t lx, uint32_t ms)
{
    if (lx > 10000u) lx = 10000u;
    s_from = s_now;
    s_to = lx;
    s_t0 = Mpb_Millis();
    s_dur = ms;
    if (!ms)
    {
        s_now = lx;
        s_dirty = 1;
    }
}

uint16_t Mpb_Rgbw_Master(void) { return s_now; }
uint8_t Mpb_Rgbw_Fading(void) { return s_dur != 0 && s_now != s_to; }
uint16_t Mpb_Rgbw_DutyQ16(uint8_t ch) { return ch < 4 ? s_duty[ch] : 0; }

void Mpb_Rgbw_SetColor(uint16_t r, uint16_t g, uint16_t b, uint16_t w)
{
    uint16_t v[4] = {r, g, b, w};
    for (uint8_t i = 0; i < 4; i++) s_mix[i] = v[i] > 1000u ? 1000u : v[i];
    s_mode = 0;
    s_dirty = 1;
}

void Mpb_Rgbw_SetLevels(uint8_t r, uint8_t g, uint8_t b, uint8_t w)
{
    s_lv[0] = r;
    s_lv[1] = g;
    s_lv[2] = b;
    s_lv[3] = w;
    s_mode = 1;
    s_dirty = 1;
}

void Mpb_Rgbw_SetHsv(uint16_t hue, uint16_t sat, uint16_t white)
{
    uint16_t r, g, b;
    Mpb_Hsv2Rgb(hue, sat, &r, &g, &b);
    if (s_n == 3u)
    {
        Mpb_Rgbw_SetColor(r, g, b, 0);           /* RGB のみ: 白は RGB の等量で */
        return;
    }
    /* RGBW: 彩度が低いほど白 LED を足す (white = 白の混合の上限) */
    Mpb_Rgbw_SetColor(r, g, b, (uint16_t)((uint32_t)white * (1000u - (sat > 1000u ? 1000u : sat)) / 1000u));
}

static void apply(void)
{
    uint32_t base = Mpb_Cie(s_now, 65535u);       /* マスターの輝度 (線形) */

    for (uint8_t i = 0; i < s_n; i++)
    {
        uint32_t d;
        if (s_mode == 0)
        {
            d = base * s_mix[i] / 1000u;          /* 線形の混合 */
        }
        else
        {
            /* チャネルごとの L*: 値 (0〜255) × マスター L* → CIE */
            d = Mpb_Cie((uint32_t)s_lv[i] * s_now / 255u, 65535u);
        }
        s_duty[i] = (uint16_t)d;
        Mpb_Bridge_LegLow(s_leg[i], (uint16_t)d);
    }
}

void Mpb_Rgbw_Task(void)
{
    uint32_t now = Mpb_Millis();

    if (now == s_t_ms && !s_dirty)
    {
        return;
    }
    s_t_ms = now;
    Mpb_Bridge_Vdd8Auto();
    if (s_dur && s_now != s_to)
    {
        uint32_t el = now - s_t0;
        if (el >= s_dur)
        {
            s_now = s_to;
        }
        else
        {
            s_now = (uint16_t)((int32_t)s_from + ((int32_t)s_to - (int32_t)s_from) * (int32_t)el / (int32_t)s_dur);
        }
        s_dirty = 1;
    }
    if (s_dirty)
    {
        s_dirty = 0;
        apply();
    }
}
