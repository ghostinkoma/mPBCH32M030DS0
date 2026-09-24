/*
 * mPBCH32M030DS0 ボード支援ライブラリ (内蔵アナログ・PD・自己診断)
 *
 * CH32M030 の「電流検出と保護」以外の内蔵機能まで使い切るための薄い API。
 * 各関数は SDK (openwch/ch32m030) の周辺ドライバで実装しており、TIM1/TIM2 の PWM 設定そのもの
 * (モーター制御アルゴリズム) はユーザー側で行う。設計の背景は docs/advanced_features.md 参照。
 *
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_H
#define MPB_H

#include <stdint.h>
#include "ch32m030.h"
#include "board.h"

/* ---- ADC チャネル割当 (回路図 Rev 0.2) ----------------------------------- */
#define MPB_ADC_IA        ADC_Channel_9    /* OPA3 出力 (内部): HB0 レッグ or バス (JP7) */
#define MPB_ADC_IB        ADC_Channel_10   /* OPA4 出力 (内部): HB1 or HB2 (JP5) */
#define MPB_ADC_IBUS      ADC_Channel_1    /* PB3: バスシャント直接 (10mV/A) */
#define MPB_ADC_OCPREF    ADC_Channel_0    /* PB2: 過電流しきい値 (読み戻し) */
#define MPB_ADC_VBUS      ADC_Channel_17   /* PB4: VBUS / 12 */
#define MPB_ADC_USBVBUS   ADC_Channel_15   /* PA2: USB VBUS / 13 */
#define MPB_ADC_NTC       ADC_Channel_5    /* PA4: NTC (ISOURCE1 駆動) */
#define MPB_ADC_SENS_U    ADC_Channel_6    /* PA5 */
#define MPB_ADC_SENS_V    ADC_Channel_2    /* PA7 (PA6 = W は ADC 無し, CMP3 専用) */
#define MPB_ADC_QII       ADC_Channel_19   /* OPA1 出力 (内部) */

#define MPB_VBUS_DIV      12u              /* 110k / 10k */
#define MPB_USBVBUS_DIV   13u              /* 120k / 10k */
#define MPB_SHUNT_MOHM    10u              /* 各レッグ / バス 10mΩ */

/* ---- 時間基準 (TIM3 1MHz フリーラン。TIM3 CH1 は QII タコ捕捉にも使う) ------ */
void     Mpb_Time_Init(void);
uint32_t Mpb_Micros(void);
uint32_t Mpb_Millis(void);

/* ---- ADC ------------------------------------------------------------------ */
void     Mpb_Adc_Init(void);
uint16_t Mpb_Adc_Read(uint8_t ch);                 /* 単発変換 (12bit) */
uint32_t Mpb_Adc_ToMilliVolt(uint16_t raw);        /* VDD33 = 3300mV 基準 */
uint32_t Mpb_Vbus_mV(void);
uint32_t Mpb_UsbVbus_mV(void);

/* ---- 電流アンプ (OPA3 / OPA4) --------------------------------------------- */
typedef enum { MPB_ISP_LEG = 0, MPB_ISP_BUS = 1 } Mpb_IspSrc;   /* JP7 の設定と一致させる */
void     Mpb_ISense_Init(OPA_ISP_GAIN_SEL_TypeDef gain, Mpb_IspSrc ia_src);
int32_t  Mpb_ISense_mA(uint16_t raw, OPA_ISP_GAIN_SEL_TypeDef gain);   /* バイアス 1.6V 基準 */

/* ---- 過電流保護 ------------------------------------------------------------ */
void     Mpb_Ocp_BusCmp3_Init(void);                       /* CMP3: PB3 vs PB2 → TIM1 BKIN */
uint8_t  Mpb_Ocp_DacCode(uint32_t limit_mA, OPA_ISP_GAIN_SEL_TypeDef gain);
void     Mpb_Ocp_Cmp2_Init(uint8_t dac_code);              /* CMP2: OPA3 出力 vs 内蔵 DAC → BKIN */
extern volatile uint8_t g_mpb_overcurrent;                 /* 過電流検出で 1 (ユーザーがクリア) */
void     Mpb_OnOvercurrent(void);                          /* weak: 過電流時のユーザー処理 (割込み内) */

/* ---- 3 相センシング (PA5/PA6/PA7) ----------------------------------------- */
void     Mpb_Bemf_Init(void);            /* CMP3: 相 (N) vs 内部仮想中性点 → TIM2 CH1-3 捕捉, TIM1 CC4 同期 */
void     Mpb_Bemf_SelectPhase(uint8_t phase);   /* 0=U(PA5) 1=W(PA6) 2=V(PA7): 転流ごとに浮き相を選ぶ */
void     Mpb_Hall_Init(void);            /* TIM2 ホールセンサ XOR モード (CH1 = 3 入力の XOR) */

/* ---- QII1 小信号入力 (PA12 → OPA1 → CMP1 → TIM3 CH1) ---------------------- */
void     Mpb_Tach_Init(OPA1_QII1_AVSEL_TypeDef gain, CMP1_QII1_HYPSEL_TypeDef hyst);
uint32_t Mpb_Tach_PeriodUs(void);        /* 直近の周期 [µs] (0 = 未検出) */

/* ---- 温度 (ISOURCE1 → NTC) ------------------------------------------------ */
void     Mpb_Ntc_Init(void);
int32_t  Mpb_Ntc_DeciCelsius(void);      /* 0.1℃ 単位 (B3435, 10kΩ@25℃) */

/* ---- 結線自己診断 (ISOURCE2 を PA5 から注入し PA7 を観測, ゲート OFF で実行) ---- */
typedef enum { MPB_WIRE_OK = 0, MPB_WIRE_OPEN_UV = 1, MPB_WIRE_NOT_TESTED = 2 } Mpb_WireResult;
Mpb_WireResult Mpb_SelfTest_Wiring(uint32_t *v_uV);   /* v_uV: PA7 に現れた電圧 [µV] */

/* ---- USB-PD シンク + 給電パス --------------------------------------------- */
typedef struct {
    uint16_t max_mV;          /* 要求上限 (既定 15000: TVS SMBJ16A / FET 30V の制約) */
    uint16_t min_mV;          /* これ未満の PDO しか無ければモーター給電しない (既定 8000) */
    uint16_t want_mA;         /* 欲しい電流 (既定 3000) */
} Mpb_PdPolicy;

typedef struct {
    uint8_t  attached;        /* PD ソース接続中 */
    uint8_t  contract;        /* 契約成立 (PS_RDY 受信) */
    uint8_t  power_enabled;   /* PD_PWR_EN = High (VBUS へ給電中) */
    uint16_t mV, mA;          /* 契約電圧・電流 */
} Mpb_PdStatus;

void     Mpb_PD_Init(const Mpb_PdPolicy *policy);   /* NULL で既定値 */
void     Mpb_PD_Task(void);                         /* loop() から 1ms 以上の頻度で呼ぶ */
const Mpb_PdStatus *Mpb_PD_Status(void);
void     Mpb_PD_PowerEnable(uint8_t on);             /* 手動制御 (通常は自動) */

/* PD スタック (pd_process.c) から呼ばれるフック */
uint8_t  Mpb_PD_SelectPdo(const uint8_t *srccap, uint8_t pdo_len);
void     Mpb_PD_OnPsRdy(void);
void     Mpb_PD_OnDetach(void);

#endif /* MPB_H */
