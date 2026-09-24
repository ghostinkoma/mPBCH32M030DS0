/*
 * ユーザースケッチ (Arduino の .ino に相当)
 *
 * 例: 状態 LED (PC4) の点滅 + USB-PD 給電ネゴシエーション + 温度/電圧の監視。
 * loop() は Delay で止めないこと (PD 処理は 1ms 周期で回す必要がある)。
 *
 * 注意: モーター出力 (PB8〜PB15) を触る前に README の「ファームウェア開発」を読むこと。
 *       HO/LO を同時に ON にするとハーフブリッジが短絡する (TIM1/TIM2 の相補 PWM +
 *       デッドタイム + ブレーキを使うこと)。
 */
#include "debug.h"
#include "mpb.h"

static void Led(uint8_t on)
{
    GPIO_WriteBit(MPB_LED_PORT, MPB_LED_PIN, on ? MPB_LED_ON : MPB_LED_OFF);
}

void setup(void)
{
    GPIO_InitTypeDef gpio = {0};

    RCC_PB2PeriphClockCmd(MPB_LED_RCC, ENABLE);
    gpio.GPIO_Pin = MPB_LED_PIN;
    gpio.GPIO_Mode = GPIO_Mode_Out_OD;        /* PC4 は USER/BOOT ボタンと共用 */
    gpio.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(MPB_LED_PORT, &gpio);

    Mpb_Time_Init();                          /* TIM3: µs 時間基準 */
    Mpb_Adc_Init();
    Mpb_Ntc_Init();                           /* ISOURCE1 → NTC */
    Mpb_ISense_Init(OPA_ISP_GAIN_16, MPB_ISP_LEG);   /* JP7=1-2 の場合 */
    Mpb_Ocp_BusCmp3_Init();                   /* バス 25.4A でハード遮断 */
    Mpb_PD_Init(NULL);                        /* 8〜15V の PDO を要求し, 確認後に VBUS へ給電 */
}

void loop(void)
{
    static uint32_t t_led;
    static uint8_t on;
    uint32_t now = Mpb_Millis();
    /* PD 給電中は速い点滅, それ以外はゆっくり */
    uint32_t period = Mpb_PD_Status()->power_enabled ? 125u : 500u;

    Mpb_PD_Task();
    if (now - t_led >= period)
    {
        t_led = now;
        on ^= 1;
        Led(on);
    }
}
