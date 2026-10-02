/*
 * mpb_bridge — ハーフブリッジ PWM (TIM1 / TIM2 同期) と PWM 同期の電流取り込み
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_bridge.h"

static uint16_t s_arr = 1800;              /* 中心揃え: f = HCLK / (2 × ARR) */
static uint16_t s_max = 900;
static uint32_t s_hz = 20000;
static uint8_t  s_tim2;
static int16_t  s_leg[4] = {MPB_LEG_FLOAT, MPB_LEG_FLOAT, MPB_LEG_FLOAT, MPB_LEG_FLOAT};
static volatile uint8_t s_fault;
static uint8_t  s_inited, s_dtg;           /* 点検用: 設定したデッドタイムのレジスタ値 */

/* 上下短絡 (同じレッグの HO と LO が同時に ON) を防ぐための下限。設定 (dead_ns) がこれより小さくても切り上げる */
#ifndef MPB_DEAD_MIN_NS
#define MPB_DEAD_MIN_NS 300u
#endif
#if MPB_DEAD_MIN_NS < 200
#error "MPB_DEAD_MIN_NS は 200ns 未満にできません (上下短絡の防止)"
#endif

/* レッグ → (ポート B のピン番号 HO / LO) */
static const uint8_t k_ho[4] = {9, 11, 13, 15};
static const uint8_t k_lo[4] = {8, 10, 12, 14};

/* PB8〜PB15 の CFGHR を直接書く (4bit/ピン)。AF_PP 30MHz = 0xB, 出力 PP 30MHz = 0x3 */
static void pin_cfg(uint8_t pin, uint32_t cfg)
{
    uint32_t sh = (uint32_t)(pin - 8u) * 4u;
    GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xFu << sh)) | (cfg << sh);
}

/* 割込み (過電流) と取り合っても設定が戻らないよう, ピン設定は割込みを止めて書く */
static inline uint32_t irq_save(void) { uint32_t m; __asm volatile("csrrci %0, mstatus, 8" : "=r"(m)); return m; }
static inline void irq_restore(uint32_t m) { __asm volatile("csrs mstatus, %0" ::"r"(m & 8u)); }

static void leg_pins(uint8_t leg, uint8_t pwm)
{
    uint32_t m = irq_save();

    if (!pwm || s_fault)
    {
        GPIOB->BCR = (1u << k_ho[leg]) | (1u << k_lo[leg]);   /* 先に Low を確定 */
        pin_cfg(k_ho[leg], 0x3u);
        pin_cfg(k_lo[leg], 0x3u);
    }
    else
    {
        /* GPIO Low → タイマー: 相補出力 + デッドタイムなので, どちらから切り替えても同時 ON にならない */
        pin_cfg(k_ho[leg], 0xBu);
        pin_cfg(k_lo[leg], 0xBu);
    }
    irq_restore(m);
}

static volatile uint32_t *ccr_of(uint8_t leg)
{
    if (leg == 0) return &TIM1->CH1CVR;
    if (leg == 1) return &TIM1->CH2CVR;
    if (leg == 2) return s_tim2 ? &TIM2->CH1CVR : &TIM1->CH3CVR;
    return &TIM2->CH2CVR;
}

void Mpb_Bridge_AllFloat(void)
{
    for (uint8_t i = 0; i < 4; i++)
    {
        leg_pins(i, 0);
        s_leg[i] = MPB_LEG_FLOAT;
    }
}

void Mpb_Bridge_Leg(uint8_t leg, int16_t duty)
{
    if (leg > 3 || (leg == 3 && !s_tim2))
    {
        return;
    }
    if (duty < 0 || s_fault)
    {
        leg_pins(leg, 0);
        s_leg[leg] = MPB_LEG_FLOAT;
        return;
    }
    if (duty > (int16_t)s_max)
    {
        duty = (int16_t)s_max;
    }
    *ccr_of(leg) = (uint32_t)((uint32_t)s_arr * (uint32_t)duty / MPB_DUTY_FULL);
    if (s_leg[leg] < 0 || s_leg[leg] > MPB_DUTY_FULL)
    {
        leg_pins(leg, 1);
    }
    s_leg[leg] = duty;
}

void Mpb_Bridge_LegQ16(uint8_t leg, uint16_t q)
{
    uint32_t mx = (uint32_t)s_max * 65536u / MPB_DUTY_FULL;

    if (leg > 3 || (leg == 3 && !s_tim2))
    {
        return;
    }
    if (s_fault)
    {
        leg_pins(leg, 0);
        s_leg[leg] = MPB_LEG_FLOAT;
        return;
    }
    if (q > mx)
    {
        q = (uint16_t)mx;
    }
    *ccr_of(leg) = ((uint32_t)s_arr * q) >> 16;
    if (s_leg[leg] < 0 || s_leg[leg] > MPB_DUTY_FULL)
    {
        leg_pins(leg, 1);
    }
    s_leg[leg] = (int16_t)(((uint32_t)q * MPB_DUTY_FULL) >> 16);
}

void Mpb_Bridge_LegLow(uint8_t leg, uint16_t on)
{
    if (leg > 3 || (leg == 3 && !s_tim2))
    {
        return;
    }
    if (on == 0 || s_fault)
    {
        leg_pins(leg, 0);
        s_leg[leg] = MPB_LEG_FLOAT;
        return;
    }
    /* CHxN は CNT ≥ CCR の間 High (相補)。CCR = ARR × (1 − on/65535) */
    *ccr_of(leg) = (uint32_t)s_arr * (uint32_t)(65535u - on) / 65535u;
    {
        uint32_t m = irq_save();
        GPIOB->BCR = 1u << k_ho[leg];
        pin_cfg(k_ho[leg], 0x3u);                /* HO: GPIO Low (ハイサイド常時 OFF) */
        if (!s_fault) pin_cfg(k_lo[leg], 0xBu);  /* LO: PWM */
        irq_restore(m);
    }
    s_leg[leg] = (int16_t)(2000 + (on >> 6));    /* 通常の PWM と区別 (>1000) */
}

int16_t Mpb_Bridge_GetLeg(uint8_t leg) { return leg < 4 ? s_leg[leg] : MPB_LEG_FLOAT; }
uint16_t Mpb_Bridge_MaxDuty(void) { return s_max; }
uint32_t Mpb_Bridge_PwmHz(void) { return s_hz; }
uint8_t Mpb_Bridge_Faulted(void) { return s_fault; }

static uint16_t s_vdd8 = 5000;
static uint32_t s_vdd8_t;

uint16_t Mpb_Bridge_Vdd8(void) { return s_vdd8; }

uint16_t Mpb_Bridge_Vdd8Auto(void)
{
    static const uint16_t th[3] = {12000, 10500, 9500};    /* VBUS のしきい値 (上げるとき) */
    static const uint16_t v8[3] = {10000, 9000, 8000};
    static const uint32_t sel[3] = {PWR_VDD8_SEL_10V, PWR_VDD8_SEL_9V, PWR_VDD8_SEL_8V};
    uint32_t now = Mpb_Millis(), vb;
    uint16_t want = 5000;
    uint32_t want_sel = PWR_VDD8_SEL_5V;

    if (now - s_vdd8_t < 100u && s_vdd8_t != 0u)
    {
        return s_vdd8;
    }
    s_vdd8_t = now ? now : 1u;
    vb = Mpb_Vbus_mV();
    for (uint8_t i = 0; i < 3; i++)
    {
        /* 下げるときは 300mV のヒステリシス */
        uint32_t t = (s_vdd8 >= v8[i]) ? th[i] - 300u : th[i];
        if (vb >= t)
        {
            want = v8[i];
            want_sel = sel[i];
            break;
        }
    }
    if (want != s_vdd8)
    {
        FLASH->CTLR2 = (uint8_t)((FLASH->CTLR2 & (uint8_t)~FLASH_CTLR2_VDD8_SEL) | (uint8_t)want_sel);
        s_vdd8 = want;
    }
    return s_vdd8;
}

void Mpb_Bridge_ClearFault(void)
{
    g_mpb_overcurrent = 0;
    s_fault = 0;
    TIM1->BDTR |= TIM_MOE;          /* ブレーキで落ちた MOE を戻す (レッグは開放のまま) */
}

static void (*s_fault_hook)(void);

void Mpb_Bridge_SetFaultHook(void (*fn)(void)) { s_fault_hook = fn; }

void Mpb_Bridge_Trip(void)
{
    s_fault = 1;
    Mpb_Gates_Off();
    Mpb_Bridge_AllFloat();
}

/* WWDG の早期警告割込み (約 29ms ごと, core/mpb_wdt.c) から呼ばれる点検。0 を返すと全ゲート OFF → リセット */
int Mpb_Bridge_SafetyCheck(void)
{
    const uint16_t pol = TIM_CC1P | TIM_CC1NP | TIM_CC2P | TIM_CC2NP | TIM_CC3P | TIM_CC3NP;
    uint32_t cfg = GPIOB->CFGHR, odr = GPIOB->OUTDR;

    if (!s_inited)
    {
        return 1;
    }
    if ((TIM1->BDTR & 0xFFu) != s_dtg || (TIM1->CCER & pol))        /* デッドタイム・極性が変わっていない */
    {
        return 0;
    }
    if (s_tim2 && ((TIM1->CCER & (TIM_CC3E | TIM_CC3NE)) || (TIM2->CCER & (TIM_CC1P | TIM_CC1NP | TIM_CC2P | TIM_CC2NP))))
    {
        return 0;                                /* TIM1 CH3 と TIM2 CH1 が同じ PB12/PB13 に重なっていない */
    }
    for (uint8_t i = 0; i < 8; i++)              /* GPIO 出力にしているゲートを High にしていない (この基板では使わない) */
    {
        if (((cfg >> (i * 4u)) & 0x3u) && ((cfg >> (i * 4u)) & 0xCu) == 0u && (odr & (1u << (8u + i))))
        {
            return 0;
        }
    }
    return 1;
}

/* core の OPA_IRQHandler (過電流) から呼ばれる: 全レッグを GPIO Low に固定する */
void Mpb_OnOvercurrent(void)
{
    s_fault = 1;
    Mpb_Bridge_AllFloat();
    if (s_fault_hook)
    {
        s_fault_hook();
    }
}

static void tim_pwm(TIM_TypeDef *t, uint8_t ch)
{
    TIM_OCInitTypeDef oc = {0};

    oc.TIM_OCMode = TIM_OCMode_PWM1;             /* CNT < CCR で HO = ON */
    oc.TIM_OutputState = TIM_OutputState_Enable;
    oc.TIM_OutputNState = TIM_OutputNState_Enable;
    oc.TIM_Pulse = 0;
    oc.TIM_OCPolarity = TIM_OCPolarity_High;
    oc.TIM_OCNPolarity = TIM_OCNPolarity_High;
    oc.TIM_OCIdleState = TIM_OCIdleState_Reset;
    oc.TIM_OCNIdleState = TIM_OCNIdleState_Reset;
    if (ch == 1) { TIM_OC1Init(t, &oc); TIM_OC1PreloadConfig(t, TIM_OCPreload_Enable); }
    if (ch == 2) { TIM_OC2Init(t, &oc); TIM_OC2PreloadConfig(t, TIM_OCPreload_Enable); }
    if (ch == 3) { TIM_OC3Init(t, &oc); TIM_OC3PreloadConfig(t, TIM_OCPreload_Enable); }
}

void Mpb_Bridge_Init(const Mpb_BridgeCfg *cfg)
{
    static const Mpb_BridgeCfg dflt = {20000, 500, 900, 0, 0};
    TIM_TimeBaseInitTypeDef tb = {0};
    TIM_OCInitTypeDef oc = {0};
    TIM_BDTRInitTypeDef bd = {0};
    uint32_t dt, dns;

    if (cfg == NULL)
    {
        cfg = &dflt;
    }
    s_hz = cfg->pwm_hz ? cfg->pwm_hz : 20000u;
    s_max = (cfg->max_duty && cfg->max_duty <= 980u) ? cfg->max_duty : 900u;
    s_tim2 = cfg->use_tim2;
    s_arr = (uint16_t)(SystemCoreClock / (2u * s_hz));
    s_inited = 0;

    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOB | RCC_PB2Periph_AFIO | RCC_PB2Periph_TIM1, ENABLE);
    s_fault = 0;
    Mpb_Bridge_AllFloat();                       /* ここから先はゲート OFF のまま設定する */

    TIM_DeInit(TIM1);
    tb.TIM_Prescaler = 0;
    tb.TIM_CounterMode = TIM_CounterMode_CenterAligned1;
    tb.TIM_Period = s_arr;
    tb.TIM_ClockDivision = TIM_CKD_DIV1;
    tb.TIM_RepetitionCounter = 0;
    TIM_TimeBaseInit(TIM1, &tb);
    tim_pwm(TIM1, 1);
    tim_pwm(TIM1, 2);
    tim_pwm(TIM1, 3);
    /* CH4: 出力なし。山 (CNT = ARR) の直後に一致 → ADC 注入変換の起動 */
    oc.TIM_OCMode = TIM_OCMode_PWM2;
    oc.TIM_OutputState = TIM_OutputState_Disable;
    oc.TIM_Pulse = (uint16_t)(s_arr - 1u);
    TIM_OC4Init(TIM1, &oc);

    if (s_tim2)
    {
        /* HB2 を TIM2 で出すときは TIM1 CH3/CH3N を出さない (同じ PB12/PB13 に重なると上下同時 ON になりうる) */
        TIM1->CCER &= (uint16_t)~(TIM_CC3E | TIM_CC3NE);
    }
    dns = cfg->dead_ns > MPB_DEAD_MIN_NS ? cfg->dead_ns : MPB_DEAD_MIN_NS;
    dt = ((uint32_t)dns * (SystemCoreClock / 1000000u) + 999u) / 1000u;   /* tDTS = 1/HCLK, 切り上げ */
    bd.TIM_OSSRState = TIM_OSSRState_Enable;
    bd.TIM_OSSIState = TIM_OSSIState_Enable;
    bd.TIM_LOCKLevel = TIM_LOCKLevel_3;          /* デッドタイム・極性・出力モードをリセットまで固定 (暴走しても変えられない) */
    bd.TIM_DeadTime = (uint8_t)(dt > 127u ? 127u : dt);
    s_dtg = bd.TIM_DeadTime;
    bd.TIM_Break = cfg->hw_break ? TIM_Break_Enable : TIM_Break_Disable;
    bd.TIM_BreakPolarity = TIM_BreakPolarity_High;   /* CMP2/CMP3 は過電流で High */
    bd.TIM_AutomaticOutput = TIM_AutomaticOutput_Disable;
    TIM_BDTRConfig(TIM1, &bd);
    s_dtg = (uint8_t)(TIM1->BDTR & 0xFFu);      /* 実際に入った値 (LOCK 済みで再設定されなかった場合も一致する) */
    TIM_SelectMasterSlaveMode(TIM1, TIM_MasterSlaveMode_Enable);
    TIM_SelectOutputTrigger(TIM1, TIM_TRGOSource_Enable);   /* TIM1 の起動で TIM2 も起動 → 同位相 */

    if (s_tim2)
    {
        RCC_PB1PeriphClockCmd(RCC_PB1Periph_TIM2, ENABLE);
        GPIO_PinRemapConfig(GPIO_PartialRemap2_TIM2, ENABLE);   /* CH1/CH1N = PB13/PB12, CH2/CH2N = PB15/PB14 */
        TIM_DeInit(TIM2);
        TIM_TimeBaseInit(TIM2, &tb);
        tim_pwm(TIM2, 1);
        tim_pwm(TIM2, 2);
        /* TIM2 のデッドタイム: (DT+1) × 4 / HCLK, 最大 16 × 55.6ns = 889ns */
        dt = ((uint32_t)dns * (SystemCoreClock / 1000000u) + 3999u) / 4000u;   /* 切り上げ */
        dt = dt ? dt - 1u : 0u;
        TIM2_DeadTimeConfig(TIM2, TIM_DTPolarity_Rising, (uint8_t)(dt > 15u ? 15u : dt), TIM_DT_DIV4);
        TIM2_DeadTimeConfig(TIM2, TIM_DTPolarity_Falling, (uint8_t)(dt > 15u ? 15u : dt), TIM_DT_DIV4);
        TIM_SelectInputTrigger(TIM2, TIM_TS_ITR0);   /* ITR0 = TIM1 */
        TIM_SelectSlaveMode(TIM2, TIM_SlaveMode_Trigger);
    }
    if (cfg->hw_break)
    {
        /* BKIN の既定端子 PA15 (I2C の SCL と共用) を Low に固定しておく (浮いていると誤ってブレーキがかかる) */
        GPIO_InitTypeDef g = {0};
        RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA, ENABLE);
        g.GPIO_Pin = GPIO_Pin_15;
        g.GPIO_Mode = GPIO_Mode_IPD;
        GPIO_Init(GPIOA, &g);
    }
    Mpb_Adc_Init();
    s_vdd8_t = 0;
    Mpb_Bridge_Vdd8Auto();                       /* ゲート駆動電圧を VBUS に合わせる */
    TIM_CtrlPWMOutputs(TIM1, ENABLE);            /* MOE: 出力の可否はピン設定 (leg_pins) で決める */
    TIM_Cmd(TIM1, ENABLE);
    s_inited = 1;
}

/* ------------------------------------------------------------ 電流 ------------------ */
static OPA_ISP_GAIN_SEL_TypeDef s_gain = OPA_ISP_GAIN_16;
static volatile int32_t  s_now[2], s_filt[2];      /* mA, s_filt は ×16 */
static volatile uint32_t s_cnt;
static volatile int32_t  s_off_acc[2];
static volatile uint16_t s_off[2];
static volatile uint16_t s_cal_n;                  /* 0 = 校正済み */
static volatile uint32_t s_vbus_f;                 /* PWM 周期ごとの VBUS [mV × 8] (IIR 1/8) */
static volatile uint8_t  s_ovp_n;

/* VBUS の上限 (回生で上がりすぎたら全 FET OFF)。子基板の運用上限 + 2V */
#ifndef MPB_VBUS_TRIP_MV
#define MPB_VBUS_TRIP_MV (MPB_VBUS_MAX_MV + 2000u)
#endif

void ADC_IRQHandler(void) MPB_IRQ;

static Mpb_BridgeHook s_hook[2];

void Mpb_Bridge_AddHook(Mpb_BridgeHook fn)
{
    for (uint8_t i = 0; i < 2; i++)
    {
        if (s_hook[i] == fn) return;
    }
    for (uint8_t i = 0; i < 2; i++)
    {
        if (!s_hook[i]) { s_hook[i] = fn; return; }
    }
}

void Mpb_Bridge_RemoveHook(Mpb_BridgeHook fn)
{
    for (uint8_t i = 0; i < 2; i++)
    {
        if (s_hook[i] == fn) s_hook[i] = 0;
    }
}

static int32_t raw_to_mA(int32_t raw_minus_off)
{
    static const uint8_t gtab[] = {4, 8, 16, 55};
    /* mV = raw × 3300 / 4096, I[mA] = mV × 1000 / (G × Rshunt[mΩ]) */
    return raw_minus_off * 3300 * 1000 / (4096 * (int32_t)(gtab[s_gain & 3] * MPB_SHUNT_MOHM));
}

void Mpb_Bridge_CurrentInit(OPA_ISP_GAIN_SEL_TypeDef gain, Mpb_IspSrc ia_src)
{
    s_gain = gain;
    Mpb_Adc_Init();
    Mpb_ISense_Init(gain, ia_src);
    ADC_InjectedSequencerLengthConfig(ADC1, 3);
    ADC_InjectedChannelConfig(ADC1, MPB_ADC_IA, 1, ADC_SampleTime_5Cycles5);
    ADC_InjectedChannelConfig(ADC1, MPB_ADC_IB, 2, ADC_SampleTime_5Cycles5);
    /* 3 番目に VBUS: 回生ブレーキで上がる母線電圧を PWM 周期ごとに見る (分圧は高インピーダンスなので長めに取り込む) */
    ADC_InjectedChannelConfig(ADC1, MPB_ADC_VBUS, 3, ADC_SampleTime_23Cycles5);
    s_vbus_f = Mpb_Vbus_mV() * 8u;
    s_ovp_n = 0;
    ADC_ExternalTrigInjectedConvConfig(ADC1, ADC_ExternalTrigInjecConv_T1_CC4);
    ADC_ExternalTrigInjectedConvCmd(ADC1, ENABLE);
    s_off_acc[0] = s_off_acc[1] = 0;
    s_cal_n = 256;
    ADC_ClearITPendingBit(ADC1, ADC_IT_JEOC);
    ADC_ITConfig(ADC1, ADC_IT_JEOC, ENABLE);
    NVIC_EnableIRQ(ADC_IRQn);
}

uint8_t Mpb_Bridge_CurrentReady(void) { return s_cal_n == 0; }
int32_t Mpb_Bridge_Current_mA(uint8_t ch) { return ch < 2 ? s_filt[ch] / 16 : 0; }
int32_t Mpb_Bridge_CurrentNow_mA(uint8_t ch) { return ch < 2 ? s_now[ch] : 0; }
uint32_t Mpb_Bridge_SampleCount(void) { return s_cnt; }
uint32_t Mpb_Bridge_Vbus_mV(void) { return s_vbus_f ? s_vbus_f / 8u : Mpb_Vbus_mV(); }

void ADC_IRQHandler(void)
{
    if (ADC_GetITStatus(ADC1, ADC_IT_JEOC) != RESET)
    {
        int32_t r0 = (int32_t)ADC_GetInjectedConversionValue(ADC1, ADC_InjectedChannel_1);
        int32_t r1 = (int32_t)ADC_GetInjectedConversionValue(ADC1, ADC_InjectedChannel_2);
        uint32_t vb = Mpb_Adc_ToMilliVolt(ADC_GetInjectedConversionValue(ADC1, ADC_InjectedChannel_3)) * MPB_VBUS_DIV;

        ADC_ClearITPendingBit(ADC1, ADC_IT_JEOC);
        s_vbus_f += vb - s_vbus_f / 8u;
        /* 回生で母線が上限を超えたら (8 周期続いたら) 全 FET OFF。通常は mpb_dc の回生制限で手前で止まる */
        if (s_vbus_f / 8u > MPB_VBUS_TRIP_MV)
        {
            if (++s_ovp_n >= 8u && !s_fault)
            {
                Mpb_Bridge_Trip();
            }
        }
        else
        {
            s_ovp_n = 0;
        }
        if (s_cal_n)
        {
            /* オフセット校正: 全レッグ開放 (電流 0) の間だけ積算する */
            if (s_leg[0] < 0 && s_leg[1] < 0 && s_leg[2] < 0 && s_leg[3] < 0)
            {
                s_off_acc[0] += r0;
                s_off_acc[1] += r1;
                if (--s_cal_n == 0)
                {
                    s_off[0] = (uint16_t)(s_off_acc[0] / 256);
                    s_off[1] = (uint16_t)(s_off_acc[1] / 256);
                }
            }
            if (s_hook[0]) s_hook[0](0, 0);           /* 校正中も歩進などは止めない (電流は 0 扱い) */
            if (s_hook[1]) s_hook[1](0, 0);
            return;
        }
        s_now[0] = raw_to_mA(r0 - (int32_t)s_off[0]);
        s_now[1] = raw_to_mA(r1 - (int32_t)s_off[1]);
        s_filt[0] += s_now[0] - s_filt[0] / 16;
        s_filt[1] += s_now[1] - s_filt[1] / 16;
        s_cnt++;
        if (s_hook[0]) s_hook[0](s_now[0], s_now[1]);
        if (s_hook[1]) s_hook[1](s_now[0], s_now[1]);
    }
}
