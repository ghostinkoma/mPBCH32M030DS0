# mPBCH32M030DS0 ファームウェア一括ビルド
#   make            ブートローダ + テンプレート + 全サンプル
#   make test       ホスト (PC) で動く単体テスト (書式化・CIE・センサ換算・ステッピングの加減速)
#   make clean
#   make POWER_STAGE=B   子基板 B (24V 系) 用にビルド
EXAMPLES := $(sort $(dir $(wildcard examples/*/Makefile)))

all: bootloader app_template examples

bootloader app_template:
	$(MAKE) -C $@

examples:
	@for d in $(EXAMPLES); do $(MAKE) -C $$d || exit 1; done

test:
	$(MAKE) -C tests

clean:
	$(MAKE) -C bootloader clean
	$(MAKE) -C app_template clean
	@for d in $(EXAMPLES); do $(MAKE) -C $$d clean; done
	$(MAKE) -C tests clean

.PHONY: all bootloader app_template examples test clean
