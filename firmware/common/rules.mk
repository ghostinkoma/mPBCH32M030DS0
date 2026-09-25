# mPBCH32M030DS0 共通ビルドルール
#   make                         # 汎用 GCC (Ubuntu: gcc-riscv64-unknown-elf + picolibc)
#   make PREFIX=riscv-none-elf- LIBC_SPECS="--specs=nano.specs --specs=nosys.specs"  # xPack / MounRiver GCC
#   make IRQ=wch PREFIX=riscv-wch-elf-  # WCH GCC (MounRiver Studio 同梱) で WCH 高速割り込みを使う
FW_ROOT    := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
SDK        ?= $(FW_ROOT)/sdk/ch32m030/EVT/EXAM/SRC
PREFIX     ?= riscv64-unknown-elf-
LIBC_SPECS ?= --specs=picolibc.specs
IRQ        ?= std
BUILD      ?= build

CC      := $(PREFIX)gcc
OBJCOPY := $(PREFIX)objcopy
SIZE    := $(PREFIX)size

ifeq ($(IRQ),wch)
ARCH    := -march=rv32imacxw -mabi=ilp32
IRQDEF  :=
else
ARCH    := -march=rv32imac_zicsr_zifencei -mabi=ilp32
IRQDEF  := -DUSE_STD_IRQ_ATTR
endif

# パワー段 (子基板) A/B/C/D。B (24V 系) は VBUS 分圧比が変わる (src/mpb.h)
POWER_STAGE ?= A
IRQDEF  += -DMPB_POWER_STAGE=\'$(POWER_STAGE)\'

CFLAGS  += $(ARCH) $(LIBC_SPECS) -Os -g -ffunction-sections -fdata-sections -fno-common \
           -msmall-data-limit=8 -Wall -Wno-unused-parameter $(IRQDEF) \
           -Isrc -I$(FW_ROOT)/common -I$(SDK)/Core -I$(SDK)/Debug -I$(SDK)/Peripheral/inc
LDFLAGS += $(ARCH) $(LIBC_SPECS) -nostartfiles -Wl,--gc-sections -Wl,-Map=$(BUILD)/$(TARGET).map \
           -T $(LDSCRIPT)

SRCS    := $(wildcard src/*.c) $(SDK)/Core/core_riscv.c $(SDK)/Debug/debug.c \
           $(wildcard $(SDK)/Peripheral/src/*.c)
ASRCS   := $(SDK)/Startup/startup_ch32m030.S
OBJS    := $(addprefix $(BUILD)/,$(notdir $(SRCS:.c=.o) $(ASRCS:.S=.o)))
vpath %.c src $(SDK)/Core $(SDK)/Debug $(SDK)/Peripheral/src
vpath %.S $(SDK)/Startup

all: check-sdk $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).hex
	@$(SIZE) $(BUILD)/$(TARGET).elf

check-sdk:
	@test -d $(SDK) || { echo "SDK がありません: $(FW_ROOT)/sdk/fetch_sdk.sh を実行してください"; exit 1; }

$(BUILD):
	@mkdir -p $@

$(BUILD)/%.o: %.c | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/%.o: %.S | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/$(TARGET).elf: $(OBJS) $(LDSCRIPT)
	$(CC) $(LDFLAGS) $(OBJS) -o $@

$(BUILD)/$(TARGET).bin: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(BUILD)/$(TARGET).hex: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

clean:
	rm -rf $(BUILD)

.PHONY: all clean check-sdk
