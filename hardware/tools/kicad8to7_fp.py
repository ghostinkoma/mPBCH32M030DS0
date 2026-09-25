#!/usr/bin/env python3
"""KiCad 8 形式 (20240108) のフットプリントを KiCad 7 形式 (20221018) へ変換する。

  python3 kicad8to7_fp.py in.kicad_mod out.kicad_mod

基板生成 (gen_pcb.py) は KiCad 7 の pcbnew Python で動かすため、KiCad 8 で作られた
フットプリントをこの形式へ落とす。形状 (パッド・外形・シルク) は変えない。
"""
import re
import sys


def parse(s):
    toks = re.findall(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+', s)
    pos = 0

    def rd():
        nonlocal pos
        t = toks[pos]
        pos += 1
        if t == "(":
            lst = []
            while toks[pos] != ")":
                lst.append(rd())
            pos += 1
            return lst
        return t
    return rd()


def dump(x, ind=0):
    if not isinstance(x, list):
        return x
    if all(not isinstance(e, list) for e in x):
        return "(" + " ".join(x) + ")"
    parts = [dump(e, ind + 1) for e in x]
    return "(" + " ".join(p if not p.startswith("(") else "\n" + "  " * (ind + 1) + p for p in parts) + ")"


def conv(x):
    if not isinstance(x, list):
        return x
    head = x[0] if x else None
    out = [head]
    for e in x[1:]:
        if isinstance(e, list) and e:
            h = e[0]
            if h in ("uuid", "generator_version", "unlocked", "embedded_fonts"):
                continue
            if h == "hide" and e[1:] == ["yes"]:
                out.append("hide")
                continue
            if h == "hide" and e[1:] == ["no"]:
                continue
            if h == "remove_unused_layers":
                if e[1:] != ["no"]:
                    out.append(["remove_unused_layers"])
                continue
            if h == "fill" and e[1:] in (["yes"], ["no"]):
                out.append(["fill", "solid" if e[1] == "yes" else "none"])
                continue
            if h == "version":
                out.append(["version", "20221018"])
                continue
            if h == "property" and head == "footprint":
                key = e[1].strip('"')
                if key in ("Reference", "Value"):
                    out.append(["fp_text", key.lower(), e[2]] + [conv(q) for q in e[3:]])
                continue
        out.append(conv(e))
    return out


src = open(sys.argv[1], encoding="utf-8").read()
tree = conv(parse(src))
open(sys.argv[2], "w", encoding="utf-8").write(dump(tree) + "\n")
