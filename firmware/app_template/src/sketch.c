/*
 * ユーザースケッチ (Arduino の .ino に相当)
 * 例: 状態 LED (PA6) を点滅させる。
 *
 * 注意: モーター出力 (PB8〜PB15) を触る前に README の「ファームウェア開発」を読むこと。
 *       HO/LO を同時に ON にするとハーフブリッジが短絡する (TIM1/TIM2 の相補 PWM +
 *       デッドタイム + ブレーキを使うこと)。
 */
#include "debug.h"
#include "board.h"

void setup(void)
{
    GPIO_InitTypeDef gpio = {0};

    RCC_PB2PeriphClockCmd(MPB_LED_RCC, ENABLE);
    gpio.GPIO_Pin = MPB_LED_PIN;
    gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    gpio.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(MPB_LED_PORT, &gpio);
}

void loop(void)
{
    static uint8_t on;

    on ^= 1;
    GPIO_WriteBit(MPB_LED_PORT, MPB_LED_PIN, on ? Bit_SET : Bit_RESET);
    Delay_Ms(500);
}
