/*
 * mpb_i2c_slave — I2C スレーブ (I2C1 リマップ2: SDA = PA14, SCL = PA15)。レジスタマップ方式
 *
 * マスタの書き込み: [レジスタ番号] [データ…] → regs[番号] から順に書く (末尾で 0 に戻る)
 * マスタの読み出し: 直前に書いたレジスタ番号から順に regs を返す (書き込み 1 バイト + リピートスタートで読む)
 * 送受信は割込みで行い, メインループは Mpb_I2cSlave_Written() で「書かれた範囲」を受け取って処理する
 * (TinyWetherMemo の i2c_slave と同じ考え方: ISR はバッファへ写すだけ, 処理は loop で)。
 *
 * 読み出し中に値が変わると多バイト値が裂けるので, 更新は Mpb_I2cSlave_Update() (割込み禁止でコピー) を使う。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_I2C_SLAVE_H
#define MPB_I2C_SLAVE_H

#include <stdint.h>

void     Mpb_I2cSlave_Init(uint8_t addr7, uint8_t *regs, uint8_t size);
void     Mpb_I2cSlave_SetWritable(uint8_t first, uint8_t count);   /* マスタが書ける範囲 (既定: 全部) */
uint8_t  Mpb_I2cSlave_Written(uint8_t *first, uint8_t *count);      /* 1 = 前回から書き込みがあった */
void     Mpb_I2cSlave_Update(uint8_t reg, const void *src, uint8_t n); /* regs への安全な書き込み */
uint32_t Mpb_I2cSlave_ReadCount(void);                              /* マスタの読み出し回数 */
uint32_t Mpb_I2cSlave_ErrorCount(void);

#endif /* MPB_I2C_SLAVE_H */
