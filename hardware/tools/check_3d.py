#!/usr/bin/env python3
"""3D 干渉チェック (KiCad の STEP 出力を CadQuery/OCP で読む)。

  python3 tools/check_3d.py <board.step> [<board.step> ...]          # 基板ごとの部品どうしの干渉
  python3 tools/check_3d.py --stack <daughter.step> <module_flipped.step> --dx 0 --dz 12.6
                                                                     # モジュールを子基板のソケットへ挿した状態の干渉

STEP は `kicad-cli pcb export step --subst-models --user-origin 0x0mm` で書き出したもの (部品名 = リファレンス)。
重なり体積が 0.001 mm³ を超える組を干渉とする。基板 (PCB) との重なりは THT のピンが穴を通るので対象外。
"""
import argparse
import re
import sys

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.Bnd import Bnd_Box
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.gp import gp_Trsf, gp_Vec
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFDoc import XCAFDoc_DocumentTool

EPS_VOL = 1e-3


def label_name(lab):
    attr = TDataStd_Name()
    if lab.FindAttribute(TDataStd_Name.GetID_s(), attr):
        return attr.Get().ToExtString()
    return ""


def read_parts(path):
    """STEP の最上位アセンブリ直下の部品 (インスタンス) を (名前, 形状) の並びで返す."""
    doc = TDocStd_Document(TCollection_ExtendedString("doc"))
    rd = STEPCAFControl_Reader()
    rd.SetNameMode(True)
    assert rd.ReadFile(path) == IFSelect_RetDone, path
    rd.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    tops = TDF_LabelSequence()
    st.GetFreeShapes(tops)
    parts = []

    def walk(lab, loc, name):
        if st.IsReference_s(lab):
            ref = lab.__class__()
            st.GetReferredShape_s(lab, ref)
            nm = name or label_name(lab)         # 最上位の参照名 (= リファレンス) を残す
            walk(ref, loc.Multiplied(st.GetLocation_s(lab)), nm)
            return
        if st.IsAssembly_s(lab):
            comps = TDF_LabelSequence()
            st.GetComponents_s(lab, comps)
            for i in range(1, comps.Length() + 1):
                walk(comps.Value(i), loc, name)
            return
        shp = st.GetShape_s(lab).Moved(loc)
        parts.append((name or label_name(lab), shp))

    for i in range(1, tops.Length() + 1):
        walk(tops.Value(i), TopLoc_Location(), "")
    # 同じ部品 (リファレンス) の形状をまとめる
    merged = {}
    for n, s in parts:
        key = n.split(" ")[0]
        merged.setdefault(key, []).append(s)
    return merged


def bbox(shapes):
    b = Bnd_Box()
    for s in shapes:
        BRepBndLib.Add_s(s, b)
    return b


def moved(shapes, dx, dy, dz):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, dz))
    return [BRepBuilderAPI_Transform(s, t, True).Shape() for s in shapes]


def common_volume(a_list, b_list):
    v = 0.0
    for a in a_list:
        for b in b_list:
            c = BRepAlgoAPI_Common(a, b).Shape()
            g = GProp_GProps()
            BRepGProp.VolumeProperties_s(c, g)
            v += abs(g.Mass())
    return v


def min_gap(a_list, b_list):
    d = 1e9
    for a in a_list:
        for b in b_list:
            e = BRepExtrema_DistShapeShape(a, b)
            if e.IsDone():
                d = min(d, e.Value())
    return d


def is_board(name):
    return name.startswith("=>") or name.upper().endswith("PCB") or name.upper().startswith("PCB") or "_PCB" in name.upper()


def clashes(A, B=None, skip=lambda a, b: False, near=0.1):
    """A (と B) の部品どうしの干渉。near mm 未満の近接も報告する."""
    out, close = [], []
    names_a = [n for n in A if not is_board(n)]
    pairs = ([(a, b) for i, a in enumerate(names_a) for b in names_a[i + 1:]] if B is None else
             [(a, b) for a in names_a for b in B if not is_board(b)])
    src_b = A if B is None else B
    boxes = {("A", n): bbox(A[n]) for n in names_a}
    boxes.update({("B", n): bbox(src_b[n]) for n in src_b if not is_board(n)})
    for a, b in pairs:
        if skip(a, b):
            continue
        ba, bb_ = boxes[("A", a)], boxes[("B" if B is not None else "A", b)] if B is not None else boxes[("A", b)]
        g = ba.Distance(bb_) if not ba.IsOut(bb_) else ba.Distance(bb_)
        if ba.IsOut(bb_) and g > near:
            continue
        v = common_volume(A[a], src_b[b])
        if v > EPS_VOL:
            out.append((a, b, v))
        else:
            gap = min_gap(A[a], src_b[b])
            if gap < near:
                close.append((a, b, gap))
    return out, close


def zrange(shapes):
    b = bbox(shapes)
    x0, y0, z0, x1, y1, z1 = b.Get()
    return z0, z1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("steps", nargs="+")
    ap.add_argument("--stack", action="store_true")
    ap.add_argument("--dx", type=float, default=0.0)
    ap.add_argument("--dz", type=float, default=12.6)
    ap.add_argument("--heatsink", action="store_true", help="下面で MOSFET より背の高い部品を調べる")
    a = ap.parse_args()
    if not a.stack:
        for p in a.steps:
            P = read_parts(p)
            bad, close = clashes(P)
            print(f"== {p}: parts {len(P)}, interferences {len(bad)}, near (<0.1mm) {len(close)}")
            for x, y, v in bad:
                print(f"   CLASH {x} x {y}: {v:.3f} mm3")
            for x, y, g in close:
                print(f"   near  {x} - {y}: {g:.3f} mm")
            if a.heatsink:
                # ヒートシンクはレッグの MOSFET (Q1〜Q8) を覆う範囲 (その外接矩形 + 0.5mm) に当てる
                box = {n: bbox(s).Get() for n, s in P.items() if not is_board(n)}
                bot = {n: b for n, b in box.items() if b[5] <= 0.01}          # 下面の部品 (Z < 0)
                fets = {n: b for n, b in bot.items() if re.fullmatch(r"Q[1-8]", n)}
                if fets:
                    h = min(-b[2] for b in fets.values())
                    X0, Y0 = min(b[0] for b in fets.values()) - 0.5, min(b[1] for b in fets.values()) - 0.5
                    X1, Y1 = max(b[3] for b in fets.values()) + 0.5, max(b[4] for b in fets.values()) + 0.5
                    under = lambda b: b[0] < X1 and b[3] > X0 and b[1] < Y1 and b[4] > Y0
                    tall = sorted(((-b[2], n) for n, b in bot.items()
                                   if n not in fets and under(b) and -b[2] > h - 1e-3), reverse=True)
                    print(f"   heatsink: MOSFET の下面高さ (最小) {h:.2f} mm, 範囲 x {X0:.1f}〜{X1:.1f} y {Y0:.1f}〜{Y1:.1f}; "
                          "その範囲でそれより高い下面部品: " + (", ".join(f"{n} {hh:.2f}" for hh, n in tall) or "なし"))
        return
    D, M = read_parts(a.steps[0]), read_parts(a.steps[1])
    M = {n: moved(s, a.dx, 0, a.dz) for n, s in M.items()}
    pins = lambda x, y: {x, y} <= {"J1", "J2"} or (x in ("J1", "J2") and y in ("J1", "J2"))
    bad, close = clashes(M, D, skip=pins, near=0.5)
    # 基板どうし (モジュール基板 × 子基板の部品, 子基板 × モジュールの部品)
    mb = [n for n in M if is_board(n)]
    db = [n for n in D if is_board(n)]
    for n in D:
        if is_board(n) or n in ("J1", "J2"):
            continue
        v = common_volume(M[mb[0]], D[n]) if mb else 0
        if v > EPS_VOL:
            bad.append((mb[0], n, v))
    print(f"== stack {a.steps[1]} on {a.steps[0]} (dx={a.dx}, dz={a.dz}): interferences {len(bad)}, near (<0.5mm) {len(close)}")
    for x, y, v in bad:
        print(f"   CLASH module:{x} x daughter:{y}: {v:.3f} mm3")
    for x, y, g in close:
        print(f"   near  module:{x} - daughter:{y}: {g:.3f} mm")
    # モジュール下面と子基板上面の最小すき間
    mz = min(zrange(M[n])[0] for n in M if not is_board(n) and n not in ("J1", "J2"))
    dz = max(zrange(D[n])[1] for n in D if not is_board(n) and n not in ("J1", "J2"))
    print(f"   module lowest part z={mz:.2f} mm, daughter tallest top part z={dz:.2f} mm")


if __name__ == "__main__":
    sys.exit(main())
