/*
 * mpb_log — UART ログ (リングバッファ + TXE 割込み)
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include <string.h>
#include "mpb_log.h"
#include "mpb.h"

void USART1_CFG(uint32_t baudrate);      /* core/iap.c */

static char s_buf[MPB_LOG_BUF];
static volatile uint32_t s_head, s_tail;  /* head: 書き込み位置, tail: 送信位置 */
static volatile uint32_t s_drop;

/* core の USART1_IRQHandler から呼ばれる */
void Mpb_Uart_TxIrq(void)
{
    if (s_tail == s_head)
    {
        USART1->CTLR1 &= (uint16_t)~UART_CTLR1_TXEIE;
        return;
    }
    USART1->DATAR = (uint8_t)s_buf[s_tail & (MPB_LOG_BUF - 1u)];
    s_tail++;
}

void Mpb_Log_Init(uint32_t baud)
{
    if (baud || !(USART1->CTLR1 & UART_CTLR1_UE))
    {
        USART1_CFG(baud ? baud : MPB_UART_BAUD);   /* MPB_UART_BOOT=0 のスケッチでもここで設定する */
    }
    NVIC_EnableIRQ(USART1_IRQn);
}

int Mpb_Log_Write(const char *s, int len)
{
    int n = 0;

    if (len < 0)
    {
        len = (int)strlen(s);
    }
    for (; n < len; n++)
    {
        if (s_head - s_tail >= MPB_LOG_BUF)
        {
            s_drop += (uint32_t)(len - n);
            break;
        }
        s_buf[s_head & (MPB_LOG_BUF - 1u)] = s[n];
        s_head++;
    }
    USART1->CTLR1 |= UART_CTLR1_TXEIE;           /* 割込みで送り出す */
    return n;
}

uint32_t Mpb_Log_Dropped(void) { return s_drop; }
uint32_t Mpb_Log_Free(void) { return MPB_LOG_BUF - (s_head - s_tail); }
uint8_t Mpb_Log_Idle(void) { return s_head == s_tail && (USART1->STATR & USART_FLAG_TC); }

/* ------------------------------------------------------------ 書式化 ---------------- */
typedef struct { char *p; int left; int n; } Out;

static void put(Out *o, char c)
{
    if (o->left > 1) { *o->p++ = c; o->left--; }
    o->n++;
}

int Mpb_VFmt(char *buf, int size, const char *f, va_list ap)
{
    Out o = {buf, size, 0};

    for (; *f; f++)
    {
        char tmp[12], pad = ' ';
        int width = 0, left = 0, neg = 0, len = 0;
        uint32_t u;
        const char *str;

        if (*f != '%') { put(&o, *f); continue; }
        f++;
        if (*f == '-') { left = 1; f++; }
        if (*f == '0') { pad = '0'; f++; }
        while (*f >= '0' && *f <= '9') { width = width * 10 + (*f++ - '0'); }
        while (*f == 'l' || *f == 'h') f++;       /* RV32: long = int = 32bit */
        switch (*f)
        {
        case 'd': case 'i':
        {
            int32_t v = va_arg(ap, int32_t);
            neg = v < 0;
            u = neg ? (uint32_t)(-(v + 1)) + 1u : (uint32_t)v;
            do { tmp[len++] = (char)('0' + u % 10u); u /= 10u; } while (u);
            break;
        }
        case 'u':
            u = va_arg(ap, uint32_t);
            do { tmp[len++] = (char)('0' + u % 10u); u /= 10u; } while (u);
            break;
        case 'x': case 'X':
            u = va_arg(ap, uint32_t);
            do { uint32_t d = u & 15u; tmp[len++] = (char)(d < 10 ? '0' + d : (*f == 'x' ? 'a' : 'A') + d - 10); u >>= 4; } while (u);
            break;
        case 'c':
            tmp[len++] = (char)va_arg(ap, int);
            break;
        case 's':
            str = va_arg(ap, const char *);
            if (!str) str = "(null)";
            len = (int)strlen(str);
            if (!left) for (int i = len; i < width; i++) put(&o, ' ');
            for (int i = 0; i < len; i++) put(&o, str[i]);
            if (left) for (int i = len; i < width; i++) put(&o, ' ');
            continue;
        case '%':
            put(&o, '%');
            continue;
        case 0:
            f--;
            continue;
        default:
            put(&o, '%');
            put(&o, *f);
            continue;
        }
        /* 数値: tmp は逆順 */
        {
            int total = len + neg;
            if (neg && pad == '0') put(&o, '-');
            if (!left) for (int i = total; i < width; i++) put(&o, pad);
            if (neg && pad != '0') put(&o, '-');
            while (len) put(&o, tmp[--len]);
            if (left) for (int i = total; i < width; i++) put(&o, ' ');
        }
    }
    if (size > 0) *o.p = 0;
    return o.n;
}

int Mpb_Fmt(char *buf, int size, const char *fmt, ...)
{
    va_list ap;
    int n;

    va_start(ap, fmt);
    n = Mpb_VFmt(buf, size, fmt, ap);
    va_end(ap);
    return n;
}

int Mpb_Log_VPrintf(const char *fmt, va_list ap)
{
    char line[128];
    int n = Mpb_VFmt(line, sizeof(line), fmt, ap);

    if (n > (int)sizeof(line) - 1) n = (int)sizeof(line) - 1;
    return Mpb_Log_Write(line, n);
}

int Mpb_Log_Printf(const char *fmt, ...)
{
    va_list ap;
    int n;

    va_start(ap, fmt);
    n = Mpb_Log_VPrintf(fmt, ap);
    va_end(ap);
    return n;
}

void Mpb_Log_Line(char level, const char *fmt, ...)
{
    va_list ap;
    uint32_t ms = Mpb_Millis();

    Mpb_Log_Printf("[%5u.%03u] %c ", ms / 1000u, ms % 1000u, level);
    va_start(ap, fmt);
    Mpb_Log_VPrintf(fmt, ap);
    va_end(ap);
    Mpb_Log_Write("\r\n", 2);
}

const char *Mpb_Log_Fixed(int32_t v, uint8_t decimals)
{
    static char b[4][16];
    static uint8_t k;
    char *p = b[k++ & 3];
    uint32_t div = 1, a;

    for (uint8_t i = 0; i < decimals; i++) div *= 10u;
    a = v < 0 ? (uint32_t)(-(v + 1)) + 1u : (uint32_t)v;
    if (decimals)
    {
        char f[16];
        Mpb_Fmt(f, sizeof(f), "%%s%%u.%%0%uu", decimals);
        Mpb_Fmt(p, 16, f, v < 0 ? "-" : "", a / div, a % div);
    }
    else
    {
        Mpb_Fmt(p, 16, "%d", v);
    }
    return p;
}
