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
 * 止め方 (状態は 4 つだけ: 惰性 COAST / 駆動 DUTY・CURRENT / 停止 STOP / 保持 BRAKE。故障は全 FET OFF)
 *   この駆動方式では「回生ブレーキ」と「短絡ブレーキ」は別の状態ではなく duty の連続した点:
 *     duty が逆起電力より小さい → 電流が逆向き = 回生 (母線へ電力を戻す)
 *     duty = 0                   → 両ローサイド ON = 短絡ブレーキ (電力は巻線で熱になる)
 *   Mpb_Dc_Stop(m, mA) は制動電流を一定に保つ電流制御で, 速度が落ちるにつれ duty が自然に 0 (短絡) へ移り,
 *   止まったら保持 (短絡ブレーキ, brake_hold_ms) → 惰性 (全 FET OFF) で終わる。切り替えの瞬間に電流が跳ねない。
 *   回生した電力で母線 (VBUS) が上がりすぎないよう, PWM 周期ごとに測る VBUS が上限を超えると制動電流を絞る
 *   (インバーターの「減速ストール防止」と同じ)。USB-PD やベンチ電源は電力を吸い込めないので, 既定の上限は
 *   「止め始めの VBUS + 1V」。バッテリーで回生したいときは brake_vbus_max_mV を上げる。
 *   duty / 電流モードで減速するときも同じく, 回生中に上限を超えたら duty を下げるのを待つ (減速が緩やかになる)。
 *   さらに上限 + 2V (MPB_VBUS_TRIP_MV) を超えると mpb_bridge が全 FET OFF。
 *   逆転させて止める (プラギング) は行わない: 電源と逆起電力の両方で電流が流れ, 大電流になるため。
 *
 * 呼び出しは全てノンブロッキング。loop() から Mpb_Dc_Task() を毎回呼ぶ (1ms ごとに VBUS 読み取りと加減速)。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_DC_H
#define MPB_DC_H

#include <stdint.h>
#include "mpb_bridge.h"

typedef enum { MPB_DC_COAST = 0, MPB_DC_BRAKE, MPB_DC_DUTY, MPB_DC_CURRENT, MPB_DC_STOP } Mpb_DcMode;

typedef struct {
    uint16_t kv_rpm_per_v;       /* モーター定数 [rpm/V] (無負荷回転数 ÷ 定格電圧)。0 = 回転数を出さない */
    uint16_t r_mohm;             /* 巻線抵抗 [mΩ] (0 = I×R の補正なし) */
    uint16_t ramp_per_ms;        /* duty の変化率 [‰/ms] (0 = 即時) */
    uint16_t i_limit_mA;         /* 電流制限 [mA] (0 = なし)。duty モードでも超えたら duty を絞る */
    uint16_t kp, ki;             /* 電流 PI ゲイン (duty‰ / A, ‰/(A·ms))。0 なら既定 (kp 40, ki 4) */
    uint16_t brake_vbus_max_mV;  /* 回生で許す VBUS の上限 [mV] (0 = 止め始めの VBUS + 1V, 子基板の上限 −1V まで) */
    uint16_t brake_hold_ms;      /* 停止後に短絡ブレーキで保持する時間 [ms] (0 = 300ms)。その後は惰性 (全 FET OFF) */
} Mpb_DcCfg;

void     Mpb_Dc_Init(uint8_t m, const Mpb_DcCfg *cfg);    /* Mpb_Bridge_Init / CurrentInit の後で呼ぶ */
void     Mpb_Dc_SetDuty(uint8_t m, int16_t duty);         /* ±1000: 正 = 正転, 負 = 逆転 */
void     Mpb_Dc_SetCurrent(uint8_t m, int32_t mA);        /* ± 目標電流 */
void     Mpb_Dc_Coast(uint8_t m);                         /* 惰性 (両レッグ開放) */
void     Mpb_Dc_Brake(uint8_t m);                         /* 短絡ブレーキ (両ローサイド ON)。高速回転中は大電流になる */
void     Mpb_Dc_Stop(uint8_t m, uint16_t brake_mA);       /* 停止: 制動電流 brake_mA で回生 → 短絡 → 保持 → 惰性 (推奨) */
void     Mpb_Dc_Task(void);                               /* loop() から毎回 */

Mpb_DcMode Mpb_Dc_Mode(uint8_t m);
int16_t  Mpb_Dc_Duty(uint8_t m);                          /* 現在の duty (±‰) */
int32_t  Mpb_Dc_Current_mA(uint8_t m);                    /* 符号付き (正転方向が正) */
int32_t  Mpb_Dc_Rpm(uint8_t m);                           /* Kv からの概算 (符号付き) */
uint32_t Mpb_Dc_VbusMv(void);                             /* Task が 1ms ごとに更新 (PWM 周期ごとの平滑値) */
uint8_t  Mpb_Dc_Regen(uint8_t m);                         /* 1 = いま回生中 (電流が duty と逆向き) */
uint8_t  Mpb_Dc_VbusLimited(uint8_t m);                   /* 1 = VBUS 上限で制動 / 減速を絞っている */

#endif /* MPB_DC_H */
