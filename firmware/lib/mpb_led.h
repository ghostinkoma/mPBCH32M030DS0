/*
 * mpb_led — MOSFET (パワー段のレッグ) につないだ単色 LED の CIE 1931 調光
 *
 *   MPB_LED_LOW  : LED (+) を VBUS, (−) を出力端子 OUTx へ。ローサイドだけで PWM (0〜100%)。推奨
 *   MPB_LED_HIGH : LED (+) を OUTx, (−) を GND へ。ハイサイド PWM (ブートストラップのため上限 max_duty)
 * 最大 4 チャネル (HB0〜HB3。HB3 は Mpb_BridgeCfg.use_tim2 = 1 のとき)。RGBW テープも 4 レッグで駆動できる。
 * 明るさは L* (×100, 0〜10000) で指定し, CIE 1931 の式で duty に換算する (暗部までなめらか)。
 * PWM の分解能は 1/ARR (20kHz で 1/1800)。暗部を細かくしたいときは Mpb_BridgeCfg.pwm_hz を下げる
 * (例: 2kHz で 1/18000。LED は可聴域でも鳴らない)。
 *
 * フェード・呼吸 (明→暗の往復) は Mpb_Led_Task() が 1ms ごとに進める (待ちなし)。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_LED_H
#define MPB_LED_H

#include <stdint.h>
#include "mpb_bridge.h"

typedef enum { MPB_LED_LOW = 0, MPB_LED_HIGH = 1 } Mpb_LedWiring;

void     Mpb_Led_Init(uint8_t ch, uint8_t leg, Mpb_LedWiring wiring);   /* ch 0〜3 */
void     Mpb_Led_Set(uint8_t ch, uint16_t lx100);                        /* 即時 */
void     Mpb_Led_Fade(uint8_t ch, uint16_t lx100, uint32_t ms);          /* L* 空間で直線に変化 */
void     Mpb_Led_Breathe(uint8_t ch, uint16_t lo, uint16_t hi, uint32_t period_ms);   /* 往復を繰り返す */
void     Mpb_Led_Task(void);
uint16_t Mpb_Led_Get(uint8_t ch);                                        /* 現在の L* (×100) */
uint8_t  Mpb_Led_Busy(uint8_t ch);                                       /* フェード中 */

#endif /* MPB_LED_H */
