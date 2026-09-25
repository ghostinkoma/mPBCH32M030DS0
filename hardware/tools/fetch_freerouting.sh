#!/bin/sh
# 自動配線ツール Freerouting (GPL-3.0) を取得する。リポジトリには含めない。
cd "$(dirname "$0")" && curl -fL -o freerouting-1.9.0.jar \
  https://github.com/freerouting/freerouting/releases/download/v1.9.0/freerouting-1.9.0.jar
