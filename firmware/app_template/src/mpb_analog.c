/*
 * 内蔵アナログ (ADC / OPA1-4 / CMP1-3 / ISOURCE) の初期化と換算
 * 数値根拠: CH32M030DS0 V1.2, CH32M030RM V1.2 第 8 章 (ADC), 第 17 章 (OPA/CMP), 第 20 章 (EXTEN)
 */
#include <math.h>
#include "mpb.h"

/* CMP3_CFGR のビット位置 (RM 17.3.4) */
#define CMP3_CFGR_PSEL_Pos   1u
#define CMP3_CFGR_NSEL_Pos   4u
#define CMP3_CFGR_RMID_EN    (1u << 9)

static void Gpio_Analog(GPIO_TypeDef *port, uint16_t pins)
{
    GPIO_InitTypeDef g = {0};

    g.GPIO_Pin = pins;
    g.GPIO_Mode = GPIO_Mode_AIN;
    GPIO_Init(port, &g);
}

/* ------------------------------------------------------------------ ADC --- */
void Mpb_Adc_Init(void)
{
    ADC_InitTypeDef a = {0};

    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA | RCC_PB2Periph_GPIOB | RCC_PB2Periph_ADC1, ENABLE);
    Gpio_Analog(GPIOA, GPIO_Pin_2 | GPIO_Pin_4 | GPIO_Pin_5 | GPIO_Pin_7);
    Gpio_Analog(GPIOB, GPIO_Pin_2 | GPIO_Pin_3 | GPIO_Pin_4);
    RCC_ADCCLKConfig(RCC_HB_Div8);
    ADC_DeInit(ADC1);
    a.ADC_Mode = ADC_Mode_Independent;
    a.ADC_ScanConvMode = DISABLE;
    a.ADC_ContinuousConvMode = DISABLE;
    a.ADC_ExternalTrigConv = ADC_ExternalTrigConv_None;
    a.ADC_DataAlign = ADC_DataAlign_Right;
    a.ADC_NbrOfChannel = 1;
    ADC_Init(ADC1, &a);
    ADC_Cmd(ADC1, ENABLE);
    ADC_ResetCalibration(ADC1);
    while (ADC_GetResetCalibrationStatus(ADC1))
        ;
    ADC_StartCalibration(ADC1);
    while (ADC_GetCalibrationStatus(ADC1))
        ;
}

uint16_t Mpb_Adc_Read(uint8_t ch)
{
    ADC_RegularChannelConfig(ADC1, ch, 1, ADC_SampleTime_59Cycles5);
    ADC_SoftwareStartConvCmd(ADC1, ENABLE);
    while (!ADC_GetFlagStatus(ADC1, ADC_FLAG_EOC))
        ;
    return ADC_GetConversionValue(ADC1);
}

uint32_t Mpb_Adc_ToMilliVolt(uint16_t raw)
{
    return (uint32_t)raw * 3300u / 4095u;
}

uint32_t Mpb_Vbus_mV(void)
{
    return Mpb_Adc_ToMilliVolt(Mpb_Adc_Read(MPB_ADC_VBUS)) * MPB_VBUS_DIV;
}

uint32_t Mpb_UsbVbus_mV(void)
{
    return Mpb_Adc_ToMilliVolt(Mpb_Adc_Read(MPB_ADC_USBVBUS)) * MPB_USBVBUS_DIV;
}

/* ------------------------------------------------------ 電流アンプ OPA3/4 --- */
static uint32_t Gain_Of(OPA_ISP_GAIN_SEL_TypeDef g)
{
    static const uint8_t tab[] = {4, 8, 16, 55};
    return tab[g & 3];
}

void Mpb_ISense_Init(OPA_ISP_GAIN_SEL_TypeDef gain, Mpb_IspSrc ia_src)
{
    OPA_ISP_InitTypeDef i = {0};

    RCC_HBPeriphClockCmd(RCC_HBPeriph_OPCM, ENABLE);
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA, ENABLE);
    Gpio_Analog(GPIOA, GPIO_Pin_8 | GPIO_Pin_10 | GPIO_Pin_11);   /* ISN1, ISP2, ISN2 (ISP1 は専用ピン) */

    i.OPA_ISP_GAIN = gain;
    i.OPA_ISP_VFBIAS = OPA_ISP_VFBIAS_1_6V;          /* 双方向電流: 1.6V 中心 */
    i.OPA_ISP_SEL_IO = OPA_ISP_SEL_TO_ADC_ON;         /* 出力 → ADC IN9 / IN10 (内部) */
    i.OPA_ISP_QDET = OPA_ISP_QDET_EN_OFF;             /* PA14/PA15 は I2C に使う */
    i.OPA_ISP_QDET_PD30K = OPA_ISP_QDET_PD30K_OFF;
    i.OPA_ISP_QDET_VBSEL = OPA_ISP_QDET_VBSEL_OFF;

    /* OPA3: JP7=1-2 (HB0 レッグ) は差動 (ISN1=ISH), JP7=2-3 (バス) は単端 (負入力=VSS) */
    i.OPA_ISP_NESL = (ia_src == MPB_ISP_BUS) ? OPA_ISP_NESL_VSS : OPA_ISP_NESL_ISN;
    OPA_ISP_Init(OPA3_ISP1, &i);
    OPA_ISP_Cmd(OPA3_ISP1, ENABLE);

    i.OPA_ISP_NESL = OPA_ISP_NESL_ISN;
    OPA_ISP_Init(OPA4_ISP2, &i);
    OPA_ISP_Cmd(OPA4_ISP2, ENABLE);
}

int32_t Mpb_ISense_mA(uint16_t raw, OPA_ISP_GAIN_SEL_TypeDef gain)
{
    int32_t mv = (int32_t)Mpb_Adc_ToMilliVolt(raw) - 1600;
    /* I[mA] = Vout[mV] / (G * Rshunt[mΩ]) * 1000 */
    return mv * 1000 / (int32_t)(Gain_Of(gain) * MPB_SHUNT_MOHM);
}

/* ------------------------------------------------------------- 過電流保護 --- */
void Mpb_Ocp_BusCmp3_Init(void)
{
    CMP3_InitTypeDef c = {0};

    RCC_HBPeriphClockCmd(RCC_HBPeriph_OPCM, ENABLE);
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOB, ENABLE);
    Gpio_Analog(GPIOB, GPIO_Pin_2 | GPIO_Pin_3);

    c.CMP3_TRG_GATE = CMP3_TRG_GATE_OFF;
    c.CMP3_COM_EN = CMP3_COM_MODE_OFF;
    c.CMP3_FILT_EN = CMP3_FILT_EN_ON;
    c.CMP3_FILT_CFG = 1;                      /* 750ns: スイッチングノイズを除去 */
    c.CMP3_BK_EN = CMP3_BK_EN_TIM1BKIN_ON;    /* TIM1 をハード遮断 */
    c.CMP3_INT_EN = CMP3_INT_EN_ON;           /* TIM2 駆動時は OPA_IRQHandler で TIM2 を停止 */
    c.CMP3_CAP = CMP3_CAP_EN_T2_Channels_OFF;
    c.CMP3_PSEL = CMP3_PSEL_PB3;              /* バス電流 (10mV/A) */
    c.CMP3_NSEL = CMP3_NSEL_PB2;              /* 外部しきい値 254mV = 25.4A */
    c.CMP3_HYS = CMP3_HYS_10mv;
    c.CMP3_RMID = CMP3_RMID_EN_OFF;
    c.CMP3_AT_IO = CMP3_AT_IO_OFF;
    c.CMP3_PT_IO = CMP3_PT_IO_OFF;
    c.CMP3_CH_SW_NUM = CMP3_CH_SW_NUM_0;
    CMP3_Init(&c);
    NVIC_EnableIRQ(OPA_IRQn);
    CMP3_Cmd(ENABLE);
}

uint8_t Mpb_Ocp_DacCode(uint32_t limit_mA, OPA_ISP_GAIN_SEL_TypeDef gain)
{
    /* CMP2 の DAC: 0.1V + 0.2V × code (0〜15), OPA 出力 = 1.6V + I × 10mΩ × G */
    uint32_t v = 1600u + limit_mA * MPB_SHUNT_MOHM * Gain_Of(gain) / 1000u;
    uint32_t code = (v > 100u) ? (v - 100u + 199u) / 200u : 0u;   /* 切り上げ = 制限値以上で遮断 */
    return (uint8_t)(code > 15u ? 15u : code);
}

void Mpb_Ocp_Cmp2_Init(uint8_t dac_code)
{
    CMP2_InitTypeDef c = {0};

    RCC_HBPeriphClockCmd(RCC_HBPeriph_OPCM, ENABLE);
    c.QII2_HYPSEL = CMP2_QII2_HYPSEL_20mv;
    c.QII2_CHPSEL = CMP2_QII2_CHPSEL_ISP1_Output;   /* OPA3 出力 (JP7: HB0 レッグ or バス) */
    c.QII2_CHNSEL = CMP2_QII2_CHNSEL_DAC1;          /* 内蔵 DAC */
    c.CMP2_FILT_EN = CMP2_FILT_EN_ON;
    c.CMP2_FILT_CFG = 1;
    c.CMP2_QII2_DACEN = CMP2_QII2_DACEN_ON;
    c.CMP2_QII2_DAC = dac_code & 0x0F;
    c.CMP2_PT_IO = CMP2_PT_IO_PA13_OFF;             /* PA13 は nFAULT 入力 */
    c.CMP2_BK_EN = CMP2_BK_EN_TIM1BKIN_ON;
    c.CMP2_INT_EN = CMP2_INT_EN_ON;
    CMP2_Init(&c);
    QII2_AE_Cmd(ENABLE);                             /* CMP2 モジュール有効 */
    NVIC_EnableIRQ(OPA_IRQn);
}

/* 過電流割込み: TIM1 は BKIN でハード停止済み。BKIN を持たない TIM2 (HB2/HB3) をここで止める */
volatile uint8_t g_mpb_overcurrent;

__attribute__((weak)) void Mpb_OnOvercurrent(void)
{
}

void OPA_IRQHandler(void) MPB_IRQ;

void OPA_IRQHandler(void)
{
    GPIO_InitTypeDef g = {0};

    if (CMP_GetFlagStatus(CMP2_FLAG_OUTHIGH) != RESET || CMP_GetFlagStatus(CMP3_FLAG_CHOUT0) != RESET)
    {
        TIM2->CCER &= (uint16_t)~(TIM_CC1E | TIM_CC1NE | TIM_CC2E | TIM_CC2NE);
        TIM_Cmd(TIM2, DISABLE);
        /* HB2/HB3 のゲートピン (PB12〜PB15) を GPIO Low に固定 (全 FET OFF) */
        GPIO_ResetBits(GPIOB, GPIO_Pin_12 | GPIO_Pin_13 | GPIO_Pin_14 | GPIO_Pin_15);
        g.GPIO_Pin = GPIO_Pin_12 | GPIO_Pin_13 | GPIO_Pin_14 | GPIO_Pin_15;
        g.GPIO_Mode = GPIO_Mode_Out_PP;
        g.GPIO_Speed = GPIO_Speed_30MHz;
        GPIO_Init(GPIOB, &g);
        g_mpb_overcurrent = 1;
        Mpb_OnOvercurrent();
    }
    CMP_ClearFlag(CMP2_FLAG_OUTHIGH);
    CMP_ClearFlag(CMP3_FLAG_CHOUT0 | CMP3_FLAG_CHOUT1 | CMP3_FLAG_CHOUT2 | CMP3_FLAG_CHOUT3);
}

/* ---------------------------------------------------- 3 相センシング ------ */
void Mpb_Bemf_Init(void)
{
    CMP3_InitTypeDef c = {0};
    TIM_ICInitTypeDef ic = {0};
    TIM_TimeBaseInitTypeDef tb = {0};
    uint16_t ch[3] = {TIM_Channel_1, TIM_Channel_2, TIM_Channel_3};

    RCC_HBPeriphClockCmd(RCC_HBPeriph_OPCM, ENABLE);
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA, ENABLE);
    RCC_PB1PeriphClockCmd(RCC_PB1Periph_TIM2, ENABLE);
    Gpio_Analog(GPIOA, GPIO_Pin_5 | GPIO_Pin_6 | GPIO_Pin_7);

    /* TIM2: 1MHz フリーラン。CH1-3 は CMP3 出力を内部で捕捉する (RM 17.2.4) */
    tb.TIM_Period = 0xFFFF;
    tb.TIM_Prescaler = (uint16_t)(SystemCoreClock / 1000000u - 1u);
    tb.TIM_CounterMode = TIM_CounterMode_Up;
    TIM_TimeBaseInit(TIM2, &tb);
    for (int i = 0; i < 3; i++)
    {
        ic.TIM_Channel = ch[i];
        ic.TIM_ICPolarity = TIM_ICPolarity_Rising;
        ic.TIM_ICSelection = TIM_ICSelection_DirectTI;
        ic.TIM_ICPrescaler = TIM_ICPSC_DIV1;
        ic.TIM_ICFilter = 0;
        TIM_ICInit(TIM2, &ic);
    }
    TIM_Cmd(TIM2, ENABLE);

    c.CMP3_TRG_SRC = CMP3_TRG_SRC_T1_CC4;     /* TIM1 CC4 (PWM ON 中央) で判定 → スイッチングノイズ回避 */
    c.CMP3_TRG_GATE = CMP3_TRG_GATE_ON;
    c.CMP3_COM_EN = CMP3_COM_MODE_OFF;
    c.CMP3_FILT_EN = CMP3_FILT_EN_ON;
    c.CMP3_FILT_CFG = 2;
    c.CMP3_BK_EN = CMP3_BK_EN_TIM1BKIN_OFF;   /* この時の過電流保護は CMP2 (JP7=バス) */
    c.CMP3_INT_EN = CMP3_INT_EN_OFF;
    c.CMP3_CAP = CMP3_CAP_EN_T2_Channels_ON;
    c.CMP3_PSEL = CMP3_PSEL_PA3;              /* 下で RMID (仮想中性点) に切り替える */
    c.CMP3_NSEL = CMP3_NSEL_PA5;
    c.CMP3_HYS = CMP3_HYS_20mv;
    c.CMP3_RMID = CMP3_RMID_EN_ON;
    c.CMP3_AT_IO = CMP3_AT_IO_OFF;
    c.CMP3_PT_IO = CMP3_PT_IO_OFF;
    c.CMP3_CH_SW_NUM = CMP3_CH_SW_NUM_3;      /* 判定結果を TIM2 CH1→CH2→CH3 に巡回で捕捉 */
    CMP3_Init(&c);
    /* 【要実機確認】RMID 使用時は P 側を未接続 (PSEL=0x7, リセット値) にし、
     * 内部仮想中性点 (PA5/PA6/PA7 を 80kΩ で星形結線) を基準にする — RM 図17-4 の解釈 */
    OPA->CMP3_CFGR = (OPA->CMP3_CFGR & ~(0x7u << CMP3_CFGR_PSEL_Pos)) | (0x7u << CMP3_CFGR_PSEL_Pos)
                     | CMP3_CFGR_RMID_EN;
    CMP3_Cmd(ENABLE);
}

void Mpb_Bemf_SelectPhase(uint8_t phase)
{
    /* NSEL: 0 = PA5 (U), 1 = PA6 (W), 2 = PA7 (V) */
    OPA->CMP3_CFGR = (OPA->CMP3_CFGR & ~(0x7u << CMP3_CFGR_NSEL_Pos)) | ((uint32_t)(phase & 3u) << CMP3_CFGR_NSEL_Pos);
}

void Mpb_Hall_Init(void)
{
    GPIO_InitTypeDef g = {0};
    TIM_TimeBaseInitTypeDef tb = {0};
    TIM_ICInitTypeDef ic = {0};

    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA, ENABLE);
    RCC_PB1PeriphClockCmd(RCC_PB1Periph_TIM2, ENABLE);
    g.GPIO_Pin = GPIO_Pin_5 | GPIO_Pin_6 | GPIO_Pin_7;   /* TIM2 CH1/CH2/CH3 (デフォルト配置) */
    g.GPIO_Mode = GPIO_Mode_IN_FLOATING;                  /* プルアップはホール側 (R100 等) */
    GPIO_Init(GPIOA, &g);

    tb.TIM_Period = 0xFFFF;
    tb.TIM_Prescaler = (uint16_t)(SystemCoreClock / 1000000u - 1u);   /* 1µs 分解能 */
    tb.TIM_CounterMode = TIM_CounterMode_Up;
    TIM_TimeBaseInit(TIM2, &tb);

    /* ホールセンサインタフェース: CH1/CH2/CH3 の XOR を TI1 にして、エッジ毎に CNT を捕捉・リセット */
    TIM_SelectHallSensor(TIM2, ENABLE);
    ic.TIM_Channel = TIM_Channel_1;
    ic.TIM_ICPolarity = TIM_ICPolarity_Rising;
    ic.TIM_ICSelection = TIM_ICSelection_TRC;
    ic.TIM_ICPrescaler = TIM_ICPSC_DIV1;
    ic.TIM_ICFilter = 0x0F;
    TIM_ICInit(TIM2, &ic);
    TIM_SelectInputTrigger(TIM2, TIM_TS_TI1F_ED);
    TIM_SelectSlaveMode(TIM2, TIM_SlaveMode_Reset);
    TIM_ITConfig(TIM2, TIM_IT_CC1, ENABLE);   /* 転流処理はユーザーの TIM2_IRQHandler で */
    NVIC_EnableIRQ(TIM2_IRQn);
    TIM_Cmd(TIM2, ENABLE);
}

/* ------------------------------------------------ QII1 タコ / リップル ----- */
void Mpb_Tach_Init(OPA1_QII1_AVSEL_TypeDef gain, CMP1_QII1_HYPSEL_TypeDef hyst)
{
    OPA1_InitTypeDef o = {0};
    CMP1_InitTypeDef c = {0};
    TIM_ICInitTypeDef ic = {0};

    RCC_HBPeriphClockCmd(RCC_HBPeriph_OPCM, ENABLE);
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA, ENABLE);
    Gpio_Analog(GPIOA, GPIO_Pin_12);

    o.QII1_AVSEL = gain;                      /* AV = 20 / 40, 自己バイアス 1.23V (AC 結合 C105) */
    OPA1_Init(&o);
    c.QII1_HYPSEL = hyst;                     /* 100mV / 200mV */
    c.CMP1_FILT_EN = CMP1_FILT_EN_ON;
    c.CMP1_FILT_CFG = 4;                      /* 1.9µs */
    c.CMP1_PT_IO = CMP1_PT_IO_PA12_OFF;
    CMP1_Init(&c);
    QII1_AE_Cmd(ENABLE);
    QII_OutToTIM3Cap_Cmd(ENABLE);             /* CMP1 出力 → TIM3 CH1 (内部) */

    ic.TIM_Channel = TIM_Channel_1;           /* TIM3 は Mpb_Time_Init() で起動済みであること */
    ic.TIM_ICPolarity = TIM_ICPolarity_Rising;
    ic.TIM_ICSelection = TIM_ICSelection_DirectTI;
    ic.TIM_ICPrescaler = TIM_ICPSC_DIV1;
    ic.TIM_ICFilter = 0;
    TIM_ICInit(TIM3, &ic);
    TIM_ClearITPendingBit(TIM3, TIM_IT_CC1);
    TIM_ITConfig(TIM3, TIM_IT_CC1, ENABLE);
}

/* ------------------------------------------------------ 温度 (ISOURCE1) --- */
static void Exten_Unlock(void)
{
    EXTEN->EXTEN_KEYR = EXTEN_KEY1;
    EXTEN->EXTEN_KEYR = EXTEN_KEY2;
}

void Mpb_Ntc_Init(void)
{
    RCC_PB1PeriphClockCmd(RCC_PB1Periph_PWR, ENABLE);
    PWR_ISINKCmd(ENABLE);                     /* ISOURCE/ISINK 共通の有効化 (RM 20.3) */
    Exten_Unlock();
    EXTEN->EXTEN_CTLR0 = (EXTEN->EXTEN_CTLR0 & ~EXTEN_ISR_C1_SEL) | EXTEN_ISR_C1_EN;   /* 低電流ギア */
}

int32_t Mpb_Ntc_DeciCelsius(void)
{
    uint32_t i_nA = ISOURCE1_GetData(ISOURCE_LEVEL_LOW);   /* 工場校正値 */
    uint32_t mv = Mpb_Adc_ToMilliVolt(Mpb_Adc_Read(MPB_ADC_NTC));
    float r, t;

    if (i_nA == 0u || mv == 0u || mv > 3200u)
    {
        return INT32_MIN;                     /* 未校正 / 断線 / 短絡 */
    }
    r = (float)mv * 1.0e6f / (float)i_nA;     /* Ω */
    t = 1.0f / (1.0f / 298.15f + logf(r / 10000.0f) / 3435.0f) - 273.15f;
    return (int32_t)(t * 10.0f);
}
