/*
 * Arduino.h — mPBCH32M030DS0 用の最小限の Arduino 互換 API
 *
 * 本体の機能は mpbfun ライブラリ (モーター, LED, I2C, 表示器 …, firmware/lib と同じ) を直接使う。
 * ここでは pinMode / digitalWrite / millis / delay / Serial など, よく使うものだけを用意している。
 *   ・delay() は待つ間 CPU を止める (モーターの *_Task() も止まる)。モーターを回すスケッチは
 *     MPB_EVERY_MS(t, 100) { … } のような待たない書き方にする。
 *   ・Serial は UART (TX = PC1 / J2-3) のログ。既定 460800bps。受信はない (PC2 は書き込み要求用)。
 *   ・analogRead(ch) の引数は ADC のチャンネル番号 (端子番号ではない)。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef Arduino_h
#define Arduino_h

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>
#include "mpbfun.h"
#include "pins_arduino.h"

#ifdef __cplusplus
extern "C" {
#endif
void setup(void);
void loop(void);
#ifdef __cplusplus
}
#endif

#define HIGH 1
#define LOW  0
#define INPUT             0x0
#define OUTPUT            0x1
#define INPUT_PULLUP      0x2
#define INPUT_PULLDOWN    0x3
#define OUTPUT_OPEN_DRAIN 0x4
#define LSBFIRST 0
#define MSBFIRST 1

typedef bool    boolean;
typedef uint8_t byte;
typedef uint16_t word;

#ifndef PI
#define PI 3.1415926535897932384626433832795
#endif
#define bit(b)                 (1UL << (b))
#define bitRead(v, b)          (((v) >> (b)) & 1UL)
#define bitSet(v, b)           ((v) |= (1UL << (b)))
#define bitClear(v, b)         ((v) &= ~(1UL << (b)))
#define bitWrite(v, b, x)      ((x) ? bitSet(v, b) : bitClear(v, b))
#define lowByte(w)             ((uint8_t)((w) & 0xFF))
#define highByte(w)            ((uint8_t)((w) >> 8))
#ifndef __cplusplus
#define min(a, b)              ((a) < (b) ? (a) : (b))
#define max(a, b)              ((a) > (b) ? (a) : (b))
#endif
#define constrain(x, lo, hi)   ((x) < (lo) ? (lo) : ((x) > (hi) ? (hi) : (x)))

static inline GPIO_TypeDef *Mpb_PinPort(uint8_t p) { return p < 16u ? GPIOA : (p < 32u ? GPIOB : GPIOC); }
static inline uint16_t Mpb_PinMask(uint8_t p) { return (uint16_t)(1u << (p & 15u)); }

static inline void pinMode(uint8_t pin, uint8_t mode)
{
    GPIO_InitTypeDef g;
    memset(&g, 0, sizeof(g));
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOA | RCC_PB2Periph_GPIOB | RCC_PB2Periph_GPIOC, ENABLE);
    g.GPIO_Pin = Mpb_PinMask(pin);
    g.GPIO_Speed = GPIO_Speed_30MHz;
    g.GPIO_Mode = mode == OUTPUT ? GPIO_Mode_Out_PP : mode == OUTPUT_OPEN_DRAIN ? GPIO_Mode_Out_OD
                : mode == INPUT_PULLUP ? GPIO_Mode_IPU : mode == INPUT_PULLDOWN ? GPIO_Mode_IPD : GPIO_Mode_IN_FLOATING;
    GPIO_Init(Mpb_PinPort(pin), &g);
}

static inline void digitalWrite(uint8_t pin, uint8_t v)
{
    if (v) Mpb_PinPort(pin)->BSHR = Mpb_PinMask(pin);
    else Mpb_PinPort(pin)->BCR = Mpb_PinMask(pin);
}

static inline int digitalRead(uint8_t pin) { return (Mpb_PinPort(pin)->INDR & Mpb_PinMask(pin)) ? HIGH : LOW; }
static inline void digitalToggle(uint8_t pin) { digitalWrite(pin, !(Mpb_PinPort(pin)->OUTDR & Mpb_PinMask(pin))); }

static inline uint32_t millis(void) { return Mpb_Millis(); }
static inline uint32_t micros(void) { return Mpb_Micros(); }
static inline void delayMicroseconds(uint32_t us) { uint32_t t = Mpb_Micros(); while (Mpb_Micros() - t < us) {} }
static inline void delay(uint32_t ms)
{
    uint32_t t = Mpb_Micros();
    while (Mpb_Micros() - t < ms * 1000u)
    {
        Mpb_Core_Service();                 /* 待っている間も USB からの書き込み要求に応える */
    }
}
static inline void yield(void) { Mpb_Core_Service(); }

static inline int analogRead(uint8_t adc_ch) { Mpb_Adc_Init(); return (int)Mpb_Adc_Read(adc_ch); }

static inline long map(long x, long in_min, long in_max, long out_min, long out_max)
{
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
}
static inline long random_range(long lo, long hi) { return hi > lo ? lo + (long)(rand() % (hi - lo)) : lo; }

#ifdef __cplusplus
#include <stdarg.h>

/* Serial: UART ログ (mpb_log) への薄い包み */
class MpbSerial {
public:
    void begin(uint32_t baud = 0) { Mpb_Log_Init(baud); }
    void end(void) {}
    operator bool() const { return true; }
    size_t write(uint8_t c) { return (size_t)Mpb_Log_Write((const char *)&c, 1); }
    size_t write(const char *s) { return (size_t)Mpb_Log_Write(s, -1); }
    size_t print(const char *s) { return write(s); }
    size_t print(char c) { return write((uint8_t)c); }
    size_t print(long v, int base = 10) { char b[16]; Mpb_Fmt(b, sizeof(b), base == 16 ? "%X" : "%d", (int)v); return write(b); }
    size_t print(unsigned long v, int base = 10) { char b[16]; Mpb_Fmt(b, sizeof(b), base == 16 ? "%X" : "%u", (unsigned)v); return write(b); }
    size_t print(int v, int base = 10) { return print((long)v, base); }
    size_t print(unsigned int v, int base = 10) { return print((unsigned long)v, base); }
    size_t print(double v, int digits = 2)
    {
        int32_t s = 1;
        for (int i = 0; i < digits; i++) s *= 10;
        return write(Mpb_Log_Fixed((int32_t)lround(v * s), (uint8_t)digits));
    }
    template <typename T> size_t println(T v) { size_t n = print(v); return n + write("\r\n"); }
    template <typename T> size_t println(T v, int f) { size_t n = print(v, f); return n + write("\r\n"); }
    size_t println(void) { return write("\r\n"); }
    int printf(const char *fmt, ...) __attribute__((format(printf, 2, 3)))
    {
        va_list ap;
        va_start(ap, fmt);
        int n = Mpb_Log_VPrintf(fmt, ap);
        va_end(ap);
        return n;
    }
    void flush(void) { while (!Mpb_Log_Idle()) {} }
    int available(void) { return 0; }
    int read(void) { return -1; }
};
static MpbSerial Serial __attribute__((unused));

template <class T, class L> static inline auto min(const T &a, const L &b) -> decltype(b < a ? b : a) { return (b < a) ? b : a; }
template <class T, class L> static inline auto max(const T &a, const L &b) -> decltype(b < a ? b : a) { return (a < b) ? b : a; }
#endif

#endif /* Arduino_h */
