# mPBCH32M030DS0 アプリ (0x08005000)。USB-C 経由で書き込む:  make upload
TARGET   := app
LDSCRIPT := ../common/app.ld
include ../common/rules.mk

UPLOAD_ARGS ?=
upload: all
	python3 ../../tools/mpb_upload.py $(UPLOAD_ARGS) $(BUILD)/$(TARGET).bin
.PHONY: upload
