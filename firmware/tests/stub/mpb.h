/* ホストテスト用の最小スタブ (実機のレジスタの代わり) */
#ifndef MPB_H
#define MPB_H
#include <stdint.h>
#include <stddef.h>
typedef struct { volatile uint16_t STATR, DATAR, CTLR1; } USART_TypeDef;
extern USART_TypeDef g_usart;
#define USART1 (&g_usart)
#define UART_CTLR1_TXEIE 0x0080u
#define UART_CTLR1_UE    0x2000u
#define USART_FLAG_TC    0x0040u
#define USART1_IRQn 0
#define MPB_UART_BAUD 460800u
static inline void NVIC_EnableIRQ(int n) { (void)n; }
uint32_t Mpb_Millis(void);
uint32_t Mpb_Micros(void);
uint32_t Mpb_Vbus_mV(void);
typedef int OPA_ISP_GAIN_SEL_TypeDef;
typedef enum { MPB_ISP_LEG = 0, MPB_ISP_BUS = 1 } Mpb_IspSrc;
static inline void __disable_irq(void) {}
static inline void __enable_irq(void) {}
#endif
