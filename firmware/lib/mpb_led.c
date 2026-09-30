/*
 * mpb_led — CIE 1931 調光 (パワー段のレッグ)
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_led.h"
#include "mpb_cie.h"

typedef struct {
    uint8_t  used, leg, wiring, breathe;
    uint16_t now, from, to, lo, hi;
    uint32_t t0, dur;
} Led;

static Led s_led[4];
static uint32_t s_t_ms;

static void out(Led *l)
{
    if (l->wiring == MPB_LED_LOW)
    {
        Mpb_Bridge_LegLow(l->leg, (uint16_t)Mpb_Cie(l->now, 65535u));
    }
    else
    {
        uint32_t d = Mpb_Cie(l->now, Mpb_Bridge_MaxDuty());
        Mpb_Bridge_Leg(l->leg, d ? (int16_t)d : MPB_LEG_FLOAT);
    }
}

void Mpb_Led_Init(uint8_t ch, uint8_t leg, Mpb_LedWiring wiring)
{
    if (ch > 3) return;
    s_led[ch] = (Led){1, leg, (uint8_t)wiring, 0, 0, 0, 0, 0, 0, 0, 0};
    out(&s_led[ch]);
}

void Mpb_Led_Set(uint8_t ch, uint16_t lx)
{
    if (ch > 3 || !s_led[ch].used) return;
    s_led[ch].breathe = 0;
    s_led[ch].dur = 0;
    s_led[ch].now = lx > 10000u ? 10000u : lx;
    out(&s_led[ch]);
}

void Mpb_Led_Fade(uint8_t ch, uint16_t lx, uint32_t ms)
{
    Led *l;

    if (ch > 3 || !s_led[ch].used) return;
    l = &s_led[ch];
    l->breathe = 0;
    l->from = l->now;
    l->to = lx > 10000u ? 10000u : lx;
    l->t0 = Mpb_Millis();
    l->dur = ms ? ms : 1u;
}

void Mpb_Led_Breathe(uint8_t ch, uint16_t lo, uint16_t hi, uint32_t period_ms)
{
    Led *l;

    if (ch > 3 || !s_led[ch].used) return;
    l = &s_led[ch];
    l->lo = lo;
    l->hi = hi;
    l->breathe = 1;
    l->from = l->now;
    l->to = hi;
    l->t0 = Mpb_Millis();
    l->dur = period_ms / 2u ? period_ms / 2u : 1u;
}

uint16_t Mpb_Led_Get(uint8_t ch) { return ch < 4 ? s_led[ch].now : 0; }
uint8_t Mpb_Led_Busy(uint8_t ch) { return ch < 4 && s_led[ch].dur != 0; }

void Mpb_Led_Task(void)
{
    uint32_t now = Mpb_Millis();

    if (now == s_t_ms) return;
    s_t_ms = now;
    Mpb_Bridge_Vdd8Auto();
    for (uint8_t i = 0; i < 4; i++)
    {
        Led *l = &s_led[i];
        uint32_t el;

        if (!l->used || !l->dur) continue;
        el = now - l->t0;
        if (el >= l->dur)
        {
            l->now = l->to;
            if (l->breathe)
            {
                uint16_t nxt = (l->to == l->hi) ? l->lo : l->hi;   /* 折り返し */
                l->from = l->to;
                l->to = nxt;
                l->t0 = now;
            }
            else
            {
                l->dur = 0;
            }
        }
        else
        {
            l->now = (uint16_t)((int32_t)l->from + ((int32_t)l->to - (int32_t)l->from) * (int32_t)el / (int32_t)l->dur);
        }
        out(l);
    }
}
