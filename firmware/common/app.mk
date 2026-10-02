# mPBCH32M030DS0 アプリ (スケッチ) 共通: 各スケッチの Makefile は次の 2 行だけでよい
#   TARGET := app
#   include ../../common/app.mk          (ディレクトリの深さに合わせる)
# src/*.c (setup()/loop() を書いた sketch.c など) + core/ + lib/ (使った物だけ) をリンクし, 0x08005000 に置く。
#   make                 ビルド (build/app.bin)
#   make upload          USB-C で書き込み (tools/mpb_upload.py, ブートローダへ自動で切り替え)
#   make POWER_STAGE=B   子基板 B (24V 系) 用
#   RTOS := freertos     (Makefile に書く) FreeRTOS を使う: src/FreeRTOSConfig.h が必要 (examples/rtos_motor_display)
MPB_APP  := 1
_APPMK_DIR := $(dir $(lastword $(MAKEFILE_LIST)))
LDSCRIPT := $(_APPMK_DIR)app.ld

ifeq ($(RTOS),freertos)
# WCH SDK 同梱の FreeRTOS (V10.4.6, RISC-V ポート: SysTick でティック, SW 割込みで切替)
_FRT_ROOT  := $(abspath $(_APPMK_DIR)/../sdk/ch32m030/EVT/EXAM/FreeRTOS/FreeRTOS)
_FRT       := $(_FRT_ROOT)/FreeRTOS
EXTRA_SRCS += $(_FRT)/tasks.c $(_FRT)/list.c $(_FRT)/queue.c $(_FRT)/timers.c $(_FRT)/portable/GCC/RISC-V/port.c
EXTRA_ASRCS += $(_FRT)/portable/GCC/RISC-V/portASM.S
# FreeRTOS 用のスタートアップ: ハードウェアの自動退避 (HPE) を切り, 割込みの入れ子を許す (INTSYSCR = 0x2)
STARTUP    := $(_FRT_ROOT)/Startup/startup_ch32m030.S
EXTRA_CFLAGS += -DMPB_RTOS=1 -I$(_FRT)/include -I$(_FRT)/portable/GCC/RISC-V \
                -I$(_FRT)/portable/GCC/RISC-V/chip_specific_extensions/RV32I_PFIC_no_extensions
# スケジューラ開始後は割込みもタスクのスタックで動くので, main のスタックは小さくてよい
RTOS_MAIN_STACK ?= 768
LDFLAGS    += -Wl,--defsym=__stack_size=$(RTOS_MAIN_STACK)
ifeq ($(IRQ),wch)
$(error RTOS := freertos は IRQ=std (標準の割込み属性) で使う。WCH の高速割込み (HPE) とは併用できない)
endif
endif

include $(_APPMK_DIR)rules.mk

ifeq ($(RTOS),freertos)
# SDK の Delay_Us / Delay_Ms は SysTick (= OS のティック) を止めるので改名し, core/mpb_time.c の TIM3 版を使う
$(BUILD)/debug.o: CFLAGS += -DDelay_Us=Sdk_Delay_Us -DDelay_Ms=Sdk_Delay_Ms
endif

UPLOAD_ARGS ?=
upload: all
	python3 $(FW_ROOT)/../tools/mpb_upload.py $(UPLOAD_ARGS) $(BUILD)/$(TARGET).bin
.PHONY: upload
