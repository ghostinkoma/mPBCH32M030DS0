/*
 * mpb_tm1640 — TM1640 2 色 8×8 マトリクスの数珠つなぎ
 * プロトコルとモジュールの列並び (列は逆順, 行は bit7 = 上) は ghostinkoma/TM1640MatrixChain
 * (TM1640.cpp / matrixchain.cpp, CC BY-NC-SA 4.0, (c) ghostinkoma) に合わせている。
 * 違い: 全モジュールの DIN を同じクロックで並列に送る / 待ちは µs 単位の短いループだけ。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_tm1640.h"

#define CMD_DATA_AUTO  0x40u      /* データ設定: アドレス自動インクリメント */
#define CMD_ADDR       0xC0u
#define CMD_DISP_ON    0x88u      /* | 明るさ 0〜7 */

typedef struct {
    volatile uint32_t *bshr;      /* 下位 16 ビット = セット, 上位 = リセット */
    uint32_t pin;
} Pin;

static Pin      s_clk, s_din[MPB_TM1640_MAX];
static uint8_t  s_n, s_duty;
static uint32_t s_half;           /* 半周期のループ回数 */
static Mpb_Matrix *s_m;

static void dly(void)
{
    for (volatile uint32_t i = s_half; i; i--) {}
}

static inline void pin_w(const Pin *p, uint32_t v) { *p->bshr = v ? p->pin : (p->pin << 16); }

static void din_all(uint32_t v)
{
    for (uint8_t i = 0; i < s_n; i++) pin_w(&s_din[i], v);
}

/* 開始: CLK High のまま DIN を Low, 続いて CLK Low */
static void start(void)
{
    din_all(0);
    dly();
    pin_w(&s_clk, 0);
    dly();
}

/* 終了: CLK High, 続いて DIN High */
static void stop(void)
{
    pin_w(&s_clk, 1);
    dly();
    din_all(1);
    dly();
}

/* モジュールごとに違うバイトを同時に送る (LSB から) */
static void send(const uint8_t *b)
{
    for (uint8_t k = 0; k < 8; k++)
    {
        for (uint8_t i = 0; i < s_n; i++) pin_w(&s_din[i], (b[i] >> k) & 1u);
        dly();
        pin_w(&s_clk, 1);
        dly();
        pin_w(&s_clk, 0);
    }
}

static void send_same(uint8_t v)
{
    uint8_t b[MPB_TM1640_MAX];
    for (uint8_t i = 0; i < s_n; i++) b[i] = v;
    send(b);
}

static void pin_init(Pin *p, GPIO_TypeDef *port, uint16_t pin)
{
    GPIO_InitTypeDef g = {0};

    p->bshr = &port->BSHR;
    p->pin = pin;
    pin_w(p, 1);
    g.GPIO_Pin = pin;
    /* PC4 は USER ボタン (押すと GND) と共用: 押しても短絡しないようオープンドレイン (10k プルアップで High) */
    g.GPIO_Mode = (port == GPIOC && pin == GPIO_Pin_4) ? GPIO_Mode_Out_OD : GPIO_Mode_Out_PP;
    g.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(port, &g);
}

void Mpb_Tm1640_Init(const Mpb_Tm1640Cfg *cfg, Mpb_Matrix *m)
{
    static GPIO_TypeDef *const def_port[4] = {GPIOA, GPIOA, GPIOC, GPIOC};
    static const uint16_t def_pin[4] = {GPIO_Pin_6, GPIO_Pin_7, GPIO_Pin_2, GPIO_Pin_4};

    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA | RCC_PB2Periph_GPIOB | RCC_PB2Periph_GPIOC, ENABLE);
    s_n = cfg->n ? cfg->n : 1u;
    if (s_n > MPB_TM1640_MAX) s_n = MPB_TM1640_MAX;
    s_duty = cfg->duty & 7u;
    /* 1 ループ ≈ 8 クロック (volatile のカウンタ) */
    s_half = (SystemCoreClock / 1000000u) * (cfg->half_us ? cfg->half_us : 2u) / 8u + 1u;
    if (cfg->sclk_port) pin_init(&s_clk, cfg->sclk_port, cfg->sclk_pin);
    else pin_init(&s_clk, GPIOA, GPIO_Pin_5);
    for (uint8_t i = 0; i < s_n; i++)
    {
        if (cfg->din_port[i]) pin_init(&s_din[i], cfg->din_port[i], cfg->din_pin[i]);
        else if (i < 4u) pin_init(&s_din[i], def_port[i], def_pin[i]);
        else pin_init(&s_din[i], GPIOA, GPIO_Pin_7);   /* 既定は 4 枚まで: 5 枚目以降は端子を指定すること */
    }
    s_m = m;
    Mpb_Matrix_Init(m, (uint8_t)(s_n * 8u));
}

void Mpb_Tm1640_SetDuty(uint8_t duty)
{
    s_duty = duty & 7u;
    if (s_m) s_m->dirty = 1;
}

void Mpb_Tm1640_Flush(void)
{
    uint8_t b[MPB_TM1640_MAX];

    if (!s_m)
    {
        return;
    }
    s_m->dirty = 0;
    start(); send_same(CMD_DATA_AUTO); stop();
    start(); send_same(CMD_ADDR);
    /* 1 モジュール 16 バイト: 0〜7 = 赤, 8〜15 = 緑。列は右から, 行は bit7 = 上 (TM1640MatrixChain と同じ) */
    for (uint8_t a = 0; a < 16u; a++)
    {
        for (uint8_t i = 0; i < s_n; i++)
        {
            uint8_t x = (uint8_t)(i * 8u + 7u - (a & 7u));
            uint8_t v = a < 8u ? s_m->r[x] : s_m->g[x];
            /* bit0 = 上 → bit7 = 上 (ビット反転) */
            v = (uint8_t)(((v & 0xF0u) >> 4) | ((v & 0x0Fu) << 4));
            v = (uint8_t)(((v & 0xCCu) >> 2) | ((v & 0x33u) << 2));
            v = (uint8_t)(((v & 0xAAu) >> 1) | ((v & 0x55u) << 1));
            b[i] = v;
        }
        send(b);
    }
    stop();
    start(); send_same((uint8_t)(CMD_DISP_ON | s_duty)); stop();   /* 毎回送る (電源の瞬断からも戻る) */
}

uint8_t Mpb_Tm1640_Task(void)
{
    if (!s_m || !Mpb_Matrix_Tick(s_m))
    {
        return 0;
    }
    Mpb_Tm1640_Flush();
    return 1;
}
