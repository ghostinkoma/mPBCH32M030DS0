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

#ifdef __cplusplus
extern "C" {            /* Arduino (C++) のスケッチからも使えるように */
#endif

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
#include "mpb_guard.h"      /* 保護: 熱・過電流・短絡で警報出力 */
#include "mpb_rgbw.h"       /* RGBW 4ch LED (CIE) */
#include "mpb_wsrx.h"       /* WS2812 互換の受信 (1 画素 + 中継) */
#include "mpb_font5x7.h"    /* 5×7 フォント */
#include "mpb_oled.h"       /* I2C OLED (SSD1306 / SH1106) */
#include "mpb_matrix.h"     /* 8×8 マトリクスの数珠つなぎ用の描画バッファ */
#include "mpb_ht16k33.h"    /* HT16K33 8×8 マトリクス (I2C, 8 枚まで) */
#include "mpb_tm1640.h"     /* TM1640 2 色 8×8 マトリクス (SCLK 共有 + DIN 個別) */

/* 周期実行の小道具: MPB_EVERY_MS(t, 100) { … } は 100ms ごとに 1 回だけ中を実行する */
#define MPB_EVERY_MS(var, ms) static uint32_t var; if ((uint32_t)(Mpb_Millis() - var) >= (ms) && ((var = Mpb_Millis()), 1))

#ifdef __cplusplus
}
#endif

#endif /* MPBFUN_H */
