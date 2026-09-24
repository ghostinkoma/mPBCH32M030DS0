/********************************** (C) COPYRIGHT *******************************
 * File Name          : main.c
 * Author             : WCH (original IAP routine V1.0.1, 2025/01/13)
 * Description        : mPBCH32M030DS0 USB/UART bootloader
 *********************************************************************************
 * Copyright (c) 2021 Nanjing Qinheng Microelectronics Co., Ltd.
 * Attention: This software (modified or not) and binary are used for
 * microcontroller manufactured by Nanjing Qinheng Microelectronics.
 *
 * Modified 2026 by ghostinkoma for mPBCH32M030DS0:
 *  - 起動条件を「アプリ未書込 / アプリからの要求フラグ / USER・BOOT ボタン (PC4)」の OR に変更
 *  - UART を TX=PC1 / RX=PC2 (リマップ1) に変更 (PC0 は RST ピン)
 *  - ブートローダ中は状態 LED (PA6) を点滅
 *  - USB bcdDevice = 0xB001 でアプリ (0xA001) と区別
 *******************************************************************************/

/*
 * ブートローダの動作
 *   リセット後、次のいずれかならブートローダに留まり USB (VID 1A86 / PID 55E0) と
 *   UART (460800bps) で書き込みを待つ。それ以外は 0x08005000 のアプリへジャンプする。
 *     1) アプリ領域が空 (0x08005000 が 0xFFFFFFFF)
 *     2) アプリが要求フラグ (0x0800FFFC = 0x5AA55AA5) を書いてリセットした
 *     3) USER/BOOT ボタン (PC4) を押しながらリセット/電源投入した
 *   書き込み完了コマンド (CMD_IAP_END) でフラグページを消去してアプリへジャンプする。
 *
 * モーター出力の安全性: HO ピン (PB9/11/13/15) はリセット時に Low 出力、
 * LO ピン (PB8/10/12/14) は内部プルダウン付き入力なので、ブートローダ中は全 FET OFF。
 */
#include "ch32m030_usbfs_device.h"
#include "debug.h"
#include "iap.h"
#include "board.h"

extern u8 End_Flag;

/*********************************************************************
 * @fn      IAP_2_APP
 * @brief   周辺を元に戻し、ソフトウェア割り込み経由でアプリへジャンプする (WCH 方式)
 */
static void IAP_2_APP(void)
{
    USBFS_Device_Init(DISABLE);
    GPIO_Cfg_Float();
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_AFIO, DISABLE);
    RCC_HBPeriphClockCmd(RCC_HBPeriph_USBFS, DISABLE);
    RCC_PB2PeriphClockCmd(RCC_PB2Periph_USART1, DISABLE);
    Delay_Ms(60);
    NVIC_EnableIRQ(Software_IRQn);
    NVIC_SetPendingIRQ(Software_IRQn);
}

static int App_Present(void)
{
    return *(volatile uint32_t *)MPB_APP_ADDR != 0xFFFFFFFFu;
}

static int Boot_Requested(void)
{
    return *(volatile uint32_t *)MPB_FLAG_ADDR == MPB_FLAG_MAGIC;
}

static void StatusLed_Init(void)
{
    GPIO_InitTypeDef gpio = {0};

    RCC_PB2PeriphClockCmd(MPB_LED_RCC, ENABLE);
    gpio.GPIO_Pin = MPB_LED_PIN;
    gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    gpio.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(MPB_LED_PORT, &gpio);
}

int main(void)
{
    uint32_t tick = 0;
    uint8_t led = 0;

    SystemCoreClockUpdate();
    Delay_Init();

    if (App_Present() && !Boot_Requested() && !BootKey_Pressed())
    {
        IAP_2_APP();
        while (1)
            ;
    }

    StatusLed_Init();
    USBFS_RCC_Init();
    USBFS_Device_Init(ENABLE);
    USART1_CFG(MPB_UART_BAUD);

    while (1)
    {
        if (USART_GetFlagStatus(USART1, USART_FLAG_RXNE) != RESET)
        {
            UART_Rx_Deal();
        }
        if (End_Flag)
        {
            Delay_Ms(10);
            IAP_2_APP();
            while (1)
                ;
        }
        /* 約 4Hz で状態 LED を点滅 (ブートローダ動作中の表示) */
        if (++tick >= 150000u)
        {
            tick = 0;
            led ^= 1;
            GPIO_WriteBit(MPB_LED_PORT, MPB_LED_PIN, led ? Bit_SET : Bit_RESET);
        }
    }
}
