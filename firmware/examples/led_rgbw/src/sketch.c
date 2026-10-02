/*
 * サンプル: RGBW 4ch LED ドライバ — パワー段の MOSFET で LED テープを CIE 1931 調光
 *
 * 操作は 2 通り (どちらも CIE 1931 L* で人の目に自然な明るさ):
 *   ① ロータリーエンコーダ (Ch32LightBox と同じ操作)
 *        回す         … 明るさ ±1 段 (64 段, L* 等間隔)。速く回すと 3 倍, 勢いよく回すと 100% / 消灯
 *        短く押す     … 点灯 / 消灯 (ソフトフェード)
 *        長押し (1 秒) … モード切替: 明るさ → 色相 → 彩度 → 白の混合 → 明るさ … (切替時に 1 回点滅)
 *   ② WS2812 / SK6812 互換入力 (DIN = J2-2)
 *        上流のコントローラから見ると, この基板は「大電流の 1 画素」。先頭 1 画素分を受け取り, 残りは DOUT へ中継。
 *        受けた値 (0〜255) は各色の L* として CIE で duty にする。エンコーダの明るさはマスター調光として掛かる。
 *        最後の受信から CFG_WSRX_HOLD_MS の間は WS2812 入力を優先し, 途切れたらエンコーダの色に戻る。
 *
 * 配線: LED + = VBUS (電源端子), R/G/B/W の − = OUT0〜OUT3。エンコーダ A/B = HALL_A_IN / HALL_C_IN (JP2/JP4 = 2-3),
 *       押し = PC4 (USER)。WS2812 入力 = J2-2 (PC2), 中継出力 = J2-19 (PA14), GND を共通に。
 */
#include "config.h"         /* このスケッチの設定 (ピン・定数) */
#include "mpbfun.h"

enum { MODE_BRIGHT = 0, MODE_HUE, MODE_SAT, MODE_WHITE, MODE_COUNT };
static const char *const k_mode[MODE_COUNT] = {"brightness", "hue", "saturation", "white mix"};

static uint8_t  s_on = 1, s_mode, s_ws;            /* s_ws: WS2812 入力を表示中 */
static int32_t  s_level = CFG_LEVEL_INIT;
static int32_t  s_hue = CFG_HUE_INIT, s_sat = CFG_SAT_INIT, s_white = CFG_WHITE_INIT;
static uint8_t  s_rgbw[4];
static uint32_t s_t_click, s_t_snap;
static int8_t   s_snap_dir;
static uint8_t  s_snap_n;
static uint32_t s_t_blink;

static uint16_t level_lx(void) { return (uint16_t)(10000u * (uint32_t)s_level / CFG_LEVELS); }

static void apply_master(uint32_t fade_ms)
{
    Mpb_Rgbw_SetMaster(s_on ? level_lx() : 0u, fade_ms);
}

static void apply_color(void)
{
    if (s_ws)
    {
        Mpb_Rgbw_SetLevels(s_rgbw[0], s_rgbw[1], s_rgbw[2], s_rgbw[3]);
    }
    else
    {
        Mpb_Rgbw_SetHsv((uint16_t)s_hue, (uint16_t)s_sat, (uint16_t)s_white);
    }
}

static int32_t clampi(int32_t v, int32_t lo, int32_t hi) { return v < lo ? lo : (v > hi ? hi : v); }

/* 1 クリック分 (dir = ±1) */
static void click(int8_t dir)
{
    uint32_t now = Mpb_Millis();
    int32_t step = (now - s_t_click < CFG_ACCEL_MS) ? CFG_ACCEL_FACTOR : 1;

    s_t_click = now;
    /* 勢い回し: CFG_SNAP_MS 以内に同じ向きへ CFG_SNAP_CLICKS 回 → 100% / 消灯 */
    if (dir != s_snap_dir || now - s_t_snap > CFG_SNAP_MS)
    {
        s_snap_dir = dir;
        s_snap_n = 0;
        s_t_snap = now;
    }
    s_snap_n++;
    switch (s_mode)
    {
    case MODE_BRIGHT:
        if (s_snap_n >= CFG_SNAP_CLICKS)
        {
            s_level = dir > 0 ? (int32_t)CFG_LEVELS : 0;
        }
        else
        {
            s_level = clampi(s_level + dir * step, 0, CFG_LEVELS);
        }
        if (s_level > 0) s_on = 1;                 /* 消灯中に回したら点灯 (明るくなる操作のとき) */
        apply_master(CFG_STEP_FADE_MS);
        break;
    case MODE_HUE:
        s_hue = (s_hue + dir * step * (int32_t)CFG_HUE_STEP + 360) % 360;
        apply_color();
        break;
    case MODE_SAT:
        s_sat = clampi(s_sat + dir * step * (int32_t)CFG_SAT_STEP, 0, 1000);
        apply_color();
        break;
    default:
        s_white = clampi(s_white + dir * step * (int32_t)CFG_WHITE_STEP, 0, 1000);
        apply_color();
        break;
    }
}

void setup(void)
{
    Mpb_BridgeCfg b = {.pwm_hz = CFG_PWM_HZ, .dead_ns = CFG_DEAD_NS, .max_duty = CFG_MAX_DUTY, .use_tim2 = 1,
                       .hw_break = CFG_HW_BREAK};
    static const uint8_t legs[4] = {CFG_LEG_R, CFG_LEG_G, CFG_LEG_B, CFG_LEG_W};
#if CFG_WSRX_ENABLE
    Mpb_WsRxCfg rx = {.dout_pin = CFG_WSRX_DOUT ? GPIO_Pin_14 : 0, .bytes = CFG_WSRX_BYTES,
                      .t1_ns = CFG_WSRX_T1_NS, .confirm = CFG_WSRX_CONFIRM};
#endif

    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_Bridge_Init(&b);
    Mpb_Rgbw_Init(legs, CFG_CHANNELS);
    Mpb_Enc_Init(NULL, 0, NULL, 0, 4);
    Mpb_Enc_Reverse(CFG_ENC_REVERSE);
    Mpb_Enc_ButtonInit(NULL, 0);
#if CFG_WSRX_ENABLE
    Mpb_WsRx_Init(&rx);
#endif
    apply_color();
    apply_master(CFG_SOFT_MS);                     /* 起動時はソフトスタート */
    MPB_LOGI("led_rgbw: %u ch, %u Hz, levels %u", CFG_CHANNELS, CFG_PWM_HZ, CFG_LEVELS);
}

void loop(void)
{
    int32_t d;

    Mpb_Enc_Task();
    Mpb_Rgbw_Task();

    /* エンコーダ */
    for (d = Mpb_Enc_Delta(); d != 0; d += (d > 0) ? -1 : 1)
    {
        click(d > 0 ? 1 : -1);
    }
    if (Mpb_Enc_Pressed())
    {
        s_on ^= 1;
        if (s_on && s_level == 0) s_level = CFG_LEVEL_INIT;
        apply_master(CFG_SOFT_MS);
        MPB_LOGI("%s", s_on ? "on" : "off");
    }
    if (Mpb_Enc_LongPressed())
    {
        s_on = 1;
        s_mode = (uint8_t)((s_mode + 1u) % MODE_COUNT);
        /* 切替の合図: 一瞬暗くして戻す */
        Mpb_Rgbw_SetMaster(level_lx() / 4u, 0);
        s_t_blink = Mpb_Millis();
        MPB_LOGI("mode: %s", k_mode[s_mode]);
    }
    if (s_t_blink && Mpb_Millis() - s_t_blink > 150u)
    {
        s_t_blink = 0;
        apply_master(100);
    }

#if CFG_WSRX_ENABLE
    /* WS2812 互換入力: 最大 CFG_WSRX_POLL_US だけ DIN を見張る */
    if (Mpb_WsRx_Poll(CFG_WSRX_POLL_US, s_rgbw))
    {
        if (!s_ws) MPB_LOGI("WS2812 input");
        s_ws = 1;
        apply_color();
    }
    if (s_ws && Mpb_Millis() - Mpb_WsRx_LastMs() > CFG_WSRX_HOLD_MS)
    {
        s_ws = 0;                                  /* 途切れたらエンコーダの色へ */
        apply_color();
        MPB_LOGI("WS2812 input lost -> local color");
    }
#endif

    MPB_EVERY_MS(t_log, CFG_LOG_MS)
    {
        MPB_LOGI("%s L* %s %%  mode %s  hue %d sat %d white %d  duty R%u G%u B%u W%u  ws %u/%u",
                 s_on ? "ON " : "OFF", Mpb_Log_Fixed(Mpb_Rgbw_Master(), 2), s_ws ? "ws2812" : k_mode[s_mode],
                 s_hue, s_sat, s_white, Mpb_Rgbw_DutyQ16(0), Mpb_Rgbw_DutyQ16(1), Mpb_Rgbw_DutyQ16(2),
                 Mpb_Rgbw_DutyQ16(3), Mpb_WsRx_Frames(), Mpb_WsRx_Errors());
    }
}
