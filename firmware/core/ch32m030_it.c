/********************************** (C) COPYRIGHT *******************************
 * File Name          : ch32m030_it.c
 * Author             : WCH
 * Version            : V1.0.0
 * Date               : 2024/09/01
 * Description        : Main Interrupt Service Routines.
*********************************************************************************
* Copyright (c) 2021 Nanjing Qinheng Microelectronics Co., Ltd.
* Attention: This software (modified or not) and binary are used for 
* microcontroller manufactured by Nanjing Qinheng Microelectronics.
*******************************************************************************/
#include "ch32m030_it.h"
#include "mpb.h"
#include "board.h"

void NMI_Handler(void) MPB_IRQ;
void HardFault_Handler(void) MPB_IRQ;

/*********************************************************************
 * @fn      NMI_Handler
 *
 * @brief   This function handles NMI exception.
 *
 * @return  none
 */
void NMI_Handler(void)
{
    Mpb_Gates_Off();                /* 全 FET OFF → リセット */
    NVIC_SystemReset();
    while(1)
    {
    }
}

/*********************************************************************
 * @fn      HardFault_Handler
 *
 * @brief   This function handles Hard Fault exception.
 *
 * @return  none
 */
void HardFault_Handler(void)
{
    Mpb_Gates_Off();                /* 全 FET OFF → リセット */
    NVIC_SystemReset();
    while (1)
    {
    }
}


