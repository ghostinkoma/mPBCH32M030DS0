#!/usr/bin/env python3
"""
基板生成の共通処理 (KiCad 8 pcbnew Python + Freerouting)。gen_pcb.py から使う。
KiCad 8 の Python (pcbnew 8.0.x) で動かす。KiCad 7 でも動くが出力は 7 形式になる。

  - parts.json (gen_schematic.py の出力) から部品とネットを読み込み, フットプリントを配置
  - 外形・取付穴・シルク・GND ベタ (両面)・大電流ネットのベタを生成
  - Specctra DSN を書き出して Freerouting で自動配線し, SES を読み戻す
  - ベタ塗り → GND スティッチングビア → DRC レポート

フットプリントは KiCad 標準ライブラリ (環境変数 KICAD8_FOOTPRINT_DIR, 既定 /usr/share/kicad/footprints) と hardware/lib を使う。
"""
import json
import math
import os
import re
import subprocess
import tempfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
STD_FP = os.environ.get("KICAD8_FOOTPRINT_DIR", os.environ.get("KICAD7_FOOTPRINT_DIR", "/usr/share/kicad/footprints"))
KICAD7 = pcbnew.Version().startswith("7")
FREEROUTING = os.environ.get("FREEROUTING_JAR", os.path.join(HERE, "tools", "freerouting-1.9.0.jar"))
MM = pcbnew.FromMM


def P(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


LAYER = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu, "F.SilkS": pcbnew.F_SilkS, "B.SilkS": pcbnew.B_SilkS,
         "F.Fab": pcbnew.F_Fab, "B.Fab": pcbnew.B_Fab, "Cmts.User": pcbnew.Cmts_User, "Dwgs.User": pcbnew.Dwgs_User}


def pcblib_pt(v):
    return pcbnew.ToMM(v.x), pcbnew.ToMM(v.y)


def to_mm(v):
    return pcbnew.ToMM(v.x), pcbnew.ToMM(v.y)


_fp_cache_dir = None


def run_freerouting(dsn, ses, passes, opts=(), log=None, timeout=3600):
    """Freerouting を実行する。MPB_FR_BRIDGE=1 (KiCad 8 の chroot 内) ではホスト側の tools/fr_bridge.sh に依頼する."""
    import time
    if os.environ.get("MPB_FR_BRIDGE"):
        done = ses + ".frdone"
        for f in (ses, done):
            if os.path.exists(f):
                os.remove(f)
        jar = os.environ.get("MPB_FR_JAR")          # 例: freerouting-2.1.0.jar (tools/ に置く)
        head = ["@" + jar] if jar else []
        if jar and not jar.startswith("freerouting-1."):
            opts = list(opts) + ["--gui.enabled=false", "-mt", "1"]
        with open(dsn + ".frreq", "w") as f:
            f.write(" ".join(head + [os.path.basename(dsn), os.path.basename(ses), str(passes)] + list(opts)))
        t0 = time.time()
        while not os.path.exists(done):
            if time.time() - t0 > timeout:
                raise TimeoutError("freerouting bridge timeout")
            time.sleep(3)
        os.remove(done)
        return
    cmd = ["xvfb-run", "-a", "java", "-Djava.awt.headless=false", "-jar", FREEROUTING,
           "-de", dsn, "-do", ses, "-mp", str(passes)] + list(opts)
    with open(log or dsn + ".frlog", "w") as lf:
        subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)


def _local_lib(nick):
    """hardware/lib の KiCad 8 形式ライブラリは一時ディレクトリで KiCad 7 形式に変換して読む."""
    global _fp_cache_dir
    src = os.path.join(HERE, "lib", nick + ".pretty")
    head = ""
    for f in os.listdir(src):
        head += open(os.path.join(src, f), encoding="utf-8").read(200)
    if "20240108" not in head or not KICAD7:   # KiCad 8 はそのまま読める
        return src
    if _fp_cache_dir is None:
        _fp_cache_dir = tempfile.mkdtemp(prefix="mpb_fp7_")
    dst = os.path.join(_fp_cache_dir, nick + ".pretty")
    if not os.path.isdir(dst):
        os.makedirs(dst)
        for f in os.listdir(src):
            subprocess.check_call(["python3", os.path.join(HERE, "tools", "kicad8to7_fp.py"),
                                   os.path.join(src, f), os.path.join(dst, f)])
    return dst


def load_fp(libid):
    nick, name = libid.split(":")
    d = os.path.join(HERE, "lib", nick + ".pretty")
    d = _local_lib(nick) if os.path.isdir(d) else os.path.join(STD_FP, nick + ".pretty")
    fp = pcbnew.FootprintLoad(d, name)
    assert fp is not None, f"footprint not found: {libid} ({d})"
    return fp


class Pcb:
    def __init__(self, prjdir, W, H, title, rev="0.3"):
        self.dir = os.path.join(HERE, prjdir)
        data = json.load(open(os.path.join(self.dir, "parts.json"), encoding="utf-8"))
        self.name = data["name"]
        self.W, self.H = W, H
        b = self.b = pcbnew.BOARD()
        b.SetCopperLayerCount(2)
        lset = pcbnew.LSET.AllNonCuMask()
        lset.AddLayer(pcbnew.F_Cu)
        lset.AddLayer(pcbnew.B_Cu)
        b.SetEnabledLayers(lset)
        b.SetVisibleLayers(lset)
        ds = b.GetDesignSettings()
        # JLCPCB 等の標準 2 層プロセスで作れる値 (0.35mm ピッチ QFN のため 0.127mm を許容)
        ds.m_TrackMinWidth = MM(0.127)
        ds.m_MinClearance = MM(0.127)
        ds.m_ViasMinSize = MM(0.5)
        ds.m_MinThroughDrill = MM(0.2)          # QFN 裏面パッドのサーマルビア 0.2mm
        ds.m_CopperEdgeClearance = MM(0.25)
        ds.m_HoleToHoleMin = MM(0.25)
        ds.m_HoleClearance = MM(0.15)           # USB-C フットプリント自身の NPTH-パッド間 0.19mm を許容
        ds.m_MinSilkTextHeight = MM(0.6)
        ds.m_MinResolvedSpokes = 1
        ns = ds.m_NetSettings
        dflt = ns.m_DefaultNetClass
        dflt.SetTrackWidth(MM(0.15))
        dflt.SetClearance(MM(0.13))
        dflt.SetViaDiameter(MM(0.6))
        dflt.SetViaDrill(MM(0.3))
        self.classes = {}
        for cname, tw, cl, vd, vdr in (("Power", 0.4, 0.2, 0.8, 0.4), ("HiCur", 1.0, 0.2, 1.0, 0.5)):
            nc = pcbnew.NETCLASS(cname)
            nc.SetTrackWidth(MM(tw))
            nc.SetClearance(MM(cl))
            nc.SetViaDiameter(MM(vd))
            nc.SetViaDrill(MM(vdr))
            ns.m_NetClasses[cname] = nc
            self.classes[cname] = nc
        tb = b.GetTitleBlock()
        tb.SetTitle(title)
        tb.SetRevision(rev)
        tb.SetCompany("ghostinkoma")
        tb.SetComment(0, "個人利用可 (クレジット表示必須) / 商用利用は要連絡 / 無保証 - LICENSE 参照")
        self.nets = {}
        self.assign = {}
        self.fps = {}
        self.parts = {p["ref"]: p for p in data["parts"]}
        for p in data["parts"]:
            fp = load_fp(p["fp"])
            fp.SetReference(p["ref"])
            fp.SetValue(p["value"])
            fp.Reference().SetTextSize(pcbnew.VECTOR2I(MM(0.7), MM(0.7)))
            fp.Reference().SetTextThickness(MM(0.1))
            fp.Value().SetVisible(False)
            if any(k in p["fp"] for k in ("0402", "0603", "0805", "1206_3216", "SOD-123", "SOT-23")):
                fp.Reference().SetLayer(pcbnew.F_Fab)  # 小型部品の参照番号は組立図 (Fab) のみ
            for pad in fp.Pads():
                num = pad.GetNumber()
                if num == "0" and "49" in p["nets"]:  # QFN 裏面パッドのサーマルビア
                    num = "49"
                net = p["nets"].get(num)
                if net:
                    pad.SetNet(self.net(net))
            b.Add(fp)
            self.fps[p["ref"]] = fp
        self.placed = set()
        self.zones_spec = []

    def assign_hicur(self):
        return {n for n, c in self.assign.items() if c == "HiCur" and n != "GND"}

    def net(self, name):
        if name not in self.nets:
            n = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(n)
            self.nets[name] = n
        return self.nets[name]

    def netclass(self, cname, names):
        for n in names:
            if n in self.nets:
                self.nets[n].SetNetClass(self.classes[cname])
                self.assign[n] = cname

    # ---- 配置 ----------------------------------------------------------------
    def place(self, ref, x, y, rot=0, side="F"):
        fp = self.fps[ref]
        if fp.IsFlipped():
            fp.Flip(fp.GetPosition(), False)
        fp.SetPosition(P(x, y))
        fp.SetOrientationDegrees(rot)
        if side == "B":
            fp.Flip(fp.GetPosition(), False)
        self.placed.add(ref)
        return fp

    def bbox(self, ref):
        fp = self.fps[ref]
        cy = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
        if cy.OutlineCount():
            bb = cy.BBox()
        else:
            bb = fp.GetBoundingBox(False, False)
        return (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()),
                pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))

    def pack(self, refs, x0, y0, x1, rot=0, side="F", gap=0.25, row_gap=0.35):
        """refs を (x0, y0) から右へ並べ, x1 を超えたら次の行へ。行の下端 y を返す."""
        x, y, rowh = x0, y0, 0.0
        for ref in refs:
            self.place(ref, 0, 0, rot, side)
            l, t, r, btm = self.bbox(ref)
            w, h = r - l, btm - t
            if x + w > x1 + 1e-6 and x > x0:
                x, y, rowh = x0, y + rowh + row_gap, 0.0
            self.place(ref, x - l, y - t, rot, side)
            x += w + gap
            rowh = max(rowh, h)
        return y + rowh

    def pad_xy(self, ref, num):
        for pad in self.fps[ref].Pads():
            if pad.GetNumber() == num:
                return to_mm(pad.GetPosition())
        raise KeyError(f"{ref}.{num}")

    def check_overlaps(self):
        """同じ面の courtyard 重なりと, 反対面の部品と THT パッド (穴) の干渉を調べる."""
        bad = []
        refs = sorted(self.placed)
        pth = {r: [(to_mm(p.GetPosition()), pcbnew.ToMM(max(p.GetSize().x, p.GetSize().y)) / 2)
                   for p in self.fps[r].Pads() if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)]
               for r in refs}
        box = {r: self.bbox(r) for r in refs}
        for i, a in enumerate(refs):
            for c in refs[i + 1:]:
                la, ta, ra, ba = box[a]
                lc, tc, rc, bc = box[c]
                if not (la < rc - 0.01 and lc < ra - 0.01 and ta < bc - 0.01 and tc < ba - 0.01):
                    continue
                if self.fps[a].IsFlipped() == self.fps[c].IsFlipped():
                    bad.append((a, c))
                    continue
                for u, v in ((a, c), (c, a)):
                    l, t, r, btm = box[v]
                    if any(l - rad < x < r + rad and t - rad < y < btm + rad for (x, y), rad in pth[u]):
                        bad.append((a, c))
                        break
        missing = set(self.fps) - self.placed
        out = []
        for ref, bb in ((r, self.bbox(r)) for r in refs):
            if bb[0] < -0.01 or bb[1] < -0.01 or bb[2] > self.W + 0.01 or bb[3] > self.H + 0.01:
                out.append(ref)
        return bad, missing, out

    # ---- 外形・装飾 ------------------------------------------------------------
    def outline(self, r=1.0):
        W, H = self.W, self.H
        segs = [((r, 0), (W - r, 0)), ((W, r), (W, H - r)), ((W - r, H), (r, H)), ((0, H - r), (0, r))]
        for a, c in segs:
            s = pcbnew.PCB_SHAPE(self.b)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(P(*a))
            s.SetEnd(P(*c))
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetWidth(MM(0.1))
            self.b.Add(s)
        for cx, cy, a0 in ((r, r, 180), (W - r, r, 270), (W - r, H - r, 0), (r, H - r, 90)):
            s = pcbnew.PCB_SHAPE(self.b)
            s.SetShape(pcbnew.SHAPE_T_ARC)
            s.SetCenter(P(cx, cy))
            st = (cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0)))
            s.SetStart(P(*st))
            s.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(90, pcbnew.DEGREES_T), True)
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetWidth(MM(0.1))
            self.b.Add(s)

    def text(self, s, x, y, size=1.0, layer="F.SilkS", rot=0, bold=False):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetPosition(P(x, y))
        t.SetLayer(LAYER[layer])
        t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
        t.SetTextThickness(MM(max(0.1, size * (0.2 if bold else 0.14))))
        t.SetTextAngleDegrees(rot)
        if layer.startswith("B."):
            t.SetMirrored(True)
        self.b.Add(t)
        return t

    def zone(self, net, layer, pts, priority=0, name=""):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(LAYER[layer])
        z.SetNet(self.net(net))
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(MM(0.25))
        z.SetMinThickness(MM(0.2))
        z.SetThermalReliefGap(MM(0.3))
        z.SetThermalReliefSpokeWidth(MM(0.4))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)  # SMD は全面接続, THT のみサーマル
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetZoneName(name or f"{net}_{layer}")
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(MM(x), MM(y))
        self.b.Add(z)
        return z

    def edge_keepout(self, w=0.5):
        """基板端から w mm は配線・ビア禁止 (Freerouting へ keepout として渡す)."""
        W, H = self.W, self.H
        for x0, y0, x1, y1 in ((0, 0, W, w), (0, H - w, W, H), (0, 0, w, H), (W - w, 0, W, H)):
            z = pcbnew.ZONE(self.b)
            z.SetIsRuleArea(True)
            z.SetDoNotAllowTracks(True)
            z.SetDoNotAllowVias(True)
            z.SetDoNotAllowCopperPour(False)
            z.SetDoNotAllowPads(False)
            z.SetDoNotAllowFootprints(False)
            ls = pcbnew.LSET()
            ls.AddLayer(pcbnew.F_Cu)
            ls.AddLayer(pcbnew.B_Cu)
            z.SetLayerSet(ls)
            ol = z.Outline()
            ol.NewOutline()
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                ol.Append(MM(x), MM(y))
            self.b.Add(z)

    def grow_zones(self, nets, grow=1.2, priority=2):
        """配線済みの大電流ネットの周囲 grow mm をベタにする (他ネットとの間隙はベタ塗りが確保)."""
        n = 0
        for net in nets:
            if net not in self.nets:
                continue
            for layer, lname in ((pcbnew.F_Cu, "F.Cu"), (pcbnew.B_Cu, "B.Cu")):
                poly = pcbnew.SHAPE_POLY_SET()

                def add(pts):
                    poly.NewOutline()
                    for x, y in pts:
                        poly.Append(MM(x), MM(y))

                def octa(cx, cy, r):
                    add([(cx + r * math.cos(math.pi / 8 + k * math.pi / 4) / math.cos(math.pi / 8),
                          cy + r * math.sin(math.pi / 8 + k * math.pi / 4) / math.cos(math.pi / 8)) for k in range(8)])

                for t in self.b.GetTracks():
                    if t.GetNetname() != net:
                        continue
                    if t.GetClass() == "PCB_VIA":
                        x, y = to_mm(t.GetPosition())
                        octa(x, y, pcbnew.ToMM(t.GetWidth()) / 2 + grow)
                    elif t.GetLayer() == layer:
                        (x1, y1), (x2, y2) = to_mm(t.GetStart()), to_mm(t.GetEnd())
                        hw = pcbnew.ToMM(t.GetWidth()) / 2 + grow
                        L = math.hypot(x2 - x1, y2 - y1)
                        if L > 1e-6:
                            nx, ny = -(y2 - y1) / L * hw, (x2 - x1) / L * hw
                            add([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])
                        octa(x1, y1, hw)
                        octa(x2, y2, hw)
                # 配線が来ているパッドだけを太らせる (未配線のパッドを孤立したベタで覆うと, 補修で見つけられない)
                ends = [to_mm(p) for t in self.b.GetTracks() if t.GetNetname() == net
                        for p in ((t.GetStart(), t.GetEnd()) if t.GetClass() != "PCB_VIA" else (t.GetPosition(),))]
                for fp in self.b.GetFootprints():
                    for pad in fp.Pads():
                        if pad.GetNetname() == net and pad.IsOnLayer(layer):
                            bb = pad.GetBoundingBox()
                            l, t_, r, b_ = (pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
                            if not any(l - 0.05 <= x <= r + 0.05 and t_ - 0.05 <= y <= b_ + 0.05 for x, y in ends):
                                continue
                            add([(l - grow, t_ - grow), (r + grow, t_ - grow), (r + grow, b_ + grow), (l - grow, b_ + grow)])
                if poly.OutlineCount() == 0:
                    continue
                poly.Simplify(False)  # PM_STRICTLY_SIMPLE
                for i in range(poly.OutlineCount()):
                    ch = poly.Outline(i)
                    pts = [pcblib_pt(ch.CPoint(k)) for k in range(ch.PointCount())]
                    pts = [(min(max(x, 0.3), self.W - 0.3), min(max(y, 0.3), self.H - 0.3)) for x, y in pts]
                    if len(pts) >= 3:
                        self.zone(net, lname, pts, priority=priority, name=f"{net}_{lname}_grow{i}")
                        n += 1
        return n

    def rect_zone(self, net, layer, x0, y0, x1, y1, priority=0):
        return self.zone(net, layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], priority)

    # ---- 自動配線 ---------------------------------------------------------------
    def autoroute(self, passes=None, timeout=None, reuse=False, opts=()):
        """reuse=True: 配置が同じ (DSN が前回と同一) なら前回の SES を再利用する."""
        passes = passes or int(os.environ.get("MPB_FR_PASSES", "40"))
        timeout = timeout or int(os.environ.get("MPB_FR_TIMEOUT", "10800"))
        work = os.path.join(self.dir, "build")
        os.makedirs(work, exist_ok=True)
        dsn = os.path.join(work, self.name + ".dsn")
        ses = os.path.join(work, self.name + ".ses")
        old = open(dsn, encoding="utf-8").read() if os.path.exists(dsn) else None
        assert pcbnew.ExportSpecctraDSN(self.b, dsn), "DSN export failed"
        self._dsn_classes(dsn)
        # KiCad は keepout やネットのピン順を毎回違う順で書き出すので, 字句の集合として比較する
        strip = lambda t: (sorted(re.findall(r"[^\s()]+", re.sub(r"\(pcb [^\n]*|\(host_version[^\n]*", "", t or ""))),
                           sorted(re.findall(r"\(class [^\n]*", t or "")))       # ネットクラスの所属も比較
        if reuse and os.path.exists(ses) and strip(old) == strip(open(dsn, encoding="utf-8").read()):
            return self.import_ses(ses)
        if os.path.exists(ses):
            os.remove(ses)
        run_freerouting(dsn, ses, passes, opts, os.path.join(work, "freerouting.log"), timeout)
        assert os.path.exists(ses), "freerouting produced no SES (see build/freerouting.log)"
        return self.import_ses(ses)

    def _dsn_classes(self, dsn):
        """DSN のネットクラス一覧へ self.assign の割当を書き込む
        (standalone の pcbnew はプロジェクトのパターン割当を DSN に反映しないため)."""
        txt = open(dsn, encoding="utf-8").read()
        m = re.search(r"\(class kicad_default ((?:\s*(?:\"[^\"]*\"|[^\s()]+))*)", txt)
        names = re.findall(r'"[^"]*"|[^\s()]+', m.group(1))
        keep = [n for n in names if n.strip('"') not in self.assign]
        txt = txt[:m.start(1)] + " " + " ".join(keep) + "\n      " + txt[m.end(1):]
        for cname in set(self.assign.values()):
            nets = [n for n, c in sorted(self.assign.items()) if c == cname]
            txt = re.sub(r"\(class %s\b[^\n(]*" % re.escape(cname),
                         "(class %s %s\n      " % (cname, " ".join(nets)), txt, count=1)
        open(dsn, "w", encoding="utf-8").write(txt)

    def second_pass(self, passes=30, opts=()):
        """配線済みの状態から Freerouting をもう一度走らせ, 残った未接続を引き剥がし再配線で解消する."""
        work = os.path.join(self.dir, "build")
        dsn = os.path.join(work, self.name + "_pass2.dsn")
        ses = os.path.join(work, self.name + "_pass2.ses")
        zones = [z for z in self.b.Zones() if not z.GetIsRuleArea()]
        for z in zones:
            self.b.Remove(z)
        assert pcbnew.ExportSpecctraDSN(self.b, dsn)
        self._dsn_classes(dsn)
        if os.path.exists(ses):
            os.remove(ses)
        run_freerouting(dsn, ses, passes, opts, os.path.join(work, "freerouting_pass2.log"))
        for z in zones:
            self.b.Add(z)
        if not os.path.exists(ses):
            return None
        for t in list(self.b.GetTracks()):
            self.b.Remove(t)
        r = self.import_ses(ses)
        self.b.BuildConnectivity()
        return r

    def import_ses(self, ses):
        txt = open(ses, encoding="utf-8").read()
        m = re.search(r"\(resolution\s+(\w+)\s+(\d+)\)", txt)
        unit, res = m.group(1), int(m.group(2))
        scale = {"um": 1e-3, "mm": 1.0, "mil": 0.0254, "inch": 25.4}[unit] / res
        # via 形状 (padstack 名 → 直径/ドリル) は DSN 側の名前 "Via[0-1]_600:300_um" から読む
        ntracks = nvias = 0
        pos = txt.index("(network_out")
        for nm in re.finditer(r'\(net\s+("[^"]*"|\S+)', txt[pos:]):
            start = pos + nm.start()
            depth, i = 0, start
            while True:
                ch = txt[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = txt[start:i]
            name = nm.group(1).strip('"')
            net = self.nets.get(name)
            if net is None:
                continue
            for w in re.finditer(r"\(wire\s+\(path\s+(\S+)\s+([\d.]+)((?:\s+-?[\d.]+)+)\s*\)", body):
                layer = LAYER[w.group(1)]
                width = float(w.group(2)) * scale
                c = [float(v) * scale for v in w.group(3).split()]
                pts = [(c[k], -c[k + 1]) for k in range(0, len(c), 2)]
                for a, e in zip(pts, pts[1:]):
                    t = pcbnew.PCB_TRACK(self.b)
                    t.SetStart(P(*a))
                    t.SetEnd(P(*e))
                    t.SetWidth(MM(width))
                    t.SetLayer(layer)
                    t.SetNet(net)
                    self.b.Add(t)
                    ntracks += 1
            for v in re.finditer(r'\(via\s+"?([^"\s]+)"?\s+(-?[\d.]+)\s+(-?[\d.]+)', body):
                mv = re.search(r"_(\d+):(\d+)_um", v.group(1))
                dia, drill = (int(mv.group(1)) / 1000, int(mv.group(2)) / 1000) if mv else (0.6, 0.3)
                via = pcbnew.PCB_VIA(self.b)
                via.SetPosition(P(float(v.group(2)) * scale, -float(v.group(3)) * scale))
                via.SetWidth(MM(dia))
                via.SetDrill(MM(drill))
                via.SetNet(net)
                self.b.Add(via)
                nvias += 1
        return ntracks, nvias

    # ---- ベタ・スティッチング・DRC ------------------------------------------------
    def fill(self):
        pcbnew.ZONE_FILLER(self.b).Fill(self.b.Zones())

    def stitch(self, net="GND", pitch=3.0, dia=0.6, drill=0.3, margin=0.35):
        """両面の GND ベタが重なり, 他の銅から十分離れた格子点に GND ビアを打つ."""
        zf = [z for z in self.b.Zones() if z.GetNetname() == net and z.GetLayer() == pcbnew.F_Cu]
        zb = [z for z in self.b.Zones() if z.GetNetname() == net and z.GetLayer() == pcbnew.B_Cu]
        r = dia / 2 + margin
        n = 0

        def inside(zs, layer, x, y):
            for z in zs:
                polys = z.GetFilledPolysList(layer)
                ok = all(polys.Contains(P(x + r * math.cos(a), y + r * math.sin(a)))
                         for a in [k * math.pi / 4 for k in range(8)]) and polys.Contains(P(x, y))
                if ok:
                    return True
            return False

        existing = [to_mm(v.GetPosition()) for v in self.b.GetTracks() if v.GetClass() == "PCB_VIA"]
        holes = []
        for fp in self.b.GetFootprints():
            for pad in fp.Pads():
                if pad.GetDrillSize().x > 0:
                    holes.append(to_mm(pad.GetPosition()))
        y = pitch / 2
        while y < self.H:
            x = pitch / 2
            while x < self.W:
                if (inside(zf, pcbnew.F_Cu, x, y) and inside(zb, pcbnew.B_Cu, x, y) and
                        all(math.hypot(x - ex, y - ey) > 1.2 for ex, ey in existing + holes)):
                    v = pcbnew.PCB_VIA(self.b)
                    v.SetPosition(P(x, y))
                    v.SetWidth(MM(dia))
                    v.SetDrill(MM(drill))
                    v.SetNet(self.net(net))
                    self.b.Add(v)
                    existing.append((x, y))
                    n += 1
                x += pitch
            y += pitch
        return n

    def stitch_islands(self, dia=0.6, drill=0.3, margin=0.3, step=0.4):
        """ベタの各島に最低 1 本, 反対面の同じネットのベタへ落ちるビアを打つ (孤立した島をなくす)."""
        n = 0
        r = dia / 2 + margin
        ring = [k * math.pi / 4 for k in range(8)]
        vias = [to_mm(v.GetPosition()) for v in self.b.GetTracks() if v.GetClass() == "PCB_VIA"]
        holes = vias + [to_mm(pd.GetPosition()) for fp in self.b.GetFootprints() for pd in fp.Pads()
                        if pd.GetDrillSize().x > 0]
        for z in list(self.b.Zones()):
            if z.GetIsRuleArea():
                continue
            net, layer = z.GetNetname(), z.GetLayer()
            other = pcbnew.B_Cu if layer == pcbnew.F_Cu else pcbnew.F_Cu
            others = [o for o in self.b.Zones() if o.GetNetname() == net and o.GetLayer() == other
                      and not o.GetIsRuleArea()]
            polys = z.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                ol = polys.Outline(i)
                pts = [to_mm(ol.CPoint(k)) for k in range(ol.PointCount())]
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                # 既にビアや THT パッドが島の中にあれば不要
                single = pcbnew.SHAPE_POLY_SET()
                single.AddOutline(ol)
                if any(single.Contains(P(x, y)) for x, y in vias):
                    continue
                if any(single.Contains(pad.GetPosition()) for fp in self.b.GetFootprints() for pad in fp.Pads()
                       if pad.GetNetname() == net and pad.GetDrillSize().x > 0):
                    continue
                done = False
                y = min(ys) + r
                while y < max(ys) - r and not done:
                    x = min(xs) + r
                    while x < max(xs) - r:
                        ok = single.Contains(P(x, y)) and all(single.Contains(P(x + r * math.cos(a), y + r * math.sin(a)))
                                                              for a in ring) and \
                            all(math.hypot(x - hx, y - hy) > 0.9 for hx, hy in holes)
                        if ok:
                            for o in others:
                                op = o.GetFilledPolysList(other)
                                if op.Contains(P(x, y)) and all(op.Contains(P(x + r * math.cos(a), y + r * math.sin(a)))
                                                                for a in ring):
                                    v = pcbnew.PCB_VIA(self.b)
                                    v.SetPosition(P(x, y))
                                    v.SetWidth(MM(dia))
                                    v.SetDrill(MM(drill))
                                    v.SetNet(self.nets[net])
                                    self.b.Add(v)
                                    vias.append((x, y))
                                    holes.append((x, y))
                                    n += 1
                                    done = True
                                    break
                        if done:
                            break
                        x += step
                    y += step
        return n

    def drop_floating_islands(self):
        """同じネットのパッド・ビア・配線と重ならない (どこにもつながらない) ベタの島を削除する."""
        n = 0
        for z in self.b.Zones():
            if z.GetIsRuleArea():
                continue
            net, L = z.GetNetname(), z.GetLayer()
            items = [pd for fp in self.b.GetFootprints() for pd in fp.Pads() if pd.GetNetname() == net and pd.IsOnLayer(L)]
            trk = [t for t in self.b.GetTracks() if t.GetNetname() == net and (t.GetClass() == "PCB_VIA" or t.GetLayer() == L)]
            polys = z.GetFilledPolysList(L)
            keep = pcbnew.SHAPE_POLY_SET()
            for i in range(polys.OutlineCount()):
                one = pcbnew.SHAPE_POLY_SET()
                one.AddOutline(polys.Outline(i))
                for h in range(polys.HoleCount(i)):
                    one.AddHole(polys.Hole(i, h))
                hit = any(one.Collide(pd.GetPosition(), max(pd.GetSize().x, pd.GetSize().y) // 2) for pd in items) or \
                    any(one.Collide(t.GetStart(), t.GetWidth() // 2) or one.Collide(t.GetEnd(), t.GetWidth() // 2) for t in trk)
                if hit:
                    idx = keep.AddOutline(polys.Outline(i))
                    for h in range(polys.HoleCount(i)):
                        keep.AddHole(polys.Hole(i, h), idx)
                else:
                    n += 1
            z.SetFilledPolysList(L, keep)
        self.b.BuildConnectivity()
        return n

    def prune_isolated_pieces(self):
        """未接続として報告されるベタの島を 1 つずつ外して試し, 未接続が減る島 (他の経路で既に接続済みの
        冗長な銅) だけを取り除く."""
        def unconn():
            return sum(b.startswith("[unconnected_items]") for b in self._drc_items())
        base = unconn()
        if base == 0:
            return 0
        n = 0
        for z in list(self.b.Zones()):
            if z.GetIsRuleArea():
                continue
            L = z.GetLayer()
            i = 0
            while i < z.GetFilledPolysList(L).OutlineCount() and base > 0:
                polys = z.GetFilledPolysList(L)
                if polys.OutlineCount() < 2:
                    break
                trial = pcbnew.SHAPE_POLY_SET()
                for k in range(polys.OutlineCount()):
                    if k != i:
                        idx = trial.AddOutline(polys.Outline(k))
                        for h in range(polys.HoleCount(k)):
                            trial.AddHole(polys.Hole(k, h), idx)
                saved = pcbnew.SHAPE_POLY_SET(polys)
                z.SetFilledPolysList(L, trial)
                self.b.BuildConnectivity()
                u = unconn()
                if u < base:
                    base = u
                    n += 1
                    continue
                z.SetFilledPolysList(L, saved)
                self.b.BuildConnectivity()
                i += 1
        return n

    def remove_dangling_vias(self):
        """DRC で「片面しか接続していない」と出たビアを, 未接続を増やさない場合に限り削除する."""
        blocks = self._drc_items()
        base = sum(b.startswith("[unconnected_items]") for b in blocks)
        pos = []
        for blk in blocks:
            if blk.startswith("[via_dangling]"):
                pos += [(float(x), float(y)) for x, y in re.findall(r"@\(([-\d.]+) mm, ([-\d.]+) mm\): Via", blk)]
        n = 0
        for x, y in pos:
            for v in list(self.b.GetTracks()):
                if v.GetClass() == "PCB_VIA" and math.hypot(to_mm(v.GetPosition())[0] - x, to_mm(v.GetPosition())[1] - y) < 0.01:
                    self.b.Remove(v)
                    self.b.BuildConnectivity()
                    if sum(b.startswith("[unconnected_items]") for b in self._drc_items()) > base:
                        self.b.Add(v)
                        self.b.BuildConnectivity()
                    else:
                        n += 1
        return n

    def _write_drc(self, rpt):
        """DRC レポートを書く。pcbnew の WriteDRCReport は取り込み直後のボードで稀に異常終了するため,
        一時ファイルに保存して kicad-cli (別プロセス) で実行する。失敗したら 1 回だけ再試行する."""
        import shutil
        tmp = os.path.join(self.dir, "build", self.name + "_drctmp.kicad_pcb")
        assert pcbnew.SaveBoard(tmp, self.b)
        pro = os.path.join(self.dir, self.name + ".kicad_pro")
        if os.path.exists(pro):
            shutil.copy(pro, tmp[:-len(".kicad_pcb")] + ".kicad_pro")   # ネットクラスの割当はプロジェクト側
        for _ in range(2):
            if os.path.exists(rpt):
                os.remove(rpt)
            subprocess.run(["kicad-cli", "pcb", "drc", "--units", "mm", "--severity-all", "-o", rpt, tmp],
                           capture_output=True)
            if os.path.exists(rpt):
                return
        raise RuntimeError("kicad-cli pcb drc failed")

    def drc(self):
        os.makedirs(os.path.join(self.dir, "build"), exist_ok=True)
        rpt = os.path.join(self.dir, "build", self.name + "_drc.rpt")
        self._write_drc(rpt)
        txt = open(rpt, encoding="utf-8").read()
        kinds = {}
        for m in re.finditer(r"^\[(\w+)\]:", txt, re.M):
            kinds[m.group(1)] = kinds.get(m.group(1), 0) + 1
        m = re.search(r"\*\* Found (\d+) unconnected pads", txt)
        return kinds, int(m.group(1)) if m else -1, rpt

    def _drc_items(self):
        rpt = os.path.join(self.dir, "build", self.name + "_repair.rpt")
        self._write_drc(rpt)
        txt = open(rpt, encoding="utf-8").read()
        blocks = re.findall(r"(^\[\w+\]:.*?\n(?:    .*\n)+)", txt, re.M)
        return blocks

    def repair_unrouted(self, maxlen=6.0, skip_nets=(), ripup=False):
        """自動配線で残った 2 点間の未接続を, 直線 / L 字の短い配線で補う (DRC が増えない時だけ採用)."""
        bad = ("[clearance]", "[shorting_items]", "[tracks_crossing]", "[copper_edge_clearance]", "[hole_clearance]",
               "[hole_near_hole]")

        def state():
            blk = self._drc_items()
            return (sum(b.startswith(bad) for b in blk), sum(b.startswith("[unconnected_items]") for b in blk))
        blocks = self._drc_items()
        base = [sum(b.startswith(bad) for b in blocks), sum(b.startswith("[unconnected_items]") for b in blocks)]
        todo = []
        for blk in blocks:
            if not blk.startswith("[unconnected_items]"):
                continue
            pts = [(x, y, d + rest, n) for x, y, d, n, rest in
                   re.findall(r"@\(([-\d.]+) mm, ([-\d.]+) mm\): (.*?) \[(.*?)\](.*)", blk)]
            if pts and pts[0][3] in skip_nets:
                continue
            if len(pts) == 2 and sum(p[2].startswith("Zone") for p in pts) == 1 and \
                    any("pad" in p[2].lower() for p in pts):
                # パッド ↔ ベタ: ベタ側は報告座標が代表点なので, 同じネットの最寄りの別パッドを目標にする
                pd = next(p for p in pts if "pad" in p[2].lower())
                zl = "B.Cu" if "B.Cu" in next(p for p in pts if p[2].startswith("Zone"))[2] else "F.Cu"
                px, py = float(pd[0]), float(pd[1])
                cands = sorted((math.hypot(x - px, y - py), x, y) for x, y in
                               (to_mm(q.GetPosition()) for f in self.b.GetFootprints() for q in f.Pads()
                                if q.GetNetname() == pd[3] and q.IsOnLayer(LAYER[zl]))
                               if math.hypot(x - px, y - py) > 0.3)
                if cands:
                    todo.append([pd, ("%.4f" % cands[0][1], "%.4f" % cands[0][2], "Track (zone) on " + zl, pd[3])])
            elif len(pts) == 2 and all(("pad" in p[2].lower()) or p[2].startswith("Track") for p in pts):
                todo.append(pts)
        fixed = []

        def commit(items):
            for it in items:
                self.b.Add(it)
            self.b.BuildConnectivity()
            self.fill()
            e, u = state()
            if os.environ.get("MPB_DEBUG"):
                print("commit", len(items), "items -> errors", e, "unconnected", u, "base", base)
                if os.environ.get("MPB_DEBUG") == "2":
                    for blk in self._drc_items():
                        if blk.startswith(bad):
                            print("   ", blk.replace("\n", " | ")[:300])
            if e <= base[0] and u < base[1]:
                base[1] = u
                return True
            for it in items:
                self.b.Remove(it)
            self.fill()
            return False

        def seg(net, layer, a, e):
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(P(*a))
            t.SetEnd(P(*e))
            t.SetWidth(MM(0.15))
            t.SetLayer(layer)
            t.SetNet(self.nets[net])
            return t

        def via(net, xy):
            v = pcbnew.PCB_VIA(self.b)
            v.SetPosition(P(*xy))
            v.SetWidth(MM(0.6))
            v.SetDrill(MM(0.3))
            v.SetNet(self.nets[net])
            return v

        def via_hop(net, a, a_tht, e, e_tht):
            """パッド脇にビアを打ち, 裏面 (B.Cu) で直線 / L 字に結ぶ。THT パッドはビア不要."""
            offs = [(0, 0)] if a_tht else [(0.9, 0), (-0.9, 0), (0, 0.9), (0, -0.9)]
            offe = [(0, 0)] if e_tht else [(0.9, 0), (-0.9, 0), (0, 0.9), (0, -0.9)]
            for da in offs:
                for de in offe:
                    pa = (a[0] + da[0], a[1] + da[1])
                    pe = (e[0] + de[0], e[1] + de[1])
                    for mid in ([], [(pe[0], pa[1])], [(pa[0], pe[1])]):
                        items = []
                        if not a_tht:
                            items += [seg(net, pcbnew.F_Cu, a, pa), via(net, pa)]
                        if not e_tht:
                            items += [seg(net, pcbnew.F_Cu, e, pe), via(net, pe)]
                        pts = [pa] + mid + [pe]
                        items += [seg(net, pcbnew.B_Cu, p0, p1) for p0, p1 in zip(pts, pts[1:])
                                  if abs(p0[0] - p1[0]) + abs(p0[1] - p1[1]) > 1e-6]
                        if commit(items):
                            return True
            return False

        def island(net, pt):
            """pt にある同ネットの銅につながる配線・ビア・パッドの集合 (端点の一致・パッド/ビアへの着地で判定)."""
            segs, vias, pads = [], [], []
            for t in self.b.GetTracks():
                if t.GetNetname() != net:
                    continue
                if t.GetClass() == "PCB_VIA":
                    vias.append(("v", ("v",) + tuple(round(v, 3) for v in to_mm(t.GetPosition())),
                                 to_mm(t.GetPosition()), pcbnew.ToMM(t.GetWidth()) / 2))
                else:
                    segs.append(("s", ("s", t.GetLayer()) + tuple(round(v, 3) for v in to_mm(t.GetStart()) + to_mm(t.GetEnd())),
                                 to_mm(t.GetStart()), to_mm(t.GetEnd()), t.GetLayer(),
                                 pcbnew.ToMM(t.GetWidth()) / 2))
            for f in self.b.GetFootprints():
                for q in f.Pads():
                    if q.GetNetname() == net:
                        bb = q.GetBoundingBox()
                        box = tuple(pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
                        lays = {L for L in (pcbnew.F_Cu, pcbnew.B_Cu) if q.IsOnLayer(L)}
                        pads.append(("p", ("p",) + tuple(round(v, 3) for v in box), box, lays))
            inbox = lambda b_, x, y, m=0.0: b_[0] - m <= x <= b_[2] + m and b_[1] - m <= y <= b_[3] + m

            def touch(u, w):
                if u[0] == "s" and w[0] == "s":
                    return u[4] == w[4] and any(math.hypot(p[0] - q[0], p[1] - q[1]) < 0.02
                                                for p in (u[2], u[3]) for q in (w[2], w[3]))
                if u[0] == "s" and w[0] == "v":
                    return any(math.hypot(p[0] - w[2][0], p[1] - w[2][1]) < w[3] for p in (u[2], u[3]))
                if u[0] == "s" and w[0] == "p":
                    return u[4] in w[3] and any(inbox(w[2], *p) for p in (u[2], u[3]))
                if u[0] == "v" and w[0] == "p":
                    return inbox(w[2], *u[2])
                if u[0] == "v" and w[0] == "v":
                    return math.hypot(u[2][0] - w[2][0], u[2][1] - w[2][1]) < 0.02
                if u[0] == "p" and w[0] == "p":
                    return False
                return touch(w, u)
            items = segs + vias + pads
            seed = [it for it in items if
                    (it[0] == "p" and inbox(it[2], *pt, 0.02)) or
                    (it[0] == "v" and math.hypot(it[2][0] - pt[0], it[2][1] - pt[1]) < it[3] + 0.02) or
                    (it[0] == "s" and min(math.hypot(q[0] - pt[0], q[1] - pt[1]) for q in (it[2], it[3])) < it[5] + 0.02)]
            if not seed:
                return set()
            seen = {it[1]: it for it in seed}
            todo_ = list(seed)
            while todo_:
                u = todo_.pop()
                for w in items:
                    if w[1] not in seen and touch(u, w):
                        seen[w[1]] = w
                        todo_.append(w)
            return {tuple(v if not isinstance(v, set) else frozenset(v) for v in it) for it in seen.values()}

        def island_cells(isl, x0, y0, nx, ny, grid):
            cells = set()
            put_ = lambda x, y, L: cells.add((int(round((x - x0) / grid)), int(round((y - y0) / grid)), L)) \
                if 0 <= round((x - x0) / grid) < nx and 0 <= round((y - y0) / grid) < ny else None
            for it in isl:
                if it[0] == "s":
                    (ax, ay), (bx, by) = it[2], it[3]
                    n_ = max(int(math.hypot(bx - ax, by - ay) / grid), 1)
                    for k in range(n_ + 1):
                        put_(ax + (bx - ax) * k / n_, ay + (by - ay) * k / n_, it[4])
                elif it[0] == "v":
                    for L in (pcbnew.F_Cu, pcbnew.B_Cu):
                        put_(it[2][0], it[2][1], L)
                else:
                    b_ = it[2]
                    cx, cy = (b_[0] + b_[2]) / 2, (b_[1] + b_[3]) / 2
                    for L in it[3]:
                        put_(cx, cy, L)
            return cells

        def maze(net, a, a_layers, e, e_layers, grid=0.1, margin=4.0, soft=False, dry=False):
            """格子 A* (2 層 + ビア) で a→e を結ぶ。障害物は他ネットのパッド・配線・ビア・穴と基板端."""
            import heapq
            x0, y0 = max(min(a[0], e[0]) - margin, 0.6), max(min(a[1], e[1]) - margin, 0.6)
            x1, y1 = min(max(a[0], e[0]) + margin, self.W - 0.6), min(max(a[1], e[1]) + margin, self.H - 0.6)
            nx, ny = int((x1 - x0) / grid) + 1, int((y1 - y0) / grid) + 1
            INF = 1e9
            dist = {L: [[INF] * nx for _ in range(ny)] for L in (pcbnew.F_Cu, pcbnew.B_Cu)}
            full = dist                     # soft=True のとき: dist = 動かせない障害物, full = 配線も含む全障害物
            if soft:
                full = {L: [[INF] * nx for _ in range(ny)] for L in (pcbnew.F_Cu, pcbnew.B_Cu)}
            softs = []                      # 引き剥がせる他ネットの配線 (track, 層, p0, p1, 半幅)

            def stamp(L, bx0, by0, bx1, by1, dfun, tgt=None):
                i0, i1 = max(int((bx0 - 0.6 - x0) / grid), 0), min(int((bx1 + 0.6 - x0) / grid) + 1, nx)
                j0, j1 = max(int((by0 - 0.6 - y0) / grid), 0), min(int((by1 + 0.6 - y0) / grid) + 1, ny)
                row = (tgt or dist)[L]
                for j in range(j0, j1):
                    yy = y0 + j * grid
                    r = row[j]
                    for i in range(i0, i1):
                        d = dfun(x0 + i * grid, yy)
                        if d < r[i]:
                            r[i] = d

            def rect_d(l, t, r, b_):
                return lambda x, y: math.hypot(max(l - x, 0, x - r), max(t - y, 0, y - b_))

            def seg_d(p0, p1, hw):
                (ax, ay), (bx, by) = p0, p1
                L2 = (bx - ax) ** 2 + (by - ay) ** 2

                def f(x, y):
                    t = 0 if L2 == 0 else max(0, min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L2))
                    return math.hypot(x - ax - t * (bx - ax), y - ay - t * (by - ay)) - hw
                return f

            inwin = lambda l, t, r, b_: r > x0 - 1 and l < x1 + 1 and b_ > y0 - 1 and t < y1 + 1
            extra = lambda n: 0.07 if self.assign.get(n) == "HiCur" else 0.0   # 大電流クラスは間隙 0.2mm
            for fp in self.b.GetFootprints():
                for pad in fp.Pads():
                    if pad.GetNetname() == net and pad.GetNetname():
                        continue
                    bb = pad.GetBoundingBox()
                    l, t, r, b_ = (pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
                    if not inwin(l, t, r, b_):
                        continue
                    ex = extra(pad.GetNetname())
                    for L in (pcbnew.F_Cu, pcbnew.B_Cu):
                        if pad.IsOnLayer(L) or pad.GetDrillSize().x > 0:
                            stamp(L, l - ex, t - ex, r + ex, b_ + ex, rect_d(l - ex, t - ex, r + ex, b_ + ex))
                            if soft:
                                stamp(L, l - ex, t - ex, r + ex, b_ + ex, rect_d(l - ex, t - ex, r + ex, b_ + ex), full)
            for tr in self.b.GetTracks():
                if tr.GetNetname() == net:
                    continue
                if tr.GetClass() == "PCB_VIA":
                    c = to_mm(tr.GetPosition())
                    rr = pcbnew.ToMM(tr.GetWidth()) / 2
                    rr += extra(tr.GetNetname())
                    if inwin(c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr):
                        for L in (pcbnew.F_Cu, pcbnew.B_Cu):
                            stamp(L, c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr, seg_d(c, c, rr))
                            if soft:
                                stamp(L, c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr, seg_d(c, c, rr), full)
                    continue
                p0, p1 = to_mm(tr.GetStart()), to_mm(tr.GetEnd())
                hw = pcbnew.ToMM(tr.GetWidth()) / 2 + extra(tr.GetNetname())
                l, t, r, b_ = min(p0[0], p1[0]) - hw, min(p0[1], p1[1]) - hw, max(p0[0], p1[0]) + hw, max(p0[1], p1[1]) + hw
                if inwin(l, t, r, b_):
                    movable = soft and tr.GetNetname() not in ("GND", "") and self.assign.get(tr.GetNetname()) != "HiCur"
                    if movable:
                        softs.append((tr, tr.GetLayer(), p0, p1, hw))
                        stamp(tr.GetLayer(), l, t, r, b_, seg_d(p0, p1, hw), full)
                    else:
                        stamp(tr.GetLayer(), l, t, r, b_, seg_d(p0, p1, hw))
                        if soft:
                            stamp(tr.GetLayer(), l, t, r, b_, seg_d(p0, p1, hw), full)
            clr = 0.13 + 0.015   # 既定クラスの間隙 + 格子誤差の余裕 (大電流クラスは障害物側を太らせてある)
            tr_ok = lambda L, i, j: dist[L][j][i] > 0.075 + clr
            via_ok = lambda i, j: all(dist[L][j][i] > 0.3 + clr for L in dist)
            cell = lambda p: (int(round((p[0] - x0) / grid)), int(round((p[1] - y0) / grid)))
            (ai, aj), (ei, ej) = cell(a), cell(e)
            if not (0 <= ai < nx and 0 <= aj < ny and 0 <= ei < nx and 0 <= ej < ny):
                return False

            def pad_cells(pt):
                """pt にある同ネットのパッド (無ければ pt 周辺 0.1mm) を覆う格子点."""
                box = (pt[0] - 0.08, pt[1] - 0.08, pt[0] + 0.08, pt[1] + 0.08)
                for fp in self.b.GetFootprints():
                    for pad in fp.Pads():
                        if pad.GetNetname() == net and math.hypot(*(u - v for u, v in zip(to_mm(pad.GetPosition()), pt))) < 0.02:
                            bb = pad.GetBoundingBox()
                            box = tuple(pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
                cells = set()
                for j in range(max(int((box[1] - y0) / grid), 0), min(int((box[3] - y0) / grid) + 2, ny)):
                    for i in range(max(int((box[0] - x0) / grid), 0), min(int((box[2] - x0) / grid) + 2, nx)):
                        xx, yy = x0 + i * grid, y0 + j * grid
                        if box[0] + 0.05 <= xx <= box[2] - 0.05 and box[1] + 0.05 <= yy <= box[3] - 0.05:
                            cells.add((i, j))
                return cells or {cell(pt)}
            a_cells, e_cells = pad_cells(a), pad_cells(e)
            a_st = {(ci, cj, L) for L in a_layers for (ci, cj) in a_cells}
            e_st = {(ci, cj, L) for L in e_layers for (ci, cj) in e_cells}
            # 始点・終点の「島」(同じネットでつながっている配線・ビア・パッド) 全体を始点・終点にする
            ia, ie = island(net, a), island(net, e)
            if ia and ie and ia & ie:
                return False
            a_st |= island_cells(ia, x0, y0, nx, ny, grid)
            e_st |= island_cells(ie, x0, y0, nx, ny, grid)
            pq, came, g = [], {}, {}
            for st in a_st:
                g[st] = 0
                heapq.heappush(pq, (0, st))
            goal = e_st - a_st
            if not goal:
                return False
            start_ok = {(ci, cj) for (ci, cj, _L) in a_st} | {(ci, cj) for (ci, cj, _L) in goal}
            h = lambda i, j: math.hypot(i - ei, j - ej)
            steps = [(1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
            found = None
            expanded = 0
            while pq:
                f, cur = heapq.heappop(pq)
                expanded += 1
                if cur in goal:
                    found = cur
                    break
                i, j, L = cur
                gc = g[cur]
                nbrs = [(i + di, j + dj, L, c) for di, dj, c in steps]
                if via_ok(i, j):
                    nbrs.append((i, j, pcbnew.B_Cu if L == pcbnew.F_Cu else pcbnew.F_Cu, 25))
                for ni, nj, NL, c in nbrs:
                    if not (0 <= ni < nx and 0 <= nj < ny):
                        continue
                    nxt = (ni, nj, NL)
                    if nxt not in goal and (ni, nj) not in start_ok and not tr_ok(NL, ni, nj):
                        continue
                    if soft and full[NL][nj][ni] <= 0.075 + clr and (ni, nj) not in start_ok:
                        c += 40                     # 他ネットの配線を横切る (引き剥がし候補) のは高コスト
                    ng = gc + c
                    if ng < g.get(nxt, INF):
                        g[nxt] = ng
                        came[nxt] = cur
                        heapq.heappush(pq, (ng + h(ni, nj), nxt))
            if os.environ.get("MPB_DEBUG"):
                print("maze", net, "found" if found else "no path", "cells", nx, ny, "expanded", expanded,
                      "start", len(a_cells), "goal", len(e_cells), "via_ok_start",
                      sum(via_ok(i, j) for i, j in a_cells))
            if not found:
                return False
            path = [found]
            while path[-1] in came:
                path.append(came[path[-1]])
            path.reverse()
            items, k = [], 0
            while k < len(path) - 1:
                i, j, L = path[k]
                if path[k + 1][2] != L:
                    items.append(via(net, (x0 + i * grid, y0 + j * grid)))
                    k += 1
                    continue
                m = k + 1
                d0 = (path[m][0] - i, path[m][1] - j)
                while m + 1 < len(path) and path[m + 1][2] == L and \
                        (path[m + 1][0] - path[m][0], path[m + 1][1] - path[m][1]) == d0:
                    m += 1
                pa = (x0 + i * grid, y0 + j * grid)
                pe = (x0 + path[m][0] * grid, y0 + path[m][1] * grid)
                items.append(seg(net, L, pa, pe))
                k = m
            if soft:
                cells = [(x0 + i * grid, y0 + j * grid, L) for i, j, L in path]
                hit = set()
                for idx, (tr, TL, p0, p1, hw) in enumerate(softs):
                    f_ = seg_d(p0, p1, hw)
                    isvia = lambda k2: (k2 + 1 < len(path) and path[k2 + 1][2] != path[k2][2]) or \
                        (k2 > 0 and path[k2 - 1][2] != path[k2][2])
                    if any((isvia(k2) and f_(x, y) <= 0.3 + clr) or (L == TL and f_(x, y) <= 0.075 + clr)
                           for k2, (x, y, L) in enumerate(cells)):
                        hit.add(idx)
                return items, [softs[i][0] for i in sorted(hit)]
            if dry:
                return items
            return commit(items)

        def try_paths(net, layer, a, targets):
            for (x2, y2) in targets:
                x1, y1 = a
                for path in ([(x1, y1), (x2, y2)], [(x1, y1), (x2, y1), (x2, y2)], [(x1, y1), (x1, y2), (x2, y2)]):
                    added = []
                    for p0, p1 in zip(path, path[1:]):
                        if abs(p0[0] - p1[0]) + abs(p0[1] - p1[1]) < 1e-6:
                            continue
                        t = pcbnew.PCB_TRACK(self.b)
                        t.SetStart(P(*p0))
                        t.SetEnd(P(*p1))
                        t.SetWidth(MM(0.15))
                        t.SetLayer(layer)
                        t.SetNet(self.nets[net])
                        self.b.Add(t)
                        added.append(t)
                    self.b.BuildConnectivity()
                    self.fill()   # ベタを塗り直してから判定 (古い塗りとの干渉を誤検出しない)
                    e, u = state()
                    if e <= base[0] and u < base[1]:   # 間隙違反を増やさず, 未接続が減った時だけ採用
                        base[1] = u
                        return True
                    for t in added:
                        self.b.Remove(t)
                    self.fill()
            return False

        lay_of = lambda d: ([pcbnew.F_Cu, pcbnew.B_Cu] if d.startswith("PTH") else
                            [pcbnew.B_Cu] if "B.Cu" in d else [pcbnew.F_Cu])

        def pairs_of(blocks, nets):
            out = []
            for blk in blocks:
                if not blk.startswith("[unconnected_items]"):
                    continue
                pts = [(float(x), float(y), d + rest, n) for x, y, d, n, rest in
                       re.findall(r"@\(([-\d.]+) mm, ([-\d.]+) mm\): (.*?) \[(.*?)\](.*)", blk)]
                if len(pts) == 2 and pts[0][3] in nets and \
                        all(("pad" in p[2].lower()) or p[2].startswith("Track") for p in pts):
                    out.append(pts)
            return out

        def ripup_route(net, a, al, e, el):
            """他の信号ネットの配線を横切る経路を引き, 横切った配線を外して引き直す。全体の未接続が減った時だけ採用."""
            r = maze(net, a, al, e, el, soft=True, margin=6.0)
            if not r or not isinstance(r, tuple):
                return False
            items, hits = r
            if not hits or len(hits) > 8:
                return False
            ripped = {t.GetNetname() for t in hits}
            for t in hits:
                self.b.Remove(t)
            added = list(items)
            for it in items:
                self.b.Add(it)
            self.b.BuildConnectivity()
            for _ in range(3):
                prs = pairs_of(self._drc_items(), ripped)
                if not prs:
                    break
                progress = False
                for (xa, ya, da, n_), (xb, yb, db, _m) in prs:
                    its = maze(n_, (xa, ya), lay_of(da), (xb, yb), lay_of(db), dry=True)
                    if its:
                        for it in its:
                            self.b.Add(it)
                        added += its
                        self.b.BuildConnectivity()
                        progress = True
                if not progress:
                    break
            self.fill()
            e_, u_ = state()
            if os.environ.get("MPB_DEBUG"):
                print("ripup", net, "hits", sorted(ripped), "-> errors", e_, "unconnected", u_, "base", base)
                if os.environ.get("MPB_DEBUG") == "2":
                    for blk in self._drc_items():
                        if blk.startswith(bad):
                            print("   ", blk.replace("\n", " | ")[:260])
            if e_ <= base[0] and u_ < base[1]:
                base[1] = u_
                return True
            for it in added:
                self.b.Remove(it)
            for t in hits:
                self.b.Add(t)
            self.b.BuildConnectivity()
            self.fill()
            return False

        for (x1, y1, d1, net), (x2, y2, d2, _n) in todo:
            x1, y1, x2, y2 = map(float, (x1, y1, x2, y2))
            layer = pcbnew.B_Cu if ("B.Cu" in d1 and "B.Cu" in d2) else pcbnew.F_Cu
            if d1.startswith("Track") or d2.startswith("Track"):
                lay = lambda d: ([pcbnew.F_Cu, pcbnew.B_Cu] if d.startswith("PTH") else
                                 [pcbnew.B_Cu] if "B.Cu" in d else [pcbnew.F_Cu])
                if maze(net, (x1, y1), lay(d1), (x2, y2), lay(d2)):
                    fixed.append(net)
                elif ripup and ripup_route(net, (x1, y1), lay(d1), (x2, y2), lay(d2)):
                    fixed.append(net)
                continue
            if abs(x1 - x2) + abs(y1 - y2) <= maxlen and try_paths(net, layer, (x1, y1), [(x2, y2)]):
                fixed.append(net)
                continue
            # 片方の島が孤立パッドの場合: 同じネットの近くの配線端点へつなぐ
            for (px, py, d) in ((x1, y1, d1), (x2, y2, d2)):
                lay = pcbnew.B_Cu if "B.Cu" in d else pcbnew.F_Cu
                ends = []
                for t in self.b.GetTracks():
                    if t.GetNetname() == net and t.GetClass() == "PCB_TRACK" and t.GetLayer() == lay:
                        for e in (to_mm(t.GetStart()), to_mm(t.GetEnd())):
                            dd = math.hypot(e[0] - px, e[1] - py)
                            if 0.3 < dd < 12.0:
                                ends.append((dd, e))
                ends = [e for _, e in sorted(ends)[:8]]
                if ends and try_paths(net, lay, (px, py), ends):
                    fixed.append(net)
                    break
            else:
                # 最後の手段: F.Cu の SMD パッド同士 / THT パッドを裏面経由で結ぶ
                if net not in fixed and abs(x1 - x2) + abs(y1 - y2) <= 14.0 and not ("B.Cu" in d1 and "B.Cu" in d2):
                    tht1, tht2 = d1.startswith("PTH"), d2.startswith("PTH")
                    if "B.Cu" in d1 and not tht1:   # 裏面 SMD 側は直接裏面の配線に乗る
                        tht1 = True
                    if "B.Cu" in d2 and not tht2:
                        tht2 = True
                    if via_hop(net, (x1, y1), tht1, (x2, y2), tht2):
                        fixed.append(net)
            if net not in fixed:
                lay = lambda d: ([pcbnew.F_Cu, pcbnew.B_Cu] if d.startswith("PTH") else
                                 [pcbnew.B_Cu] if "B.Cu" in d else [pcbnew.F_Cu])
                if maze(net, (x1, y1), lay(d1), (x2, y2), lay(d2)):
                    fixed.append(net)
            if net not in fixed and ripup and ripup_route(net, (x1, y1), lay_of(d1), (x2, y2), lay_of(d2)):
                fixed.append(net)
        # ベタの島どうしが未接続: 小さい島のパッドから, 島の外の同じネットの銅へ迷路配線する
        zone_nets = set()
        for blk in self._drc_items():
            if blk.startswith("[unconnected_items]"):
                zz = re.findall(r"Zone \[(.*?)\] on (\S+)", blk)
                if len(zz) == 2 and zz[0] == zz[1]:
                    zone_nets.add(zz[0])
        for net, lname in zone_nets:
            L = LAYER[lname]
            for z in [z for z in self.b.Zones() if z.GetNetname() == net and z.GetLayer() == L and not z.GetIsRuleArea()]:
                polys = z.GetFilledPolysList(L)
                pieces = []
                for i in range(polys.OutlineCount()):
                    one = pcbnew.SHAPE_POLY_SET()
                    one.AddOutline(polys.Outline(i))
                    pads = [pd for fp in self.b.GetFootprints() for pd in fp.Pads()
                            if pd.GetNetname() == net and pd.IsOnLayer(L) and one.Contains(pd.GetPosition())]
                    pieces.append((abs(one.Area()), one, pads))
                pieces.sort(key=lambda q: -q[0])
                vias = [t for t in self.b.GetTracks() if t.GetNetname() == net and t.GetClass() == "PCB_VIA"]
                thts = [q for fp in self.b.GetFootprints() for q in fp.Pads()
                        if q.GetNetname() == net and q.GetDrillSize().x > 0]
                for area, one, pads in pieces[1:]:
                    if not pads:
                        continue
                    # 反対面へ抜けるビア / THT を持つ島は面間で接続済みとみなし, 持たない島だけを対象にする
                    if any(one.Contains(v.GetPosition()) for v in vias) or \
                            any(one.Collide(q.GetPosition(), max(q.GetSize().x, q.GetSize().y) // 2) for q in thts):
                        continue
                    pd = pads[0]
                    a = to_mm(pd.GetPosition())
                    cands = [(math.hypot(*(u - w for u, w in zip(to_mm(v.GetPosition()), a))), to_mm(v.GetPosition()), "PTH")
                             for v in vias] + \
                            [(math.hypot(*(u - w for u, w in zip(to_mm(q.GetPosition()), a))), to_mm(q.GetPosition()), "PTH")
                             for q in thts]
                    others = []
                    for fp in self.b.GetFootprints():
                        for q in fp.Pads():
                            if q.GetNetname() == net and q.GetDrillSize().x == 0 and not one.Contains(q.GetPosition()):
                                others.append((math.hypot(*(u - w for u, w in zip(to_mm(q.GetPosition()), a))),
                                               to_mm(q.GetPosition()), q.GetLayerName() if hasattr(q, "GetLayerName") else lname))
                    for t in self.b.GetTracks():
                        if t.GetNetname() == net and t.GetClass() == "PCB_TRACK" and not one.Contains(t.GetStart()):
                            e = to_mm(t.GetStart())
                            others.append((math.hypot(e[0] - a[0], e[1] - a[1]), e, t.GetLayerName()))
                    for dd, e, ld in sorted(cands)[:4] + sorted(others)[:4]:
                        if dd > 15:
                            continue
                        el = [pcbnew.F_Cu, pcbnew.B_Cu] if ld == "PTH" else [LAYER.get(ld, L)]
                        if maze(net, a, [L], e, el):
                            fixed.append(net)
                            break
        return fixed

    def save(self):
        """基板とプロジェクト (ネットクラス・デザインルール) を保存する."""
        path = os.path.join(self.dir, self.name + ".kicad_pcb")
        pro = path[:-10] + ".kicad_pro"
        old = json.load(open(pro, encoding="utf-8")) if os.path.exists(pro) else {}
        assert pcbnew.SaveBoard(path, self.b)
        d = json.load(open(pro, encoding="utf-8"))
        for k, v in old.items():  # 既存プロジェクトの項目 (回路図設定など) は残す
            d.setdefault(k, v)
        d["net_settings"]["netclass_patterns"] = [
            {"netclass": c, "pattern": n} for n, c in sorted(self.assign.items())]
        rules = d["board"]["design_settings"]["rules"]
        rules["min_text_height"] = 0.6
        rules["min_silk_clearance"] = 0.0
        json.dump(d, open(pro, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        return path

    def reload(self):
        """保存して読み直す (standalone の pcbnew はベタ塗りに読み込み済みボードが必要)."""
        path = self.save()
        self.b = pcbnew.LoadBoard(path)
        self.b.SynchronizeNetsAndNetClasses(True)   # パターン割当を各ネットへ反映 (DSN 出力が参照する)
        self.b.BuildConnectivity()
        self.nets = {str(k): v for k, v in self.b.GetNetsByName().items() if str(k)}
        self.fps = {fp.GetReference(): fp for fp in self.b.GetFootprints()}
        return path
