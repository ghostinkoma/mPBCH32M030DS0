"""銅箔の 2D 抵抗網で電流分布を解き, 電流密度・ビア電流・ピン電流を IPC-2221 と比べる.

usage: solve.py <board.json> <case-spec-json>
case = {"name", "net", "src": [refs or ref.num], "dst": [...], "I": A}
"""
import json
import math
import sys

import numpy as np
import pyamg
import scipy.sparse as sp
import scipy.sparse.csgraph  # noqa

H = 0.05                      # 格子 (mm)
RHO = 1.72e-8                 # 銅 (Ω·m, 20°C)
T_CU = 35e-6                  # 1oz
RSQ = RHO / T_CU              # シート抵抗 (Ω/□)
T_PLATE = 20e-6               # スルーホールめっき厚 (JLCPCB 公称 ≥18µm)
BOARD_T = 1.6e-3


def w_req(I, dT, t_mil=1.378):
    """IPC-2221 外層: I = 0.048 ΔT^0.44 A^0.725 (A: mil²) → 必要幅 (mm)."""
    A = (I / (0.048 * dT ** 0.44)) ** (1 / 0.725)
    return A / t_mil * 0.0254


def via_cap(drill, dT=20):
    """めっき筒の許容電流 (IPC-2221 内層式で保守的に)."""
    A = math.pi * drill * 1e-3 * T_PLATE * 1e6 / (0.0254 ** 2)   # mm² → mil²
    A = math.pi * drill * (T_PLATE * 1e3) / 0.0254 ** 2
    return 0.024 * dT ** 0.44 * A ** 0.725


def raster_poly(mask, chains, x0, y0):
    ny, nx = mask.shape
    xs_all = np.concatenate([np.array(c)[:, 0] for c in chains])
    ys_all = np.concatenate([np.array(c)[:, 1] for c in chains])
    r0 = max(int((ys_all.min() - y0) / H) - 1, 0)
    r1 = min(int((ys_all.max() - y0) / H) + 2, ny)
    edges = []
    for c in chains:
        a = np.array(c)
        b = np.roll(a, -1, axis=0)
        edges.append(np.hstack([a, b]))
    E = np.vstack(edges)
    for r in range(r0, r1):
        yc = y0 + (r + 0.5) * H
        y1, y2 = E[:, 1], E[:, 3]
        m = ((y1 <= yc) & (y2 > yc)) | ((y2 <= yc) & (y1 > yc))
        if not m.any():
            continue
        e = E[m]
        xi = np.sort(e[:, 0] + (yc - e[:, 1]) * (e[:, 2] - e[:, 0]) / (e[:, 3] - e[:, 1]))
        for xa, xb in zip(xi[0::2], xi[1::2]):
            c0 = max(int(math.ceil((xa - x0) / H - 0.5)), 0)
            c1 = min(int(math.floor((xb - x0) / H - 0.5)), nx - 1)
            if c1 >= c0:
                mask[r, c0:c1 + 1] ^= True if False else True
    return mask


def raster_poly_xor(shape, chains, x0, y0):
    """even-odd で塗る (穴あきポリゴン対応)."""
    ny, nx = shape
    m = np.zeros(shape, bool)
    E = np.vstack([np.hstack([np.array(c), np.roll(np.array(c), -1, axis=0)]) for c in chains])
    r0 = max(int((E[:, [1, 3]].min() - y0) / H) - 1, 0)
    r1 = min(int((E[:, [1, 3]].max() - y0) / H) + 2, ny)
    for r in range(r0, r1):
        yc = y0 + (r + 0.5) * H
        y1, y2 = E[:, 1], E[:, 3]
        sel = ((y1 <= yc) & (y2 > yc)) | ((y2 <= yc) & (y1 > yc))
        if not sel.any():
            continue
        e = E[sel]
        xi = np.sort(e[:, 0] + (yc - e[:, 1]) * (e[:, 2] - e[:, 0]) / (e[:, 3] - e[:, 1]))
        for xa, xb in zip(xi[0::2], xi[1::2]):
            c0 = max(int(math.ceil((xa - x0) / H - 0.5)), 0)
            c1 = min(int(math.floor((xb - x0) / H - 0.5)), nx - 1)
            if c1 >= c0:
                m[r, c0:c1 + 1] = True
    return m


def raster_seg(mask, s, x0, y0):
    xa, ya, xb, yb, w = s
    r = w / 2
    ny, nx = mask.shape
    c0 = max(int((min(xa, xb) - r - x0) / H) - 1, 0)
    c1 = min(int((max(xa, xb) + r - x0) / H) + 2, nx)
    r0 = max(int((min(ya, yb) - r - y0) / H) - 1, 0)
    r1 = min(int((max(ya, yb) + r - y0) / H) + 2, ny)
    X, Y = np.meshgrid(x0 + (np.arange(c0, c1) + 0.5) * H, y0 + (np.arange(r0, r1) + 0.5) * H)
    dx, dy = xb - xa, yb - ya
    L2 = dx * dx + dy * dy
    t = np.clip(((X - xa) * dx + (Y - ya) * dy) / L2, 0, 1) if L2 > 0 else 0
    d = np.hypot(X - (xa + t * dx), Y - (ya + t * dy))
    mask[r0:r1, c0:c1] |= d <= r


def disk(shape, x, y, rad, x0, y0):
    ny, nx = shape
    c0, c1 = max(int((x - rad - x0) / H) - 1, 0), min(int((x + rad - x0) / H) + 2, nx)
    r0, r1 = max(int((y - rad - y0) / H) - 1, 0), min(int((y + rad - y0) / H) + 2, ny)
    X, Y = np.meshgrid(x0 + (np.arange(c0, c1) + 0.5) * H, y0 + (np.arange(r0, r1) + 0.5) * H)
    m = np.zeros(shape, bool)
    m[r0:r1, c0:c1] = np.hypot(X - x, Y - y) <= rad
    return m


def solve(board, case):
    net = board["nets"][case["net"]]
    x0, y0 = -0.5, -0.5
    nx, ny = int((board["W"] + 1) / H) + 1, int((board["H"] + 1) / H) + 1
    shape = (ny, nx)
    cu = {}
    for L in ("F", "B"):
        m = np.zeros(shape, bool)
        for poly in net[L]:
            m |= raster_poly_xor(shape, poly, x0, y0)
        for s in net["segs"][L]:
            raster_seg(m, s, x0, y0)
        cu[L] = m
    links = []   # (mask of ring cells, total conductance, label)
    holes = np.zeros(shape, bool)
    for (x, y, drill, dia) in net["vias"]:
        cu["F"] |= disk(shape, x, y, dia / 2, x0, y0)
        cu["B"] |= disk(shape, x, y, dia / 2, x0, y0)
        hole = disk(shape, x, y, drill / 2, x0, y0)
        ring = disk(shape, x, y, dia / 2, x0, y0) & ~hole
        g = math.pi * drill * 1e-3 * T_PLATE / (RHO * BOARD_T)
        links.append((ring, g, f"via({x:.2f},{y:.2f}) d{drill}", drill))
        holes |= hole

    def sel(spec):
        out = []
        for p in net["pads"]:
            if p["ref"] in spec or f'{p["ref"]}.{p["num"]}' in spec:
                out.append(p)
        return out
    padmask = {L: np.zeros(shape, bool) for L in ("F", "B")}
    padcells = []
    for p in net["pads"]:
        pm = {}
        for L, polys in p["poly"].items():
            m = np.zeros(shape, bool)
            for poly in polys:
                m |= raster_poly_xor(shape, poly, x0, y0)
            if p["tht"] and p["drill"] > 0:
                m &= ~disk(shape, p["x"], p["y"], p["drill"] / 2, x0, y0)
            cu[L] |= m
            padmask[L] |= m
            pm[L] = m
        padcells.append((p, pm))
        if p["tht"] and p["drill"] > 0 and "F" in pm and "B" in pm:
            g = math.pi * p["drill"] * 1e-3 * T_PLATE / (RHO * BOARD_T) * 3   # 筒 + ピン + はんだ (保守的に 3 倍まで)
            links.append((pm["F"] & pm["B"], g, f'{p["ref"]}.{p["num"]}', None))
    for L in cu:
        cu[L] &= ~holes
    # ---- ノード番号 ----
    idx = {}
    n = 0
    for L in ("F", "B"):
        a = -np.ones(shape, np.int64)
        k = int(cu[L].sum())
        a[cu[L]] = np.arange(n, n + k)
        idx[L] = a
        n += k
    rows, cols, vals = [], [], []
    g0 = 1.0 / RSQ
    for L in ("F", "B"):
        a = idx[L]
        for (da, db) in ((a[:, :-1], a[:, 1:]), (a[:-1, :], a[1:, :])):
            m = (da >= 0) & (db >= 0)
            i, j = da[m], db[m]
            rows += [i, j]
            cols += [j, i]
            vals += [np.full(i.size, -g0), np.full(i.size, -g0)]
    link_edges = []
    for ring, g, label, drill in links:
        fi, bi = idx["F"][ring], idx["B"][ring]
        ok = (fi >= 0) & (bi >= 0)
        fi, bi = fi[ok], bi[ok]
        if fi.size == 0:
            continue
        gg = g / fi.size
        rows += [fi, bi]
        cols += [bi, fi]
        vals += [np.full(fi.size, -gg), np.full(fi.size, -gg)]
        link_edges.append((fi, bi, gg, label, drill))
    # ---- 境界: 部品パッドは等電位で固定, コネクタのピン (THT の J*) は接触抵抗 RC を介して外部ノードへ ----
    RC = 0.010
    src_pads, dst_pads = sel(case["src"]), sel(case["dst"])
    assert src_pads and dst_pads, (case, [p["ref"] for p in net["pads"]])
    ext = {1.0: n, 0.0: n + 1}
    n += 2
    fixed_ids, fixed_v, bnd = [], [], []
    for p, pm in padcells:
        tag = 1.0 if p in src_pads else (0.0 if p in dst_pads else None)
        if tag is None:
            continue
        ids = np.concatenate([idx[L][pm[L]] for L in pm])
        ids = ids[ids >= 0]
        if p["tht"] and p["ref"].startswith("J"):
            gg = 1.0 / RC / ids.size
            e = np.full(ids.size, ext[tag])
            rows += [ids, e]
            cols += [e, ids]
            vals += [np.full(ids.size, -gg), np.full(ids.size, -gg)]
            bnd.append((p, ids, tag, gg))
        else:
            fixed_ids.append(ids)
            fixed_v.append(np.full(ids.size, tag))
            bnd.append((p, ids, tag, None))
    Rw = np.concatenate(rows)
    Cw = np.concatenate(cols)
    Vw = np.concatenate(vals)
    A = sp.coo_matrix((Vw, (Rw, Cw)), shape=(n, n)).tocsr()
    A = A - sp.diags(np.asarray(A.sum(axis=1)).ravel())     # ラプラシアン (対角 = Σg)
    fixed = np.zeros(n, bool)
    V = np.zeros(n)
    for ids, v in zip(fixed_ids, fixed_v):
        fixed[ids] = True
        V[ids] = v
    for tag, e in ext.items():
        fixed[e] = True
        V[e] = tag
    free = ~fixed
    # 連結していない銅 (島) は解けないので, 境界につながる成分だけを解く
    ncomp, lab = sp.csgraph.connected_components(A != 0, directed=False)
    alive = np.isin(lab, list(set(lab[fixed])))
    free2 = free & alive
    Aff = A[free2][:, free2].tocsr()
    b = -A[free2][:, fixed] @ V[fixed]
    ml = pyamg.smoothed_aggregation_solver(Aff)
    x = ml.solve(b, tol=1e-10, maxiter=500, accel="cg")
    V[free2] = x
    V[~alive] = np.nan
    flow = A @ np.nan_to_num(V)              # 各ノードからの湧き出し (V=1 のとき)
    Vn = np.nan_to_num(V)
    def pad_current(p, ids, tag, gg):
        if gg is None:
            return float(flow[ids].sum())
        return float(((Vn[ids] - V[ext[tag]]) * gg).sum()) * -1.0
    Itot = sum(pad_current(*t) for t in bnd if t[2] == 1.0)
    Rpath = 1.0 / Itot
    scale = case["I"] / Itot                 # V を目標電流に合わせる
    Vs = V * scale
    res = {"name": case["name"], "net": case["net"], "I": case["I"], "R_mohm": Rpath * 1e3,
           "Vdrop_mV": case["I"] * Rpath * 1e3, "P_mW": case["I"] ** 2 * Rpath * 1e3}
    # 電流密度 (A/mm): 各セルの左右・上下の辺電流の平均
    res = {"name": case["name"], "net": case["net"], "I": case["I"], "R_mohm": Rpath * 1e3,
           "Vdrop_mV": case["I"] * Rpath * 1e3, "P_mW": case["I"] ** 2 * Rpath * 1e3}
    jmax = []
    for L in ("F", "B"):
        a = idx[L]
        VV = np.full(shape, np.nan)
        VV[a >= 0] = Vs[a[a >= 0]]
        ex = np.zeros(shape)
        ey = np.zeros(shape)
        dxv = (VV[:, :-1] - VV[:, 1:]) * g0          # 右向きの辺電流 (A)
        dxv = np.nan_to_num(dxv)
        dyv = np.nan_to_num((VV[:-1, :] - VV[1:, :]) * g0)
        ex[:, :-1] += dxv / 2
        ex[:, 1:] += dxv / 2
        ey[:-1, :] += dyv / 2
        ey[1:, :] += dyv / 2
        j = np.hypot(ex, ey) / H                      # A/mm
        # パッド (部品・はんだで覆われる) とその 0.1mm 周囲は除外
        pm = padmask[L]
        dil = pm.copy()
        for _ in range(2):
            dil = dil | np.roll(dil, 1, 0) | np.roll(dil, -1, 0) | np.roll(dil, 1, 1) | np.roll(dil, -1, 1)
        jj = np.where(cu[L] & ~dil & ~np.isnan(VV), j, 0)
        if case.get("png"):
            from PIL import Image
            ok = case["I"] / w_req(case["I"], 20)
            img = np.full(shape + (3,), 255, np.uint8)
            img[cu[L]] = (200, 200, 200)
            r = np.clip(j / ok, 0, 3) / 3                  # 0..3 倍の許容密度を色に
            m = cu[L] & ~np.isnan(VV)
            img[m] = np.stack([255 * r[m], 255 * (1 - np.abs(r[m] - 0.33) * 1.5).clip(0, 1), 255 * (1 - r[m])], -1).astype(np.uint8)
            img[m & (j > ok)] = (255, 0, 0)
            img[pm] = (60, 60, 60)
            Image.fromarray(img).save(f'{case["png"]}_{L}.png')
        k = np.unravel_index(np.argmax(jj), shape)
        # パッドの口元 (0.5mm 以内) を除いた最大密度と, 許容 (ΔT 20°C) を超える面積
        far = pm.copy()
        for _ in range(10):
            far = far | np.roll(far, 1, 0) | np.roll(far, -1, 0) | np.roll(far, 1, 1) | np.roll(far, -1, 1)
        jf = np.where(~far, jj, 0)
        okd = case["I"] / w_req(case["I"], 20)
        kf = np.unravel_index(np.argmax(jf), shape)
        # 熱の広がり (銅箔 + 基材で ~1mm) を考え, 銅のある格子だけで ±0.5mm を平均した密度の最大
        from scipy.ndimage import uniform_filter
        cm = (jj > 0).astype(float)
        n1 = int(round(1.0 / H)) | 1
        js = uniform_filter(jj, n1) / np.maximum(uniform_filter(cm, n1), 1e-9)
        js = np.where(~far & (jj > 0), js, 0)
        ks = np.unravel_index(np.argmax(js), shape)
        jmax.append((float(jj.max()), L, x0 + (k[1] + 0.5) * H, y0 + (k[0] + 0.5) * H,
                     float(np.percentile(jj[jj > 0], 99.5)) if (jj > 0).any() else 0.0,
                     float(jf.max()), (round(x0 + (kf[1] + 0.5) * H, 2), round(y0 + (kf[0] + 0.5) * H, 2)),
                     float((jf > okd).sum() * H * H), float(js.max()),
                     (round(x0 + (ks[1] + 0.5) * H, 2), round(y0 + (ks[0] + 0.5) * H, 2))))
    top = max(jmax)
    fartop = max(jmax, key=lambda v: v[5])
    stop = max(jmax, key=lambda v: v[8])
    res.update({"j_max": top[0], "j_layer": top[1], "j_at": (round(top[2], 2), round(top[3], 2)),
                "j_p995": max(v[4] for v in jmax), "j_far": fartop[5], "j_far_at": (fartop[1],) + fartop[6],
                "j_far1": stop[8], "j_far1_at": (stop[1],) + stop[9],
                "hot_mm2": sum(v[7] for v in jmax)})
    # ビア電流
    vi = []
    for fi, bi, gg, label, drill in link_edges:
        i = float(np.nansum(np.abs((Vs[fi] - Vs[bi]) * gg)))
        vi.append((i, label, drill))
    vi.sort(reverse=True)
    res["vias_top"] = [(round(i, 2), l, d) for i, l, d in vi[:4] if d]
    res["via_over"] = [(round(i, 2), l, d, round(via_cap(d), 2)) for i, l, d in vi if d and i > via_cap(d)]
    # ピン (THT 境界) ごとの電流
    pins = []
    for t in bnd:
        pins.append((f'{t[0]["ref"]}.{t[0]["num"]}', round(pad_current(*t) * scale, 2)))
    res["pins"] = pins
    return res


if __name__ == "__main__":
    board = json.load(open(sys.argv[1]))
    cases = json.loads(sys.argv[2])
    out = []
    for c in cases:
        r = solve(board, c)
        wq = w_req(c["I"], 20)
        r["j_ok20"] = c["I"] / wq
        r["j_ok10"] = c["I"] / w_req(c["I"], 10)
        r["w_eff"] = c["I"] / r["j_max"] if r["j_max"] else 0
        r["w_req20"] = wq
        out.append(r)
        print(json.dumps(r, ensure_ascii=False))
        sys.stdout.flush()
