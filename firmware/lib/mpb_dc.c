/*
 * mpb_dc — ブラシ付き DC モーター
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_dc.h"

typedef struct {
    Mpb_DcCfg  cfg;
    Mpb_DcMode mode;
    int16_t    target;      /* duty モードの目標 (±‰) */
    int16_t    duty;        /* 実際の duty (±‰) */
    int32_t    i_ref;       /* 電流モードの目標 [mA] */
    int32_t    integ;       /* PI の積分項 (‰ × 1000) */
    uint8_t    used;
} Dc;

static Dc s_m[2];
static uint32_t s_vbus_mv;
static uint32_t s_t_ms;

/* レッグ番号: モーター 0 = HB0/HB1, モーター 1 = HB2/HB3 */
static void apply(uint8_t m)
{
    Dc *d = &s_m[m];
    uint8_t a = (uint8_t)(m * 2u), b = (uint8_t)(a + 1u);

    switch (d->mode)
    {
    case MPB_DC_COAST:
        Mpb_Bridge_Leg(a, MPB_LEG_FLOAT);
        Mpb_Bridge_Leg(b, MPB_LEG_FLOAT);
        break;
    case MPB_DC_BRAKE:
        Mpb_Bridge_Leg(a, 0);
        Mpb_Bridge_Leg(b, 0);
        break;
    default:
        if (d->duty >= 0)
        {
            Mpb_Bridge_Leg(a, d->duty);   /* 正転: A を PWM, B はローサイド ON */
            Mpb_Bridge_Leg(b, 0);
        }
        else
        {
            Mpb_Bridge_Leg(a, 0);
            Mpb_Bridge_Leg(b, (int16_t)-d->duty);
        }
        break;
    }
}

void Mpb_Dc_Init(uint8_t m, const Mpb_DcCfg *cfg)
{
    static const Mpb_DcCfg dflt = {0, 0, 2, 0, 0, 0};
    Dc *d;

    if (m > 1)
    {
        return;
    }
    d = &s_m[m];
    d->cfg = cfg ? *cfg : dflt;
    if (!d->cfg.kp) d->cfg.kp = 40;
    if (!d->cfg.ki) d->cfg.ki = 4;
    d->mode = MPB_DC_COAST;
    d->duty = d->target = 0;
    d->i_ref = d->integ = 0;
    d->used = 1;
    apply(m);
}

void Mpb_Dc_SetDuty(uint8_t m, int16_t duty)
{
    if (m > 1) return;
    if (duty > MPB_DUTY_FULL) duty = MPB_DUTY_FULL;
    if (duty < -MPB_DUTY_FULL) duty = -MPB_DUTY_FULL;
    if (s_m[m].mode != MPB_DC_DUTY)
    {
        s_m[m].duty = 0;          /* 停止状態からは ramp で立ち上げる */
        s_m[m].mode = MPB_DC_DUTY;
    }
    s_m[m].target = duty;
}

void Mpb_Dc_SetCurrent(uint8_t m, int32_t mA)
{
    if (m > 1) return;
    if (s_m[m].mode != MPB_DC_CURRENT)
    {
        s_m[m].integ = (int32_t)s_m[m].duty * 1000;   /* 今の duty から滑らかに移る */
        s_m[m].mode = MPB_DC_CURRENT;
    }
    s_m[m].i_ref = mA;
}

void Mpb_Dc_Coast(uint8_t m)
{
    if (m > 1) return;
    s_m[m].mode = MPB_DC_COAST;
    s_m[m].duty = s_m[m].target = 0;
    apply(m);
}

void Mpb_Dc_Brake(uint8_t m)
{
    if (m > 1) return;
    s_m[m].mode = MPB_DC_BRAKE;
    s_m[m].duty = s_m[m].target = 0;
    apply(m);
}

Mpb_DcMode Mpb_Dc_Mode(uint8_t m) { return m < 2 ? s_m[m].mode : MPB_DC_COAST; }
int16_t Mpb_Dc_Duty(uint8_t m) { return m < 2 ? s_m[m].duty : 0; }
uint32_t Mpb_Dc_VbusMv(void) { return s_vbus_mv; }

int32_t Mpb_Dc_Current_mA(uint8_t m)
{
    /* シャントは各レッグのローサイドの帰路。PWM の山では両ローサイド ON で,
     * 正転の電流は B レッグに +I, A レッグに −I が流れる (ソース → GND を正) */
    if (m == 0)
    {
        return (Mpb_Bridge_Current_mA(1) - Mpb_Bridge_Current_mA(0)) / 2;
    }
    return -Mpb_Bridge_Current_mA(1);   /* モーター 1: IB = HB2 (JP5=2-3) */
}

int32_t Mpb_Dc_Rpm(uint8_t m)
{
    Dc *d;
    int32_t mv;

    if (m > 1 || !s_m[m].cfg.kv_rpm_per_v) return 0;
    d = &s_m[m];
    mv = (int32_t)s_vbus_mv * d->duty / MPB_DUTY_FULL;                      /* 平均印加電圧 */
    mv -= Mpb_Dc_Current_mA(m) * (int32_t)d->cfg.r_mohm / 1000;             /* 巻線の電圧降下 */
    if ((d->duty > 0 && mv < 0) || (d->duty < 0 && mv > 0)) mv = 0;
    return mv * (int32_t)d->cfg.kv_rpm_per_v / 1000;
}

static int16_t clamp_duty(int32_t v)
{
    int32_t mx = Mpb_Bridge_MaxDuty();
    return (int16_t)(v > mx ? mx : (v < -mx ? -mx : v));
}

void Mpb_Dc_Task(void)
{
    uint32_t now = Mpb_Millis();

    if (now == s_t_ms)
    {
        return;                              /* 1ms ごと */
    }
    s_t_ms = now;
    Mpb_Bridge_Vdd8Auto();
    s_vbus_mv = Mpb_Vbus_mV();
    for (uint8_t m = 0; m < 2; m++)
    {
        Dc *d = &s_m[m];
        int32_t i = Mpb_Dc_Current_mA(m);

        if (!d->used || Mpb_Bridge_Faulted())
        {
            continue;
        }
        if (d->mode == MPB_DC_DUTY)
        {
            int32_t step = d->cfg.ramp_per_ms ? d->cfg.ramp_per_ms : MPB_DUTY_FULL;
            int32_t tgt = d->target;
            /* 電流制限: 超えた分だけ目標を 0 側へ寄せる */
            if (d->cfg.i_limit_mA && (i > (int32_t)d->cfg.i_limit_mA || i < -(int32_t)d->cfg.i_limit_mA))
            {
                tgt = d->duty - (d->duty > 0 ? 5 : -5);
            }
            if (tgt > d->duty + step) tgt = d->duty + step;
            if (tgt < d->duty - step) tgt = d->duty - step;
            d->duty = clamp_duty(tgt);
        }
        else if (d->mode == MPB_DC_CURRENT && Mpb_Bridge_CurrentReady())
        {
            int32_t ref = d->i_ref, e, out;
            if (d->cfg.i_limit_mA)
            {
                if (ref > (int32_t)d->cfg.i_limit_mA) ref = d->cfg.i_limit_mA;
                if (ref < -(int32_t)d->cfg.i_limit_mA) ref = -(int32_t)d->cfg.i_limit_mA;
            }
            e = ref - i;                                           /* mA */
            d->integ += e * (int32_t)d->cfg.ki;                    /* ‰×1000 / ms */
            if (d->integ > 1000000) d->integ = 1000000;
            if (d->integ < -1000000) d->integ = -1000000;
            out = (e * (int32_t)d->cfg.kp + d->integ) / 1000;
            d->duty = clamp_duty(out);
            if (d->duty == Mpb_Bridge_MaxDuty() || d->duty == -(int16_t)Mpb_Bridge_MaxDuty())
            {
                d->integ -= e * (int32_t)d->cfg.ki;                /* 飽和中は積分しない */
            }
        }
        apply(m);
    }
}
