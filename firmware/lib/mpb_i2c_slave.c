/*
 * mpb_i2c_slave — I2C スレーブ (レジスタマップ, 割込み駆動)
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include <string.h>
#include "mpb_i2c_slave.h"
#include "mpb.h"

static uint8_t *s_regs;
static uint8_t  s_size;
static uint8_t  s_wfirst, s_wlast = 0xFF;          /* 書き込み可能な範囲 */
static volatile uint8_t s_ptr;
static volatile uint8_t s_first_byte;              /* 1 = 次の受信バイトはレジスタ番号 */
static volatile uint8_t s_dirty, s_dmin = 0xFF, s_dmax;
static volatile uint32_t s_reads, s_errs;

void I2C1_EV_IRQHandler(void) MPB_IRQ;
void I2C1_ER_IRQHandler(void) MPB_IRQ;

void Mpb_I2cSlave_Init(uint8_t addr7, uint8_t *regs, uint8_t size)
{
    GPIO_InitTypeDef g = {0};
    I2C_InitTypeDef i = {0};

    s_regs = regs;
    s_size = size;
    s_wfirst = 0;
    s_wlast = (uint8_t)(size - 1u);
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA | RCC_PB2Periph_AFIO, ENABLE);
    RCC_PB1PeriphClockCmd(RCC_PB1Periph_I2C1, ENABLE);
    GPIO_PinRemapConfig(GPIO_PartialRemap2_I2C1, ENABLE);
    g.GPIO_Pin = GPIO_Pin_14 | GPIO_Pin_15;
    g.GPIO_Mode = GPIO_Mode_AF_OD;
    g.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(GPIOA, &g);

    I2C_DeInit(I2C1);
    i.I2C_ClockSpeed = 400000;               /* スレーブでは使われないが FREQ の設定に必要 */
    i.I2C_Mode = I2C_Mode_I2C;
    i.I2C_DutyCycle = I2C_DutyCycle_2;
    i.I2C_OwnAddress1 = (uint16_t)(addr7 << 1);
    i.I2C_Ack = I2C_Ack_Enable;
    i.I2C_AcknowledgedAddress = I2C_AcknowledgedAddress_7bit;
    I2C_Init(I2C1, &i);
    I2C_ITConfig(I2C1, I2C_IT_EVT | I2C_IT_BUF | I2C_IT_ERR, ENABLE);
    NVIC_EnableIRQ(I2C1_EV_IRQn);
    NVIC_EnableIRQ(I2C1_ER_IRQn);
    I2C_Cmd(I2C1, ENABLE);
    I2C_AcknowledgeConfig(I2C1, ENABLE);
}

void Mpb_I2cSlave_SetWritable(uint8_t first, uint8_t count)
{
    s_wfirst = first;
    s_wlast = (uint8_t)(first + count - 1u);
}

uint8_t Mpb_I2cSlave_Written(uint8_t *first, uint8_t *count)
{
    uint8_t d;

    __disable_irq();
    d = s_dirty;
    if (d)
    {
        if (first) *first = s_dmin;
        if (count) *count = (uint8_t)(s_dmax - s_dmin + 1u);
        s_dirty = 0;
        s_dmin = 0xFF;
        s_dmax = 0;
    }
    __enable_irq();
    return d;
}

void Mpb_I2cSlave_Update(uint8_t reg, const void *src, uint8_t n)
{
    if ((uint16_t)reg + n > s_size) return;
    __disable_irq();
    memcpy(&s_regs[reg], src, n);
    __enable_irq();
}

uint32_t Mpb_I2cSlave_ReadCount(void) { return s_reads; }
uint32_t Mpb_I2cSlave_ErrorCount(void) { return s_errs; }

void I2C1_EV_IRQHandler(void)
{
    uint16_t sr1 = I2C1->STAR1;

    if (sr1 & I2C_STAR1_ADDR)
    {
        uint16_t sr2 = I2C1->STAR2;              /* STAR1 → STAR2 の順に読むと ADDR が消える */
        if (sr2 & I2C_STAR2_TRA)
        {
            s_reads++;                            /* 読み出し開始: 現在のポインタから送る */
        }
        else
        {
            s_first_byte = 1;
        }
    }
    if (sr1 & I2C_STAR1_RXNE)
    {
        uint8_t b = (uint8_t)I2C1->DATAR;
        if (s_first_byte)
        {
            s_ptr = (b < s_size) ? b : 0;
            s_first_byte = 0;
        }
        else
        {
            uint8_t p = s_ptr;
            if (p >= s_wfirst && p <= s_wlast)
            {
                s_regs[p] = b;
                if (p < s_dmin) s_dmin = p;
                if (p > s_dmax) s_dmax = p;
                s_dirty = 1;
            }
            s_ptr = (uint8_t)((p + 1u) < s_size ? p + 1u : 0u);
        }
    }
    if (sr1 & I2C_STAR1_TXE)
    {
        uint8_t p = s_ptr;
        I2C1->DATAR = s_regs[p];
        s_ptr = (uint8_t)((p + 1u) < s_size ? p + 1u : 0u);
    }
    if (sr1 & I2C_STAR1_STOPF)
    {
        I2C1->CTLR1 |= I2C_CTLR1_PE;              /* STAR1 を読んだ後 CTLR1 に書くと STOPF が消える */
    }
}

void I2C1_ER_IRQHandler(void)
{
    uint16_t sr1 = I2C1->STAR1;

    if (sr1 & I2C_STAR1_AF)
    {
        /* 読み出しの最後にマスタが NACK するのは正常 (送り過ぎた 1 バイト分ポインタを戻す) */
        s_ptr = (uint8_t)(s_ptr ? s_ptr - 1u : s_size - 1u);
        I2C1->STAR1 = (uint16_t)~I2C_STAR1_AF;
    }
    if (sr1 & (I2C_STAR1_BERR | I2C_STAR1_ARLO | I2C_STAR1_OVR))
    {
        s_errs++;
        I2C1->STAR1 = (uint16_t)~(I2C_STAR1_BERR | I2C_STAR1_ARLO | I2C_STAR1_OVR);
    }
}
