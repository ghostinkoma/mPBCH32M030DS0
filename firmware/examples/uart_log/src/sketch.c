/*
 * サンプル: UART ログ — 基板の状態 (電圧・温度・PD) を 1 秒ごとに出す。待ちなしで状態 LED も点滅させる
 *
 * 接続: USB-UART 変換 (3.3V) の RX ← J2-3 (UART_TX = PC1), GND ← J2-1。460800bps 8N1。
 *   例: picocom -b 460800 /dev/ttyUSB0
 * Mpb_Log_* はバッファに積むだけで, 送信は割込みが行う (loop が止まらない)。
 */
#include "config.h"         /* このスケッチの設定 (ピン・定数) */
#include "mpbfun.h"

static void led(uint8_t on)
{
    GPIO_WriteBit(MPB_LED_PORT, MPB_LED_PIN, on ? MPB_LED_ON : MPB_LED_OFF);
}

void setup(void)
{
    GPIO_InitTypeDef g = {0};

    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_Adc_Init();
    Mpb_Ntc_Init();
    Mpb_PD_Init(NULL);
    RCC_PB2PeriphClockCmd(MPB_LED_RCC, ENABLE);
    g.GPIO_Pin = MPB_LED_PIN;
    g.GPIO_Mode = GPIO_Mode_Out_OD;
    g.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(MPB_LED_PORT, &g);

    Mpb_Log_Printf("\r\n=== mPBCH32M030DS0 uart_log (power stage %c) ===\r\n", MPB_POWER_STAGE);
    MPB_LOGI("SystemCoreClock %u Hz", SystemCoreClock);
}

void loop(void)
{
    static uint8_t on;
    const Mpb_PdStatus *pd;

    Mpb_PD_Task();

    MPB_EVERY_MS(t_led, CFG_LED_MS)
    {
        on ^= 1;
        led(on);
    }
    MPB_EVERY_MS(t_log, CFG_LOG_MS)
    {
        int32_t t = Mpb_Ntc_DeciCelsius();
        pd = Mpb_PD_Status();
        MPB_LOGI("VBUS %s V  USB %s V  NTC %s C", Mpb_Log_Fixed((int32_t)Mpb_Vbus_mV() / 10, 2),
                 Mpb_Log_Fixed((int32_t)Mpb_UsbVbus_mV() / 10, 2), t == INT32_MIN ? "--" : Mpb_Log_Fixed(t, 1));
        if (pd->attached)
        {
            MPB_LOGI("PD contract=%u %u mV %u mA power=%u", pd->contract, pd->mV, pd->mA, pd->power_enabled);
        }
        if (Mpb_Log_Dropped())
        {
            MPB_LOGW("log dropped %u bytes", Mpb_Log_Dropped());
        }
    }
}
