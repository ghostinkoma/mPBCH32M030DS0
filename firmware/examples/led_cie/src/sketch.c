/*
 * サンプル: MOSFET (パワー段) につないだ単色 LED の CIE 1931 調光
 *
 * 配線: LED テープ (12V 等, 電流制限抵抗入り) の + を VBUS (電源端子), − を OUT0 へ。
 *       → HB0 のローサイドだけで PWM する (MPB_LED_LOW)。0〜100% を使え, ブートストラップの制約もない。
 *       4 レッグあるので RGBW テープも同じように 4 チャネルで点灯できる (use_tim2 = 1 で HB3 まで)。
 *       エンコーダ A → HALL_A_IN (JP2 = 2-3), B → HALL_C_IN (JP4 = 2-3), 押し → PC4。
 * 操作: 回す … 明るさ (L* 2% 刻み, 0.3 秒でフェード)。押す … 呼吸 ⇔ 固定。
 * PWM は 2kHz (分解能 1/18000): 暗いところまでなめらかにするため, モーター用の 20kHz より下げている。
 * 明るさは L* (人の目に等間隔) で指定し, duty = CIE 1931 の式で換算する (Ch32LightBox と同じ式)。
 */
#include "config.h"         /* このスケッチの設定 (ピン・定数) */
#include "mpbfun.h"

static int32_t s_l = 5000;              /* L* ×100 */
static uint8_t s_breathe;

void setup(void)
{
    Mpb_BridgeCfg b = {.pwm_hz = CFG_PWM_HZ, .dead_ns = CFG_DEAD_NS, .max_duty = CFG_MAX_DUTY, .use_tim2 = 0,
                       .hw_break = CFG_HW_BREAK};

    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_Bridge_Init(&b);
    Mpb_Led_Init(0, CFG_LED_LEG, MPB_LED_LOW);    /* ch0 = HB0 のローサイド */
    Mpb_Enc_Init(NULL, 0, NULL, 0, 4);
    Mpb_Enc_ButtonInit(NULL, 0);
    Mpb_Led_Fade(0, (uint16_t)s_l, 1000);
    MPB_LOGI("led_cie: HB0 low-side, 2 kHz");
}

void loop(void)
{
    int32_t d;

    Mpb_Led_Task();
    Mpb_Enc_Task();

    d = Mpb_Enc_Delta();
    if (d && !s_breathe)
    {
        s_l += d * CFG_LEVEL_STEP;
        if (s_l < 0) s_l = 0;
        if (s_l > 10000) s_l = 10000;
        Mpb_Led_Fade(0, (uint16_t)s_l, CFG_FADE_MS);
        MPB_LOGI("L* %s  duty %s %%", Mpb_Log_Fixed(s_l, 2), Mpb_Log_Fixed((int32_t)Mpb_Cie((uint32_t)s_l, 10000), 2));
    }
    if (Mpb_Enc_Pressed())
    {
        s_breathe ^= 1;
        if (s_breathe) Mpb_Led_Breathe(0, 0, (uint16_t)s_l, CFG_BREATHE_MS);
        else Mpb_Led_Fade(0, (uint16_t)s_l, CFG_FADE_MS);
        MPB_LOGI("%s", s_breathe ? "breathe" : "steady");
    }
}
