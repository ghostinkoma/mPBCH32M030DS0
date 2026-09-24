#!/bin/sh
# WCH 公式 CH32M030 SDK (EVT) を取得する。ライセンス上、SDK 本体はこのリポジトリに含めない。
# 固定コミットを使うことでビルドの再現性を確保する。
set -e
cd "$(dirname "$0")"
REPO=https://github.com/openwch/ch32m030
REV=add6584304f80ba3752ca9543cfe61e3be744690
if [ ! -d ch32m030/.git ]; then
    git init -q ch32m030
    git -C ch32m030 remote add origin "$REPO"
fi
git -C ch32m030 fetch -q --depth 1 origin "$REV"
git -C ch32m030 checkout -q FETCH_HEAD
echo "SDK: $(pwd)/ch32m030 @ $REV"
