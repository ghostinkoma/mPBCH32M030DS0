/*
 * mpb_i2c — I2C マスタ (ポーリングのステートマシン)
 * 読み出しの手順は RM (STM32F1 互換の I2C) の 1 / 2 / N バイト受信の手順どおり:
 * どの待ちでもハードが SCL を Low に保つので, 1 手ずつ遅れて進めても安全。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_i2c.h"
#include "mpb.h"

enum { S_IDLE, S_SB, S_ADDRW, S_TX, S_TXBTF, S_SB2, S_ADDRR, S_RX1, S_RX2, S_RXN, S_RXLAST, S_STOP };

static uint8_t  s_state = S_IDLE, s_addr, s_ntx, s_nrx, s_i;
static const uint8_t *s_tx;
static uint8_t *s_rx;
static Mpb_I2cResult s_res = MPB_I2C_OK;
static uint8_t  s_done;
static uint32_t s_t0;
static uint16_t s_tmo = 20;
static uint32_t s_hz = 100000;

#define SR1   (I2C1->STAR1)
#define CR1   (I2C1->CTLR1)

static void pins_af(void)
{
    GPIO_InitTypeDef g = {0};

    g.GPIO_Pin = GPIO_Pin_14 | GPIO_Pin_15;
    g.GPIO_Mode = GPIO_Mode_AF_OD;
    g.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(GPIOA, &g);
}

static void hw_init(void)
{
    I2C_InitTypeDef i = {0};

    I2C_DeInit(I2C1);
    i.I2C_ClockSpeed = s_hz;
    i.I2C_Mode = I2C_Mode_I2C;
    i.I2C_DutyCycle = I2C_DutyCycle_2;
    i.I2C_OwnAddress1 = 0;
    i.I2C_Ack = I2C_Ack_Enable;
    i.I2C_AcknowledgedAddress = I2C_AcknowledgedAddress_7bit;
    I2C_Init(I2C1, &i);
    I2C_Cmd(I2C1, ENABLE);
}

void Mpb_I2c_Init(uint32_t hz)
{
    s_hz = hz ? hz : 100000u;
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA | RCC_PB2Periph_AFIO, ENABLE);
    RCC_PB1PeriphClockCmd(RCC_PB1Periph_I2C1, ENABLE);
    GPIO_PinRemapConfig(GPIO_PartialRemap2_I2C1, ENABLE);    /* SDA = PA14, SCL = PA15 */
    pins_af();
    hw_init();
    s_state = S_IDLE;
}

void Mpb_I2c_SetTimeoutMs(uint16_t ms) { s_tmo = ms ? ms : 1; }

void Mpb_I2c_Recover(void)
{
    GPIO_InitTypeDef g = {0};
    uint32_t t;

    I2C_Cmd(I2C1, DISABLE);
    g.GPIO_Pin = GPIO_Pin_14 | GPIO_Pin_15;
    g.GPIO_Mode = GPIO_Mode_Out_OD;
    g.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_SetBits(GPIOA, GPIO_Pin_14 | GPIO_Pin_15);
    GPIO_Init(GPIOA, &g);
    /* スレーブが SDA を離すまで SCL を最大 9 回 (≈ 50kHz)。ここだけは短い待ち (異常時のみ, 約 0.2ms) */
    for (uint8_t k = 0; k < 9 && !GPIO_ReadInputDataBit(GPIOA, GPIO_Pin_14); k++)
    {
        GPIO_ResetBits(GPIOA, GPIO_Pin_15);
        t = Mpb_Micros(); while (Mpb_Micros() - t < 10u) {}
        GPIO_SetBits(GPIOA, GPIO_Pin_15);
        t = Mpb_Micros(); while (Mpb_Micros() - t < 10u) {}
    }
    /* STOP 条件: SCL High のまま SDA を Low → High */
    GPIO_ResetBits(GPIOA, GPIO_Pin_14);
    t = Mpb_Micros(); while (Mpb_Micros() - t < 10u) {}
    GPIO_SetBits(GPIOA, GPIO_Pin_14);
    pins_af();
    CR1 |= I2C_CTLR1_SWRST;
    CR1 &= (uint16_t)~I2C_CTLR1_SWRST;
    hw_init();
}

uint8_t Mpb_I2c_Start(uint8_t addr7, const uint8_t *tx, uint8_t ntx, uint8_t *rx, uint8_t nrx)
{
    if (s_state != S_IDLE || (ntx == 0 && nrx == 0))
    {
        return 0;
    }
    s_addr = (uint8_t)(addr7 << 1);
    s_tx = tx;
    s_ntx = ntx;
    s_rx = rx;
    s_nrx = nrx;
    s_i = 0;
    s_done = 0;
    s_res = MPB_I2C_BUSY;
    s_t0 = Mpb_Millis();
    CR1 &= (uint16_t)~I2C_CTLR1_POS;
    CR1 |= I2C_CTLR1_ACK | I2C_CTLR1_START;
    s_state = S_SB;
    return 1;
}

uint8_t Mpb_I2c_Busy(void) { return s_state != S_IDLE; }
Mpb_I2cResult Mpb_I2c_Result(void) { s_done = 0; return s_res; }

uint8_t Mpb_I2c_Done(void)
{
    Mpb_I2c_Task();
    return s_done;
}

static void finish(Mpb_I2cResult r)
{
    s_res = r;
    s_done = 1;
    s_state = S_IDLE;
}

static void clear_addr(void)
{
    volatile uint16_t d = I2C1->STAR1;
    d = I2C1->STAR2;
    (void)d;
}

void Mpb_I2c_Task(void)
{
    uint16_t sr;

    if (s_state == S_IDLE)
    {
        return;
    }
    sr = SR1;
    if (sr & (I2C_STAR1_BERR | I2C_STAR1_ARLO))
    {
        I2C1->STAR1 = 0;
        Mpb_I2c_Recover();
        finish(MPB_I2C_BUSERR);
        return;
    }
    if (sr & I2C_STAR1_AF)
    {
        I2C1->STAR1 = (uint16_t)~I2C_STAR1_AF;
        CR1 |= I2C_CTLR1_STOP;
        s_res = MPB_I2C_NACK;
        s_state = S_STOP;
        return;
    }
    if (Mpb_Millis() - s_t0 > s_tmo)
    {
        Mpb_I2c_Recover();
        finish(MPB_I2C_TIMEOUT);
        return;
    }

    switch (s_state)
    {
    case S_SB:                                    /* START 送出 → アドレス (書き込み or 読み出しのみ) */
        if (sr & I2C_STAR1_SB)
        {
            I2C1->DATAR = s_ntx ? s_addr : (uint8_t)(s_addr | 1u);
            s_state = s_ntx ? S_ADDRW : S_ADDRR;
        }
        break;
    case S_ADDRW:
        if (sr & I2C_STAR1_ADDR)
        {
            clear_addr();
            I2C1->DATAR = s_tx[0];
            s_i = 1;
            s_state = S_TX;
        }
        break;
    case S_TX:
        if (s_i < s_ntx)
        {
            if (sr & I2C_STAR1_TXE) I2C1->DATAR = s_tx[s_i++];
        }
        else if (sr & I2C_STAR1_BTF)
        {
            if (s_nrx)
            {
                CR1 |= I2C_CTLR1_START;           /* リピートスタート → 読み出し */
                s_state = S_SB2;
            }
            else
            {
                CR1 |= I2C_CTLR1_STOP;
                s_res = MPB_I2C_OK;
                s_state = S_STOP;
            }
        }
        break;
    case S_SB2:
        if (sr & I2C_STAR1_SB)
        {
            I2C1->DATAR = (uint8_t)(s_addr | 1u);
            s_state = S_ADDRR;
        }
        break;
    case S_ADDRR:
        if (sr & I2C_STAR1_ADDR)
        {
            s_i = 0;
            if (s_nrx == 1)
            {
                CR1 &= (uint16_t)~I2C_CTLR1_ACK;
                clear_addr();
                CR1 |= I2C_CTLR1_STOP;
                s_state = S_RX1;
            }
            else if (s_nrx == 2)
            {
                CR1 &= (uint16_t)~I2C_CTLR1_ACK;
                CR1 |= I2C_CTLR1_POS;
                clear_addr();
                s_state = S_RX2;
            }
            else
            {
                CR1 |= I2C_CTLR1_ACK;
                clear_addr();
                s_state = S_RXN;
            }
        }
        break;
    case S_RX1:
        if (sr & I2C_STAR1_RXNE)
        {
            s_rx[0] = (uint8_t)I2C1->DATAR;
            s_res = MPB_I2C_OK;
            s_state = S_STOP;
        }
        break;
    case S_RX2:
        if (sr & I2C_STAR1_BTF)
        {
            CR1 |= I2C_CTLR1_STOP;
            s_rx[0] = (uint8_t)I2C1->DATAR;
            s_rx[1] = (uint8_t)I2C1->DATAR;
            CR1 &= (uint16_t)~I2C_CTLR1_POS;
            s_res = MPB_I2C_OK;
            s_state = S_STOP;
        }
        break;
    case S_RXN:
        if (s_nrx - s_i > 3)
        {
            if (sr & I2C_STAR1_RXNE) s_rx[s_i++] = (uint8_t)I2C1->DATAR;
        }
        else if (sr & I2C_STAR1_BTF)              /* 残り 3: N-2 が DR, N-1 がシフトレジスタ */
        {
            CR1 &= (uint16_t)~I2C_CTLR1_ACK;
            s_rx[s_i++] = (uint8_t)I2C1->DATAR;
            CR1 |= I2C_CTLR1_STOP;
            s_rx[s_i++] = (uint8_t)I2C1->DATAR;
            s_state = S_RXLAST;
        }
        break;
    case S_RXLAST:
        if (sr & I2C_STAR1_RXNE)
        {
            s_rx[s_i++] = (uint8_t)I2C1->DATAR;
            s_res = MPB_I2C_OK;
            s_state = S_STOP;
        }
        break;
    case S_STOP:                                  /* STOP を出し終えるのを待つ */
        if (!(CR1 & I2C_CTLR1_STOP))
        {
            CR1 |= I2C_CTLR1_ACK;
            finish(s_res);
        }
        break;
    default:
        finish(MPB_I2C_BUSERR);
        break;
    }
}
