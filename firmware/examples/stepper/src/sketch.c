/*
 * サンプル: ステッピングモーター (2 相バイポーラ) — 正転 / 逆転, マイクロステップ 1/16, ソフトウェア タコ
 *
 * 配線: A 相 = OUT0 (A+) / OUT1 (A−), B 相 = OUT2 (B+) / OUT3 (B−)。JP7 = 1-2, JP5 = 2-3 (IB = HB2)。
 *       エンコーダ A → HALL_A_IN (JP2 = 2-3), B → HALL_C_IN (JP4 = 2-3), 押し → USER ボタン (PC4)。
 * 操作: 回す     … 連続回転の回転数 ±10rpm / クリック (0 を越えると逆転)
 *       短く押す … 停止
 *       長押し   … 位置決めデモ: 1 回転先へ移動 → 元の位置へ戻る を 1 往復
 * 電流は「電流 × 巻線抵抗 ÷ VBUS」で duty に換算する (電圧モード)。実際の相電流は PWM 同期で測ってログに出す。
 */
#include "config.h"         /* このスケッチの設定 (ピン・定数) */
#include "mpbfun.h"

static uint8_t s_ready, s_demo;
static int32_t s_rpm;

void setup(void)
{
    Mpb_BridgeCfg b = {.pwm_hz = CFG_PWM_HZ, .dead_ns = CFG_DEAD_NS, .max_duty = CFG_MAX_DUTY, .use_tim2 = 1,
                       .hw_break = CFG_HW_BREAK};
    Mpb_StepperCfg st = {.steps_per_rev = CFG_STEPS_PER_REV, .microstep = CFG_MICROSTEP, .current_mA = CFG_COIL_MA,
                         .coil_r_mohm = CFG_COIL_R_MOHM, .accel = CFG_ACCEL, .hold_pct = CFG_HOLD_PCT,
                         .hold_ms = CFG_HOLD_MS};

    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_PD_Init(NULL);
    Mpb_Bridge_Init(&b);
    Mpb_Bridge_CurrentInit(OPA_ISP_GAIN_16, MPB_ISP_LEG);
    Mpb_Ocp_BusCmp3_Init();
    Mpb_Stepper_Init(&st);
    Mpb_Enc_Init(NULL, 0, NULL, 0, 4);
    Mpb_Enc_ButtonInit(NULL, 0);
    MPB_LOGI("stepper: %u steps/rev, 1/%u, %u mA", CFG_STEPS_PER_REV, CFG_MICROSTEP, CFG_COIL_MA);
}

void loop(void)
{
    int32_t d;

    Mpb_PD_Task();
    Mpb_Stepper_Task();
    Mpb_Enc_Task();

    if (!s_ready)
    {
        if (Mpb_Bridge_CurrentReady() && Mpb_Vbus_mV() >= CFG_VBUS_MIN_MV)
        {
            s_ready = 1;
            Mpb_Stepper_Enable(1);                  /* 校正が済んでから励磁する */
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
            Mpb_Stepper_SetSpeed(0);
            Mpb_Stepper_Enable(1);
        }
        return;
    }

    d = Mpb_Enc_Delta();
    if (d && !s_demo)
    {
        s_rpm += d * CFG_RPM_PER_CLICK;
        Mpb_Stepper_SetRpm(s_rpm);
        MPB_LOGI("target %d rpm", s_rpm);
    }
    if (Mpb_Enc_Pressed())
    {
        s_rpm = 0;
        s_demo = 0;
        Mpb_Stepper_Stop();
    }
    if (Mpb_Enc_LongPressed() && !s_demo)
    {
        s_rpm = 0;
        s_demo = 1;
        Mpb_Stepper_Move((int32_t)(CFG_STEPS_PER_REV * CFG_MICROSTEP), CFG_DEMO_SPEED);   /* 1 回転, 最高 8000 µstep/s */
        MPB_LOGI("demo: +1 rev");
    }
    /* 位置決めデモ: 到着したら戻る */
    if (s_demo && !Mpb_Stepper_Busy())
    {
        if (s_demo == 1)
        {
            s_demo = 2;
            Mpb_Stepper_MoveTo(0, CFG_DEMO_SPEED);
            MPB_LOGI("demo: back to 0");
        }
        else
        {
            s_demo = 0;
            MPB_LOGI("demo: done at %d", Mpb_Stepper_Position());
        }
    }

    MPB_EVERY_MS(t_log, CFG_LOG_MS)
    {
        MPB_LOGI("pos %d  %s rpm  IA %d mA  IB %d mA", Mpb_Stepper_Position(), Mpb_Log_Fixed(Mpb_Stepper_RpmX10(), 1),
                 Mpb_Stepper_CoilA_mA(), Mpb_Stepper_CoilB_mA());
    }
}
