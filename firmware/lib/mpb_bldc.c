/*
 * mpb_bldc — 3 相ブラシレスモーター (6 ステップ)
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_bldc.h"

/* セクタ → (PWM する相, ローサイド ON の相)。残りの 1 相は開放 */
static const uint8_t k_hi[6] = {0, 0, 1, 1, 2, 2};
static const uint8_t k_lo[6] = {1, 2, 2, 0, 0, 1};
/* ホール状態 (A=bit0, B=bit1, C=bit2) → セクタ。正転の並び 1,3,2,6,4,5 を 0〜5 に対応させる */
static const int8_t k_hall[8] = {-1, 0, 2, 1, 4, 5, 3, -1};

static Mpb_BldcCfg s_cfg;
static volatile int16_t  s_duty;           /* 実際の |duty| に符号 (向き) */
static int16_t  s_target;
static volatile uint8_t  s_sector;
static volatile uint8_t  s_run;            /* 0 = 開放 / ブレーキ中 */
static volatile uint32_t s_period_us;      /* ホール: エッジ間隔 */
static volatile int8_t   s_rot;            /* 実際の回転方向 (+1 / −1) */
static volatile uint32_t s_commut;
static volatile int8_t   s_last_hsec = -1;
/* オープンループ */
static volatile uint32_t s_acc, s_inc;
static int32_t  s_hz_x10, s_hz_target_x10;   /* 0.1Hz 単位 */
static uint32_t s_t_ms;

uint8_t Mpb_Bldc_HallState(void)
{
    uint32_t in = GPIOA->INDR;
    return (uint8_t)(((in >> 5) & 1u) | (((in >> 7) & 1u) << 1) | (((in >> 6) & 1u) << 2));
}

static void apply(uint8_t sec)
{
    int16_t d = s_duty < 0 ? (int16_t)-s_duty : s_duty;
    uint8_t hi = k_hi[sec], lo = k_lo[sec];

    for (uint8_t p = 0; p < 3; p++)
    {
        if (p == hi) Mpb_Bridge_Leg(p, d);
        else if (p == lo) Mpb_Bridge_Leg(p, 0);
        else Mpb_Bridge_Leg(p, MPB_LEG_FLOAT);
    }
    if (sec != s_sector)
    {
        s_commut++;
    }
    s_sector = sec;
}

/* ホールから転流 (割込み・Task 共通) */
static void hall_commutate(void)
{
    int8_t hs = k_hall[Mpb_Bldc_HallState()];
    uint8_t sec;

    if (hs < 0)
    {
        Mpb_Bridge_Leg(0, MPB_LEG_FLOAT);        /* ホール異常: 開放 */
        Mpb_Bridge_Leg(1, MPB_LEG_FLOAT);
        Mpb_Bridge_Leg(2, MPB_LEG_FLOAT);
        return;
    }
    if (s_last_hsec >= 0 && hs != s_last_hsec)
    {
        s_rot = (hs == (s_last_hsec + 1) % 6) ? 1 : -1;
    }
    s_last_hsec = hs;
    if (!s_run)
    {
        return;
    }
    /* 正転は 1 セクタ先 (ロータ位置の 90° 先) を励磁, 逆転は反対向き (+3 セクタ) */
    sec = (uint8_t)((hs + 1 + s_cfg.hall_shift + (s_duty < 0 ? 3 : 0)) % 6);
    apply(sec);
}

void TIM2_IRQHandler(void) MPB_IRQ;

void TIM2_IRQHandler(void)
{
    if (TIM_GetITStatus(TIM2, TIM_IT_CC1) != RESET)
    {
        /* ホール I/F: エッジごとに CNT をリセットし, 直前の CNT を CH1 に捕捉 = エッジ間隔 [µs] */
        s_period_us = TIM_GetCapture1(TIM2);
        TIM_ClearITPendingBit(TIM2, TIM_IT_CC1);
        hall_commutate();
    }
    if (TIM_GetITStatus(TIM2, TIM_IT_Update) != RESET)
    {
        s_period_us = 0;                          /* 65ms エッジ無し = 停止とみなす */
        TIM_ClearITPendingBit(TIM2, TIM_IT_Update);
    }
}

/* オープンループ: PWM 周期ごとに位相を進める */
static void open_isr(int32_t ia, int32_t ib)
{
    (void)ia;
    (void)ib;
    if (!s_run || !s_inc)
    {
        return;
    }
    s_acc += s_inc;
    if (s_acc >= 65536u)
    {
        s_acc -= 65536u;
        apply((uint8_t)((s_sector + (s_hz_x10 >= 0 ? 1 : 5)) % 6));
    }
}

void Mpb_Bldc_Init(const Mpb_BldcCfg *cfg)
{
    static const Mpb_BldcCfg dflt = {MPB_BLDC_HALL, 2, 0, 2, 0, 5, 20, 20, 60, 0};

    s_cfg = cfg ? *cfg : dflt;
    if (!s_cfg.pole_pairs) s_cfg.pole_pairs = 2;
    if (!s_cfg.open_start_hz) s_cfg.open_start_hz = 5;
    if (!s_cfg.open_hz_per_s) s_cfg.open_hz_per_s = 20;
    if (!s_cfg.open_duty_per_hz) s_cfg.open_duty_per_hz = 20;
    if (!s_cfg.open_min_duty) s_cfg.open_min_duty = 60;
    s_cfg.hall_shift %= 6;
    s_run = 0;
    s_duty = s_target = 0;
    s_hz_x10 = s_hz_target_x10 = 0;
    Mpb_Bldc_Coast();
    if (s_cfg.sense == MPB_BLDC_HALL)
    {
        Mpb_Hall_Init();                          /* core: TIM2 ホール I/F + CC1 割込み */
        TIM_ITConfig(TIM2, TIM_IT_Update, ENABLE);
    }
    else
    {
        Mpb_Bridge_AddHook(open_isr);
    }
}

void Mpb_Bldc_SetDuty(int16_t duty)
{
    if (duty > MPB_DUTY_FULL) duty = MPB_DUTY_FULL;
    if (duty < -MPB_DUTY_FULL) duty = -MPB_DUTY_FULL;
    s_target = duty;
}

void Mpb_Bldc_SetOpenHz(int16_t e_hz) { s_hz_target_x10 = (int32_t)e_hz * 10; }
void Mpb_Bldc_SetRpm(int32_t rpm)
{
    s_hz_target_x10 = rpm * (int32_t)s_cfg.pole_pairs / 6;   /* ×10 / 60 */
}

void Mpb_Bldc_Coast(void)
{
    s_run = 0;
    s_duty = s_target = 0;
    s_hz_x10 = s_hz_target_x10 = 0;
    s_inc = 0;
    for (uint8_t p = 0; p < 3; p++) Mpb_Bridge_Leg(p, MPB_LEG_FLOAT);
}

void Mpb_Bldc_Brake(void)
{
    Mpb_Bldc_Coast();
    for (uint8_t p = 0; p < 3; p++) Mpb_Bridge_Leg(p, 0);
}

int16_t Mpb_Bldc_Duty(void) { return s_duty; }
uint32_t Mpb_Bldc_Commutations(void) { return s_commut; }

int32_t Mpb_Bldc_Current_mA(void)
{
    int32_t iu = Mpb_Bridge_Current_mA(0), iv = Mpb_Bridge_Current_mA(1);
    uint8_t lo = k_lo[s_sector];
    /* 山ではローサイド ON の相のシャントに +I (ソース → GND) が流れる */
    return lo == 0 ? iu : (lo == 1 ? iv : -(iu + iv));
}

int32_t Mpb_Bldc_Rpm(void)
{
    if (s_cfg.sense == MPB_BLDC_HALL)
    {
        uint32_t p = s_period_us;
        if (!p) return 0;
        return (int32_t)(60000000u / (p * 6u * s_cfg.pole_pairs)) * s_rot;
    }
    return s_hz_x10 * 6 / (int32_t)s_cfg.pole_pairs;           /* Hz×10 × 60 / 10 / pp */
}

int32_t Mpb_Bldc_TachRpm(void)
{
    uint32_t p = Mpb_Tach_PeriodUs();
    if (!s_cfg.tach_ppr || !p) return 0;
    return (int32_t)(60000000u / (p * s_cfg.tach_ppr));
}

static int16_t clampd(int32_t v)
{
    int32_t mx = Mpb_Bridge_MaxDuty();
    return (int16_t)(v > mx ? mx : (v < -mx ? -mx : v));
}

void Mpb_Bldc_Task(void)
{
    uint32_t now = Mpb_Millis();
    int32_t step = s_cfg.ramp_per_ms ? s_cfg.ramp_per_ms : MPB_DUTY_FULL;
    int32_t i;

    if (now == s_t_ms || Mpb_Bridge_Faulted())
    {
        return;
    }
    Mpb_Bridge_Vdd8Auto();
    s_t_ms = now;
    i = Mpb_Bldc_Current_mA();
    if (i < 0) i = -i;

    if (s_cfg.sense == MPB_BLDC_HALL)
    {
        int32_t tgt = s_target;
        /* 向きを変えるときは一度 0 を通り, 回転が止まってから反転する */
        if ((tgt > 0 && s_duty < 0) || (tgt < 0 && s_duty > 0) || (s_duty == 0 && tgt != 0 && Mpb_Bldc_Rpm() * tgt < 0))
        {
            tgt = 0;
        }
        if (s_cfg.i_limit_mA && i > (int32_t)s_cfg.i_limit_mA)
        {
            tgt = s_duty - (s_duty > 0 ? 5 : (s_duty < 0 ? -5 : 0));
        }
        if (tgt > s_duty + step) tgt = s_duty + step;
        if (tgt < s_duty - step) tgt = s_duty - step;
        __disable_irq();
        s_duty = clampd(tgt);
        s_run = (s_duty != 0);
        if (s_run)
        {
            hall_commutate();                     /* 起動時・duty 変更時 (同じセクタなら duty の更新だけ) */
        }
        else
        {
            for (uint8_t p = 0; p < 3; p++) Mpb_Bridge_Leg(p, MPB_LEG_FLOAT);
        }
        __enable_irq();
    }
    else
    {
        /* オープンループ: 周波数を目標へ (Hz/s), duty は V/f */
        int32_t df = (int32_t)s_cfg.open_hz_per_s * 10 / 1000;   /* 0.1Hz / ms */
        int32_t tgt = s_hz_target_x10, f, d;
        if (df < 1) df = 1;
        if (tgt != 0 && s_hz_x10 == 0)
        {
            s_hz_x10 = (tgt > 0 ? 1 : -1) * (int32_t)s_cfg.open_start_hz * 10;
        }
        if ((tgt > 0 && s_hz_x10 < 0) || (tgt < 0 && s_hz_x10 > 0)) tgt = 0;
        if (tgt > s_hz_x10 + df) tgt = s_hz_x10 + df;
        if (tgt < s_hz_x10 - df) tgt = s_hz_x10 - df;
        if (tgt != 0 && tgt > -(int32_t)s_cfg.open_start_hz * 10 && tgt < (int32_t)s_cfg.open_start_hz * 10 &&
            s_hz_target_x10 == 0)
        {
            tgt = 0;                              /* 起動周波数を下回ったら止める */
        }
        s_hz_x10 = tgt;
        f = tgt < 0 ? -tgt : tgt;
        d = (int32_t)s_cfg.open_duty_per_hz * f / 100;           /* ‰×10/Hz × Hz×10 / 100 */
        if (d < (int32_t)s_cfg.open_min_duty) d = s_cfg.open_min_duty;
        if (s_cfg.i_limit_mA && i > (int32_t)s_cfg.i_limit_mA && s_duty > 0)
        {
            d = (s_duty < 0 ? -s_duty : s_duty) - 5;
        }
        __disable_irq();
        s_duty = (tgt == 0) ? 0 : clampd(tgt > 0 ? d : -d);
        /* 1 セクタ = 1/(6f) 秒。PWM 周期あたりの位相 = 6f / fPWM (Q16) */
        s_inc = (uint32_t)(((uint64_t)f * 6u * 65536u / 10u) / Mpb_Bridge_PwmHz());
        if (tgt == 0)
        {
            s_run = 0;
            for (uint8_t p = 0; p < 3; p++) Mpb_Bridge_Leg(p, MPB_LEG_FLOAT);
        }
        else if (!s_run)
        {
            s_run = 1;
            apply(s_sector);
        }
        else
        {
            apply(s_sector);                      /* duty の更新 */
        }
        __enable_irq();
    }
}
