/*
 * mPBCH32M030DS0 アプリケーション テンプレート (Arduino 風: setup() / loop())
 *
 * このファイルは「書き込み要求に応える仕組み」を持つ main() で、ユーザーのコードは
 * sketch.c の setup() / loop() に書く。0x08005000 にリンクされ、ブートローダから起動される。
 *
 *  - USB: WCH IAP 互換のベンダーインターフェース (VID 1A86 / PID 55E0, bcdDevice 0xA001)
 *         ホストが CMD_JUMP_IAP (0x84) を送ると、要求フラグを書いてリセット → ブートローダへ。
 *         tools/mpb_upload.py はこれを自動で行う (ESP32 / Arduino の自動リセットと同じ感覚)。
 *  - UART (PC1/PC2, 460800bps) でも同じコマンドを受け付ける (MPB_UART_BOOT=0 で無効化)。
 *
 * 原型: WCH CH32M030 EVT "UART_USB_IAP/CH32M030_APP" (Copyright (c) 2021 Nanjing Qinheng
 * Microelectronics Co., Ltd. — WCH 製 MCU で使用する場合に限り利用可)
 * Modified 2026 by ghostinkoma.
 */
#include "ch32m030_usbfs_device.h"
#include "debug.h"
#include "iap.h"
#include "board.h"

#ifndef MPB_UART_BOOT
#define MPB_UART_BOOT 1
#endif

void setup(void);
void loop(void);

void USART1_IRQHandler(void) MPB_IRQ;

/* ブート要求フラグが書かれていたらリセットしてブートローダへ */
static void Mpb_ServiceBootRequest(void)
{
    if (*(vu32 *)CalAddr == CheckNum)
    {
        Delay_Ms(10);
        NVIC_SystemReset();
        while (1)
            ;
    }
}

#if MPB_UART_BOOT
static void USART1_IT_CFG(void)
{
    USART_ITConfig(USART1, USART_IT_RXNE, ENABLE);
    NVIC_SetPriority(USART1_IRQn, 1 << 6);
    NVIC_EnableIRQ(USART1_IRQn);
    USART_Cmd(USART1, ENABLE);
}

void USART1_IRQHandler(void)
{
    if (USART_GetFlagStatus(USART1, USART_FLAG_RXNE) != RESET)
    {
        UART_Rx_Deal();
    }
}
#endif

int main(void)
{
    SystemCoreClockUpdate();
    Delay_Init();

    /* USB ベンダーインターフェース (書き込み要求の受付) */
    USBFS_RCC_Init();
    USBFS_Device_Init(ENABLE);
#if MPB_UART_BOOT
    USART1_CFG(MPB_UART_BAUD);
    USART1_IT_CFG();
#endif

    setup();
    while (1)
    {
        loop();
        Mpb_ServiceBootRequest();
    }
}
