/*
 * mpb_bridge — 4 本のハーフブリッジ (HB0〜HB3) の PWM と電流の同期取り込み
 *
 *   HB0 = TIM1 CH1/CH1N (HO0 PB9 / LO0 PB8)      HB2 = TIM1 CH3/CH3N (PB13/PB12)  … use_tim2=0
 *   HB1 = TIM1 CH2/CH2N (HO1 PB11 / LO1 PB10)    HB2 = TIM2 CH1/CH1N (リマップ2) … use_tim2=1
 *                                                HB3 = TIM2 CH2/CH2N (PB15/PB14, リマップ2, use_tim2=1 のときだけ)
 *
 * PWM は中心揃え (TIM1 と TIM2 は同期) の相補 PWM + デッドタイム。duty は 0〜1000 (‰) で,
 * 0 = ローサイド常時 ON (GND に短絡 = ブレーキ), MPB_LEG_FLOAT = 両方 OFF (開放)。
 * 上限は Mpb_BridgeCfg.max_duty (既定 900‰): ブートストラップの充電と電流の取り込みにローサイド ON の時間が要るため。
 *
 * 電流: PWM の山 (全ローサイド ON) で ADC 注入変換 (TIM1 CC4 起動) → IA (OPA3, HB0) / IB (OPA4, HB1 or HB2: JP5)。
 * 各レッグのシャントはローサイドの帰路にあるので, 山で取り込めば向きも含めて相電流が得られる。
 *
 * 過電流: Mpb_Ocp_* (core/mpb.h) のコンパレータが OPA_IRQHandler で全出力を止める (TIM1 はハードの BKIN も可)。
 * 【注意】TIM1 の BKIN 端子は既定配置で PA15 (= I2C の SCL)。I2C を使うときは hw_break=0 にすること
 *        (SCL の High をブレーキと誤認して出力が止まる)。hw_break=0 でも割込みで数 µs 以内に止める。
 *
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_BRIDGE_H
#define MPB_BRIDGE_H

#include <stdint.h>
#include "mpb.h"

#define MPB_LEG_FLOAT   (-1)       /* Mpb_Bridge_Leg(): 両方 OFF */
#define MPB_DUTY_FULL   1000

typedef struct {
    uint32_t pwm_hz;               /* PWM 周波数 (既定 20000) */
    uint16_t dead_ns;              /* デッドタイム (既定 500ns, TIM2 は最大 880ns) */
    uint16_t max_duty;             /* duty の上限 ‰ (既定 900) */
    uint8_t  use_tim2;             /* 1: HB2/HB3 を TIM2 で駆動 (ステッピング / DC 2ch) */
    uint8_t  hw_break;             /* 1: CMP → TIM1 BKIN のハード遮断も使う (PA15 を I2C に使わないとき) */
} Mpb_BridgeCfg;

void     Mpb_Bridge_Init(const Mpb_BridgeCfg *cfg);   /* NULL で既定値。全レッグ開放で起動 */
void     Mpb_Bridge_Leg(uint8_t leg, int16_t duty);   /* duty 0〜1000 / MPB_LEG_FLOAT */
int16_t  Mpb_Bridge_GetLeg(uint8_t leg);
/* Leg の細かい版: duty を 0〜65535 (16bit) で指定 (上限は max_duty)。分解能は実際には 1/ARR (20kHz で 1/1800) */
void     Mpb_Bridge_LegQ16(uint8_t leg, uint16_t duty_q16);
/* ローサイドだけの PWM (ハイサイドは常時 OFF)。on = ローサイド ON の割合 0〜65535 (上限なし, 16bit)。
 * LED・ソレノイドなどを VBUS と出力端子の間につなぎ, ローサイドスイッチとして使う (0 = 開放) */
void     Mpb_Bridge_LegLow(uint8_t leg, uint16_t on);
void     Mpb_Bridge_AllFloat(void);                   /* 全レッグ開放 (即時) */
uint16_t Mpb_Bridge_MaxDuty(void);
uint32_t Mpb_Bridge_PwmHz(void);

/* ゲート駆動電源 VDD8 (リセット時は 5V) を VBUS に合わせて選ぶ: VBUS ≥ 12V → 10V, ≥ 10.5V → 9V, ≥ 9.5V → 8V,
 * それ未満 → 5V (VDD8 ≤ VHV ≈ VBUS − 0.5V が条件)。Init で 1 回, 以後は各モーターの Task が 100ms ごとに呼ぶ。
 * 戻り値: 設定した VDD8 [mV] */
uint16_t Mpb_Bridge_Vdd8Auto(void);
uint16_t Mpb_Bridge_Vdd8(void);

/* 過電流などで止まったか (Mpb_OnOvercurrent から立つ)。Clear で再び出力できる */
uint8_t  Mpb_Bridge_Faulted(void);
void     Mpb_Bridge_ClearFault(void);

/* ---- 電流 (PWM 同期) ---------------------------------------------------------------- */
/* gain: OPA のゲイン (OPA_ISP_GAIN_4/8/16/55)。ia_src: JP7 の設定 (MPB_ISP_LEG / MPB_ISP_BUS)。
 * 出力を開放した状態で 256 回平均してオフセットを取る (約 13ms, その間 Mpb_Bridge_CurrentReady() = 0) */
void     Mpb_Bridge_CurrentInit(OPA_ISP_GAIN_SEL_TypeDef gain, Mpb_IspSrc ia_src);
uint8_t  Mpb_Bridge_CurrentReady(void);
int32_t  Mpb_Bridge_Current_mA(uint8_t ch);           /* ch 0 = IA, 1 = IB。1/16 の IIR で平滑化 */
int32_t  Mpb_Bridge_CurrentNow_mA(uint8_t ch);        /* 直近 1 回 (平滑化なし) */
uint32_t Mpb_Bridge_SampleCount(void);                /* 取り込み回数 (PWM 周期ごとに +1) */

/* PWM 周期ごと (電流を取り込んだ直後) に割込みから呼ぶ関数を登録する (最大 2 個, NULL で解除)。
 * ステッピングの歩進・3 相の強制転流が使う。ユーザーも電流ループなどの高速処理に使える (短く書くこと)。
 * 割込みは ADC の注入変換完了なので, Mpb_Bridge_CurrentInit() を呼んでおくこと (モーター制御では必須) */
typedef void (*Mpb_BridgeHook)(int32_t ia_mA, int32_t ib_mA);
void     Mpb_Bridge_AddHook(Mpb_BridgeHook fn);
void     Mpb_Bridge_RemoveHook(Mpb_BridgeHook fn);

#endif /* MPB_BRIDGE_H */
