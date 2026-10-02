/*
 * config.h — このスケッチの設定 (rtos_motor_display: FreeRTOS — モーターを回しながら OLED / HT16K33 ×4 / TM1640 ×4 に表示)
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

/* ============================================================== このスケッチ ===== */
/* ---- FreeRTOS のタスク (スタックは 4 バイト単位の「語」。合計 RAM 12KB: 現在 約 9KB 使用) ---------------------------
 * 優先度: モーター 4 > TM1640 3 > 監視 2 > I2C 表示 1 (I2C は待ちの間も回し続けるので一番低くする)。
 * I2C の OLED と HT16K33 は同じバスなので必ず同じタスクから触る (mpb_i2c はタスク間で排他しない)。 */
#define CFG_STACK_MOTOR     256u        /* [語] */
#define CFG_STACK_I2C       352u
#define CFG_STACK_TM1640    224u
#define CFG_STACK_MONITOR   320u

/* ---- ハーフブリッジ + ステッピングモーター (examples/stepper と同じ。モーターの例は stepper の config.h) ---- */
#define CFG_PWM_HZ          20000u
#define CFG_DEAD_NS         500u
#define CFG_MAX_DUTY        900u
#define CFG_HW_BREAK        0           /* PA15 = I2C SCL なので BKIN は使わない */
#define CFG_VBUS_MIN_MV     8000u
#define CFG_STEPS_PER_REV   200u
#define CFG_MICROSTEP       16u         /* 1 ティック (1ms) に複数のマイクロステップを進めるので 1/16 程度が目安 */
#define CFG_COIL_MA         800u
#define CFG_COIL_R_MOHM     2800u
#define CFG_ACCEL           40000u
#define CFG_HOLD_PCT        40u
#define CFG_HOLD_MS         500u
/* 自動運転: CFG_PROFILE の rpm を CFG_PROFILE_MS ごとに順に切り替える (正転 → 停止 → 逆転 …) */
#define CFG_PROFILE         {60, 120, 240, 0, -120, -60, 0}
#define CFG_PROFILE_MS      4000u
#define CFG_RPM_MAX         240         /* OLED のバーの 100% */

/* ---- I2C 表示 (SDA = PA14 / J2-19, SCL = PA15 / J2-18, 4.7k プルアップ R114/R115 を実装) ---------------- */
#define CFG_I2C_HZ          400000u
#define CFG_OLED_ADDR       0x3C        /* SSD1306 / SH1106 の 7 ビットアドレス (0x3C / 0x3D) */
#define CFG_OLED_HEIGHT     64u         /* 64 / 32 */
#define CFG_OLED_TYPE       MPB_OLED_SSD1306      /* 1.3 インチは MPB_OLED_SH1106 が多い */
#define CFG_HT_ADDR         0x70        /* HT16K33 の先頭アドレス (0x70, 0x71, … と連番に) */
#define CFG_HT_COUNT        4u          /* 枚数 (1〜8) */
#define CFG_HT_MAP          MPB_HT_ADAFRUIT       /* LED の配線: MPB_HT_PLAIN / MPB_HT_ADAFRUIT / MPB_HT_BICOLOR (| FLIPX …) */
#define CFG_HT_BRIGHT       6u          /* 0〜15 */

/* ---- TM1640 2 色マトリクス (SCLK = PA5, DIN = PA6 / PA7 / PC2 / PC4) ----------------------------------
 * JP2〜JP4 = 2-3 (ホール入力を外部端子に)。PC2 を使うので MPB_UART_BOOT は 0 (書き込みは USB-C)。 */
#define CFG_TM_COUNT        4u          /* 枚数 (既定の端子は 4 枚まで) */
#define CFG_TM_DUTY         2u          /* 明るさ 0〜7 */
#define CFG_TM_HALF_US      2u          /* クロックの半周期 [µs] */
#define CFG_SCROLL_MS       35u         /* 流れる文字の速さ [ms/ドット] */

#define CFG_LOG_MS          1000u

#endif /* CONFIG_H */
