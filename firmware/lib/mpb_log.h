/*
 * mpb_log — UART ログ出力 (USART1 TX = PC1, モジュール J2-3 UART_TX, 既定 460800bps)
 *
 * 書き込みはリングバッファに積むだけで, 送信は TXE 割込みが行う (ノンブロッキング)。
 * バッファ (既定 512 バイト) が一杯のときは溢れた分を捨てて数える (Mpb_Log_Dropped)。
 * printf 形式の書式は整数のみ: %d %i %u %x %X %c %s %% (幅, 0 詰め, - 左寄せ)。
 * RV32 では int と long (int32_t) が同じ 32bit なので, int32_t / uint32_t も %d / %u でよい (l は無視)。
 * 小数は Mpb_Log_Fixed() (例: 1234, 1 → "123.4") で出す。
 *
 *   Mpb_Log_Init(0);                                  // 0 = core が設定済みのボーレートのまま
 *   MPB_LOGI("vbus=%u mV i=%d mA", v, i);             // "[   12.345] I vbus=12003 mV i=-35 mA\r\n"
 *
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_LOG_H
#define MPB_LOG_H

#include <stdarg.h>
#include <stdint.h>

#ifndef MPB_LOG_BUF
#define MPB_LOG_BUF 512u              /* 2 のべき乗 */
#endif

void     Mpb_Log_Init(uint32_t baud);                 /* 0 = 既定 (MPB_UART_BAUD) */
int      Mpb_Log_Write(const char *s, int len);       /* len < 0 で strlen。積めたバイト数を返す */
int      Mpb_Log_Printf(const char *fmt, ...);
int      Mpb_Log_VPrintf(const char *fmt, va_list ap);
void     Mpb_Log_Line(char level, const char *fmt, ...);
uint32_t Mpb_Log_Dropped(void);
uint32_t Mpb_Log_Free(void);                           /* バッファの空き */
uint8_t  Mpb_Log_Idle(void);                           /* 送信し終えた */
const char *Mpb_Log_Fixed(int32_t v, uint8_t decimals);   /* v / 10^decimals を文字列に (静的バッファ) */

/* 汎用の書式化 (snprintf の整数版) */
int      Mpb_Fmt(char *buf, int size, const char *fmt, ...);
int      Mpb_VFmt(char *buf, int size, const char *fmt, va_list ap);

#define MPB_LOGI(...) Mpb_Log_Line('I', __VA_ARGS__)
#define MPB_LOGW(...) Mpb_Log_Line('W', __VA_ARGS__)
#define MPB_LOGE(...) Mpb_Log_Line('E', __VA_ARGS__)
#ifdef MPB_DEBUG
#define MPB_LOGD(...) Mpb_Log_Line('D', __VA_ARGS__)
#else
#define MPB_LOGD(...) ((void)0)
#endif

#endif /* MPB_LOG_H */
