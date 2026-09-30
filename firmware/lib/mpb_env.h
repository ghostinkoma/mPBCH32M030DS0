/*
 * mpb_env — I2C 環境センサ (温度・湿度・気圧) の共通インタフェース (待ちなし)
 *
 *   MPB_ENV_SHT3X   Sensirion SHT30/31/35  (0x44 / 0x45)  温度・湿度
 *   MPB_ENV_AHT20   Aosong AHT20/AHT21/AHT10 (0x38)       温度・湿度
 *   MPB_ENV_BMX280  Bosch BMP280 / BME280 (0x76 / 0x77)   温度・気圧 (+ 湿度: BME280 は自動判別)
 *   MPB_ENV_S5851A  ABLIC S-5851A (0x48〜0x4F)            温度
 * ghostinkoma/TinyWetherMemo の host_esp32c3 (Arduino + Adafruit ライブラリ, ブロッキング) と同じ種類を,
 * データシートの手順どおり C のステートマシンに書き直したもの。変換待ちは時刻の比較で行う。
 *
 *   Mpb_Env sht;
 *   Mpb_I2c_Init(100000);
 *   Mpb_Env_Init(&sht, MPB_ENV_SHT3X, 0x44);
 *   loop: Mpb_I2c_Task(); if (Mpb_Env_Task(&sht)) { sht.r.t_c100 … }   // 周期は period_ms (既定 1000)
 *
 * 複数のセンサを同じバスに置ける (I2C が空くまで順番に待つ)。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_ENV_H
#define MPB_ENV_H

#include <stdint.h>
#include "mpb_i2c.h"

typedef enum { MPB_ENV_SHT3X = 0, MPB_ENV_AHT20, MPB_ENV_BMX280, MPB_ENV_S5851A } Mpb_EnvType;

#define MPB_ENV_CAP_T  0x01u
#define MPB_ENV_CAP_H  0x02u
#define MPB_ENV_CAP_P  0x04u

typedef struct {
    uint8_t  ok;          /* 1 = 直近の測定が成功 */
    uint8_t  caps;        /* 有効な量 (MPB_ENV_CAP_*) */
    int16_t  t_c100;      /* 温度 [0.01℃] */
    uint16_t rh_100;      /* 相対湿度 [0.01%] */
    uint32_t p_pa;        /* 気圧 [Pa] (hPa × 100) */
} Mpb_EnvReading;

typedef struct {
    Mpb_EnvType type;
    uint8_t  addr, state, present, is_bme, errors;
    uint16_t period_ms;
    uint32_t t_next, t_wait;
    uint8_t  cmd[4], buf[26];
    /* BMP280 / BME280 の補正係数 */
    uint16_t T1; int16_t T2, T3;
    uint16_t P1; int16_t P2, P3, P4, P5, P6, P7, P8, P9;
    uint8_t  H1, H3; int16_t H2, H4, H5; int8_t H6;
    Mpb_EnvReading r;
} Mpb_Env;

void        Mpb_Env_Init(Mpb_Env *e, Mpb_EnvType type, uint8_t addr);   /* addr 0 = 既定 */
void        Mpb_Env_SetPeriod(Mpb_Env *e, uint16_t ms);                 /* 測定周期 (既定 1000ms) */
uint8_t     Mpb_Env_Task(Mpb_Env *e);        /* 新しい測定値が出た回だけ 1 (失敗も 1, r.ok で判定) */
const char *Mpb_Env_Name(const Mpb_Env *e);

#endif /* MPB_ENV_H */
