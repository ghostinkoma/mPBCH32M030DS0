/*
 * mpb_guard — 保護と警報出力: 熱・過電流・短絡・電圧の異常で GPIO を High にする (待ちなし)
 *
 *   検出                         方法                                               反応
 *   短絡 / 瞬時の過電流 (SHORT)  コンパレータ (Mpb_Ocp_BusCmp3_Init / Mpb_Ocp_Cmp2_Init)  割込みで数 µs 以内に警報 High + 全ゲート OFF
 *   過電流 (OVERCURRENT)         PWM 同期の相電流 |IA|, |IB| が i_trip_mA を i_trip_ms 続けて超えた   Task (1ms) で警報 High
 *   過熱 (OVERTEMP)              NTC (子基板の MOSFET 近く) が temp_trip を超えた (temp_clear まで下がると解除)
 *   センサ異常 (NTC_FAULT)       NTC の断線・短絡 (読めない)
 *   過電圧 / 低電圧              VBUS が vbus_max_mV を超えた / vbus_min_mV を下回った (0 = 見ない)
 *
 * 警報端子は Mpb_GuardCfg で選ぶ。既定は PC5 (J1-5 GPIO_PC5):
 *   PC5 は VHV (≈ VBUS − 0.5V) で動く高電圧 I/O で, High = VHV (12V 系なら約 11.5V) の軽負荷プッシュプル。
 *   リレー用トランジスタ / MOSFET のゲート, PLC の 12/24V 入力, 抵抗付き LED・ブザーを直接駆動できるが,
 *   3.3V / 5V のマイコンにはつながないこと (分圧するか, 3.3V の端子を選ぶ: PA14/PA15 など)。
 * latch = 1 なら, 原因が消えても Mpb_Guard_Clear() まで High のまま (異常の見逃し防止)。
 * stop_bridge = 1 なら, ソフトウェアで検出した異常 (過熱・過電流・電圧) でも全ゲートを止める。
 *
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_GUARD_H
#define MPB_GUARD_H

#include <stdint.h>
#include "mpb.h"

#define MPB_GUARD_SHORT        0x01u   /* ハード (コンパレータ) の過電流 = 短絡 */
#define MPB_GUARD_OVERCURRENT  0x02u   /* ソフトの過電流 (持続) */
#define MPB_GUARD_OVERTEMP     0x04u
#define MPB_GUARD_NTC_FAULT    0x08u
#define MPB_GUARD_OVERVOLT     0x10u
#define MPB_GUARD_UNDERVOLT    0x20u

typedef struct {
    GPIO_TypeDef *port;                /* 警報端子 (NULL = PC5) */
    uint16_t pin;
    uint8_t  active_low;               /* 1: 異常で Low (既定 0 = 異常で High) */
    uint8_t  latch;                    /* 1: Mpb_Guard_Clear() まで保持 */
    uint8_t  stop_bridge;              /* 1: ソフトで検出した異常でも全ゲートを止める */
    uint8_t  ntc_fault_alarm;          /* 1: NTC が読めないのも異常とする */
    int16_t  temp_trip_c10;            /* 過熱 [0.1℃] (0 = 見ない) */
    int16_t  temp_clear_c10;           /* 解除 [0.1℃] (ヒステリシス) */
    uint32_t i_trip_mA;                /* 過電流 [mA] (0 = 見ない) */
    uint16_t i_trip_ms;                /* 超え続けた時間 [ms] */
    uint32_t vbus_max_mV;              /* 過電圧 [mV] (0 = 見ない) */
    uint32_t vbus_min_mV;              /* 低電圧 [mV] (0 = 見ない) */
} Mpb_GuardCfg;

void     Mpb_Guard_Init(const Mpb_GuardCfg *cfg);
uint8_t  Mpb_Guard_Task(void);         /* loop から毎回 (1ms ごとに判定)。戻り値 = 現在の異常フラグ */
uint8_t  Mpb_Guard_Flags(void);        /* 異常フラグ (MPB_GUARD_*)。latch 中は消えない */
uint8_t  Mpb_Guard_Alarm(void);        /* 警報出力中 */
void     Mpb_Guard_Clear(void);        /* ラッチを解除 (原因が残っていればすぐ再び警報) + ブリッジの故障も解除 */
int32_t  Mpb_Guard_TempC10(void);      /* 直近の NTC 温度 [0.1℃] (INT32_MIN = 読めない) */
const char *Mpb_Guard_Text(uint8_t flags);   /* "SHORT OVERTEMP" のような文字列 (静的) */

#endif /* MPB_GUARD_H */
