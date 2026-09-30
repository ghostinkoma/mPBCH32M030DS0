/*
 * mpb_encoder — ロータリーエンコーダ (2 相, 機械式 / 光学式) + 押しボタン
 *
 * 既定の端子: A = PA5 (HALL_A_IN, J1-14, JP2=2-3), B = PA6 (HALL_C_IN, J1-16, JP4=2-3)。
 *   ホール入力には 4.7k プルアップ + 1k/1nF の RC があるので, 機械式エンコーダをそのままつなげる。
 *   ボタン: PC4 (USER ボタン SW2 と共用, 押すと Low)。
 * どの GPIO でも使える (EXTI の両エッジ割込みで状態表をたどる 4 逓倍デコード。チャタリングの往復は打ち消し合う)。
 * 3 相モーターをホールセンサで回すときは PA5〜PA7 がふさがるので, 他の端子を使うこと。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_ENCODER_H
#define MPB_ENCODER_H

#include <stdint.h>
#include "mpb.h"

/* NULL / 0 で既定の端子。steps_per_detent: クリック 1 つあたりの 4 逓倍カウント (多くの機械式は 4) */
void    Mpb_Enc_Init(GPIO_TypeDef *pa, uint16_t pina, GPIO_TypeDef *pb, uint16_t pinb, uint8_t steps_per_detent);
int32_t Mpb_Enc_Count(void);            /* クリック数 (累計, 符号付き) */
int32_t Mpb_Enc_Delta(void);            /* 前回呼んでからのクリック数 */
void    Mpb_Enc_SetCount(int32_t c);
void    Mpb_Enc_Reverse(uint8_t on);    /* 向きを反転 */

/* ボタン (Low = 押下, 20ms のデバウンス)。NULL / 0 で PC4 */
void    Mpb_Enc_ButtonInit(GPIO_TypeDef *port, uint16_t pin);
void    Mpb_Enc_Task(void);             /* loop から毎回 (ボタンのデバウンス) */
uint8_t Mpb_Enc_Pressed(void);          /* 押した瞬間 1 回だけ 1 */
uint8_t Mpb_Enc_LongPressed(void);      /* 1 秒押し続けたら 1 回だけ 1 */
uint8_t Mpb_Enc_Down(void);             /* 押されている */

#endif /* MPB_ENCODER_H */
