/*
 * mpb_ws2812 — WS2812B / SK6812
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_ws2812.h"
#include "mpb_cie.h"

static uint8_t  s_buf[MPB_WS2812_MAX * 4u];
static GPIO_TypeDef *s_port;
static uint16_t s_pin;
static uint8_t  s_n, s_bpp = 3;
static Mpb_WsOrder s_order;
static uint8_t  s_dirty;
static uint32_t s_last_us;

/* SysTick: bit0 STE (有効), bit2 STCLK (1 = HCLK) */
#define STK_EN_HCLK  ((1u << 0) | (1u << 2))

/* RAM 上で実行 (フラッシュのウェイトでタイミングが揺れないように)。割込み禁止で呼ぶこと */
__attribute__((section(".data.mpb_ws2812"), noinline))
static void ws_send(volatile uint32_t *bshr, volatile uint32_t *bcr, uint32_t mask,
                    const uint8_t *p, uint32_t n, uint32_t t0h, uint32_t t1h, uint32_t tbit)
{
    volatile uint32_t *cnt = &SysTick->CNT;
    uint32_t t = *cnt;

    while (n--)
    {
        uint32_t b = *p++;
        for (uint32_t k = 0; k < 8u; k++, b <<= 1)
        {
            uint32_t th = (b & 0x80u) ? t1h : t0h;
            while ((uint32_t)(*cnt - t) < tbit) {}     /* 前のビットの終わりまで Low */
            t = *cnt;
            *bshr = mask;                              /* High */
            while ((uint32_t)(*cnt - t) < th) {}
            *bcr = mask;                               /* Low */
        }
    }
    while ((uint32_t)(*cnt - t) < tbit) {}
}

void Mpb_Ws2812_Init(GPIO_TypeDef *port, uint16_t pin, uint8_t count, Mpb_WsOrder order)
{
    GPIO_InitTypeDef g = {0};

    s_port = port ? port : GPIOC;
    s_pin = pin ? pin : GPIO_Pin_2;
    s_n = count > MPB_WS2812_MAX ? (uint8_t)MPB_WS2812_MAX : count;
    s_order = order;
    s_bpp = (order == MPB_WS_GRBW || order == MPB_WS_RGBW) ? 4u : 3u;
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA | RCC_PB2Periph_GPIOB | RCC_PB2Periph_GPIOC, ENABLE);
    GPIO_ResetBits(s_port, s_pin);
    g.GPIO_Pin = s_pin;
    g.GPIO_Mode = GPIO_Mode_Out_PP;
    g.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(s_port, &g);
    for (uint32_t i = 0; i < sizeof(s_buf); i++) s_buf[i] = 0;
    s_dirty = 1;                                       /* 起動時に消灯を送る */
}

void Mpb_Ws2812_SetW(uint8_t i, uint8_t r, uint8_t g, uint8_t b, uint8_t w)
{
    uint8_t *p;

    if (i >= s_n) return;
    p = &s_buf[i * s_bpp];
    if (s_order == MPB_WS_RGB || s_order == MPB_WS_RGBW) { p[0] = r; p[1] = g; }
    else { p[0] = g; p[1] = r; }
    p[2] = b;
    if (s_bpp == 4u) p[3] = w;
}

void Mpb_Ws2812_Set(uint8_t i, uint8_t r, uint8_t g, uint8_t b) { Mpb_Ws2812_SetW(i, r, g, b, 0); }

void Mpb_Ws2812_Fill(uint8_t r, uint8_t g, uint8_t b)
{
    for (uint8_t i = 0; i < s_n; i++) Mpb_Ws2812_Set(i, r, g, b);
}

void Mpb_Ws2812_SetLevel(uint8_t i, uint32_t rgb, uint16_t lx100)
{
    Mpb_Ws2812_Set(i, (uint8_t)Mpb_Cie(lx100, (rgb >> 16) & 0xFFu), (uint8_t)Mpb_Cie(lx100, (rgb >> 8) & 0xFFu),
                   (uint8_t)Mpb_Cie(lx100, rgb & 0xFFu));
}

void Mpb_Ws2812_Hsv(uint8_t i, uint16_t hue, uint8_t sat, uint16_t lx100)
{
    uint32_t h = hue % 360u, f = (h % 60u) * 255u / 60u, v = 255u;
    uint32_t p = v * (255u - sat) / 255u, q = v * (255u - sat * f / 255u) / 255u;
    uint32_t t = v * (255u - sat * (255u - f) / 255u) / 255u, r, g, b;

    switch (h / 60u)
    {
    case 0: r = v; g = t; b = p; break;
    case 1: r = q; g = v; b = p; break;
    case 2: r = p; g = v; b = t; break;
    case 3: r = p; g = q; b = v; break;
    case 4: r = t; g = p; b = v; break;
    default: r = v; g = p; b = q; break;
    }
    Mpb_Ws2812_SetLevel(i, (r << 16) | (g << 8) | b, lx100);
}

void Mpb_Ws2812_Show(void) { s_dirty = 1; }
uint8_t Mpb_Ws2812_Count(void) { return s_n; }

void Mpb_Ws2812_Task(void)
{
    uint32_t now = Mpb_Micros(), ctl, mhz;

    if (!s_dirty || !s_port || now - s_last_us < 300u)   /* リセット (Low ≥ 280µs) を確保 */
    {
        return;
    }
    s_dirty = 0;
    mhz = SystemCoreClock / 1000000u;
    ctl = SysTick->CTLR;
    SysTick->CTLR = STK_EN_HCLK;                          /* 上り計数・HCLK (Delay_* は使うたびに設定し直す) */
    __disable_irq();
    /* T0H 0.35µs, T1H 0.70µs, 1 ビット 1.25µs */
    ws_send(&s_port->BSHR, &s_port->BCR, s_pin, s_buf, (uint32_t)s_n * s_bpp,
            mhz * 35u / 100u, mhz * 70u / 100u, mhz * 125u / 100u);
    __enable_irq();
    SysTick->CTLR = ctl;
    s_last_us = Mpb_Micros();
}
