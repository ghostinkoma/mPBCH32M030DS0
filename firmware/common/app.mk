# mPBCH32M030DS0 アプリ (スケッチ) 共通: 各スケッチの Makefile は次の 2 行だけでよい
#   TARGET := app
#   include ../../common/app.mk          (ディレクトリの深さに合わせる)
# src/*.c (setup()/loop() を書いた sketch.c など) + core/ + lib/ (使った物だけ) をリンクし, 0x08005000 に置く。
#   make                 ビルド (build/app.bin)
#   make upload          USB-C で書き込み (tools/mpb_upload.py, ブートローダへ自動で切り替え)
#   make POWER_STAGE=B   子基板 B (24V 系) 用
MPB_APP  := 1
_APPMK_DIR := $(dir $(lastword $(MAKEFILE_LIST)))
LDSCRIPT := $(_APPMK_DIR)app.ld
include $(_APPMK_DIR)rules.mk

UPLOAD_ARGS ?=
upload: all
	python3 $(FW_ROOT)/../tools/mpb_upload.py $(UPLOAD_ARGS) $(BUILD)/$(TARGET).bin
.PHONY: upload
