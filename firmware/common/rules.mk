# mPBCH32M030DS0 共通ビルドルール
#   アプリ (スケッチ) は common/app.mk を include する (core/ と lib/ を使う)。ブートローダはこのファイルを直接使う。
#   make                         # 汎用 GCC (Ubuntu: gcc-riscv64-unknown-elf + picolibc)
#   make PREFIX=riscv-none-elf- LIBC_SPECS="--specs=nano.specs --specs=nosys.specs"  # xPack / MounRiver GCC
#   make IRQ=wch PREFIX=riscv-wch-elf-  # WCH GCC (MounRiver Studio 同梱) で WCH 高速割り込みを使う
FW_ROOT    := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
SDK        ?= $(FW_ROOT)/sdk/ch32m030/EVT/EXAM/SRC
PREFIX     ?= riscv64-unknown-elf-
LIBC_SPECS ?= --specs=picolibc.specs
IRQ        ?= std
BUILD      ?= build
MPB_APP    ?= 0
CORE       := $(FW_ROOT)/core
LIBDIR     := $(FW_ROOT)/lib

CC      := $(PREFIX)gcc
AR      := $(PREFIX)ar
OBJCOPY := $(PREFIX)objcopy
SIZE    := $(PREFIX)size

ifeq ($(IRQ),wch)
ARCH    := -march=rv32imacxw -mabi=ilp32
IRQDEF  :=
else
ARCH    := -march=rv32imac_zicsr_zifencei -mabi=ilp32
IRQDEF  := -DUSE_STD_IRQ_ATTR
endif

# パワー段 (子基板) A/B/C。B (24V 系) は VBUS 分圧比が変わる (core/mpb.h)。
# 通常はスケッチの src/config.h の MPB_POWER_STAGE で指定し, make POWER_STAGE=B で一時的に上書きできる
ifdef POWER_STAGE
IRQDEF  += -DMPB_POWER_STAGE=\'$(POWER_STAGE)\'
endif

CFLAGS  += $(ARCH) $(LIBC_SPECS) -Os -g -ffunction-sections -fdata-sections -fno-common \
           -msmall-data-limit=8 -Wall -Wno-unused-parameter $(IRQDEF) \
           -Isrc -I$(FW_ROOT)/common -I$(SDK)/Core -I$(SDK)/Debug -I$(SDK)/Peripheral/inc $(EXTRA_CFLAGS)
LDFLAGS += $(ARCH) $(LIBC_SPECS) -nostartfiles -Wl,--gc-sections -Wl,-Map=$(BUILD)/$(TARGET).map \
           -T $(LDSCRIPT)

SRCS    := $(wildcard src/*.c) $(SDK)/Core/core_riscv.c $(SDK)/Debug/debug.c \
           $(wildcard $(SDK)/Peripheral/src/*.c)
ASRCS   := $(SDK)/Startup/startup_ch32m030.S
LIBA    :=
ifeq ($(MPB_APP),1)
# アプリ: core/ (起動・USB 書き込み・PD) は常にリンク, lib/ (機能ライブラリ) はアーカイブにして使った物だけリンク
CFLAGS  += -I$(CORE) -I$(LIBDIR)
# スケッチの設定 src/config.h は core / lib を含む全ファイルの先頭で読む (ライブラリの設定もここで変える)
ifneq ($(wildcard src/config.h),)
CFLAGS  += -include $(abspath src/config.h)
endif
SRCS    += $(wildcard $(CORE)/*.c)
LIBSRCS := $(wildcard $(LIBDIR)/*.c)
LIBOBJS := $(addprefix $(BUILD)/lib/,$(notdir $(LIBSRCS:.c=.o)))
LIBA    := $(BUILD)/libmpb.a
# WS2812 の送信関数を RAM (.data) で実行するため, RAM の区画は RWX になる (意図どおり)
LDFLAGS += -Wl,--no-warn-rwx-segments
endif
OBJS    := $(addprefix $(BUILD)/,$(notdir $(SRCS:.c=.o) $(ASRCS:.S=.o)))
vpath %.c src $(CORE) $(SDK)/Core $(SDK)/Debug $(SDK)/Peripheral/src
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

# config.h を変えたら全部作り直す
ifneq ($(wildcard src/config.h),)
$(OBJS) $(LIBOBJS): src/config.h
endif

$(BUILD)/lib/%.o: $(LIBDIR)/%.c | $(BUILD)
	@mkdir -p $(BUILD)/lib
	$(CC) $(CFLAGS) -c $< -o $@

$(LIBA): $(LIBOBJS)
	@rm -f $@
	$(AR) rcs $@ $^

$(BUILD)/$(TARGET).elf: $(OBJS) $(LIBA) $(LDSCRIPT)
	$(CC) $(LDFLAGS) $(OBJS) $(LIBA) -lm -o $@

$(BUILD)/$(TARGET).bin: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(BUILD)/$(TARGET).hex: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

clean:
	rm -rf $(BUILD)

.PHONY: all clean check-sdk
