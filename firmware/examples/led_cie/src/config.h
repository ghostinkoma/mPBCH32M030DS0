/*
 * config.h — このスケッチの設定 (led_cie: LED の CIE 調光 (1ch))
 *
 * ・core / lib / SDK を含む全ソースの先頭で読み込まれる (common/rules.mk が -include する)。
 *   ここで決めた値はライブラリにも効く (例: MPB_LOG_BUF, MPB_UART_BOOT)。
 * ・#define だけを書くこと (変数や関数を書くと全ファイルに複製されてリンクエラーになる)。
 * ・新しいスケッチは  python3 tools/new_sketch.py <ディレクトリ>  で作る。この雛形と同じ形になる。
 * ・値を変えたら make で全部作り直される (config.h に依存)。
 */
#ifndef CONFIG_H
#define CONFIG_H

/* ===================================================================== ボード ===== */
#ifndef MPB_POWER_STAGE
#define MPB_POWER_STAGE     'A'     /* 子基板: 'A' 12V 系 / 'B' 24V 系 / 'C' 廉価版 (make POWER_STAGE=B で一時的に上書き) */
#endif
#define MPB_UART_BOOT       1       /* 1: UART (PC2) からの書き込み要求も受ける。PC2 を別の用途に使うときは 0 */
/* #define MPB_UART_BAUD    460800u */        /* UART の速度 (ログと書き込み要求) */

/* ================================================================= ライブラリ ===== */
/* #define MPB_LOG_BUF      512u */           /* UART ログのリングバッファ [バイト] (2 のべき乗) */
/* #define MPB_WS2812_MAX   32u */            /* WS2812 の最大個数 (RAM 4 バイト/個) */
/* #define MPB_DEBUG */                       /* MPB_LOGD() を有効にする */
/* #define MPB_WDT_MS       200u */           /* ウォッチドッグ: loop() がこれ以上戻らなければ全 FET OFF → リセット [ms] (0 = 無効, デバッグ時のみ) */

/* ============================================================== このスケッチ ===== */
/* ハーフブリッジ (mpb_bridge) */
#define CFG_PWM_HZ          2000u      /* PWM 周波数 [Hz]: LED は 2kHz で分解能 1/18000 */
#define CFG_DEAD_NS         500u        /* デッドタイム [ns] (TIM2 は最大 880) */
#define CFG_MAX_DUTY        900u        /* duty 上限 [‰] (ブートストラップと電流の取り込みのため 100% にしない) */
#define CFG_HW_BREAK        0           /* 1: TIM1 BKIN のハード遮断も使う (PA15 = I2C SCL を使わないときだけ) */
#define CFG_VBUS_MIN_MV     8000u       /* これ未満ではモーターを回さない [mV] */

#define CFG_LED_LEG         0u          /* LED の − をつなぐ出力 (0 = OUT0) */
#define CFG_LEVEL_STEP      200         /* エンコーダ 1 クリックの明るさ [L* ×100] */
#define CFG_FADE_MS         300u
#define CFG_BREATHE_MS      4000u

#endif /* CONFIG_H */
