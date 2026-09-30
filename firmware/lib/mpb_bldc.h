/*
 * mpb_bldc — 3 相ブラシレスモーター (6 ステップ = 120° 矩形波駆動)
 *
 *   U = HB0, V = HB1, W = HB2 (TIM1 CH1〜CH3, Mpb_BridgeCfg.use_tim2 = 0)
 *   電流: IA = U (JP7=1-2), IB = V (JP5=1-2), W = −(U+V)
 *
 * 転流の方式
 *   MPB_BLDC_HALL : ホールセンサ (JP2〜JP4 = 2-3, HALL_A/B/C = PA5/PA7/PA6)。TIM2 のホール I/F で
 *                   エッジごとに割込みで転流し, 同時にエッジ間隔 (1µs 分解能) を測る → タコ
 *   MPB_BLDC_OPEN : センサなしのオープンループ (同期モーターとして回す)。電気角周波数と duty を
 *                   V/f で上げていく。軽負荷・一定速度向け (脱調しても検出できない)。
 *                   【未実装】BEMF ゼロクロスによる閉ループ (センサレス) は Mpb_Bemf_* を使って今後追加する
 *
 * 回転数: ホール = エッジ間隔 (6 回/電気角 1 周), オープンループ = 転流周期,
 *         外部タコ (TACH_IN → QII1 → TIM3) = Mpb_Tach_PeriodUs() と tach_ppr から (Mpb_Bldc_TachRpm)
 * 正転 / 逆転: Mpb_Bldc_SetDuty(±‰)。向きを変えるときは duty を 0 まで下げて停止を確認してから反転する。
 * 電流制限: 導通中の相の電流 (PWM の山) が i_limit_mA を超えたら duty を絞る (ハードの過電流遮断は別途)。
 *
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_BLDC_H
#define MPB_BLDC_H

#include <stdint.h>
#include "mpb_bridge.h"

typedef enum { MPB_BLDC_HALL = 0, MPB_BLDC_OPEN = 1 } Mpb_BldcSense;

typedef struct {
    Mpb_BldcSense sense;
    uint8_t  pole_pairs;         /* 極対数 (例: 14 極なら 7) */
    uint8_t  hall_shift;         /* ホールと転流の対応を 60° 単位でずらす (0〜5, 回らない / 逆に回るとき調整) */
    uint16_t ramp_per_ms;        /* duty の変化率 [‰/ms] */
    uint16_t i_limit_mA;         /* 電流制限 (0 = なし) */
    /* オープンループ */
    uint16_t open_start_hz;      /* 起動時の電気角周波数 [Hz] (既定 5) */
    uint16_t open_hz_per_s;      /* 周波数の上げ下げ [Hz/s] (既定 20) */
    uint16_t open_duty_per_hz;   /* V/f: 1Hz あたりの duty [‰×10] (既定 20 = 2‰/Hz) */
    uint16_t open_min_duty;      /* 低速での最小 duty [‰] (既定 60) */
    /* 外部タコ */
    uint8_t  tach_ppr;           /* TACH_IN の 1 回転あたりパルス数 (0 = 使わない) */
} Mpb_BldcCfg;

void     Mpb_Bldc_Init(const Mpb_BldcCfg *cfg);   /* Bridge_Init / CurrentInit の後 */
void     Mpb_Bldc_SetDuty(int16_t duty);          /* ホール: ±duty。符号 = 向き */
void     Mpb_Bldc_SetOpenHz(int16_t e_hz);        /* オープンループ: 目標の電気角周波数 (±) */
void     Mpb_Bldc_SetRpm(int32_t rpm);            /* オープンループ: rpm で指定 (極対数から換算) */
void     Mpb_Bldc_Coast(void);                    /* 全相開放 */
void     Mpb_Bldc_Brake(void);                    /* 全ローサイド ON */
void     Mpb_Bldc_Task(void);                     /* loop() から毎回 */

int16_t  Mpb_Bldc_Duty(void);
int32_t  Mpb_Bldc_Rpm(void);                      /* ソフトウェア タコ (ホール / 転流周期), 符号付き */
int32_t  Mpb_Bldc_TachRpm(void);                  /* 外部タコ (TACH_IN) */
int32_t  Mpb_Bldc_Current_mA(void);               /* 導通中の相の電流 */
uint8_t  Mpb_Bldc_HallState(void);                /* 1〜6 (0/7 は配線異常) */
uint32_t Mpb_Bldc_Commutations(void);             /* 転流回数 */

#endif /* MPB_BLDC_H */
