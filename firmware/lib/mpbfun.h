/*
 * mpbfun.h — mPBCH32M030DS0 のライブラリ一式 (スケッチはこれ 1 つを include すればよい)
 *
 *   core (常にリンク)   : mpb.h — 時間 (µs/ms), ADC, 電流アンプ, 過電流, ホール/BEMF/タコ, NTC, USB-PD
 *   lib  (使った物だけ) : 以下
 * どの関数も待たない (delay を使わない)。loop() で各 *_Task() を毎回呼ぶ。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPBFUN_H
#define MPBFUN_H

#include "mpb.h"            /* core */
#include "mpb_bridge.h"     /* ハーフブリッジ PWM + PWM 同期の電流 */
#include "mpb_dc.h"         /* DC モーター */
#include "mpb_stepper.h"    /* ステッピングモーター */
#include "mpb_bldc.h"       /* 3 相ブラシレス (6 ステップ) */
#include "mpb_led.h"        /* パワー段で LED を CIE 調光 */
#include "mpb_cie.h"        /* CIE 1931 L* */
#include "mpb_ws2812.h"     /* WS2812B / SK6812 */
#include "mpb_encoder.h"    /* ロータリーエンコーダ + ボタン */
#include "mpb_i2c.h"        /* I2C マスタ */
#include "mpb_i2c_slave.h"  /* I2C スレーブ */
#include "mpb_env.h"        /* I2C 環境センサ */
#include "mpb_log.h"        /* UART ログ */

/* 周期実行の小道具: MPB_EVERY_MS(t, 100) { … } は 100ms ごとに 1 回だけ中を実行する */
#define MPB_EVERY_MS(var, ms) static uint32_t var; if ((uint32_t)(Mpb_Millis() - var) >= (ms) && ((var = Mpb_Millis()), 1))

#endif /* MPBFUN_H */
