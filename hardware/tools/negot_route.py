#!/usr/bin/env python3
"""
自動配線で残った未接続を, 周りの信号ネットごと引き直して解消する (交渉型ルータ, KiCad 8 の Python + numpy)。

  python3 tools/negot_route.py <board.kicad_pcb> <out.kicad_pcb> NET1,NET2,... [--auto-rip]

指定ネット (と --auto-rip で経路を塞いでいる信号ネット) の配線・ビアを全部外し, 0.05mm 格子の 2 層で
PathFinder 方式 (混雑コストを反復で上げて取り合いを解く) で引き直す。GND・電源・大電流のネット, パッド,
外さなかった配線は障害物として扱う。ベタを塗り直して kicad-cli の DRC を取り, 未接続が減って
電気的エラーが増えない時だけ <out> に保存する。
"""
import heapq
import json
import math
import os
import re
import shutil
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pcblib import pcbnew  # noqa: E402

G = 0.05                      # 格子 (mm)
TW = 0.127                    # 引き直す配線の幅
CLR = 0.127                   # 間隙 (既定クラス)
VIA_D, VIA_H = 0.6, 0.3       # ビア
EDGE = 0.5                    # 基板端から配線禁止
MARGIN = 0.02                 # 格子の丸め誤差の余裕
PADZ = 0.25                   # 自分のパッドからこの距離以内は占有・取り合いの判定から外す (隣のパッドとの間隙は別に確保)
FIXED = {"GND", "+3V3", "+5V", "VBUS", "USB_VBUS", "VHV", "VHV_IN", "USB_VBUS_F", "VDD8", ""}
ERR = ("[clearance]", "[shorting_items]", "[tracks_crossing]", "[copper_edge_clearance]", "[hole_clearance]",
       "[hole_near_hole]", "[via_diameter]", "[annular_width]", "[track_width]")
mm = pcbnew.ToMM
MMI = pcbnew.FromMM


def drc(path, rpt):
    subprocess.run(["kicad-cli", "pcb", "drc", "--units", "mm", "--severity-all", "-o", rpt, path], capture_output=True)
    txt = open(rpt, encoding="utf-8").read()
    blocks = re.findall(r"(^\[\w+\]:.*?\n(?:    .*\n)+)", txt, re.M)
    return sum(b.startswith(ERR) for b in blocks), sum(b.startswith("[unconnected_items]") for b in blocks), blocks


class Grid:
    def __init__(self, W, H):
        self.nx, self.ny = int(W / G) + 1, int(H / G) + 1
        self.W, self.H = W, H

    def idx(self, x, y):
        return int(round(x / G)), int(round(y / G))

    def xy(self, i, j):
        return i * G, j * G


def seg_dist_field(nx, ny, i0, j0, i1, j1, p0, p1):
    """格子の部分領域 [i0:i1, j0:j1] について, 線分 p0-p1 までの距離 (mm) を返す."""
    xs = np.arange(i0, i1) * G
    ys = np.arange(j0, j1) * G
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    (ax, ay), (bx, by) = p0, p1
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return np.hypot(X - ax, Y - ay)
    t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0, 1)
    return np.hypot(X - ax - t * dx, Y - ay - t * dy)


def rect_dist_field(i0, j0, i1, j1, l, t, r, b):
    xs = np.arange(i0, i1) * G
    ys = np.arange(j0, j1) * G
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    return np.hypot(np.maximum(np.maximum(l - X, 0), X - r), np.maximum(np.maximum(t - Y, 0), Y - b))


class Router:
    def __init__(self, path, nets, auto_rip):
        self.path = path
        self.b = pcbnew.LoadBoard(path)
        bb = self.b.GetBoardEdgesBoundingBox()
        self.W, self.H = mm(bb.GetRight()), mm(bb.GetBottom())
        self.g = Grid(self.W, self.H)
        self.targets = set(nets)
        pro = json.load(open(path[:-len(".kicad_pcb")] + ".kicad_pro", encoding="utf-8"))
        self.cls = {p["pattern"]: p["netclass"] for p in pro["net_settings"].get("netclass_patterns", [])}
        self.fixed = FIXED | {n for n, c in self.cls.items() if c in ("HiCur", "Power")}
        self.rip = set(nets)
        if auto_rip:
            self.rip |= self.blockers()
        self.rip -= self.fixed
        print("rip nets:", len(self.rip), ",".join(sorted(self.rip)))

    # ---- 周りのネット (目標ネットの端点を結ぶ帯を横切る信号ネット) ---------------------
    def blockers(self):
        pads = self.net_pads()
        out = set()
        for n in self.targets:
            ps = pads.get(n, [])
            if len(ps) < 2:
                continue
            xs = [(p[0] + p[2]) / 2 for p in ps]
            ys = [(p[1] + p[3]) / 2 for p in ps]
            x0, x1, y0, y1 = min(xs) - 1.0, max(xs) + 1.0, min(ys) - 1.0, max(ys) + 1.0
            for t in self.b.GetTracks():
                if t.GetClass() == "PCB_VIA":
                    continue
                (ax, ay), (bx, by) = (mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))
                if max(ax, bx) >= x0 and min(ax, bx) <= x1 and max(ay, by) >= y0 and min(ay, by) <= y1:
                    out.add(t.GetNetname())
        return out

    def net_pads(self):
        d = {}
        for f in self.b.GetFootprints():
            for p in f.Pads():
                bb = p.GetBoundingBox()
                lay = tuple(L for L, nm in ((0, "F.Cu"), (1, "B.Cu")) if p.IsOnLayer(self.b.GetLayerID(nm)))
                d.setdefault(p.GetNetname(), []).append(
                    (mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()), lay,
                     p.GetDrillSize().x > 0, mm(p.GetPosition().x), mm(p.GetPosition().y)))
        return d

    # ---- 障害物 (外さない銅) の距離場 ------------------------------------------------
    def build(self, soft=False):
        g = self.g
        self.soft = np.full((2, g.nx, g.ny), 9.0, dtype=np.float32) if soft else None
        self.hard = np.full((2, g.nx, g.ny), 9.0, dtype=np.float32)     # 外さない銅までの距離 (mm)
        self.padnet = {}                                                # 引き直すネットのパッドの距離場
        self.zones = [z for z in self.b.Zones() if not z.GetIsRuleArea()]
        for z in self.zones:
            self.b.RemoveNative(z)
        for t in list(self.b.GetTracks()):
            if t.GetNetname() in self.rip:
                self.b.RemoveNative(t)

        def stamp(arr_list, l, t, r, b, fn, pad):
            i0, j0 = max(int((l - pad) / G), 0), max(int((t - pad) / G), 0)
            i1, j1 = min(int((r + pad) / G) + 2, g.nx), min(int((b + pad) / G) + 2, g.ny)
            if i0 >= i1 or j0 >= j1:
                return
            f = fn(i0, j0, i1, j1)
            for arr in arr_list:
                arr[i0:i1, j0:j1] = np.minimum(arr[i0:i1, j0:j1], f)

        R = 1.2
        for f in self.b.GetFootprints():
            for p in f.Pads():
                bb = p.GetBoundingBox()
                l, t, r, b = mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())
                th = p.GetDrillSize().x > 0
                layers = [L for L, nm in ((0, "F.Cu"), (1, "B.Cu")) if th or p.IsOnLayer(self.b.GetLayerID(nm))]
                fn = (lambda l, t, r, b: lambda i0, j0, i1, j1: rect_dist_field(i0, j0, i1, j1, l, t, r, b))(l, t, r, b)
                net = p.GetNetname()
                if net in self.rip:
                    arr = self.padnet.setdefault(net, np.full((2, g.nx, g.ny), 9.0, dtype=np.float32))
                    stamp([arr[L] for L in layers], l, t, r, b, fn, R)
                else:
                    stamp([self.hard[L] for L in layers], l, t, r, b, fn, R)
        for tr in self.b.GetTracks():
            if tr.GetClass() == "PCB_VIA":
                c = (mm(tr.GetPosition().x), mm(tr.GetPosition().y))
                rr = mm(tr.GetWidth()) / 2
                fn = (lambda c, rr: lambda i0, j0, i1, j1: seg_dist_field(0, 0, i0, j0, i1, j1, c, c) - rr)(c, rr)
                tgt = self.soft if (soft and tr.GetNetname() not in self.fixed) else self.hard
                stamp([tgt[0], tgt[1]], c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr, fn, R)
                continue
            p0 = (mm(tr.GetStart().x), mm(tr.GetStart().y))
            p1 = (mm(tr.GetEnd().x), mm(tr.GetEnd().y))
            hw = mm(tr.GetWidth()) / 2
            extra = 0.03 if self.cls.get(tr.GetNetname()) == "HiCur" else 0.0     # 大電流クラスは間隙 0.15
            L = 0 if tr.GetLayer() == pcbnew.F_Cu else 1
            fn = (lambda p0, p1, hw: lambda i0, j0, i1, j1: seg_dist_field(0, 0, i0, j0, i1, j1, p0, p1) - hw - extra)(p0, p1, hw)
            tgt = self.soft if (soft and tr.GetNetname() not in self.fixed) else self.hard
            stamp([tgt[L]], min(p0[0], p1[0]) - hw, min(p0[1], p1[1]) - hw, max(p0[0], p1[0]) + hw,
                  max(p0[1], p1[1]) + hw, fn, R)
        # 基板端
        xs = np.arange(g.nx) * G
        ys = np.arange(g.ny) * G
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        de = np.minimum(np.minimum(X, self.W - X), np.minimum(Y, self.H - Y)) - EDGE + CLR
        for L in (0, 1):
            self.hard[L] = np.minimum(self.hard[L], de)
        self.tr_need = TW / 2 + CLR + MARGIN
        self.via_need = VIA_D / 2 + CLR + MARGIN
        self.free = self.hard > self.tr_need                                  # 配線を通せる格子
        self.via_free = (self.hard[0] > self.via_need) & (self.hard[1] > self.via_need)

    # ---- 1 ネットの配線 (パッドを順に木でつなぐ) ------------------------------------
    def route_net(self, net, pads, occ, hist, pres):
        g = self.g
        own = self.padnet[net]
        term = []
        for (l, t, r, b, lay, th, cx, cy) in pads:
            cells = set()
            for L in ((0, 1) if th else lay):
                for i in range(int(l / G) + 1, int(r / G) + 1):
                    for j in range(int(t / G) + 1, int(b / G) + 1):
                        if own[L, i, j] <= 0.0:
                            cells.add((i, j, L))
                i, j = g.idx(cx, cy)
                cells.add((i, j, L))
            term.append(cells)
        xs = [p[6] for p in pads]
        ys = [p[7] for p in pads]
        wi0, wi1 = max(int((min(xs) - 6) / G), 1), min(int((max(xs) + 6) / G), g.nx - 2)
        wj0, wj1 = max(int((min(ys) - 6) / G), 1), min(int((max(ys) + 6) / G), g.ny - 2)
        block = self.blocks[net]                   # 他のネットのパッド近くは通れない
        tree = set(term[0])
        paths = []
        remaining = term[1:]
        steps = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                 (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
        while remaining:
            goal = set().union(*remaining)
            gl = list(goal)
            gi = np.array([c[0] for c in gl])
            gj = np.array([c[1] for c in gl])
            h = lambda i, j: float(np.min(np.hypot(gi - i, gj - j))) * 0.9
            dist, came, pq = {}, {}, []
            for c in tree:
                dist[c] = 0.0
                heapq.heappush(pq, (h(c[0], c[1]), 0.0, c))
            found = None
            n_exp = 0
            while pq:
                f, gc, cur = heapq.heappop(pq)
                if gc > dist.get(cur, 1e18):
                    continue
                if cur in goal:
                    found = cur
                    break
                n_exp += 1
                if n_exp > 3000000:
                    break
                i, j, L = cur
                nb = [(i + di, j + dj, L, c) for di, dj, c in steps]
                if self.via_free[i, j] and not block[0, i, j] and not block[1, i, j]:
                    nb.append((i, j, 1 - L, 12.0))
                for ni, nj, NL, c in nb:
                    if not (wi0 <= ni <= wi1 and wj0 <= nj <= wj1):
                        continue
                    nxt = (ni, nj, NL)
                    if nxt not in goal:
                        if not self.free[NL, ni, nj] or block[NL, ni, nj]:
                            continue
                    cost = c * (1.0 + hist[NL, ni, nj]) + pres * occ[NL, ni, nj] * c
                    if self.soft is not None and self.soft[NL, ni, nj] <= self.tr_need:
                        cost += 30.0 * c                  # 他の信号ネットの配線を横切る (後で引き直す候補)
                    ng = gc + cost
                    if ng < dist.get(nxt, 1e18):
                        dist[nxt] = ng
                        came[nxt] = cur
                        heapq.heappush(pq, (ng + h(ni, nj), ng, nxt))
            if found is None:
                if os.environ.get("NEGOT_DEBUG"):
                    print("   no path", net, "expanded", n_exp, "tree", len(tree), "goal", len(goal))
                return None
            path = [found]
            while path[-1] in came:
                path.append(came[path[-1]])
            path.reverse()
            paths.append(path)
            tree |= set(path)
            for k, cells in enumerate(remaining):
                if found in cells:
                    tree |= cells
                    remaining.pop(k)
                    break
        return paths

    def soft_blockers(self):
        """目標ネットを「他の信号配線は横切れる (高コスト)」として引き, 横切った信号ネットを返す."""
        self.build(soft=True)
        pads = self.net_pads()
        g = self.g
        self.blocks = {}
        for n in self.targets:
            blk = np.zeros((2, g.nx, g.ny), dtype=bool)
            for n2, a in self.padnet.items():
                if n2 != n:
                    blk |= a < self.tr_need
            self.blocks[n] = blk
        occ = np.zeros((2, g.nx, g.ny), dtype=np.float32)
        hist = np.zeros_like(occ)
        cells = []
        for n in self.targets:
            r = self.route_net(n, pads[n], occ, hist, 0.0)
            if r is None:
                print("  soft: no path even crossing tracks:", n)
                continue
            cells += [c for p in r for c in p]
        crossed = set()
        if not cells:
            return crossed
        I = np.array([c[0] for c in cells]) * G
        J = np.array([c[1] for c in cells]) * G
        L = np.array([c[2] for c in cells])
        b = pcbnew.LoadBoard(self.path)
        for tr in b.GetTracks():
            n = tr.GetNetname()
            if n in self.fixed or n in self.targets:
                continue
            if tr.GetClass() == "PCB_VIA":
                c = (mm(tr.GetPosition().x), mm(tr.GetPosition().y))
                if np.any(np.hypot(I - c[0], J - c[1]) < mm(tr.GetWidth()) / 2 + self.tr_need):
                    crossed.add(n)
                continue
            Lt = 0 if tr.GetLayer() == pcbnew.F_Cu else 1
            (ax, ay), (bx, by) = (mm(tr.GetStart().x), mm(tr.GetStart().y)), (mm(tr.GetEnd().x), mm(tr.GetEnd().y))
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy or 1e-12
            t = np.clip(((I - ax) * dx + (J - ay) * dy) / L2, 0, 1)
            d = np.hypot(I - ax - t * dx, J - ay - t * dy)
            if np.any((L == Lt) & (d < mm(tr.GetWidth()) / 2 + self.tr_need)):
                crossed.add(n)
        return crossed

    # ---- 占有 (他ネットとの間隙を含む領域) -------------------------------------------
    def claim(self, paths, arr, sign, net=None):
        rt = int(math.ceil((TW + CLR + MARGIN) / G))
        rv = int(math.ceil((VIA_D / 2 + CLR + TW / 2 + MARGIN) / G))
        g = self.g
        for path in paths:
            own = self.padnet.get(net) if net else None
            for k, (i, j, L) in enumerate(path):
                isvia = (k + 1 < len(path) and path[k + 1][2] != L) or (k > 0 and path[k - 1][2] != L)
                if own is not None and not isvia and own[L, i, j] <= PADZ:
                    continue                       # 自分のパッドの上 (銅は元からある) は占有に数えない
                r = rv if isvia else rt
                i0, i1, j0, j1 = max(i - r, 0), min(i + r + 1, g.nx), max(j - r, 0), min(j + r + 1, g.ny)
                I, J = np.meshgrid(np.arange(i0, i1), np.arange(j0, j1), indexing="ij")
                m = (I - i) ** 2 + (J - j) ** 2 <= r * r
                for LL in ((0, 1) if isvia else (L,)):
                    arr[LL, i0:i1, j0:j1][m] += sign

    def run(self, iters=40):
        self.build()
        pads = self.net_pads()
        nets = [n for n in sorted(self.rip, key=lambda n: len(pads.get(n, []))) if len(pads.get(n, [])) >= 2]
        g = self.g
        self.blocks = {}
        for n in nets:
            blk = np.zeros((2, g.nx, g.ny), dtype=bool)
            for n2, a in self.padnet.items():
                if n2 != n:
                    blk |= a < self.tr_need
            self.blocks[n] = blk
        hist = np.zeros((2, g.nx, g.ny), dtype=np.float32)
        occ = np.zeros((2, g.nx, g.ny), dtype=np.float32)
        routes = {}
        pres = 0.5
        order = list(nets)
        for it in range(iters):
            for n in order:
                if n in routes:
                    self.claim(routes[n], occ, -1, n)
                r = self.route_net(n, pads[n], occ, hist, pres)
                if r is None:
                    routes.pop(n, None)
                    print(f"  iter {it}: {n} no path", flush=True)
                    continue
                routes[n] = r
                self.claim(r, occ, +1, n)
            over = self.overuse(routes)
            missing = [n for n in nets if n not in routes]
            print(f"iter {it}: routed {len(routes)}/{len(nets)}, conflicting nets {len(over)} {sorted(over)[:8]}",
                  flush=True)
            if not over and not missing:
                return routes
            self.last_routes = routes
            for (L_, I_, J_) in self.hot:              # 取り合いになった格子だけ履歴コストを上げる
                hist[L_, I_, J_] += 0.8
            pres *= 1.7
            order = list(dict.fromkeys(sorted(over) + missing))
        return None

    def overuse(self, routes):
        g = self.g
        claimed = {}
        total = np.zeros((2, g.nx, g.ny), dtype=np.int16)
        for n, paths in routes.items():
            arr = np.zeros((2, g.nx, g.ny), dtype=np.int16)
            self.claim(paths, arr, +1, n)
            arr = (arr > 0).astype(np.int16)
            claimed[n] = arr
            total += arr
        bad = set()
        self.hot = []
        for n, paths in routes.items():
            others = total - claimed[n]
            own = self.padnet[n]
            cells = [c for path in paths for c in path if own[c[2], c[0], c[1]] > PADZ]
            if not cells:
                continue
            I = np.array([c[0] for c in cells])
            J = np.array([c[1] for c in cells])
            L = np.array([c[2] for c in cells])
            hitm = others[L, I, J] > 0
            if np.any(hitm):
                bad.add(n)
                self.hot.append((L[hitm], I[hitm], J[hitm]))
                if os.environ.get("NEGOT_DEBUG") and len(bad) <= 6:
                    k = int(np.argmax(hitm))
                    who = [m for m in routes if m != n and claimed[m][L[k], I[k], J[k]]]
                    print(f"   conflict {n} at ({I[k]*G:.2f},{J[k]*G:.2f}) L{L[k]} with {who} cells {int(hitm.sum())}")
        return bad

    # ---- 書き戻し ---------------------------------------------------------------------
    def write(self, routes, out):
        nets = {str(k): v for k, v in self.b.GetNetsByName().items() if str(k)}
        nt = nv = 0
        for n, paths in routes.items():
            for path in paths:
                k = 0
                while k < len(path) - 1:
                    i, j, L = path[k]
                    if path[k + 1][2] != L:
                        v = pcbnew.PCB_VIA(self.b)
                        v.SetPosition(pcbnew.VECTOR2I(MMI(i * G), MMI(j * G)))
                        v.SetWidth(MMI(VIA_D))
                        v.SetDrill(MMI(VIA_H))
                        v.SetNet(nets[n])
                        self.b.Add(v)
                        nv += 1
                        k += 1
                        continue
                    m = k + 1
                    d0 = (path[m][0] - i, path[m][1] - j)
                    while m + 1 < len(path) and path[m + 1][2] == L and \
                            (path[m + 1][0] - path[m][0], path[m + 1][1] - path[m][1]) == d0:
                        m += 1
                    t = pcbnew.PCB_TRACK(self.b)
                    t.SetStart(pcbnew.VECTOR2I(MMI(i * G), MMI(j * G)))
                    t.SetEnd(pcbnew.VECTOR2I(MMI(path[m][0] * G), MMI(path[m][1] * G)))
                    t.SetWidth(MMI(TW))
                    t.SetLayer(pcbnew.F_Cu if L == 0 else pcbnew.B_Cu)
                    t.SetNet(nets[n])
                    self.b.Add(t)
                    nt += 1
                    k = m
        for z in self.zones:
            self.b.Add(z)
        self.b.BuildConnectivity()
        pcbnew.ZONE_FILLER(self.b).Fill(self.b.Zones())
        pcbnew.SaveBoard(out, self.b)
        shutil.copy(self.path[:-len(".kicad_pcb")] + ".kicad_pro", out[:-len(".kicad_pcb")] + ".kicad_pro")
        print(f"written: tracks {nt} vias {nv} -> {out}")


if __name__ == "__main__":
    src, out, nets = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
    work = os.path.dirname(os.path.abspath(out))
    e0, u0, _ = drc(src, os.path.join(work, "negot_before.rpt"))
    if "--soft-rip" in sys.argv:
        probe = Router(src, nets, False)
        extra = probe.soft_blockers()
        print("soft-rip adds:", len(extra), ",".join(sorted(extra)), flush=True)
        nets = sorted(set(nets) | extra)
    r = Router(src, nets, "--auto-rip" in sys.argv)
    routes = r.run(int(os.environ.get("NEGOT_ITERS", "40")))
    if routes is None:
        print("negotiation did not converge")
        sys.exit(1)
    tmp = out[:-len(".kicad_pcb")] + "_try.kicad_pcb"
    r.write(routes, tmp)
    e1, u1, blocks = drc(tmp, os.path.join(work, "negot_after.rpt"))
    print(f"DRC: errors {e0} -> {e1}, unconnected {u0} -> {u1}")
    for blk in blocks:
        if blk.startswith(ERR) or blk.startswith("[unconnected_items]"):
            print("   ", blk.replace("\n", " | ")[:220])
    if e1 <= e0 and u1 < u0:
        shutil.copy(tmp, out)
        shutil.copy(tmp[:-len(".kicad_pcb")] + ".kicad_pro", out[:-len(".kicad_pcb")] + ".kicad_pro")
        print("saved", out)
