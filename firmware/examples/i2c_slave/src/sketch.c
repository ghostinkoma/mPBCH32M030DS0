/*
 * サンプル: I2C スレーブ — モジュールを I2C の周辺機器として使う (アドレス 0x30)
 *
 * 配線: SDA → J2-19 (PA14), SCL → J2-18 (PA15), GND。プルアップはマスタ側か R114/R115。
 * レジスタ (リトルエンディアン):
 *   0x00      R   WHO_AM_I = 0x4D
 *   0x01      R   状態 (bit0 = USB-PD 給電中)
 *   0x02-0x03 R   VBUS [mV]
 *   0x04-0x05 R   NTC 温度 [0.1℃] (符号付き, 未接続は 0x8000)
 *   0x06-0x09 R   起動からの ms
 *   0x10      RW  状態 LED: 0 = 消灯, 1 = 点灯, 2 = 点滅
 *   0x11      RW  点滅周期 [10ms]
 * 例 (Linux の i2c-tools): i2cget -y 1 0x30 0x00 → 0x4d / i2cset -y 1 0x30 0x10 2 / i2cget -y 1 0x30 0x02 w
 * 書き込みは割込みがレジスタへ写すだけで, loop が Mpb_I2cSlave_Written() で受け取って反映する。
 */
#include "mpbfun.h"

#define REG_WHO     0x00
#define REG_STAT    0x01
#define REG_VBUS    0x02
#define REG_NTC     0x04
#define REG_MS      0x06
#define REG_LEDMODE 0x10
#define REG_BLINK   0x11

static uint8_t s_regs[0x20];

static void led(uint8_t on)
{
    GPIO_WriteBit(MPB_LED_PORT, MPB_LED_PIN, on ? MPB_LED_ON : MPB_LED_OFF);
}

void setup(void)
{
    GPIO_InitTypeDef g = {0};

    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_Adc_Init();
    Mpb_Ntc_Init();
    RCC_PB2PeriphClockCmd(MPB_LED_RCC, ENABLE);
    g.GPIO_Pin = MPB_LED_PIN;
    g.GPIO_Mode = GPIO_Mode_Out_OD;
    g.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(MPB_LED_PORT, &g);

    s_regs[REG_WHO] = 0x4D;
    s_regs[REG_LEDMODE] = 2;
    s_regs[REG_BLINK] = 50;
    Mpb_I2cSlave_Init(0x30, s_regs, sizeof(s_regs));
    Mpb_I2cSlave_SetWritable(REG_LEDMODE, 2);          /* 0x10〜0x11 だけ書ける */
    MPB_LOGI("i2c_slave: address 0x30");
}

void loop(void)
{
    static uint8_t on;
    static uint32_t t_blink;
    uint8_t first, n;

    if (Mpb_I2cSlave_Written(&first, &n))
    {
        MPB_LOGI("master wrote reg 0x%02x..0x%02x: mode %u blink %u0 ms", first, first + n - 1, s_regs[REG_LEDMODE],
                 s_regs[REG_BLINK]);
    }
    /* LED */
    if (s_regs[REG_LEDMODE] == 2)
    {
        uint32_t per = (uint32_t)(s_regs[REG_BLINK] ? s_regs[REG_BLINK] : 1) * 10u;
        if (Mpb_Millis() - t_blink >= per)
        {
            t_blink = Mpb_Millis();
            on ^= 1;
        }
    }
    else
    {
        on = s_regs[REG_LEDMODE] ? 1 : 0;
    }
    led(on);
    /* 読み出し用の値を 100ms ごとに更新 (割込み禁止でまとめて写すので, 多バイト値が裂けない) */
    MPB_EVERY_MS(t_upd, 100)
    {
        uint16_t vbus = (uint16_t)Mpb_Vbus_mV();
        int32_t t = Mpb_Ntc_DeciCelsius();
        int16_t t16 = (t == INT32_MIN) ? (int16_t)0x8000 : (int16_t)t;
        uint32_t ms = Mpb_Millis();
        uint8_t st = Mpb_PD_Status()->power_enabled ? 1u : 0u;
        Mpb_I2cSlave_Update(REG_STAT, &st, 1);
        Mpb_I2cSlave_Update(REG_VBUS, &vbus, 2);
        Mpb_I2cSlave_Update(REG_NTC, &t16, 2);
        Mpb_I2cSlave_Update(REG_MS, &ms, 4);
    }
}
