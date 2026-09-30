/*
 * サンプル: 3 相ブラシレス (センサなし, オープンループ) — エンコーダで回転数, ソフトウェア タコ
 *
 * センサの無いモーター (ファン・ポンプ・ジンバル用など) を同期モーターとして回す。V/f で周波数と電圧を上げる。
 * 軽負荷・一定速度向け: 負荷が急に増えると脱調する (このモードでは検出できない)。
 * 回転数は転流周期から計算する (= 指令どおりに回っている前提のソフトウェア タコ)。
 * 実回転を確かめたいときは TACH_IN (J1-20) に回転センサ / FG 出力をつなぐと Mpb_Bldc_TachRpm() で読める。
 *
 * 配線: U/V/W = OUT0/OUT1/OUT2。エンコーダ A → HALL_A_IN (JP2 = 2-3), B → HALL_C_IN (JP4 = 2-3), 押し → PC4。
 * 操作: 回す … 目標回転数 ±100rpm / クリック (符号 = 向き)。押す … 停止。
 */
#include "mpbfun.h"

#define POLE_PAIRS  7u          /* 例: 14 極のアウターロータ */

static int32_t s_rpm;
static uint8_t s_ready;

void setup(void)
{
    Mpb_BridgeCfg b = {.pwm_hz = 20000, .dead_ns = 500, .max_duty = 900, .use_tim2 = 0, .hw_break = 0};
    Mpb_BldcCfg m = {.sense = MPB_BLDC_OPEN, .pole_pairs = POLE_PAIRS, .i_limit_mA = 3000,
                     .open_start_hz = 5, .open_hz_per_s = 30, .open_duty_per_hz = 15, .open_min_duty = 60,
                     .tach_ppr = 1};

    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_PD_Init(NULL);
    Mpb_Bridge_Init(&b);
    Mpb_Bridge_CurrentInit(OPA_ISP_GAIN_16, MPB_ISP_LEG);
    Mpb_Ocp_BusCmp3_Init();
    Mpb_Tach_Init(OPA1_QII1_AVSEL_20, CMP1_QII1_HYPSEL_100mv);
    Mpb_Bldc_Init(&m);
    Mpb_Enc_Init(NULL, 0, NULL, 0, 4);
    Mpb_Enc_ButtonInit(NULL, 0);
    MPB_LOGI("bldc_open: pole pairs %u", POLE_PAIRS);
}

void loop(void)
{
    int32_t d;

    Mpb_PD_Task();
    Mpb_Bldc_Task();
    Mpb_Enc_Task();

    if (!s_ready)
    {
        if (Mpb_Bridge_CurrentReady() && Mpb_Vbus_mV() >= 8000u)
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
            s_rpm = 0;
            Mpb_Bldc_Coast();
        }
        return;
    }
    d = Mpb_Enc_Delta();
    if (d)
    {
        s_rpm += d * 100;
        Mpb_Bldc_SetRpm(s_rpm);
        MPB_LOGI("target %d rpm", s_rpm);
    }
    if (Mpb_Enc_Pressed())
    {
        s_rpm = 0;
        Mpb_Bldc_SetRpm(0);
    }
    MPB_EVERY_MS(t_log, 250)
    {
        MPB_LOGI("rpm %d (soft)  %d (TACH_IN)  duty %d  I %d mA", Mpb_Bldc_Rpm(), Mpb_Bldc_TachRpm(), Mpb_Bldc_Duty(),
                 Mpb_Bldc_Current_mA());
    }
}
