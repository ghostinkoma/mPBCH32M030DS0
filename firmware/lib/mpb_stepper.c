/*
 * mpb_stepper — 2 相バイポーラ ステッピングモーター
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_stepper.h"

/* sin 0〜90° を 32 分割 (×1000)。電気角 1 周 = 128 (1/32 マイクロステップ) */
static const uint16_t k_sin[33] = {
    0, 49, 98, 146, 195, 243, 290, 337, 383, 428, 471, 514, 556, 596, 634, 672,
    707, 741, 773, 803, 831, 858, 882, 904, 924, 942, 957, 970, 981, 989, 995, 999, 1000};

static Mpb_StepperCfg s_cfg;
static volatile int32_t  s_pos;          /* マイクロステップ */
static volatile int32_t  s_rate;         /* マイクロステップ/s (符号 = 向き) */
static volatile uint32_t s_acc;          /* 位相アキュムレータ (Q16) */
static volatile uint32_t s_inc;          /* |s_rate| × 65536 / fPWM */
static volatile int32_t  s_target;
static volatile uint8_t  s_goto;         /* 1 = MoveTo 中 */
static volatile uint8_t  s_dirty = 1;
static volatile uint16_t s_amp;          /* 相電圧の振幅 [‰] */
static volatile int32_t s_vcmd;          /* 連続回転の目標速度 / MoveTo の最高速度 */
static uint8_t  s_en;
static uint32_t s_t_ms, s_idle_ms;

static int16_t sin_e(uint32_t e)         /* e: 0〜127 */
{
    uint32_t q = (e >> 5) & 3u, i = e & 31u;
    int16_t v = (int16_t)((q & 1u) ? k_sin[32u - i] : k_sin[i]);
    return (q & 2u) ? (int16_t)-v : v;
}

static void coil(uint8_t lp, uint8_t ln, int32_t v)
{
    if (v >= 0)
    {
        Mpb_Bridge_Leg(lp, (int16_t)v);
        Mpb_Bridge_Leg(ln, 0);
    }
    else
    {
        Mpb_Bridge_Leg(lp, 0);
        Mpb_Bridge_Leg(ln, (int16_t)-v);
    }
}

static void output(void)
{
    uint32_t e;
    int32_t a, b;

    if (!s_en)
    {
        return;
    }
    e = (uint32_t)(s_pos * (int32_t)(32u / s_cfg.microstep)) + (s_cfg.microstep == 1u ? 16u : 0u);
    a = (int32_t)s_amp * sin_e(e & 127u) / 1000;
    b = (int32_t)s_amp * sin_e((e + 32u) & 127u) / 1000;   /* cos = sin + 90° */
    coil(0, 1, a);
    coil(2, 3, b);
}

/* PWM 周期ごと (割込み) */
static void step_isr(int32_t ia, int32_t ib)
{
    (void)ia;
    (void)ib;
    if (s_goto && s_pos == s_target)
    {
        s_rate = 0;
        s_inc = 0;
        s_goto = 0;
        s_vcmd = 0;                                /* 到着したら停止のまま */
    }
    if (s_inc)
    {
        s_acc += s_inc;
        if (s_acc >= 65536u)
        {
            s_acc -= 65536u;
            s_pos += (s_rate > 0) ? 1 : -1;
            s_dirty = 1;
        }
    }
    if (s_dirty)
    {
        s_dirty = 0;
        output();
    }
}

static void set_rate(int32_t r)
{
    uint32_t hz = Mpb_Bridge_PwmHz();
    uint32_t ar = (uint32_t)(r < 0 ? -r : r);

    if (ar > hz) ar = hz;                          /* 1 PWM 周期に 1 ステップまで */
    __disable_irq();
    s_rate = r < 0 ? -(int32_t)ar : (int32_t)ar;
    s_inc = (uint32_t)(((uint64_t)ar << 16) / hz);
    __enable_irq();
}

static void update_amp(void)
{
    uint32_t mv = Mpb_Vbus_mV(), a;
    uint32_t i = s_cfg.current_mA;

    if (s_rate == 0 && s_cfg.hold_pct && s_idle_ms >= s_cfg.hold_ms)
    {
        i = i * s_cfg.hold_pct / 100u;
    }
    if (s_cfg.coil_r_mohm == 0u)
    {
        a = i;                                    /* current_mA を duty‰ として使う */
    }
    else
    {
        a = mv ? (uint32_t)((uint64_t)i * s_cfg.coil_r_mohm / mv) : 0u;   /* mA×mΩ/mV = ‰ */
    }
    if (a > Mpb_Bridge_MaxDuty()) a = Mpb_Bridge_MaxDuty();
    if (a != s_amp)
    {
        s_amp = (uint16_t)a;
        s_dirty = 1;
    }
}

void Mpb_Stepper_Init(const Mpb_StepperCfg *cfg)
{
    static const Mpb_StepperCfg dflt = {200, 16, 500, 0, 20000, 50, 500};

    s_cfg = cfg ? *cfg : dflt;
    if (!s_cfg.steps_per_rev) s_cfg.steps_per_rev = 200;
    if (s_cfg.microstep == 0 || s_cfg.microstep > 32 || (s_cfg.microstep & (s_cfg.microstep - 1)))
    {
        s_cfg.microstep = 16;
    }
    if (!s_cfg.hold_ms) s_cfg.hold_ms = 500;
    s_pos = s_target = 0;
    s_goto = 0;
    set_rate(0);
    s_en = 0;
    Mpb_Bridge_AddHook(step_isr);
}

void Mpb_Stepper_Enable(uint8_t on)
{
    s_en = on;
    if (!on)
    {
        for (uint8_t i = 0; i < 4; i++) Mpb_Bridge_Leg(i, MPB_LEG_FLOAT);
    }
    else
    {
        update_amp();
        s_dirty = 1;
    }
}

void Mpb_Stepper_SetSpeed(int32_t usps)
{
    s_goto = 0;
    s_vcmd = usps;
}

void Mpb_Stepper_SetRpm(int32_t rpm)
{
    Mpb_Stepper_SetSpeed(rpm * (int32_t)s_cfg.steps_per_rev * s_cfg.microstep / 60);
}

void Mpb_Stepper_MoveTo(int32_t pos, uint32_t vmax)
{
    s_target = pos;
    s_vcmd = (int32_t)vmax;
    s_goto = (pos != s_pos);
}

void Mpb_Stepper_Move(int32_t delta, uint32_t vmax) { Mpb_Stepper_MoveTo(s_pos + delta, vmax); }

void Mpb_Stepper_Stop(void)
{
    s_goto = 0;
    s_vcmd = 0;
}

void Mpb_Stepper_SetCurrent(uint16_t mA)
{
    s_cfg.current_mA = mA;
    update_amp();
}

void Mpb_Stepper_Task(void)
{
    uint32_t now = Mpb_Millis();
    int32_t v = s_rate, want;
    int32_t dv = (int32_t)(s_cfg.accel / 1000u);   /* 1ms あたりの速度変化 */

    if (now == s_t_ms)
    {
        return;
    }
    s_idle_ms = (v == 0) ? s_idle_ms + (now - s_t_ms) : 0u;
    Mpb_Bridge_Vdd8Auto();
    s_t_ms = now;
    if (dv == 0) dv = 0x7FFFFFFF;

    if (s_goto)
    {
        int32_t d = s_target - s_pos;                 /* 残り距離 */
        int32_t ad = d < 0 ? -d : d;
        int32_t av = v < 0 ? -v : v;
        /* 減速距離 v²/(2a) 以下になったら減速 (台形) */
        uint64_t stop = s_cfg.accel ? (uint64_t)av * (uint64_t)av / (2u * s_cfg.accel) : 0u;
        int32_t vm = s_vcmd < 0 ? -s_vcmd : s_vcmd;
        int32_t vmin = dv > 50 ? dv : 50;             /* 目標の手前は最低速で寄せる (停止は割込みで正確に) */
        if (vmin > vm) vmin = vm;
        if (d == 0 || (d > 0 && v < 0) || (d < 0 && v > 0))
        {
            want = 0;                                 /* 到着 / 逆向きに動いていたらまず止める */
        }
        else
        {
            int32_t mag = ((uint64_t)ad <= stop + 1u) ? av - dv : vm;   /* 減速区間 / 巡航 */
            if (mag < vmin) mag = vmin;
            want = (d > 0) ? mag : -mag;
        }
    }
    else
    {
        want = s_vcmd;
    }
    if (want > v + dv) want = v + dv;
    if (want < v - dv) want = v - dv;
    if (want != v)
    {
        set_rate(want);
    }
    update_amp();
}

int32_t Mpb_Stepper_Position(void) { return s_pos; }

void Mpb_Stepper_SetPosition(int32_t pos)
{
    __disable_irq();
    s_pos = pos;
    s_target = pos;
    s_goto = 0;
    __enable_irq();
}

int32_t Mpb_Stepper_Speed(void) { return s_rate; }

int32_t Mpb_Stepper_RpmX10(void)
{
    return (int32_t)((int64_t)s_rate * 600 / ((int32_t)s_cfg.steps_per_rev * s_cfg.microstep));
}

int32_t Mpb_Stepper_Rpm(void) { return Mpb_Stepper_RpmX10() / 10; }
uint8_t Mpb_Stepper_Busy(void) { return s_goto || s_rate != 0 || s_vcmd != 0; }

/* 相電流: 山ではシャントに −I が流れる (PWM 側・ON 側どちらの向きでも A+ から A− を正とすると IA = −I) */
int32_t Mpb_Stepper_CoilA_mA(void) { return -Mpb_Bridge_Current_mA(0); }
int32_t Mpb_Stepper_CoilB_mA(void) { return -Mpb_Bridge_Current_mA(1); }
