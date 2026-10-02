/*
 * mpb_wsrx — WS2812B / SK6812 互換の受信 (デコード + 中継)
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include <string.h>
#include "mpb_wsrx.h"

#define STK_EN_HCLK  ((1u << 0) | (1u << 2))     /* SysTick: 有効, HCLK, 上り計数 */

typedef struct {
    volatile uint32_t *din;      /* INDR */
    uint32_t din_mask;
    volatile uint32_t *set, *clr;
    uint32_t dout_mask;          /* 0 = 中継しない */
    uint32_t nbits;
    uint32_t t1, tbit_max, tgap_max, tend;
} Rx;

static Rx s_rx;
static Mpb_WsRxCfg s_cfg;
static uint8_t  s_last[4], s_have_last, s_applied[4], s_have_applied;
static uint32_t s_frames, s_errors, s_last_ms;

/* 1 フレーム受信 (割込み禁止, RAM 上)。立ち上がりを見つけた直後に呼ぶ。0 = 失敗 */
__attribute__((section(".data.mpb_wsrx"), noinline))
static uint32_t rx_frame(const Rx *r, uint8_t *out, uint32_t t_rise)
{
    volatile uint32_t *cnt = &SysTick->CNT;
    volatile uint32_t *din = r->din;
    uint32_t m = r->din_mask, t, acc = 0;

    for (uint32_t i = 0; i < r->nbits; i++)
    {
        while (*din & m)                                   /* High の終わりを待つ */
        {
            if ((uint32_t)(*cnt - t_rise) > r->tbit_max) return 0;
        }
        t = *cnt;
        acc = (acc << 1) | ((uint32_t)(t - t_rise) > r->t1 ? 1u : 0u);
        if ((i & 7u) == 7u)
        {
            out[i >> 3] = (uint8_t)acc;
            acc = 0;
        }
        if (i + 1u == r->nbits)
        {
            break;
        }
        while (!(*din & m))                                /* 次のビットの立ち上がり */
        {
            if ((uint32_t)(*cnt - t) > r->tgap_max) return 0;   /* 自分の分の途中で切れた */
        }
        t_rise = *cnt;
    }
    /* 残りのデータを DOUT へ中継 (Low が tend 続いたらフレームの終わり) */
    if (r->dout_mask)
    {
        t = *cnt;
        for (;;)
        {
            if (*din & m)
            {
                *r->set = r->dout_mask;
                t = *cnt;
            }
            else
            {
                *r->clr = r->dout_mask;
                if ((uint32_t)(*cnt - t) > r->tend) break;
            }
        }
    }
    return 1;
}

void Mpb_WsRx_Init(const Mpb_WsRxCfg *cfg)
{
    GPIO_InitTypeDef g = {0};
    uint32_t mhz = SystemCoreClock / 1000000u;

    s_cfg = *cfg;
    if (!s_cfg.din_port) { s_cfg.din_port = GPIOC; s_cfg.din_pin = GPIO_Pin_2; }
    if (!s_cfg.dout_port) { s_cfg.dout_port = GPIOA; if (!s_cfg.dout_pin) s_cfg.dout_pin = 0; }
    if (s_cfg.bytes != 3u) s_cfg.bytes = 4u;
    if (!s_cfg.t1_ns) s_cfg.t1_ns = 500u;
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA | RCC_PB2Periph_GPIOB | RCC_PB2Periph_GPIOC, ENABLE);
    g.GPIO_Pin = s_cfg.din_pin;
    g.GPIO_Mode = GPIO_Mode_IPD;                  /* 未接続のとき Low (= 待機) */
    GPIO_Init(s_cfg.din_port, &g);
    if (s_cfg.dout_pin)
    {
        GPIO_ResetBits(s_cfg.dout_port, s_cfg.dout_pin);
        g.GPIO_Pin = s_cfg.dout_pin;
        g.GPIO_Mode = GPIO_Mode_Out_PP;
        g.GPIO_Speed = GPIO_Speed_30MHz;
        GPIO_Init(s_cfg.dout_port, &g);
    }
    s_rx.din = &s_cfg.din_port->INDR;
    s_rx.din_mask = s_cfg.din_pin;
    s_rx.set = &s_cfg.dout_port->BSHR;
    s_rx.clr = &s_cfg.dout_port->BCR;
    s_rx.dout_mask = s_cfg.dout_pin;
    s_rx.nbits = (uint32_t)s_cfg.bytes * 8u;
    s_rx.t1 = mhz * s_cfg.t1_ns / 1000u;
    s_rx.tbit_max = mhz * 3u;                     /* High が 3µs を超えたら異常 */
    s_rx.tgap_max = mhz * 8u;                     /* ビット間の Low が 8µs を超えたら途中で切れた */
    s_rx.tend = mhz * 20u;                        /* 中継: Low が 20µs 続いたらフレームの終わり */
    s_have_last = 0;
}

uint32_t Mpb_WsRx_Frames(void) { return s_frames; }
uint32_t Mpb_WsRx_Errors(void) { return s_errors; }
uint32_t Mpb_WsRx_LastMs(void) { return s_last_ms; }

uint8_t Mpb_WsRx_Poll(uint32_t max_us, uint8_t rgbw[4])
{
    volatile uint32_t *cnt = &SysTick->CNT;
    volatile uint32_t *din = s_rx.din;
    uint32_t m = s_rx.din_mask, ctl, t0, low_t = 0, low_ok = 0, now, prev, mhz = SystemCoreClock / 1000000u;
    uint32_t tmax = max_us * mhz, treset = 40u * mhz;
    uint8_t buf[4] = {0, 0, 0, 0}, got = 0;

    ctl = SysTick->CTLR;
    SysTick->CTLR = STK_EN_HCLK;
    t0 = prev = *cnt;
    for (;;)
    {
        now = *cnt;
        if ((uint32_t)(now - t0) > tmax)
        {
            break;
        }
        if (!(*din & m))
        {
            if (!low_ok) { low_ok = 1; low_t = now; }
            prev = now;
            continue;
        }
        /* High: 40µs 以上の Low の後ならフレームの先頭。立ち上がりは最後に Low を見た時刻との中点とする
         * (見張りの間隔が 1µs を超えた = 割込みが入ったときは時刻が不確かなので捨てる) */
        if (low_ok && (uint32_t)(now - low_t) >= treset && (uint32_t)(now - prev) < mhz)
        {
            uint32_t ok;
            __disable_irq();
            ok = rx_frame(&s_rx, buf, prev + (now - prev) / 2u);
            __enable_irq();
            if (ok) { got = 1; s_frames++; }
            else s_errors++;
            break;
        }
        low_ok = 0;                               /* フレームの途中に入った: 次のリセットを待つ */
    }
    SysTick->CTLR = ctl;
    if (!got)
    {
        return 0;
    }
    s_last_ms = Mpb_Millis();
    if (!s_last_ms) s_last_ms = 1;
    /* G R B (W) → R G B W */
    {
        uint8_t v[4] = {buf[1], buf[0], buf[2], s_cfg.bytes == 4u ? buf[3] : 0u};
        uint8_t same_last = s_have_last && !memcmp(v, s_last, 4);
        uint8_t same_applied = s_have_applied && !memcmp(v, s_applied, 4);
        memcpy(s_last, v, 4);
        s_have_last = 1;
        /* confirm: 同じ値が 2 回続いたら反映。どちらも, 反映済みと同じなら何もしない */
        if ((s_cfg.confirm && !same_last) || same_applied)
        {
            return 0;
        }
        memcpy(s_applied, v, 4);
        s_have_applied = 1;
        if (rgbw) memcpy(rgbw, v, 4);
        return 1;
    }
}
