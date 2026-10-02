/*
 * サンプル: WS2812B / SK6812 — 虹色の流れ + CIE 1931 で明るさを揃える, エンコーダで明るさ
 *
 * 配線: DIN → J2-2 (UART_RX = PC2), LED の GND をモジュールの GND へ。8 個 (GRB)。
 *       5V で光らせる場合は先頭 1 個を 4V 前後で給電するか, レベル変換 (74AHCT1G125 等) を入れると確実。
 *       エンコーダ A → HALL_A_IN (JP2 = 2-3), B → HALL_C_IN (JP4 = 2-3), 押し → PC4。
 * 操作: 回す … 明るさ (L* で 5% 刻み)。押す … 虹 ⇔ 呼吸 (白) の切り替え。
 * UART ログ (TX = PC1) はそのまま使える。書き込み要求は UART では受けないので USB-C で書き込む。
 */
#include "config.h"         /* このスケッチの設定 (ピン・定数) */
#include "mpbfun.h"


static int32_t s_level = 3000;          /* L* ×100 */
static uint8_t s_mode;

void setup(void)
{
    Mpb_Time_Init();
    Mpb_Log_Init(0);                    /* 先に UART を設定 → その後 PC2 を出力にする */
    Mpb_Ws2812_Init(CFG_WS_PORT, CFG_WS_PIN, CFG_WS_COUNT, CFG_WS_ORDER);
    Mpb_Enc_Init(NULL, 0, NULL, 0, 4);
    Mpb_Enc_ButtonInit(NULL, 0);
    MPB_LOGI("ws2812: %u LEDs on PC2", CFG_WS_COUNT);
}

void loop(void)
{
    int32_t d;

    Mpb_Enc_Task();
    Mpb_Ws2812_Task();                  /* 変化があったときだけ送る */

    d = Mpb_Enc_Delta();
    if (d)
    {
        s_level += d * CFG_LEVEL_STEP;
        if (s_level < 0) s_level = 0;
        if (s_level > 10000) s_level = 10000;
        MPB_LOGI("L* %s %%", Mpb_Log_Fixed(s_level, 2));
    }
    if (Mpb_Enc_Pressed())
    {
        s_mode ^= 1;
    }

    MPB_EVERY_MS(t_frame, CFG_FRAME_MS)           /* 50 フレーム/s */
    {
        uint32_t ms = Mpb_Millis();
        if (s_mode == 0)
        {
            for (uint8_t i = 0; i < CFG_WS_COUNT; i++)
            {
                Mpb_Ws2812_Hsv(i, (uint16_t)((ms / 10u + i * 360u / CFG_WS_COUNT) % 360u), 255, (uint16_t)s_level);
            }
        }
        else
        {
            /* 呼吸: 2 秒で 0 → L* → 0 (L* 空間で三角波 = 目には一定の速さで明暗が変わる) */
            uint32_t ph = ms % 2000u;
            uint32_t lx = (ph < 1000u ? ph : 2000u - ph) * (uint32_t)s_level / 1000u;
            for (uint8_t i = 0; i < CFG_WS_COUNT; i++)
            {
                Mpb_Ws2812_SetLevel(i, 0xFFFFFF, (uint16_t)lx);
            }
        }
        Mpb_Ws2812_Show();
    }
}
