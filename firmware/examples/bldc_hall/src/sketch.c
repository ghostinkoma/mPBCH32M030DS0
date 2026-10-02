/*
 * サンプル: 3 相ブラシレス (ホールセンサ付き) — 正転 / 逆転, タコ (ホール周期 / TACH_IN)
 *
 * 配線: U/V/W = OUT0/OUT1/OUT2。ホール A/B/C → HALL_A/B/C_IN (J1-14〜16), JP2〜JP4 = 2-3, ホールの電源は +5V (J1-7)。
 *       JP7 = 1-2 (IA = U), JP5 = 1-2 (IB = V)。外部タコがあれば TACH_IN (J1-20, JP8 = 1-2)。
 * 操作: USER ボタン (PC4) を押すたびに duty を 0 → +15% → +30% → +50% → 0 → −15% → −30% → −50% → 0 …
 *       (向きを変えるときはライブラリが一度止めてから反転する)
 * 回らない / 振動する / 逆に回るときは Mpb_BldcCfg.hall_shift を 0〜5 で変える (ホールと相の対応がモーターで違う)。
 */
#include "config.h"         /* このスケッチの設定 (ピン・定数) */
#include "mpbfun.h"

static const int16_t k_steps[] = {0, 150, 300, 500, 0, -150, -300, -500};
static uint8_t s_idx, s_ready;

void setup(void)
{
    Mpb_BridgeCfg b = {.pwm_hz = CFG_PWM_HZ, .dead_ns = CFG_DEAD_NS, .max_duty = CFG_MAX_DUTY, .use_tim2 = 0,
                       .hw_break = CFG_HW_BREAK};
    Mpb_BldcCfg m = {.sense = MPB_BLDC_HALL, .pole_pairs = CFG_POLE_PAIRS, .hall_shift = CFG_HALL_SHIFT,
                     .ramp_per_ms = CFG_RAMP_PER_MS,
                     .i_limit_mA = CFG_I_LIMIT_MA, .tach_ppr = CFG_TACH_PPR};

    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_PD_Init(NULL);
    Mpb_Bridge_Init(&b);
    Mpb_Bridge_CurrentInit(OPA_ISP_GAIN_16, MPB_ISP_LEG);
    Mpb_Ocp_BusCmp3_Init();
    Mpb_Tach_Init(OPA1_QII1_AVSEL_20, CMP1_QII1_HYPSEL_100mv);   /* TACH_IN → TIM3 CH1 (外部タコ) */
    Mpb_Bldc_Init(&m);
    Mpb_Enc_ButtonInit(NULL, 0);                                  /* USER ボタンだけ使う */
    MPB_LOGI("bldc_hall: pole pairs %u, hall=%u", CFG_POLE_PAIRS, Mpb_Bldc_HallState());
}

void loop(void)
{
    Mpb_PD_Task();
    Mpb_Bldc_Task();
    Mpb_Enc_Task();

    if (!s_ready)
    {
        if (Mpb_Bridge_CurrentReady() && Mpb_Vbus_mV() >= CFG_VBUS_MIN_MV)
        {
            s_ready = 1;
            MPB_LOGI("ready");
        }
        return;
    }
    if (Mpb_Bridge_Faulted())
    {
        MPB_EVERY_MS(t_f, 1000) { MPB_LOGE("overcurrent! press button to clear"); }
        if (Mpb_Enc_Pressed())
        {
            Mpb_Bridge_ClearFault();
            s_idx = 0;
            Mpb_Bldc_Coast();
        }
        return;
    }
    if (Mpb_Enc_Pressed())
    {
        s_idx = (uint8_t)((s_idx + 1u) % (sizeof(k_steps) / sizeof(k_steps[0])));
        Mpb_Bldc_SetDuty(k_steps[s_idx]);
        MPB_LOGI("duty -> %d", k_steps[s_idx]);
    }
    MPB_EVERY_MS(t_log, CFG_LOG_MS)
    {
        MPB_LOGI("duty %d  hall %u  rpm %d (hall)  %d (TACH_IN)  I %d mA  comm %u", Mpb_Bldc_Duty(),
                 Mpb_Bldc_HallState(), Mpb_Bldc_Rpm(), Mpb_Bldc_TachRpm(), Mpb_Bldc_Current_mA(),
                 Mpb_Bldc_Commutations());
    }
}
