/*
 * mpb_stepper — 2 相バイポーラ ステッピングモーター
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_stepper.h"

/* sin 0〜90° を 128 分割 (×65535)。電気角 1 周 = 512 点 = 1/128 マイクロステップ。
 * static const なのでフラッシュに置かれ (258 バイト), RAM は使わない。1/4 周期だけ持ち, 対称性で 1 周に広げる */
#define QSTEPS 128u                      /* 1/4 周期の分割数 */
static const uint16_t k_sin[QSTEPS + 1u] = {
    0, 804, 1608, 2412, 3216, 4019, 4821, 5623, 6424, 7223, 8022, 8820,
    9616, 10411, 11204, 11996, 12785, 13573, 14359, 15142, 15924, 16703, 17479, 18253,
    19024, 19792, 20557, 21319, 22078, 22834, 23586, 24334, 25079, 25820, 26557, 27291,
    28020, 28745, 29465, 30181, 30893, 31600, 32302, 32999, 33692, 34379, 35061, 35738,
    36409, 37075, 37736, 38390, 39039, 39682, 40319, 40950, 41575, 42194, 42806, 43411,
    44011, 44603, 45189, 45768, 46340, 46905, 47464, 48014, 48558, 49095, 49624, 50145,
    50659, 51166, 51664, 52155, 52638, 53113, 53580, 54039, 54490, 54933, 55367, 55794,
    56211, 56620, 57021, 57413, 57797, 58171, 58537, 58895, 59243, 59582, 59913, 60234,
    60546, 60850, 61144, 61429, 61704, 61970, 62227, 62475, 62713, 62942, 63161, 63371,
    63571, 63762, 63943, 64114, 64276, 64428, 64570, 64703, 64826, 64939, 65042, 65136,
    65219, 65293, 65357, 65412, 65456, 65491, 65515, 65530, 65535};

static Mpb_StepperCfg s_cfg;
static volatile int32_t  s_pos;          /* マイクロステップ */
static volatile int32_t  s_rate;         /* マイクロステップ/s (符号 = 向き) */
static volatile uint32_t s_acc;          /* 位相アキュムレータ (Q16) */
static volatile uint32_t s_inc;          /* |s_rate| × 65536 / fPWM (1 周期に複数ステップ進むときは 65536 以上) */
static volatile int32_t  s_target;
static volatile uint8_t  s_goto;         /* 1 = MoveTo 中 */
static volatile uint8_t  s_dirty = 1;
static volatile uint16_t s_amp;          /* 相電圧の振幅 (duty, 0〜65535) */
static volatile int32_t s_vcmd;          /* 連続回転の目標速度 / MoveTo の最高速度 */
static uint8_t  s_en;
static uint32_t s_t_ms, s_idle_ms;

static int32_t sin_e(uint32_t e)         /* e: 0〜511 → −65535〜65535 */
{
    uint32_t q = (e / QSTEPS) & 3u, i = e % QSTEPS;
    int32_t v = (q & 1u) ? k_sin[QSTEPS - i] : k_sin[i];
    return (q & 2u) ? -v : v;
}

/* 振幅 × sin (どちらも 16bit) → 割込み内なので 32bit の掛け算とシフトだけで計算する */
static int32_t scale(uint32_t amp, int32_t sn)
{
    uint32_t m = (amp * (uint32_t)(sn < 0 ? -sn : sn)) >> 16;
    return sn < 0 ? -(int32_t)m : (int32_t)m;
}

static void coil(uint8_t lp, uint8_t ln, int32_t v)
{
    if (v >= 0)
    {
        Mpb_Bridge_LegQ16(lp, (uint16_t)v);
        Mpb_Bridge_LegQ16(ln, 0);
    }
    else
    {
        Mpb_Bridge_LegQ16(lp, 0);
        Mpb_Bridge_LegQ16(ln, (uint16_t)-v);
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
    /* 1 マイクロステップ = 512 / (4 × 分割) 点。フルステップは 45° ずらして両相を励磁 */
    e = (uint32_t)(s_pos * (int32_t)(QSTEPS / s_cfg.microstep)) + (s_cfg.microstep == 1u ? QSTEPS / 2u : 0u);
    a = scale(s_amp, sin_e(e & (4u * QSTEPS - 1u)));
    b = scale(s_amp, sin_e((e + QSTEPS) & (4u * QSTEPS - 1u)));   /* cos = sin + 90° */
    coil(0, 1, a);
    coil(2, 3, b);
}

/* PWM 周期ごと (割込み)。速いときは 1 周期に複数マイクロステップ進める (最大 1 フルステップ = 電気角 90°) */
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
        uint32_t n;
        s_acc += s_inc;
        n = s_acc >> 16;
        if (n)
        {
            s_acc &= 0xFFFFu;
            if (s_goto)
            {
                /* 目標を通り越さない */
                int32_t d = s_target - s_pos;
                uint32_t ad = (uint32_t)(d < 0 ? -d : d);
                if (n > ad) n = ad;
            }
            s_pos += (s_rate > 0) ? (int32_t)n : -(int32_t)n;
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

    if (ar > hz * s_cfg.microstep) ar = hz * s_cfg.microstep;   /* 1 PWM 周期に 1 フルステップまで */
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
        a = i * 65535u / MPB_DUTY_FULL;           /* current_mA を duty‰ として使う */
    }
    else
    {
        /* duty = I × R / VBUS (mA × mΩ / mV = ‰) を 16bit に */
        a = mv ? (uint32_t)((uint64_t)i * s_cfg.coil_r_mohm * 65535u / ((uint64_t)mv * 1000u)) : 0u;
    }
    if (a > (uint32_t)Mpb_Bridge_MaxDuty() * 65535u / MPB_DUTY_FULL)
    {
        a = (uint32_t)Mpb_Bridge_MaxDuty() * 65535u / MPB_DUTY_FULL;
    }
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
    if (s_cfg.microstep == 0 || s_cfg.microstep > QSTEPS || (s_cfg.microstep & (s_cfg.microstep - 1)))
    {
        s_cfg.microstep = 16;
    }
    if (!s_cfg.hold_ms) s_cfg.hold_ms = 500;
    s_pos = s_target = 0;
    s_goto = 0;
    s_idle_ms = 0;
    s_amp = 0;
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
