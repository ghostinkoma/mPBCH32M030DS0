/*
 * mpb_guard — 保護と警報出力
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include <string.h>
#include "mpb_guard.h"
#include "mpb_bridge.h"

static Mpb_GuardCfg s_cfg;
static volatile uint8_t s_flags;        /* 現在 (ラッチ込み) の異常 */
static uint8_t  s_alarm;
static uint16_t s_over_ms;
static int32_t  s_temp = INT32_MIN;
static uint32_t s_t_ms, s_t_slow;

static void alarm_out(uint8_t on)
{
    uint8_t level = on ^ (s_cfg.active_low ? 1u : 0u);
    if (level) s_cfg.port->BSHR = s_cfg.pin;
    else s_cfg.port->BCR = s_cfg.pin;
    s_alarm = on;
}

/* 過電流 (短絡) の割込みから: すぐに警報を出す */
static void on_short(void)
{
    s_flags |= MPB_GUARD_SHORT;
    alarm_out(1);
}

void Mpb_Guard_Init(const Mpb_GuardCfg *cfg)
{
    GPIO_InitTypeDef g = {0};

    s_cfg = *cfg;
    if (!s_cfg.port)
    {
        s_cfg.port = GPIOC;
        s_cfg.pin = GPIO_Pin_5;
    }
    if (s_cfg.temp_clear_c10 == 0 || s_cfg.temp_clear_c10 > s_cfg.temp_trip_c10)
    {
        s_cfg.temp_clear_c10 = (int16_t)(s_cfg.temp_trip_c10 - 100);   /* 既定のヒステリシス 10℃ */
    }
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA | RCC_PB2Periph_GPIOB | RCC_PB2Periph_GPIOC, ENABLE);
    s_flags = 0;
    alarm_out(0);                                  /* 先に出力値を決めてから出力にする */
    g.GPIO_Pin = s_cfg.pin;
    g.GPIO_Mode = GPIO_Mode_Out_PP;
    g.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(s_cfg.port, &g);
    Mpb_Adc_Init();
    Mpb_Ntc_Init();
    Mpb_Bridge_SetFaultHook(on_short);
}

uint8_t Mpb_Guard_Flags(void) { return s_flags; }
uint8_t Mpb_Guard_Alarm(void) { return s_alarm; }
int32_t Mpb_Guard_TempC10(void) { return s_temp; }

void Mpb_Guard_Clear(void)
{
    __disable_irq();
    s_flags = 0;
    s_over_ms = 0;
    __enable_irq();
    if (Mpb_Bridge_Faulted())
    {
        Mpb_Bridge_ClearFault();
    }
    alarm_out(0);
}

uint8_t Mpb_Guard_Task(void)
{
    uint32_t now = Mpb_Millis();
    uint8_t now_flags = 0, keep;
    int32_t ia, ib, imax;

    if (now == s_t_ms)
    {
        return s_flags;
    }
    s_t_ms = now;

    /* 短絡: コンパレータの割込み (core の OPA_IRQHandler) が立てたフラグ */
    if (g_mpb_overcurrent)
    {
        now_flags |= MPB_GUARD_SHORT;
    }
    /* 持続する過電流 (PWM 同期の相電流) */
    if (s_cfg.i_trip_mA && Mpb_Bridge_CurrentReady())
    {
        ia = Mpb_Bridge_Current_mA(0);
        ib = Mpb_Bridge_Current_mA(1);
        imax = (ia < 0 ? -ia : ia) > (ib < 0 ? -ib : ib) ? (ia < 0 ? -ia : ia) : (ib < 0 ? -ib : ib);
        s_over_ms = (imax > (int32_t)s_cfg.i_trip_mA) ? (uint16_t)(s_over_ms < 60000u ? s_over_ms + 1u : s_over_ms) : 0u;
        if (s_over_ms >= (s_cfg.i_trip_ms ? s_cfg.i_trip_ms : 1u))
        {
            now_flags |= MPB_GUARD_OVERCURRENT;
        }
    }
    /* 温度と電圧は 100ms ごと (ADC の読み取り) */
    if (now - s_t_slow >= 100u)
    {
        s_t_slow = now;
        s_temp = Mpb_Ntc_DeciCelsius();
    }
    if (s_temp == INT32_MIN)
    {
        if (s_cfg.ntc_fault_alarm) now_flags |= MPB_GUARD_NTC_FAULT;
    }
    else if (s_cfg.temp_trip_c10)
    {
        /* ヒステリシス: 過熱中は temp_clear まで下がるまで解除しない */
        int32_t th = (s_flags & MPB_GUARD_OVERTEMP) ? s_cfg.temp_clear_c10 : s_cfg.temp_trip_c10;
        if (s_temp >= th) now_flags |= MPB_GUARD_OVERTEMP;
    }
    if (s_cfg.vbus_max_mV || s_cfg.vbus_min_mV)
    {
        uint32_t vb = Mpb_Vbus_mV();
        if (s_cfg.vbus_max_mV && vb > s_cfg.vbus_max_mV) now_flags |= MPB_GUARD_OVERVOLT;
        if (s_cfg.vbus_min_mV && vb < s_cfg.vbus_min_mV) now_flags |= MPB_GUARD_UNDERVOLT;
    }

    /* ラッチしないときは原因が消えたら下ろす (短絡はブリッジの故障解除まで残る) */
    keep = s_cfg.latch ? s_flags : 0u;
    __disable_irq();
    s_flags = (uint8_t)(keep | now_flags);
    __enable_irq();
    if (s_cfg.stop_bridge && (now_flags & ~MPB_GUARD_SHORT) && !Mpb_Bridge_Faulted())
    {
        Mpb_Bridge_Trip();                         /* ソフトで検出した異常でも全ゲート OFF (故障扱い) */
    }
    alarm_out(s_flags != 0);
    return s_flags;
}

const char *Mpb_Guard_Text(uint8_t f)
{
    static char b[64];
    static const char *const k[6] = {"SHORT", "OVERCURRENT", "OVERTEMP", "NTC_FAULT", "OVERVOLT", "UNDERVOLT"};

    b[0] = 0;
    for (uint8_t i = 0; i < 6; i++)
    {
        if (f & (1u << i))
        {
            if (b[0]) strcat(b, " ");
            strcat(b, k[i]);
        }
    }
    if (!b[0]) strcpy(b, "OK");
    return b;
}
