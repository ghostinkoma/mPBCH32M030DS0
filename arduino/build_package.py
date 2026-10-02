#!/usr/bin/env python3
"""
build_package.py — Arduino Boards Manager 用のパッケージを作る

  1. arduino/platform (boards.txt, platform.txt, Arduino.h …) に firmware/core, firmware/lib, WCH SDK,
     リンカスクリプト, 書き込みツールを足して 1 つのプラットフォームにまとめる
  2. mpbch32m030-<版>.tar.bz2 を作る (中身・時刻・所有者を固定 = 何度作っても同じバイト列)
  3. package_mpbch32m030_index.json を作る (コア + ツールチェーン xPack riscv-none-elf-gcc)

  python3 arduino/build_package.py --version 0.1.0 --out dist \\
      --release-url https://github.com/ghostinkoma/mPBCH32M030DS0/releases/download/arduino-v0.1.0 \\
      --tools-dir dist                 # ツールチェーンのアーカイブ (ミラーする物) があるディレクトリ
  python3 arduino/build_package.py --version 0.1.0 --out dist --stage-only     # 展開した形だけ作る (試験用)

--tools-dir を付けると, そこにある xPack のアーカイブを下の TOOLCHAIN の SHA-256 で確かめ,
--release-url (= このリポジトリの Releases) から配る索引を作る (ミラー)。付けないと xPack 本家の URL を使う
(その場合サイズが分からないので --tool-sizes で与える)。
GitHub Actions (.github/workflows/arduino-package.yml) が arduino-v* のタグでこれを実行する。

Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
"""
import argparse
import bz2
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FW = os.path.join(ROOT, "firmware")
SDK = os.path.join(FW, "sdk", "ch32m030", "EVT", "EXAM", "SRC")
PKG = "mpbch32m030"
ARCH = "ch32m030"
REPO_URL = "https://github.com/ghostinkoma/mPBCH32M030DS0"

# xPack riscv-none-elf-gcc (SHA-256 は xPack の公開ページの値: website/blog/2025-10-23-riscv-none-elf-gcc-v14-3-0-1-released.mdx)
TOOL_NAME = "xpack-riscv-none-elf-gcc"
TOOL_VER = "14.3.0-1"
TOOL_UPSTREAM = f"https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v{TOOL_VER}/"
TOOLCHAIN = {
    # ファイル名の末尾: (SHA-256, Arduino のホスト名の並び)
    "darwin-arm64.tar.gz": ("1cb71ea516a0b1042b8f7b584da2d4aee97d425f6b74ad96c37e791142a4784c", ["arm64-apple-darwin"]),
    "darwin-x64.tar.gz":   ("0ebd4116c85a72b0e6c49a9e991f396f271269118af45b415286473482795e8a", ["x86_64-apple-darwin"]),
    "linux-arm64.tar.gz":  ("9e6ab407bf8eb4a39fa6b7a7f2cfd8d068a50bcf25685614a415d7f4bae6b311", ["aarch64-linux-gnu"]),
    "linux-x64.tar.gz":    ("be1768ef22789f4d9c41384e0261996f51724b84c2efa940d975dd7d9938c726", ["x86_64-linux-gnu"]),
    "win32-x64.zip":       ("44749ebaac273114f6689360d6e1a10b7e0debe9cee7cbc24e83ef84b0c21cc5", ["x86_64-mingw32", "i686-mingw32"]),
}

FRT = os.path.join(FW, "sdk", "ch32m030", "EVT", "EXAM", "FreeRTOS", "FreeRTOS", "FreeRTOS")
# FreeRTOS を使うサンプル (mpbfun ではなく MpbFreeRTOS のスケッチ例に入れる)
RTOS_EXAMPLES = {"rtos_motor_display"}


def tool_file(suffix):
    return f"xpack-riscv-none-elf-gcc-{TOOL_VER}-{suffix}"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def copy_tree(src, dst, exts):
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        if os.path.isfile(p) and os.path.splitext(name)[1] in exts:
            copy(p, os.path.join(dst, name))


def subst(path, version):
    s = open(path, encoding="utf-8").read().replace("@VERSION@", version)
    open(path, "w", encoding="utf-8").write(s)


def arduino_config(cfg):
    """firmware の config.h → Arduino 用 (子基板と UART 書き込みはツールメニューで選ぶ)"""
    uart = re.search(r"#define MPB_UART_BOOT\s+(\d)", cfg)
    note = ("/* Arduino: 子基板は「ツール → Power stage」, UART 書き込みは「ツール → UART boot request」で選ぶ"
            + (" (このスケッチは Off にする: PC2 を使う)" if uart and uart.group(1) == "0" else "") + " */\n")
    cfg = re.sub(r"#ifndef MPB_POWER_STAGE\n#define MPB_POWER_STAGE[^\n]*\n#endif\n", note, cfg)
    cfg = re.sub(r"#define MPB_UART_BOOT[^\n]*\n", "", cfg)
    cfg = cfg.replace("src/config.h", "config.h").replace("common/rules.mk が -include する",
                                                          "platform.txt の -include mpb_config_select.h が読む")
    return cfg


def stage(out, version):
    top = os.path.join(out, f"{PKG}-{version}")
    if os.path.exists(top):
        shutil.rmtree(top)
    if not os.path.isdir(SDK):
        sys.exit("WCH SDK がありません: firmware/sdk/fetch_sdk.sh を実行してください")
    shutil.copytree(os.path.join(ROOT, "arduino", "platform"), top)
    for f in ("platform.txt", os.path.join("libraries", "mpbfun", "library.properties"),
              os.path.join("libraries", "MpbFreeRTOS", "library.properties")):
        subst(os.path.join(top, f), version)
    core = os.path.join(top, "cores", "mpb")
    copy_tree(os.path.join(FW, "core"), os.path.join(core, "mpb"), {".c", ".h"})
    copy(os.path.join(FW, "common", "board.h"), os.path.join(core, "mpb", "board.h"))
    for d in ("Core", "Debug"):
        copy_tree(os.path.join(SDK, d), os.path.join(core, "sdk", d), {".c", ".h"})
    copy_tree(os.path.join(SDK, "Peripheral", "inc"), os.path.join(core, "sdk", "Peripheral", "inc"), {".h"})
    copy_tree(os.path.join(SDK, "Peripheral", "src"), os.path.join(core, "sdk", "Peripheral", "src"), {".c"})
    # スタートアップは 1 つで RTOS と切り替える (違いは 2 行: FreeRTOS はハードウェアの自動退避 HPE を使わない)
    st = open(os.path.join(SDK, "Startup", "startup_ch32m030.S"), encoding="utf-8").read()
    for a, b in (("\tli t0, 0x3\n", "\tli t0, 0x2\n"), ("\tli t0, 0x88\n", "\tli t0, 0x1800\n")):
        if st.count(a) != 1:
            sys.exit(f"startup_ch32m030.S の想定外の内容: {a!r}")
        st = st.replace(a, f"#if MPB_RTOS\n{b}#else\n{a}#endif\n")
    os.makedirs(os.path.join(core, "sdk", "Startup"), exist_ok=True)
    open(os.path.join(core, "sdk", "Startup", "startup_ch32m030.S"), "w", encoding="utf-8").write(st)
    # RTOS では SDK の Delay_Us/Ms (SysTick を止める) を改名し, core/mpb_time.c の TIM3 版を使う (make 版と同じ)
    dbg = os.path.join(core, "sdk", "Debug", "debug.c")
    s2 = open(dbg, encoding="utf-8").read()
    open(dbg, "w", encoding="utf-8").write("#if MPB_RTOS\n#define Delay_Us Sdk_Delay_Us\n#define Delay_Ms Sdk_Delay_Ms\n#endif\n" + s2)
    copy(os.path.join(FW, "common", "app.ld"), os.path.join(top, "ld", "app.ld"))
    copy(os.path.join(ROOT, "tools", "mpb_upload.py"), os.path.join(top, "tools", "mpb_upload.py"))
    copy(os.path.join(ROOT, "tools", "99-mpb.rules"), os.path.join(top, "tools", "99-mpb.rules"))
    for f in ("LICENSE", "NOTICE"):
        if os.path.exists(os.path.join(ROOT, f)):
            copy(os.path.join(ROOT, f), os.path.join(top, f))
    lib = os.path.join(top, "libraries", "mpbfun")
    copy_tree(os.path.join(FW, "lib"), os.path.join(lib, "src"), {".c", ".h"})
    # FreeRTOS (WCH SDK 同梱 V10.4.6) → libraries/MpbFreeRTOS/src (平らに置く)
    frt = os.path.join(top, "libraries", "MpbFreeRTOS", "src")
    for f in ("tasks.c", "list.c", "queue.c", "timers.c", "event_groups.c", "stream_buffer.c"):
        copy(os.path.join(FRT, f), os.path.join(frt, f))
    copy_tree(os.path.join(FRT, "include"), frt, {".h"})
    rv = os.path.join(FRT, "portable", "GCC", "RISC-V")
    for f in ("port.c", "portASM.S", "portmacro.h"):
        copy(os.path.join(rv, f), os.path.join(frt, f))
    copy(os.path.join(rv, "chip_specific_extensions", "RV32I_PFIC_no_extensions",
                      "freertos_risc_v_chip_specific_extensions.h"),
         os.path.join(frt, "freertos_risc_v_chip_specific_extensions.h"))
    copy(os.path.join(FRT, "portable", "MemMang", "heap_4.c"), os.path.join(frt, "heap_4.inc"))
    exdir = os.path.join(FW, "examples")
    for name in sorted(os.listdir(exdir)):
        src = os.path.join(exdir, name, "src")
        if not os.path.isfile(os.path.join(src, "sketch.c")):
            continue
        dst = os.path.join(top, "libraries", "MpbFreeRTOS" if name in RTOS_EXAMPLES else "mpbfun", "examples", name)
        os.makedirs(dst, exist_ok=True)
        copy(os.path.join(src, "sketch.c"), os.path.join(dst, name + ".ino"))
        cfg = open(os.path.join(src, "config.h"), encoding="utf-8").read()
        open(os.path.join(dst, "config.h"), "w", encoding="utf-8").write(arduino_config(cfg))
        if os.path.isfile(os.path.join(src, "FreeRTOSConfig.h")):
            copy(os.path.join(src, "FreeRTOSConfig.h"), os.path.join(dst, "FreeRTOSConfig.h"))
    return top


def make_archive(top, out):
    """決まった順序・時刻・所有者で tar → bzip2 (同じ入力なら同じバイト列)"""
    name = os.path.basename(top)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        entries = []
        for dp, dns, fns in os.walk(top):
            dns.sort()
            entries.append(dp)
            entries += [os.path.join(dp, f) for f in sorted(fns)]
        for p in sorted(entries):
            arc = os.path.join(name, os.path.relpath(p, top)).replace(os.sep, "/").rstrip("/.")
            ti = tar.gettarinfo(p, arcname=arc)
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            ti.mtime = 1767225600            # 2026-01-01
            ti.mode = 0o755 if ti.isdir() or p.endswith(".py") else 0o644
            if ti.isfile():
                with open(p, "rb") as f:
                    tar.addfile(ti, f)
            else:
                tar.addfile(ti)
    path = os.path.join(out, name + ".tar.bz2")
    with open(path, "wb") as f:
        f.write(bz2.compress(buf.getvalue(), 9))
    return path


def tools_entry(args):
    systems = []
    sizes = json.loads(args.tool_sizes) if args.tool_sizes else {}
    for suffix, (sha, hosts) in TOOLCHAIN.items():
        fn = tool_file(suffix)
        if args.tools_dir:
            p = os.path.join(args.tools_dir, fn)
            if not os.path.isfile(p):
                sys.exit(f"ツールチェーンがありません: {p}")
            got = sha256_file(p)
            if got != sha:
                sys.exit(f"SHA-256 が xPack の公開値と違います: {fn}\n  {got}\n  {sha}")
            url, size = args.release_url.rstrip("/") + "/" + fn, os.path.getsize(p)
        else:
            url, size = TOOL_UPSTREAM + fn, sizes.get(fn)
            if size is None:
                sys.exit(f"--tool-sizes に {fn} のサイズがありません")
        for h in hosts:
            systems.append({"host": h, "url": url, "archiveFileName": fn, "checksum": "SHA-256:" + sha,
                            "size": str(size)})
    return {"name": TOOL_NAME, "version": TOOL_VER, "systems": systems}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True, help="プラットフォームの版 (例 0.1.0)")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--release-url", help="アーカイブを置く URL (GitHub Releases のダウンロード先)")
    ap.add_argument("--tools-dir", help="ミラーする xPack のアーカイブがあるディレクトリ")
    ap.add_argument("--tool-sizes", help='xPack 本家を指すときのサイズ (JSON: {"ファイル名": バイト数})')
    ap.add_argument("--merge", help="既存の索引 (JSON) に版を足す (前の版も Boards Manager で選べるように)")
    ap.add_argument("--stage-only", action="store_true", help="展開した形だけ作る (アーカイブ・索引なし)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    top = stage(args.out, args.version)
    if args.stage_only:
        print(top)
        return
    if not args.release_url:
        sys.exit("--release-url が要ります")
    arc = make_archive(top, args.out)
    platform = {
        "name": "mPBCH32M030DS0", "architecture": ARCH, "version": args.version, "category": "Contributed",
        "help": {"online": REPO_URL}, "url": args.release_url.rstrip("/") + "/" + os.path.basename(arc),
        "archiveFileName": os.path.basename(arc), "checksum": "SHA-256:" + sha256_file(arc),
        "size": str(os.path.getsize(arc)), "boards": [{"name": "mPBCH32M030DS0 (CH32M030)"}],
        "toolsDependencies": [{"packager": PKG, "name": TOOL_NAME, "version": TOOL_VER}],
    }
    tool = tools_entry(args)
    index = {"packages": [{"name": PKG, "maintainer": "ghostinkoma", "websiteURL": REPO_URL,
                           "email": "sinhex.k@gmail.com", "help": {"online": REPO_URL},
                           "platforms": [], "tools": []}]}
    if args.merge and os.path.isfile(args.merge):
        index = json.load(open(args.merge, encoding="utf-8"))
    pk = index["packages"][0]
    pk["platforms"] = [p for p in pk["platforms"] if p["version"] != args.version] + [platform]
    pk["tools"] = [t for t in pk["tools"] if not (t["name"] == TOOL_NAME and t["version"] == TOOL_VER)] + [tool]
    path = os.path.join(args.out, f"package_{PKG}_index.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"{arc}\n  sha256 {platform['checksum'][8:]}  {platform['size']} bytes\n{path}")


if __name__ == "__main__":
    main()
