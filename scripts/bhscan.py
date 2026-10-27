"""Quét chiến lược "Mua đáy và giữ" khung tuần cho crypto và chứng khoán Việt Nam.
Điều kiện: giá đóng tuần thấp hơn đỉnh lịch sử (đỉnh cao nhất tính tới tuần đó) ít nhất 70% (crypto) / 40% (chứng khoán) và tuần tín hiệu đóng dưới đáy mây Ichimoku tuần;
trong 52 tuần trước đã có >= 2 lần đóng trên Tenkan rồi đóng xuống lại trong 4 tuần; lần thứ 3 đóng trên Tenkan -> mua ở giá mở tuần sau, giữ mãi.
Mỗi mã tối đa 1 lần mua trong 52 tuần. Chạy: python3 bhscan.py bh_status.csv bh_buys.csv
"""
import sys, time, csv, math, requests, numpy as np, pandas as pd
from datetime import datetime, timezone

BIN = "https://data-api.binance.vision/api/v3"
ENT = "https://services.entrade.com.vn/chart-api/v2/ohlcs"
CMC = "https://api.coinmarketcap.com/data-api/v3.1/cryptocurrency/historical"
CRYPTO = ["BTC", "ETH", "BNB", "SOL", "LINK", "AAVE", "UNI", "TWT", "LDO", "MORPHO", "HYPE", "ONDO", "XPL"]
CMC_ID = {"HYPE": 32196, "MORPHO": 34104}          # Binance spot có quá ít lịch sử -> lấy nến ngày CoinMarketCap
STOCKS = ["PLX", "POW", "GAS", "MSR", "OIL", "HVN", "VNM", "SAB", "VNZ", "TCB", "MSN", "GMD", "MCH", "MBB", "REE", "PNJ"]
CRASH = {"Crypto": 0.70, "Chứng khoán": 0.40}
NOW_MS = time.time() * 1000
WEEK = 7 * 86400000


def get(url, params):
    for i in range(3):
        try:
            r = requests.get(url, params=params, timeout=60); r.raise_for_status(); return r.json()
        except Exception:
            if i == 2: raise
            time.sleep(2)


def weekly_from_daily(x):
    x["dt"] = pd.to_datetime(x.t, unit="ms")
    w = x.resample("W-MON", on="dt", label="left", closed="left").agg({"o": "first", "h": "max", "l": "min", "c": "last"}).dropna().reset_index()
    w["t"] = ((w.dt - pd.Timestamp("1970-01-01")) // pd.Timedelta(milliseconds=1)).astype("int64")
    return w[w.t + WEEK - 1 < NOW_MS].reset_index(drop=True)[["t", "o", "h", "l", "c"]]


def crypto(sym):
    if sym in CMC_ID:
        rows, end = {}, int(time.time())
        for _ in range(8):
            q = get(CMC, {"id": CMC_ID[sym], "convertId": 2781, "timeStart": end - 400 * 86400, "timeEnd": end, "interval": "1d"})["data"]["quotes"]
            if not q: break
            for z in q:
                t = int(pd.Timestamp(z["timeOpen"]).value // 10**6); u = z["quote"]
                rows[t] = (t, u["open"], u["high"], u["low"], u["close"])
            first = min(int(pd.Timestamp(z["timeOpen"]).value // 10**9) for z in q)
            if first >= end - 86400: break
            end = first - 1
            time.sleep(0.5)
        x = pd.DataFrame(sorted(rows.values()), columns=["t", "o", "h", "l", "c"]).astype({"o": float, "h": float, "l": float, "c": float})
        live = float(x.c.iloc[-1])
        return weekly_from_daily(x), live, "CoinMarketCap"
    j = get(f"{BIN}/klines", {"symbol": sym + "USDT", "interval": "1w", "limit": 1000})
    d = pd.DataFrame(j, columns="t o h l c v ct qv n tb tq x".split())
    for k in "ohlc": d[k] = d[k].astype(float)
    live = float(d.c.iloc[-1])
    d = d[d.ct.astype(float) < NOW_MS].reset_index(drop=True)[["t", "o", "h", "l", "c"]]
    d["t"] = d.t.astype("int64")
    return d, live, "Binance"


def stock(sym):
    j = get(f"{ENT}/stock", {"from": 1325376000, "to": int(time.time()), "symbol": sym, "resolution": "1D"})
    x = pd.DataFrame({"t": np.array(j["t"]) * 1000, "o": j["o"], "h": j["h"], "l": j["l"], "c": j["c"]}).astype(float)
    x["t"] = x.t.astype("int64")
    return weekly_from_daily(x), float(x.c.iloc[-1]), "DNSE (Entrade)"


def failed(C, T, i, look=52, within=4):
    n = 0
    for j in range(max(1, i - look), i):
        if C[j] > T[j] and C[j - 1] <= T[j - 1] and any(C[k] < T[k] for k in range(j + 1, min(j + 1 + within, i))):
            n += 1
    return n


def sig(v, n=6):
    return "" if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else float(f"{v:.{n}g}")


def dstr(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def analyze(sym, market, d, live, src):
    hh = lambda n: d.h.rolling(n).max(); ll = lambda n: d.l.rolling(n).min()
    T = ((hh(9) + ll(9)) / 2).values; K = (hh(26) + ll(26)) / 2
    sa = (((hh(9) + ll(9)) / 2 + K) / 2).shift(26); sb = ((hh(52) + ll(52)) / 2).shift(26)
    lo, hi = np.minimum(sa, sb).values, np.maximum(sa, sb).values
    peak = d.h.cummax().values          # đỉnh lịch sử tính tới từng tuần, không nhìn trước
    O, C, ts = d.o.values, d.c.values, d.t.values; n = len(d); th = CRASH[market]
    def ok(i):   # điều kiện tại tuần i đã đóng
        return (not np.isnan(T[i]) and not np.isnan(lo[i]) and C[i] <= peak[i] * (1 - th) and C[i] < lo[i]
                and C[i] > T[i] and C[i - 1] <= T[i - 1] and failed(C, T, i) >= 2)
    buys, lastb = [], -999
    for i in range(1, n):
        if i - lastb >= 52 and ok(i):
            lastb = i
            if i < n - 1:
                buys.append(dict(market=market, symbol=sym, signal_week=dstr(int(ts[i])), buy_date=dstr(int(ts[i + 1])), buy_price=sig(O[i + 1]),
                                 dd_at_signal=round(C[i] / peak[i] - 1, 4), price=sig(live), ret=round(live / O[i + 1] - 1, 4),
                                 low_after=sig(d.l.values[i + 1:].min()), max_dd_after=round(d.l.values[i + 1:].min() / O[i + 1] - 1, 4)))
    i = n - 1
    dd = C[i] / peak[i] - 1; crash = C[i] <= peak[i] * (1 - th); fc = failed(C, T, i)
    pos = "" if np.isnan(lo[i]) else ("Dưới mây" if C[i] < lo[i] else "Trên mây" if C[i] > hi[i] else "Trong mây")
    new = lastb == i
    if new:
        st, rk, note = "Báo mua", 1, f"Lần thứ 3 đóng trên Tenkan sau {fc} lần thất bại: mua ở giá mở tuần này và giữ."
    elif np.isnan(lo[i]):
        st, rk, note = "Chưa đủ dữ liệu", 6, f"Mới có {n} tuần, cần khoảng 78 tuần để có mây Ichimoku tuần."
    elif crash and pos == "Dưới mây" and fc >= 2 and C[i] <= T[i]:
        st, rk, note = "Chờ lần 3", 2, f"Đủ {fc} lần vượt Tenkan thất bại: báo mua nếu tuần tới đóng trên Tenkan ({sig(T[i])})."
    elif crash and pos == "Dưới mây":
        st, rk, note = "Đang tích lũy", 3, f"Giảm mạnh và dưới mây, mới có {fc}/2 lần vượt Tenkan thất bại trong 52 tuần."
    elif crash:
        st, rk, note = "Giảm mạnh, chưa dưới mây", 4, "Đã giảm đủ nhưng giá không nằm dưới mây tuần."
    else:
        st, rk, note = "Chưa giảm đủ", 5, f"Cần giảm ít nhất {th:.0%} từ đỉnh lịch sử; hiện {dd:.0%}."
    if buys and lastb == i - 1 and not new:
        pass
    held = [b for b in buys]
    avg = sum(b["buy_price"] for b in held) / len(held) if held else None
    row = dict(market=market, symbol=sym, price=sig(live), week_close=sig(C[i]), peak_ath=sig(peak[i]), dd=round(dd, 4),
               need_dd=-th, tenkan=sig(T[i]), cloud_lo=sig(lo[i]), cloud_hi=sig(hi[i]), cloud_pos=pos, failed_52w=fc,
               status=st, rank=rk, note=note, n_buys=len(held), first_buy=held[0]["buy_date"] if held else "",
               last_buy=held[-1]["buy_date"] if held else "", last_buy_price=held[-1]["buy_price"] if held else "",
               avg_entry=sig(avg) if avg else "", ret_avg=round(live / avg - 1, 4) if avg else "",
               ret_last=held[-1]["ret"] if held else "", weeks=n, source=src, week_closed=dstr(int(ts[i])))
    return row, buys


def main(out_status, out_buys):
    rows, buys = [], []
    plan = [(s, "Crypto", crypto) for s in CRYPTO] + [(s, "Chứng khoán", stock) for s in STOCKS]
    for s, m, f in plan:
        try:
            d, live, src = f(s)
            r, b = analyze(s, m, d, live, src); rows.append(r); buys += b
        except Exception as e:
            print("bỏ qua", s, e, file=sys.stderr)
        time.sleep(0.1)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in rows + buys: r["as_of"] = stamp
    for path, data in ((out_status, rows), (out_buys, buys)):
        fields = list(dict.fromkeys(k for r in data for k in r)) if data else ["market", "symbol", "as_of"]
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, restval=""); w.writeheader(); w.writerows(data)
    print(f"{len(rows)} mã, {len(buys)} lần mua lịch sử, {stamp}")
    for r in sorted(rows, key=lambda r: r["rank"]):
        print("·", r["market"], r["symbol"], r["status"], f"giảm {r['dd']:.0%}", r["cloud_pos"], "vượt hỏng", r["failed_52w"], "| đã mua", r["n_buys"], "lần", r["ret_avg"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bh_status.csv", sys.argv[2] if len(sys.argv) > 2 else "bh_buys.csv")
