/*
 * config.h — このスケッチの設定 (protect: 熱・過電流・短絡で警報出力)
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
/* ハーフブリッジ (負荷: DC モーター OUT0–OUT1) */
#define CFG_PWM_HZ          20000u
#define CFG_DEAD_NS         500u
#define CFG_MAX_DUTY        900u
#define CFG_HW_BREAK        0
#define CFG_VBUS_MIN_MV     8000u

/* 警報出力: 異常で High。既定は PC5 (J1-5)。
 *   PC5 は VHV (≈ VBUS − 0.5V) で動く高電圧の出力 (High = 約 11.5V @12V 系)。リレー用トランジスタ・MOSFET の
 *   ゲート・PLC の 12/24V 入力・抵抗付き LED / ブザーを直接駆動できる (軽負荷)。3.3V / 5V のマイコンへは直結しない。
 *   3.3V で出したいときは GPIOA / GPIO_Pin_14 (J2-19, I2C を使わない場合) などに変える */
#define CFG_ALARM_PORT      GPIOC
#define CFG_ALARM_PIN       GPIO_Pin_5
#define CFG_ALARM_ACTIVE_LOW 0          /* 1: 異常で Low (フェイルセーフの配線にするとき) */
#define CFG_ALARM_LATCH     1           /* 1: 原因が消えてもボタンで解除するまで保持 */

/* しきい値 */
#define CFG_TEMP_TRIP_C10   850         /* 過熱 [0.1℃] (MOSFET 近くの NTC) */
#define CFG_TEMP_CLEAR_C10  700         /* 解除 [0.1℃] */
#define CFG_I_TRIP_MA       4000u       /* 持続する過電流 [mA] */
#define CFG_I_TRIP_MS       50u         /* その時間 [ms] 続いたら異常 */
#define CFG_SHORT_LEG_MA    8000u       /* 短絡 (瞬時): HB0 レッグ, CMP2 + DAC でハード検出 [mA] */
#define CFG_VBUS_MAX_MV     16500u      /* 過電圧 [mV] (子基板 B は 26000 程度) */
#define CFG_VBUS_UV_MV      7000u       /* 低電圧 [mV] (0 = 見ない) */
#define CFG_NTC_FAULT_ALARM 1           /* NTC の断線・短絡も異常とする */

/* 操作 */
#define CFG_DUTY_PER_CLICK  20          /* エンコーダ 1 クリックの duty [‰] */
#define CFG_LOG_MS          500u

#endif /* CONFIG_H */
