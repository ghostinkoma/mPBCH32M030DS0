/*
 * サンプル: DC モーター (ブラシ付き) — 正転 / 逆転, 電流制御, ロータリーエンコーダで操作
 *
 * 配線: モーターを OUT0 (HB0) と OUT1 (HB1) の間へ。子基板の JP7 = 1-2, JP5 = 1-2 (出荷時のまま)。
 *       エンコーダ A → HALL_A_IN (J1-14, JP2 = 2-3), B → HALL_C_IN (J1-16, JP4 = 2-3), 押し → USER ボタン (PC4)。
 * 操作: 回す      … 速度モード: 回転数の目安 (Kv から逆算した duty) ±50rpm / クリック
 *                   電流モード: 目標電流 ±50mA / クリック (符号 = 向き)
 *       短く押す  … 停止 (0 に戻す)
 *       長押し    … 速度モード ⇔ 電流モードの切り替え
 * DC モーターは電流 (= トルク) しか直接制御できないので, 回転数は Kv [rpm/V] と巻線抵抗から概算する。
 * ログ: UART (J2-3 TX, 460800bps) に 200ms ごと。
 */
#include "mpbfun.h"

#define KV_RPM_PER_V   800u     /* 例: 12V で無負荷 9600rpm のモーター */
#define R_MOHM         1500u    /* 例: 巻線抵抗 1.5Ω */
#define I_LIMIT_MA     3000u

static uint8_t s_current_mode;
static int32_t s_set;           /* 速度モード: rpm, 電流モード: mA */
static uint8_t s_ready;

void setup(void)
{
    Mpb_BridgeCfg b = {.pwm_hz = 20000, .dead_ns = 500, .max_duty = 900, .use_tim2 = 0, .hw_break = 0};
    Mpb_DcCfg dc = {.kv_rpm_per_v = KV_RPM_PER_V, .r_mohm = R_MOHM, .ramp_per_ms = 2, .i_limit_mA = I_LIMIT_MA};

    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_PD_Init(NULL);                              /* USB-PD からモーター電源を取る場合 */
    Mpb_Bridge_Init(&b);
    Mpb_Bridge_CurrentInit(OPA_ISP_GAIN_16, MPB_ISP_LEG);   /* ±10A 程度 */
    Mpb_Ocp_BusCmp3_Init();                         /* バス 25.4A でハード停止 (割込み) */
    Mpb_Ocp_Cmp2_Init(Mpb_Ocp_DacCode(8000, OPA_ISP_GAIN_16));   /* HB0 レッグ 8A */
    Mpb_Dc_Init(0, &dc);
    Mpb_Enc_Init(NULL, 0, NULL, 0, 4);
    Mpb_Enc_ButtonInit(NULL, 0);
    MPB_LOGI("dc_motor: Kv=%u rpm/V R=%u mOhm", KV_RPM_PER_V, R_MOHM);
}

/* 目標回転数 → duty (逆算): duty = (rpm / Kv + I × R) / VBUS */
static int16_t rpm_to_duty(int32_t rpm)
{
    int32_t vbus = (int32_t)Mpb_Dc_VbusMv();
    int32_t mv = rpm * 1000 / (int32_t)KV_RPM_PER_V;
    int32_t i = Mpb_Dc_Current_mA(0);
    mv += i * (int32_t)R_MOHM / 1000;
    return vbus > 0 ? (int16_t)(mv * 1000 / vbus) : 0;
}

void loop(void)
{
    int32_t d;

    Mpb_PD_Task();
    Mpb_Dc_Task();
    Mpb_Enc_Task();

    /* 起動条件: VBUS ≥ 8V かつ電流オフセットの校正が済んだ */
    if (!s_ready)
    {
        if (Mpb_Bridge_CurrentReady() && Mpb_Dc_VbusMv() >= 8000u)
        {
            s_ready = 1;
            MPB_LOGI("ready: VBUS %s V", Mpb_Log_Fixed((int32_t)Mpb_Dc_VbusMv() / 10, 2));
        }
        return;
    }
    if (Mpb_Bridge_Faulted())
    {
        MPB_EVERY_MS(t_f, 1000) { MPB_LOGE("overcurrent! press button to clear"); }
        if (Mpb_Enc_Pressed())
        {
            Mpb_Bridge_ClearFault();
            s_set = 0;
            Mpb_Dc_Coast(0);
        }
        return;
    }

    d = Mpb_Enc_Delta();
    if (d)
    {
        s_set += d * 50;
        MPB_LOGI("set %d %s", s_set, s_current_mode ? "mA" : "rpm");
    }
    if (Mpb_Enc_Pressed())
    {
        s_set = 0;
    }
    if (Mpb_Enc_LongPressed())
    {
        s_current_mode ^= 1;
        s_set = 0;
        MPB_LOGI("mode: %s", s_current_mode ? "current" : "speed (Kv)");
    }

    if (s_set == 0)
    {
        Mpb_Dc_Brake(0);                            /* 0 は短絡ブレーキで止める */
    }
    else if (s_current_mode)
    {
        Mpb_Dc_SetCurrent(0, s_set);
    }
    else
    {
        Mpb_Dc_SetDuty(0, rpm_to_duty(s_set));
    }

    MPB_EVERY_MS(t_log, 200)
    {
        MPB_LOGI("duty %d  I %d mA  rpm~%d  VBUS %u mV", Mpb_Dc_Duty(0), Mpb_Dc_Current_mA(0), Mpb_Dc_Rpm(0),
                 Mpb_Dc_VbusMv());
    }
}
