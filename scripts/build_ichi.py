"""Chiến lược Ichimoku "lần thứ 3" trên Binance spot (dữ liệu công khai). Xuất 4 file CSV:
  Khung 3D (BTC, ETH, BNB, SOL, LINK) – thoát toàn bộ khi nến 3D đóng dưới Kijun:
      signals_3d.csv, trades_3d.csv
  Khung 1W (15 coin theo dõi) – chốt 50% ở 2R (dời SL về hòa vốn), 50% còn lại thoát khi nến tuần đóng dưới MA18:
      signals_1w.csv, trades_1w.csv
Chạy: python3 build_ichi.py [thư_mục_ra]      (chỉ dùng thư viện chuẩn của Python)
"""
import json, sys, os, time, csv, urllib.request
from datetime import datetime, timezone, timedelta

API = "https://data-api.binance.vision/api/v3"
COINS_3D = ["BTC", "ETH", "BNB", "SOL", "LINK"]
COINS_1W = ["BTC", "ETH", "BNB", "SOL", "AAVE", "MORPHO", "LINK", "UNI", "LDO", "TWT", "XPL", "ZEC", "NEAR", "ONDO", "TAO"]
CFG = {"3d": dict(window=121, maxfail=9, ms=3 * 86400000, label="3D"),
       "1w": dict(window=52, maxfail=4, ms=7 * 86400000, label="tuần")}
NEEDFAIL, FEE, TP_R = 2, 0.001, 2.0
VN = timezone(timedelta(hours=7))


def get(path):
    for i in range(3):
        try:
            with urllib.request.urlopen(API + path, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if i == 2:
                raise
            time.sleep(2)


def vn(ms, fmt="%Y-%m-%d %H:%M"):
    return datetime.fromtimestamp(ms / 1000, VN).strftime(fmt)


def r6(x):
    return "" if x is None else float(f"{x:.6g}")


def mid(h, l, i, n):
    return None if i + 1 < n else (max(h[i - n + 1:i + 1]) + min(l[i - n + 1:i + 1])) / 2


def sma(c, i, n):
    return None if i + 1 < n else sum(c[i - n + 1:i + 1]) / n


def series(coin, itv, now_ms):
    k = [x for x in get(f"/klines?symbol={coin}USDT&interval={itv}&limit=1000") if x[6] < now_ms]   # nến đã đóng
    ct = [x[6] + 1 for x in k]
    o, h, l, c = ([float(x[j]) for x in k] for j in (1, 2, 3, 4))
    return ct, o, h, l, c


def signals(h, l, c, window, maxfail):
    n = len(c)
    ten = [mid(h, l, i, 9) for i in range(n)]
    above = [ten[i] is not None and c[i] > ten[i] for i in range(n)]
    runs, i = [], 0
    while i < n:
        if above[i]:
            j = i
            while j + 1 < n and above[j + 1]:
                j += 1
            runs.append((i, j - i + 1)); i = j + 1
        else:
            i += 1
    fails = [sum(1 for s, ln in runs if s + ln - 1 <= x - 1 and x - s <= window and ln <= maxfail) for x in range(n)]
    sig = [x >= 1 and above[x] and not above[x - 1] and fails[x] >= NEEDFAIL for x in range(n)]
    return ten, above, fails, sig


def r_of(e, risk, px):
    net = (px * (1 - FEE)) / (e * (1 + FEE)) - 1
    return round(net * e / risk, 2), round(net * 100, 2)


def waiting_note(above, fails, ten, last, lbl):
    if above[last]:
        return "Giá đang trên Tenkan nhưng không phải lần thứ 3: không vào lệnh."
    if fails[last] >= NEEDFAIL:
        return f"Đủ {fails[last]} lần thất bại: báo mua nếu nến {lbl} tới ĐÓNG trên Tenkan ({r6(ten[last])})."
    return f"Mới có {fails[last]}/{NEEDFAIL} lần thất bại trong 52 tuần: chưa đủ điều kiện."


def analyze_3d(coin, now_ms):
    cf = CFG["3d"]
    ct, o, h, l, c = series(coin, "3d", now_ms)
    n = len(c)
    kij = [mid(h, l, i, 26) for i in range(n)]
    ten, above, fails, sig = signals(h, l, c, cf["window"], cf["maxfail"])
    trades, i = [], 0
    while i < n:
        if not sig[i]:
            i += 1; continue
        e, sl = c[i], l[i]; risk = e - sl
        if risk <= 0:
            i += 1; continue
        px, res, j = None, "Đang mở", n - 1
        for j in range(i + 1, n):
            if l[j] <= sl:
                px, res = min(o[j], sl), "Dừng lỗ"; break
            if kij[j] is not None and c[j] < kij[j]:
                px, res = c[j], "Đóng dưới Kijun"; break
        if px is None:
            j, px = n - 1, c[n - 1]
        R, pct = r_of(e, risk, px)
        trades.append(dict(coin=coin, ngay_vao=vn(ct[i], "%Y-%m-%d"), gia_vao=r6(e), dung_lo=r6(sl),
                           ngay_thoat="" if res == "Đang mở" else vn(ct[j], "%Y-%m-%d"),
                           gia_thoat="" if res == "Đang mở" else r6(px), ket_qua=res, so_nen=j - i,
                           rui_ro_pct=round(risk / e * 100, 2), R=R, lai_pct=pct, _i=i, _j=j))
        i = j + 1
    live = float(get(f"/ticker/price?symbol={coin}USDT")["price"])
    last = n - 1
    tr = trades[-1] if trades else None
    row = dict(coin=coin, trang_thai="Chờ tín hiệu", bao_mua="", gia_dong_nen=r6(c[last]), gia_hien_tai=r6(live),
               nen_dong_luc=vn(ct[last]), nen_tiep_luc=vn(ct[last] + cf["ms"]),
               tenkan=r6(ten[last]), kijun=r6(kij[last]), ngay_vao="", gia_vao="", dung_lo="", chot_loi_kijun="",
               moc_2R="", rui_ro_pct="", R_hien_tai="", lai_pct="", so_lan_that_bai=fails[last], ghi_chu="")
    if tr and tr["ket_qua"] == "Đang mở":
        e, sl = float(tr["gia_vao"]), float(tr["dung_lo"])
        new = tr["_i"] == last
        row.update(trang_thai="Mua mới" if new else "Đang giữ", bao_mua="MUA" if new else "",
                   ngay_vao=tr["ngay_vao"], gia_vao=tr["gia_vao"], dung_lo=tr["dung_lo"],
                   chot_loi_kijun=r6(kij[last]), moc_2R=r6(e + 2 * (e - sl)), rui_ro_pct=tr["rui_ro_pct"],
                   R_hien_tai=round((live - e) / (e - sl), 2), lai_pct=round((live / e - 1) * 100, 2),
                   ghi_chu=("Tín hiệu mới: mua ngay sau khi nến 3D đóng. " if new else "")
                   + "Dừng lỗ đặt sẵn trên sàn; chốt lời toàn bộ khi một nến 3D ĐÓNG dưới Kijun.")
    elif tr and tr["_j"] == last:
        row.update(trang_thai="Thoát lệnh", ngay_vao=tr["ngay_vao"], gia_vao=tr["gia_vao"], dung_lo=tr["dung_lo"],
                   R_hien_tai=tr["R"], lai_pct=tr["lai_pct"],
                   ghi_chu=f"Nến 3D vừa đóng: {tr['ket_qua'].lower()} tại {tr['gia_thoat']}. Bán toàn bộ.")
    else:
        row["ghi_chu"] = waiting_note(above, fails, ten, last, "3D")
    for t in trades:
        t.pop("_i"); t.pop("_j")
    return row, trades


def analyze_1w(coin, now_ms):
    cf = CFG["1w"]
    ct, o, h, l, c = series(coin, "1w", now_ms)
    n = len(c)
    ma18 = [sma(c, i, 18) for i in range(n)]
    ten, above, fails, sig = signals(h, l, c, cf["window"], cf["maxfail"])
    trades, i = [], 0
    while i < n:
        if not sig[i]:
            i += 1; continue
        e, sl = c[i], l[i]; risk = e - sl
        if risk <= 0:
            i += 1; continue
        tp = e + TP_R * risk
        p1 = p2 = None; k1 = None; res = "Đang mở"; j = n - 1
        for j in range(i + 1, n):
            below = ma18[j] is not None and c[j] < ma18[j]
            if p1 is None:
                if l[j] <= sl:
                    p1 = p2 = min(o[j], sl); res = "Dừng lỗ"; break
                if h[j] >= tp:
                    p1 = max(o[j], tp); k1 = j
                    if below:
                        p2 = c[j]; res = "Chốt 50% + đóng dưới MA18"; break
            else:
                if l[j] <= e:
                    p2 = min(o[j], e); res = "Chốt 50% + hòa vốn"; break
                if below:
                    p2 = c[j]; res = "Chốt 50% + đóng dưới MA18"; break
        if p2 is None:
            j = n - 1; res = "Đang mở (đã chốt 50%)" if p1 is not None else "Đang mở"
            mark = c[n - 1]; avg = ((p1 if p1 is not None else mark) + mark) / 2
        else:
            avg = (p1 + p2) / 2
        R, pct = r_of(e, risk, avg)
        trades.append(dict(coin=coin, ngay_vao=vn(ct[i], "%Y-%m-%d"), gia_vao=r6(e), dung_lo=r6(sl), chot_2R=r6(tp),
                           ngay_chot_50=vn(ct[k1], "%Y-%m-%d") if k1 is not None else "",
                           ngay_thoat="" if res.startswith("Đang mở") else vn(ct[j], "%Y-%m-%d"),
                           gia_thoat_tb="" if res.startswith("Đang mở") else r6(avg), ket_qua=res, so_tuan=j - i,
                           rui_ro_pct=round(risk / e * 100, 2), R=R, lai_pct=pct, _i=i, _j=j, _k1=k1, _p1=p1))
        i = j + 1
    live = float(get(f"/ticker/price?symbol={coin}USDT")["price"])
    last = n - 1
    tr = trades[-1] if trades else None
    row = dict(coin=coin, trang_thai="Chờ tín hiệu", bao_mua="", gia_dong_nen=r6(c[last]), gia_hien_tai=r6(live),
               nen_dong_luc=vn(ct[last]), nen_tiep_luc=vn(ct[last] + cf["ms"]),
               tenkan=r6(ten[last]), ma18=r6(ma18[last]), ngay_vao="", gia_vao="", dung_lo="", chot_loi_1_2R="",
               chot_loi_2_ma18="", da_chot_50="", rui_ro_pct="", R_hien_tai="", lai_pct="",
               so_lan_that_bai=fails[last], so_tuan_du_lieu=n, ghi_chu="")
    if tr and tr["ket_qua"].startswith("Đang mở"):
        e, sl = float(tr["gia_vao"]), float(tr["dung_lo"]); risk = e - sl
        new, half = tr["_i"] == last, tr["_k1"] is not None
        just_half = half and tr["_k1"] == last
        avg_now = ((tr["_p1"] if half else live) + live) / 2
        state = "Mua mới" if new else ("Vừa chốt 50%" if just_half else ("Đã chốt 50%" if half else "Đang giữ"))
        note = {"Mua mới": "Tín hiệu mới: mua sau khi nến tuần đóng; đặt dừng lỗ và lệnh chốt 50% tại mốc 2R.",
                "Vừa chốt 50%": "Tuần vừa rồi giá chạm 2R: đã chốt 50%, dời dừng lỗ phần còn lại về giá vào.",
                "Đã chốt 50%": "Còn 50%: dừng lỗ ở giá vào; bán nốt khi nến tuần ĐÓNG dưới MA18.",
                "Đang giữ": "Chờ chạm 2R để chốt 50%; dừng lỗ đặt sẵn trên sàn."}[state]
        row.update(trang_thai=state, bao_mua="MUA" if new else "", ngay_vao=tr["ngay_vao"], gia_vao=tr["gia_vao"],
                   dung_lo=r6(e) if half else tr["dung_lo"], chot_loi_1_2R=tr["chot_2R"],
                   chot_loi_2_ma18=r6(ma18[last]), da_chot_50="Có" if half else "Chưa", rui_ro_pct=tr["rui_ro_pct"],
                   R_hien_tai=round((avg_now - e) / risk, 2), lai_pct=round((avg_now / e - 1) * 100, 2), ghi_chu=note)
    elif tr and tr["_j"] == last:
        row.update(trang_thai="Thoát lệnh", ngay_vao=tr["ngay_vao"], gia_vao=tr["gia_vao"], dung_lo=tr["dung_lo"],
                   chot_loi_1_2R=tr["chot_2R"], da_chot_50="Có" if tr["_k1"] is not None else "Chưa",
                   R_hien_tai=tr["R"], lai_pct=tr["lai_pct"],
                   ghi_chu=f"Nến tuần vừa đóng: {tr['ket_qua'].lower()}. "
                   + ("Bán phần còn lại." if tr["_k1"] is not None else "Bán toàn bộ."))
    else:
        row["ghi_chu"] = waiting_note(above, fails, ten, last, "tuần")
    if n < 78:
        row["ghi_chu"] += " (Ít dữ liệu: dưới 1,5 năm.)"
    for t in trades:
        for k in ("_i", "_j", "_k1", "_p1"):
            t.pop(k)
    return row, trades


def write(outdir, name, data):
    with open(os.path.join(outdir, name), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader(); w.writerows(data)


def main(outdir):
    now_ms = int(time.time() * 1000)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(outdir, exist_ok=True)
    for tf, coins, fn in (("3d", COINS_3D, analyze_3d), ("1w", COINS_1W, analyze_1w)):
        rows, trades = [], []
        for coin in coins:
            try:
                r, t = fn(coin, now_ms)
                r["cap_nhat"] = stamp
                rows.append(r); trades += t
            except Exception as e:
                print("bỏ qua", tf, coin, e, file=sys.stderr)
        write(outdir, f"signals_{tf}.csv", rows)
        write(outdir, f"trades_{tf}.csv", trades)
        print(f"[{tf}] {len(rows)} coin, {len(trades)} lệnh, nến đóng {rows[0]['nen_dong_luc'] if rows else '-'}")
        for r in rows:
            print(f"  {r['coin']}: {r['trang_thai']} | giá {r['gia_hien_tai']} | SL {r['dung_lo']} | R {r['R_hien_tai']} | {r['ghi_chu']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
