/*
 * mpb_dc — ブラシ付き DC モーター (H ブリッジ = ハーフブリッジ 2 本)
 *
 *   モーター 0: HB0 / HB1 (電流: IA = HB0, IB = HB1 → JP7=1-2, JP5=1-2)
 *   モーター 1: HB2 / HB3 (Mpb_BridgeCfg.use_tim2 = 1。電流は IB = HB2 → JP5=2-3 のときだけ)
 *
 * 駆動は「片側 PWM + 反対側ローサイド ON」(sign-magnitude, 同期整流): 正転は HB0 を PWM, HB1 を Low。
 * PWM の OFF 期間はローサイド 2 石で還流する (減衰が遅く, 電流リップルが小さい)。
 *
 * 制御モード
 *   - 電圧 (duty): Mpb_Dc_SetDuty(m, -1000〜+1000)。加減速は ramp で制限
 *   - 電流: Mpb_Dc_SetCurrent(m, ±mA)。PWM 周期ごとの電流で PI 制御 (トルク一定)
 * DC モーターは電流 (≒トルク) しか直接制御できないので, 回転数は Kv [rpm/V] から概算する:
 *   rpm ≈ Kv × (VBUS × duty − I × R)     (R = 巻線抵抗, 0 なら I×R を無視)
 * QII (TACH_IN or JP8=2-3 の電流リップル) で実測できる場合は Mpb_Tach_PeriodUs() を使う。
 *
 * 呼び出しは全てノンブロッキング。loop() から Mpb_Dc_Task() を毎回呼ぶ (1ms ごとに VBUS 読み取りと加減速)。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_DC_H
#define MPB_DC_H

#include <stdint.h>
#include "mpb_bridge.h"

typedef enum { MPB_DC_COAST = 0, MPB_DC_BRAKE, MPB_DC_DUTY, MPB_DC_CURRENT } Mpb_DcMode;

typedef struct {
    uint16_t kv_rpm_per_v;       /* モーター定数 [rpm/V] (無負荷回転数 ÷ 定格電圧)。0 = 回転数を出さない */
    uint16_t r_mohm;             /* 巻線抵抗 [mΩ] (0 = I×R の補正なし) */
    uint16_t ramp_per_ms;        /* duty の変化率 [‰/ms] (0 = 即時) */
    uint16_t i_limit_mA;         /* 電流制限 [mA] (0 = なし)。duty モードでも超えたら duty を絞る */
    uint16_t kp, ki;             /* 電流 PI ゲイン (duty‰ / A, ‰/(A·ms))。0 なら既定 (kp 40, ki 4) */
} Mpb_DcCfg;

void     Mpb_Dc_Init(uint8_t m, const Mpb_DcCfg *cfg);    /* Mpb_Bridge_Init / CurrentInit の後で呼ぶ */
void     Mpb_Dc_SetDuty(uint8_t m, int16_t duty);         /* ±1000: 正 = 正転, 負 = 逆転 */
void     Mpb_Dc_SetCurrent(uint8_t m, int32_t mA);        /* ± 目標電流 */
void     Mpb_Dc_Coast(uint8_t m);                         /* 惰性 (両レッグ開放) */
void     Mpb_Dc_Brake(uint8_t m);                         /* 短絡ブレーキ (両ローサイド ON) */
void     Mpb_Dc_Task(void);                               /* loop() から毎回 */

Mpb_DcMode Mpb_Dc_Mode(uint8_t m);
int16_t  Mpb_Dc_Duty(uint8_t m);                          /* 現在の duty (±‰) */
int32_t  Mpb_Dc_Current_mA(uint8_t m);                    /* 符号付き (正転方向が正) */
int32_t  Mpb_Dc_Rpm(uint8_t m);                           /* Kv からの概算 (符号付き) */
uint32_t Mpb_Dc_VbusMv(void);                             /* Task が 1ms ごとに更新 */

#endif /* MPB_DC_H */
