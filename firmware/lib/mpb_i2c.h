/*
 * mpb_i2c — I2C マスタ (I2C1 リマップ2: SDA = PA14 / J2-19, SCL = PA15 / J2-18)
 *
 * プルアップはモジュールの R114/R115 (4.7k, 出荷時未実装) を実装するか, 外付けで入れる。
 * 転送は Mpb_I2c_Start() で予約し, Mpb_I2c_Task() (loop から毎回) が 1 手ずつ進める (割込みなし・待ちなし)。
 * 待っている間はハードがクロック (SCL) を Low に保つので, loop が遅くてもデータは壊れない (遅くなるだけ)。
 * 転送ごとにタイムアウト (既定 20ms) があり, 固まったら SWRST + SCL 9 回でバスを復旧する。
 *
 *   uint8_t reg = 0xFD, rx[6];
 *   Mpb_I2c_Start(0x44, &reg, 1, rx, 6);          // 書き込み 1 バイト → リピートスタート → 読み出し 6 バイト
 *   ... loop: if (Mpb_I2c_Done()) { if (Mpb_I2c_Result() == MPB_I2C_OK) 使う; }
 *
 * 複数のドライバで共有するときは, 自分が Start した転送だけ Done/Result で受け取ること
 * (受け取るまで次の Start は 0 を返す = 結果の取り違えが起きない)。
 * 【注意】TIM1 の BKIN 既定端子は PA15。モーターと併用するときは Mpb_BridgeCfg.hw_break = 0 にする。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_I2C_H
#define MPB_I2C_H

#include <stdint.h>

typedef enum {
    MPB_I2C_OK = 0,
    MPB_I2C_BUSY,         /* 転送中 */
    MPB_I2C_NACK,         /* アドレス / データに ACK が無い */
    MPB_I2C_TIMEOUT,      /* タイムアウト (バスを復旧済み) */
    MPB_I2C_BUSERR        /* バスエラー / アービトレーション負け */
} Mpb_I2cResult;

void     Mpb_I2c_Init(uint32_t hz);              /* 100000 / 400000 */
uint8_t  Mpb_I2c_Start(uint8_t addr7, const uint8_t *tx, uint8_t ntx, uint8_t *rx, uint8_t nrx);   /* 0 = 使用中 */
void     Mpb_I2c_Task(void);
uint8_t  Mpb_I2c_Busy(void);
uint8_t  Mpb_I2c_Done(void);                     /* 前回の転送が終わった (結果を読むと 0 に戻る) */
Mpb_I2cResult Mpb_I2c_Result(void);
void     Mpb_I2c_SetTimeoutMs(uint16_t ms);
void     Mpb_I2c_Recover(void);                  /* バス復旧 (SCL 9 パルス + STOP) */

/* 便利関数: 1 回の転送を予約する (結果は Done/Result で) */
static inline uint8_t Mpb_I2c_WriteReg(uint8_t a, const uint8_t *regdata, uint8_t n) { return Mpb_I2c_Start(a, regdata, n, 0, 0); }
static inline uint8_t Mpb_I2c_ReadReg(uint8_t a, const uint8_t *reg, uint8_t *rx, uint8_t n) { return Mpb_I2c_Start(a, reg, 1, rx, n); }

#endif /* MPB_I2C_H */
