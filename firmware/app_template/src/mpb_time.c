/*
 * 時間基準: TIM3 を 1MHz フリーランで回し、オーバーフロー割込みで 32bit µs を作る。
 * TIM1 はモーター PWM、TIM2 は HB2/HB3 PWM またはホール/BEMF 捕捉に使うため、
 * 時間基準と QII1 (タコ) 捕捉は TIM3 にまとめる (QII 出力は TIM3 CH1 に内部接続されている)。
 */
#include "mpb.h"

static volatile uint32_t s_ovf;          /* 上位 16bit */
static volatile uint32_t s_tach_last;    /* 直近の捕捉時刻 [µs] */
static volatile uint32_t s_tach_period;  /* 直近の周期 [µs] */

void TIM3_IRQHandler(void) MPB_IRQ;

void Mpb_Time_Init(void)
{
    TIM_TimeBaseInitTypeDef tb = {0};

    RCC_PB1PeriphClockCmd(RCC_PB1Periph_TIM3, ENABLE);
    tb.TIM_Period = 0xFFFF;
    tb.TIM_Prescaler = (uint16_t)(SystemCoreClock / 1000000u - 1u);
    tb.TIM_ClockDivision = TIM_CKD_DIV1;
    tb.TIM_CounterMode = TIM_CounterMode_Up;
    TIM_TimeBaseInit(TIM3, &tb);
    TIM_ClearITPendingBit(TIM3, TIM_IT_Update);
    TIM_ITConfig(TIM3, TIM_IT_Update, ENABLE);
    NVIC_EnableIRQ(TIM3_IRQn);
    TIM_Cmd(TIM3, ENABLE);
}

uint32_t Mpb_Micros(void)
{
    uint32_t hi, lo;

    do
    {
        hi = s_ovf;
        lo = TIM3->CNT;
    } while (hi != s_ovf);
    return (hi << 16) | lo;
}

uint32_t Mpb_Millis(void)
{
    return Mpb_Micros() / 1000u;
}

uint32_t Mpb_Tach_PeriodUs(void)
{
    /* 1 秒以上パルスが無ければ停止とみなす */
    if (Mpb_Micros() - s_tach_last > 1000000u)
    {
        return 0;
    }
    return s_tach_period;
}

void TIM3_IRQHandler(void)
{
    if (TIM_GetITStatus(TIM3, TIM_IT_Update) != RESET)
    {
        s_ovf++;
        TIM_ClearITPendingBit(TIM3, TIM_IT_Update);
    }
    if (TIM_GetITStatus(TIM3, TIM_IT_CC1) != RESET)
    {
        uint32_t t = (s_ovf << 16) | TIM_GetCapture1(TIM3);
        /* 捕捉と同時にオーバーフローが未処理の場合の補正 */
        if (TIM_GetITStatus(TIM3, TIM_IT_Update) != RESET && TIM_GetCapture1(TIM3) < 0x8000u)
        {
            t += 0x10000u;
        }
        s_tach_period = t - s_tach_last;
        s_tach_last = t;
        TIM_ClearITPendingBit(TIM3, TIM_IT_CC1);
    }
}
