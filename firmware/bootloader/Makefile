# mPBCH32M030DS0 ブートローダ (0x08000000, 20KB)。最初の 1 回だけ WCH-LinkE (SWD) で書き込む。
TARGET   := mpb_bootloader
LDSCRIPT := ../common/bootloader.ld
include ../common/rules.mk

# WCH-LinkE + wlink (https://github.com/ch32-rs/wlink) で書き込む場合。
# wlink が CH32M030 未対応の場合は WCH-LinkUtility / MounRiver Studio で build/mpb_bootloader.hex を書く。
flash: all
	wlink flash --address 0x08000000 $(BUILD)/$(TARGET).bin
.PHONY: flash
