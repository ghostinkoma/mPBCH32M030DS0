/*
 * サンプル: 保護と警報出力 — 熱・異常電流・短絡・電圧異常で GPIO (既定 PC5) を High にする
 *
 * 負荷として DC モーター (OUT0–OUT1) をエンコーダの duty で回し, 異常を見張る:
 *   短絡 / 瞬時の過電流 … コンパレータ (CMP2: HB0 レッグ CFG_SHORT_LEG_MA, CMP3: バス 25.4A) の割込みで
 *                          数 µs 以内に警報 High + 全ゲート OFF (ソフトの処理を待たない)
 *   持続する過電流       … PWM 同期の相電流が CFG_I_TRIP_MA を CFG_I_TRIP_MS 続けて超えた
 *   過熱 / NTC 異常      … 子基板の NTC (MOSFET の近く)
 *   過電圧 / 低電圧      … VBUS
 * 異常のときは UART に原因を出す (PC4 はボタンに使うので, 表示は警報端子側の LED で)。ラッチ中はボタンを押すと解除 (原因が残っていればすぐ再発報)。
 *
 * 配線: モーター = OUT0–OUT1, エンコーダ A/B = HALL_A_IN / HALL_C_IN (JP2/JP4 = 2-3), 押し = PC4 (USER)。
 *       警報 = J1-5 (GPIO_PC5) → リレー用トランジスタ / PLC 入力 / 抵抗付き LED など (config.h の注意を読むこと)。
 */
#include "config.h"         /* このスケッチの設定 (ピン・定数) */
#include "mpbfun.h"

static uint8_t s_ready;
static int32_t s_duty;

void setup(void)
{
    Mpb_BridgeCfg b = {.pwm_hz = CFG_PWM_HZ, .dead_ns = CFG_DEAD_NS, .max_duty = CFG_MAX_DUTY, .use_tim2 = 0,
                       .hw_break = CFG_HW_BREAK};
    Mpb_DcCfg dc = {.ramp_per_ms = 2};
    Mpb_GuardCfg gd = {.port = CFG_ALARM_PORT, .pin = CFG_ALARM_PIN, .active_low = CFG_ALARM_ACTIVE_LOW,
                       .latch = CFG_ALARM_LATCH, .stop_bridge = 1, .ntc_fault_alarm = CFG_NTC_FAULT_ALARM,
                       .temp_trip_c10 = CFG_TEMP_TRIP_C10, .temp_clear_c10 = CFG_TEMP_CLEAR_C10,
                       .i_trip_mA = CFG_I_TRIP_MA, .i_trip_ms = CFG_I_TRIP_MS,
                       .vbus_max_mV = CFG_VBUS_MAX_MV, .vbus_min_mV = CFG_VBUS_UV_MV};

    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_Guard_Init(&gd);                            /* 最初に警報端子を Low (正常) に確定 */
    Mpb_Bridge_Init(&b);
    Mpb_Bridge_CurrentInit(OPA_ISP_GAIN_16, MPB_ISP_LEG);
    Mpb_Ocp_BusCmp3_Init();                         /* バス 25.4A (短絡) */
    Mpb_Ocp_Cmp2_Init(Mpb_Ocp_DacCode(CFG_SHORT_LEG_MA, OPA_ISP_GAIN_16));   /* HB0 レッグ (短絡) */
    Mpb_Dc_Init(0, &dc);
    Mpb_Enc_Init(NULL, 0, NULL, 0, 4);
    Mpb_Enc_ButtonInit(NULL, 0);
    MPB_LOGI("protect: trip %s C / %u mA (%u ms) / short %u mA / VBUS > %u mV", Mpb_Log_Fixed(CFG_TEMP_TRIP_C10, 1),
             CFG_I_TRIP_MA, CFG_I_TRIP_MS, CFG_SHORT_LEG_MA, CFG_VBUS_MAX_MV);
}

void loop(void)
{
    static uint8_t last;
    uint8_t f;
    int32_t d;

    Mpb_Dc_Task();
    Mpb_Enc_Task();
    f = Mpb_Guard_Task();

    if (f != last)                                  /* 異常の発生・解除をすぐ知らせる */
    {
        if (f) MPB_LOGE("ALARM: %s (T %s C, VBUS %u mV)", Mpb_Guard_Text(f), Mpb_Log_Fixed(Mpb_Guard_TempC10(), 1),
                        Mpb_Vbus_mV());
        else MPB_LOGI("alarm cleared");
        last = f;
    }
    if (f)
    {
        s_duty = 0;
        Mpb_Dc_Coast(0);
        if (Mpb_Enc_Pressed())
        {
            Mpb_Guard_Clear();
            MPB_LOGI("clear requested");
        }
        return;
    }
    if (!s_ready)
    {
        if (Mpb_Bridge_CurrentReady() && Mpb_Vbus_mV() >= CFG_VBUS_MIN_MV)
        {
            s_ready = 1;
            MPB_LOGI("ready");
        }
        return;
    }
    d = Mpb_Enc_Delta();
    if (d)
    {
        s_duty += d * CFG_DUTY_PER_CLICK;
        if (s_duty > (int32_t)CFG_MAX_DUTY) s_duty = CFG_MAX_DUTY;
        if (s_duty < -(int32_t)CFG_MAX_DUTY) s_duty = -(int32_t)CFG_MAX_DUTY;
    }
    if (Mpb_Enc_Pressed())
    {
        s_duty = 0;
    }
    if (s_duty) Mpb_Dc_SetDuty(0, (int16_t)s_duty);
    else Mpb_Dc_Stop(0, 1000);                     /* 回生 → 短絡 → 保持 → 惰性 */

    MPB_EVERY_MS(t_log, CFG_LOG_MS)
    {
        MPB_LOGI("duty %d  I %d mA  T %s C  VBUS %u mV  %s", Mpb_Dc_Duty(0), Mpb_Dc_Current_mA(0),
                 Mpb_Log_Fixed(Mpb_Guard_TempC10(), 1), Mpb_Dc_VbusMv(), Mpb_Guard_Text(f));
    }
}
