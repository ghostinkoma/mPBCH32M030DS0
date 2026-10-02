/*
 * config.h — このスケッチの設定 (led_rgbw: RGBW 4ch LED (CIE 1931) — エンコーダ + WS2812 互換入力)
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
#define MPB_UART_BOOT       0       /* 1: UART (PC2) からの書き込み要求も受ける。PC2 を別の用途に使うときは 0 */
/* #define MPB_UART_BAUD    460800u */        /* UART の速度 (ログと書き込み要求) */

/* ================================================================= ライブラリ ===== */
/* #define MPB_LOG_BUF      512u */           /* UART ログのリングバッファ [バイト] (2 のべき乗) */
/* #define MPB_WS2812_MAX   32u */            /* WS2812 の最大個数 (RAM 4 バイト/個) */
/* #define MPB_DEBUG */                       /* MPB_LOGD() を有効にする */
/* #define MPB_WDT_MS       200u */           /* ウォッチドッグ: loop() がこれ以上戻らなければ全 FET OFF → リセット [ms] (0 = 無効, デバッグ時のみ) */

/* ============================================================== このスケッチ ===== */
/* ---- 出力 (パワー段のローサイドで LED テープを駆動) ----------------------------------------
 * LED テープ (12V/24V, RGBW 共通アノード) の + を VBUS, R/G/B/W の − を OUT0〜OUT3 へ。
 * 1ch あたりの電流は子基板の容量まで (A: 約 5A, はんだ盛りなし 4A)。 */
#define CFG_PWM_HZ          2000u       /* PWM 周波数: 2kHz で分解能 1/18000 (暗部までなめらか)。ちらつきが気になれば 4000 */
#define CFG_DEAD_NS         500u
#define CFG_MAX_DUTY        900u        /* (ローサイドだけの PWM には効かない: 0〜100% 使える) */
#define CFG_HW_BREAK        0
#define CFG_CHANNELS        4u          /* 4 = RGBW, 3 = RGB */
#define CFG_LEG_R           0u          /* 各色の出力 (OUT0〜3) */
#define CFG_LEG_G           1u
#define CFG_LEG_B           2u
#define CFG_LEG_W           3u

/* ---- 調光 (Ch32LightBox と同じ考え方: CIE 1931 L* で 1 クリック = 目に等量の変化) ---------- */
#define CFG_LEVELS          64u         /* 明るさの段数 (0 = 消灯 〜 CFG_LEVELS = 最大) */
#define CFG_LEVEL_INIT      32u         /* 起動時の段 */
#define CFG_SOFT_MS         600u        /* 点灯 / 消灯 / 起動のフェード [ms] (0 = 即時) */
#define CFG_STEP_FADE_MS    80u         /* 1 クリックごとのフェード [ms] */
#define CFG_HUE_STEP        6u          /* 色相モードの 1 クリック [°] */
#define CFG_SAT_STEP        50u         /* 彩度モードの 1 クリック [‰] */
#define CFG_WHITE_STEP      50u         /* 白混合モードの 1 クリック [‰] */
#define CFG_HUE_INIT        30u         /* 起動時の色: 電球色寄り */
#define CFG_SAT_INIT        300u
#define CFG_WHITE_INIT      1000u       /* RGBW: 彩度が低いとき白 LED をどれだけ足すか [‰] */

/* ---- エンコーダ (HALL_A_IN / HALL_C_IN, JP2/JP4 = 2-3, 押し = PC4) ---------------------------- */
#define CFG_ENC_REVERSE     0           /* 1: 回転方向を逆にする */
#define CFG_ACCEL_MS        50u         /* 前のクリックからこれ未満なら加速 */
#define CFG_ACCEL_FACTOR    3           /* 加速時の倍率 */
#define CFG_SNAP_MS         500u        /* この時間内に… */
#define CFG_SNAP_CLICKS     6u          /* 同じ向きにこの回数回したら 100% / 消灯へ (勢い回し) */

/* ---- WS2812 互換入力 (この基板を 1 画素として数珠つなぎに入れる) ------------------------------
 * DIN = PC2 (J2-2) なので MPB_UART_BOOT は 0 にしてある (書き込みは USB-C)。DOUT = PA14 (J2-19)。 */
#define CFG_WSRX_ENABLE     1
#define CFG_WSRX_BYTES      4u          /* 4 = SK6812 RGBW (GRBW), 3 = WS2812 (GRB) */
#define CFG_WSRX_T1_NS      500u        /* 1 と判定する High の幅 [ns] */
#define CFG_WSRX_CONFIRM    1           /* 同じ値が 2 回続いたら反映 (ノイズ対策) */
#define CFG_WSRX_DOUT       1           /* 1: 残りのデータを DOUT (PA14) へ中継 */
#define CFG_WSRX_POLL_US    2000u       /* 1 回の loop で DIN を見張る時間 [µs] */
#define CFG_WSRX_HOLD_MS    3000u       /* 最後の受信からこの時間はエンコーダの色より WS2812 入力を優先 */
#define CFG_LOG_MS          1000u

#endif /* CONFIG_H */
