/*
 * mpb_encoder — ロータリーエンコーダ (EXTI 両エッジ + 状態表)
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_encoder.h"

/* (前の AB << 2 | 今の AB) → +1 / −1 / 0 (不正な遷移 = チャタリングは 0) */
static const int8_t k_qd[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};

static GPIO_TypeDef *s_pa, *s_pb, *s_btn_port;
static uint16_t s_pina, s_pinb, s_btn_pin;
static volatile uint8_t s_ab;
static volatile int32_t s_raw;           /* 4 逓倍のカウント */
static volatile int32_t s_det, s_base;   /* クリック数と, 直前のクリック位置 (raw) */
static uint8_t  s_div = 4;
static int8_t   s_sign = 1;
static int32_t  s_last;
static uint8_t  s_btn_state, s_btn_raw, s_pressed, s_long, s_long_done;
static uint32_t s_btn_t, s_btn_down_t;

void EXTI7_0_IRQHandler(void) MPB_IRQ;
void EXTI15_8_IRQHandler(void) MPB_IRQ;

static uint8_t port_src(GPIO_TypeDef *p)
{
    return p == GPIOA ? GPIO_PortSourceGPIOA : (p == GPIOB ? GPIO_PortSourceGPIOB : GPIO_PortSourceGPIOC);
}

static uint8_t pin_num(uint16_t pin)
{
    uint8_t n = 0;
    while (pin > 1u) { pin >>= 1; n++; }
    return n;
}

static uint8_t read_ab(void)
{
    return (uint8_t)(((s_pa->INDR & s_pina) ? 2u : 0u) | ((s_pb->INDR & s_pinb) ? 1u : 0u));
}

static void on_edge(void)
{
    uint8_t ab = read_ab();
    s_raw += k_qd[(s_ab << 2) | ab];
    s_ab = ab;
    /* 前のクリック位置から ±1 クリック分動いたら数える (向きによらず同じ位置で数える) */
    if (s_raw - s_base >= (int32_t)s_div) { s_det++; s_base += s_div; }
    else if (s_raw - s_base <= -(int32_t)s_div) { s_det--; s_base -= s_div; }
}

static void exti_pin(GPIO_TypeDef *p, uint16_t pin)
{
    GPIO_InitTypeDef g = {0};
    EXTI_InitTypeDef e = {0};
    uint8_t n = pin_num(pin);

    g.GPIO_Pin = pin;
    g.GPIO_Mode = GPIO_Mode_IPU;          /* 外付けのプルアップが無い端子でも使えるように */
    GPIO_Init(p, &g);
    GPIO_EXTILineConfig(port_src(p), n);
    e.EXTI_Line = pin;                     /* EXTI_Linex = 1 << x = GPIO_Pin_x */
    e.EXTI_Mode = EXTI_Mode_Interrupt;
    e.EXTI_Trigger = EXTI_Trigger_Rising_Falling;
    e.EXTI_LineCmd = ENABLE;
    EXTI_Init(&e);
    NVIC_EnableIRQ(n < 8u ? EXTI7_0_IRQn : EXTI15_8_IRQn);
}

void Mpb_Enc_Init(GPIO_TypeDef *pa, uint16_t pina, GPIO_TypeDef *pb, uint16_t pinb, uint8_t spd)
{
    s_pa = pa ? pa : GPIOA;
    s_pina = pina ? pina : GPIO_Pin_5;
    s_pb = pb ? pb : GPIOA;
    s_pinb = pinb ? pinb : GPIO_Pin_6;
    s_div = spd ? spd : 4u;
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA | RCC_PB2Periph_GPIOB | RCC_PB2Periph_GPIOC | RCC_PB2Periph_AFIO, ENABLE);
    exti_pin(s_pa, s_pina);
    exti_pin(s_pb, s_pinb);
    s_ab = read_ab();
    s_raw = s_det = s_base = 0;
    s_last = 0;
}

static void exti_isr(void)
{
    uint32_t pend = EXTI->INTFR & (uint32_t)(s_pina | s_pinb);
    if (pend)
    {
        EXTI->INTFR = pend;
        on_edge();
    }
}

void EXTI7_0_IRQHandler(void) { exti_isr(); }
void EXTI15_8_IRQHandler(void) { exti_isr(); }

int32_t Mpb_Enc_Count(void) { return s_sign * s_det; }

int32_t Mpb_Enc_Delta(void)
{
    int32_t c = Mpb_Enc_Count(), d = c - s_last;
    s_last = c;
    return d;
}

void Mpb_Enc_SetCount(int32_t c)
{
    __disable_irq();
    s_det = c * s_sign;
    s_base = s_raw;
    __enable_irq();
    s_last = c;
}

void Mpb_Enc_Reverse(uint8_t on) { s_sign = on ? -1 : 1; }

void Mpb_Enc_ButtonInit(GPIO_TypeDef *port, uint16_t pin)
{
    GPIO_InitTypeDef g = {0};

    s_btn_port = port ? port : GPIOC;
    s_btn_pin = pin ? pin : GPIO_Pin_4;
    g.GPIO_Pin = s_btn_pin;
    g.GPIO_Mode = GPIO_Mode_IPU;
    GPIO_Init(s_btn_port, &g);
    s_btn_state = s_btn_raw = 0;
}

void Mpb_Enc_Task(void)
{
    uint32_t now = Mpb_Millis();
    uint8_t raw;

    if (!s_btn_port) return;
    raw = (s_btn_port->INDR & s_btn_pin) ? 0u : 1u;
    if (raw != s_btn_raw)
    {
        s_btn_raw = raw;
        s_btn_t = now;
    }
    else if (raw != s_btn_state && now - s_btn_t >= 20u)
    {
        s_btn_state = raw;
        if (raw)
        {
            s_pressed = 1;
            s_btn_down_t = now;
            s_long_done = 0;
        }
    }
    if (s_btn_state && !s_long_done && now - s_btn_down_t >= 1000u)
    {
        s_long = 1;
        s_long_done = 1;
    }
}

uint8_t Mpb_Enc_Pressed(void) { uint8_t p = s_pressed; s_pressed = 0; return p; }
uint8_t Mpb_Enc_LongPressed(void) { uint8_t p = s_long; s_long = 0; return p; }
uint8_t Mpb_Enc_Down(void) { return s_btn_state; }
