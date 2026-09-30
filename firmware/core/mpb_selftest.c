/*
 * 結線自己診断: パワー段を通電せずにモーターの接続 (U-V 間の導通) を確認する。
 *
 * 原理: ISOURCE2 (PA5 = SENS_U) から微小電流 Is を BEMF_U ノードへ注入する。
 *   モーター接続時:  Is → 20k → OUT0 → 巻線 → OUT1 → 20k → BEMF_V → 3k → GND の経路ができ、
 *                   BEMF_V ≈ Is × 131Ω の電圧が PA7 (ADC IN2) に現れる。
 *   未接続/断線時:  BEMF_V ≈ 0V。
 * 前提: JP2/JP3 = 1-2 (相電圧側), TIM1/TIM2 出力 OFF (全 FET OFF) の状態で呼ぶこと。
 */
#include "mpb.h"
#include "debug.h"

static void Isrc2(uint8_t on)
{
    RCC_PB1PeriphClockCmd(RCC_PB1Periph_PWR, ENABLE);
    PWR_ISINKCmd(ENABLE);
    EXTEN->EXTEN_KEYR = EXTEN_KEY1;
    EXTEN->EXTEN_KEYR = EXTEN_KEY2;
    if (on)
    {
        EXTEN->EXTEN_CTLR0 |= EXTEN_ISR_C2_EN | EXTEN_ISR_C2_SEL;   /* 高電流ギア */
    }
    else
    {
        EXTEN->EXTEN_CTLR0 &= ~(EXTEN_ISR_C2_EN | EXTEN_ISR_C2_SEL);
    }
}

static uint32_t Avg_uV(uint8_t ch)
{
    uint32_t sum = 0;

    for (int i = 0; i < 64; i++)
    {
        sum += Mpb_Adc_Read(ch);
    }
    /* 64 回平均 → µV */
    return (uint32_t)((uint64_t)sum * 3300000u / 4095u / 64u);
}

Mpb_WireResult Mpb_SelfTest_Wiring(uint32_t *v_uV)
{
    uint32_t base, on, i_nA = ISOURCE2_GetData(ISOURCE_LEVEL_HIGH);
    uint32_t expect;

    if (i_nA == 0u)
    {
        return MPB_WIRE_NOT_TESTED;           /* 工場校正値なし */
    }
    Isrc2(0);
    Delay_Ms(5);
    base = Avg_uV(MPB_ADC_SENS_V);
    Isrc2(1);
    Delay_Ms(20);                             /* 1nF + 分圧抵抗の整定 */
    on = Avg_uV(MPB_ADC_SENS_V);
    Isrc2(0);

    if (v_uV != NULL)
    {
        *v_uV = (on > base) ? on - base : 0u;
    }
    expect = i_nA * 131u / 1000u;             /* µV: 理論値 Is × 131Ω */
    /* 理論値の 30% 以上が現れれば導通ありとみなす */
    return (on > base && (on - base) * 10u >= expect * 3u) ? MPB_WIRE_OK : MPB_WIRE_OPEN_UV;
}
