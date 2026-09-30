/*
 * mpb_stepper — 2 相バイポーラ ステッピングモーター (フル / ハーフ / マイクロステップ 1/4〜1/32)
 *
 *   A 相: HB0 (A+) / HB1 (A−)    B 相: HB2 (B+) / HB3 (B−)   → Mpb_BridgeCfg.use_tim2 = 1 が必要
 *   電流: IA = HB0 (JP7=1-2), IB = HB2 (JP5=2-3)
 *
 * 各相は「片側 PWM + 反対側ローサイド ON」で, 電圧 (duty) を sin / cos で与える (電圧モードのマイクロステップ)。
 * 相電流の振幅は 電流 × 巻線抵抗 ÷ VBUS で duty に換算する (低速では電流 ≒ 設定値, 高速では逆起電力で減る)。
 *
 * 歩進は PWM 周期 (既定 20kHz) の割込みで位相アキュムレータを回す: 最高 PWM 周波数 [マイクロステップ/s]。
 *   200 ステップ/回転, 1/16 なら 20000 / 3200 = 6.25 回転/s (375rpm)。速くするときは分割を粗くする。
 * 加減速は Mpb_Stepper_Task() (1ms ごと) で台形に行う。停止後 hold_ms で保持電流 (hold_pct) に下げる。
 * 回転数 (ソフトウェア タコ) は歩進レートから計算する (脱調していなければ実回転数と一致)。
 *
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_STEPPER_H
#define MPB_STEPPER_H

#include <stdint.h>
#include "mpb_bridge.h"

typedef struct {
    uint16_t steps_per_rev;      /* フルステップ数/回転 (既定 200) */
    uint8_t  microstep;          /* 1, 2, 4, 8, 16, 32 */
    uint16_t current_mA;         /* 相電流 (ピーク) */
    uint16_t coil_r_mohm;        /* 巻線抵抗 [mΩ]。0 なら current_mA を duty‰ として扱う (電圧直接) */
    uint32_t accel;              /* 加速度 [マイクロステップ/s²] (0 = 即時) */
    uint8_t  hold_pct;           /* 停止中の保持電流 [%] (既定 50, 0 = 停止で開放) */
    uint16_t hold_ms;            /* 停止してから保持電流に下げるまで [ms] (既定 500) */
} Mpb_StepperCfg;

void     Mpb_Stepper_Init(const Mpb_StepperCfg *cfg);   /* Bridge_Init(use_tim2=1) / CurrentInit の後 */
void     Mpb_Stepper_Enable(uint8_t on);                 /* 0: 両相開放 (脱力) */
void     Mpb_Stepper_SetSpeed(int32_t usteps_per_s);     /* 連続回転 (±: 正転 / 逆転) */
void     Mpb_Stepper_SetRpm(int32_t rpm);                /* 同上 (rpm 指定) */
void     Mpb_Stepper_MoveTo(int32_t pos, uint32_t max_usteps_per_s);  /* 絶対位置 [マイクロステップ] */
void     Mpb_Stepper_Move(int32_t delta, uint32_t max_usteps_per_s);  /* 相対移動 */
void     Mpb_Stepper_Stop(void);                         /* 減速して停止 */
void     Mpb_Stepper_SetCurrent(uint16_t mA);
void     Mpb_Stepper_Task(void);                         /* loop() から毎回 */

int32_t  Mpb_Stepper_Position(void);                     /* 現在位置 [マイクロステップ] */
void     Mpb_Stepper_SetPosition(int32_t pos);           /* 原点合わせ */
int32_t  Mpb_Stepper_Speed(void);                        /* 現在の速度 [マイクロステップ/s] */
int32_t  Mpb_Stepper_Rpm(void);                          /* ソフトウェア タコ (×1) */
int32_t  Mpb_Stepper_RpmX10(void);                       /* 同 0.1rpm 単位 */
uint8_t  Mpb_Stepper_Busy(void);                         /* 移動中 (MoveTo 未完了 / 回転中) */
int32_t  Mpb_Stepper_CoilA_mA(void);                     /* 相電流の実測 (PWM 同期) */
int32_t  Mpb_Stepper_CoilB_mA(void);

#endif /* MPB_STEPPER_H */
