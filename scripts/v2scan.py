"""Quét tín hiệu chiến lược V2 khung tuần cho crypto (Binance) và chứng khoán Việt Nam (Entrade).
V2: mua khi nến tuần đóng cắt lên Tenkan và 52 tuần trước có >= 2 lần vượt Tenkan thất bại (đóng lại dưới trong 4 tuần);
dừng lỗ = đáy nến tín hiệu; bán 50% ở 2R rồi dời dừng lỗ về giá vào; bán phần còn lại khi nến tuần đóng dưới MA18.
Chạy: python3 v2scan.py v2_signals.csv
"""
import sys, time, csv, math, requests, numpy as np, pandas as pd
from datetime import datetime, timezone

BIN = "https://data-api.binance.vision/api/v3"
ENT = "https://services.entrade.com.vn/chart-api/v2/ohlcs"
C_WATCH = ["BTC", "ETH", "BNB", "SOL", "AAVE", "MORPHO", "LINK", "UNI", "LDO", "TWT", "XPL", "ZEC", "NEAR", "ONDO", "TAO"]
SKIP = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "AEUR", "XUSD", "USD1", "BFUSD", "PAXG", "WBTC", "WBETH", "BUSD",
        "USDE", "RLUSD", "EURI", "RWUSD", "USDF"}
V_WATCH = ["PLX", "SAB", "POW", "MSR", "OIL", "HVN", "VNZ", "BSR", "PVS", "PVT"]
VN30 = ["ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG", "LPB", "MBB", "MSN", "MWG", "PLX",
        "SAB", "SHB", "SSB", "SSI", "STB", "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"]
NOW_MS = time.time() * 1000


def get(url, params):
    for i in range(3):
        try:
            r = requests.get(url, params=params, timeout=60); r.raise_for_status(); return r.json()
        except Exception:
            if i == 2: raise
            time.sleep(2)


def ind(d):
    hh = lambda n: d.h.rolling(n).max(); ll = lambda n: d.l.rolling(n).min()
    d["ten"] = (hh(9) + ll(9)) / 2; d["kij"] = (hh(26) + ll(26)) / 2; d["ma"] = d.c.rolling(18).mean()
    return d


def crypto_weekly(base):
    j = get(f"{BIN}/klines", {"symbol": base + "USDT", "interval": "1w", "limit": 1000})
    d = pd.DataFrame(j, columns="t o h l c v ct qv n tb tq x".split())
    for k in "ohlc": d[k] = d[k].astype(float)
    live = float(d.c.iloc[-1])
    d = d[d.ct.astype(float) < NOW_MS].reset_index(drop=True)[["t", "o", "h", "l", "c"]]
    d["t"] = d.t.astype("int64")
    return ind(d), live


def vn_weekly(sym, kind):
    j = get(f"{ENT}/{kind}", {"from": 1325376000, "to": int(time.time()), "symbol": sym, "resolution": "1D"})
    x = pd.DataFrame({"t": j["t"], "o": j["o"], "h": j["h"], "l": j["l"], "c": j["c"]}).astype(float)
    live = float(x.c.iloc[-1])
    x["dt"] = pd.to_datetime(x.t, unit="s")
    w = x.resample("W-MON", on="dt", label="left", closed="left").agg({"o": "first", "h": "max", "l": "min", "c": "last"}).dropna().reset_index()
    w["t"] = ((w.dt - pd.Timestamp("1970-01-01")) // pd.Timedelta(milliseconds=1)).astype("int64")
    w = w[w.t + 7 * 86400000 - 1 < NOW_MS].reset_index(drop=True)[["t", "o", "h", "l", "c"]]   # chỉ tuần đã đóng
    return ind(w), live


def failed(C, T, i, look=52, within=4):
    n = 0
    for j in range(max(1, i - look), i):
        if C[j] > T[j] and C[j - 1] <= T[j - 1] and any(C[k] < T[k] for k in range(j + 1, min(j + 1 + within, i))):
            n += 1
    return n


def dstr(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d") if ms else ""


def sig(v, n=6):
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else float(f"{v:.{n}g}")


def simulate(d, fee):
    O, H, L, C, T, M = [d[k].values for k in ("o", "h", "l", "c", "ten", "ma")]; ts = d.t.values
    n = len(d); pos = None; trades = []
    def close(px, i, why):
        nonlocal pos
        p = pos; pos = None
        R = p["half"] * (p["tp"] - p["ep"]) / p["R"] + (1 - p["half"]) * (px - p["ep"]) / p["R"] - 2 * fee * p["ep"] / p["R"]
        trades.append(dict(e=p["e"], x=int(ts[i]), R=R, why=why))
    for i in range(52, n):
        if pos and i >= pos["i"]:
            if L[i] <= pos["stop"]:
                close(min(O[i], pos["stop"]), i, "Hòa vốn" if pos["half"] else "Dừng lỗ")
            else:
                if not pos["half"] and H[i] >= pos["tp"]:
                    pos["half"] = 0.5; pos["stop"] = pos["ep"]
                if pos and pos["half"] and C[i] < M[i] and i < n - 1:
                    close(O[i + 1], i + 1, "Đóng dưới MA18")
                elif pos and pos["half"] and C[i] < M[i] and i == n - 1:
                    pos["exit_next"] = True
        if pos is None and i < n - 1 and not np.isnan(T[i]) and C[i] > T[i] and C[i - 1] <= T[i - 1] and failed(C, T, i) >= 2:
            ep = O[i + 1]; st = L[i]
            if st < ep:
                pos = dict(i=i + 1, e=int(ts[i + 1]), sigw=int(ts[i]), ep=ep, stop=st, stop0=st, R=ep - st, tp=ep + 2 * (ep - st), half=0)
    return pos, trades


def analyze(sym, market, group, d, live, fee):
    if len(d) < 70: raise ValueError("ít dữ liệu")
    C, T = d.c.values, d.ten.values; last = len(d) - 1
    pos, trades = simulate(d, fee)
    closed = [t for t in trades]
    row = dict(market=market, symbol=sym, group=group, price=sig(live), week_close=sig(C[last]),
               tenkan=sig(T[last]), kijun=sig(d.kij.values[last]), ma18=sig(d.ma.values[last]),
               failed_52w=failed(C, T, last + 1 if False else last), signal_week="", entry_date="", entry="", stop0="", stop_now="",
               target_2r="", tp1_done="", r_now="", risk_pct="", last_exit="", last_exit_r="",
               n_trades=len(closed), win_rate=round(sum(t["R"] > 0 for t in closed) / len(closed), 3) if closed else "",
               total_r=round(sum(t["R"] for t in closed), 2) if closed else 0)
    # tín hiệu ở nến tuần vừa đóng (vào lệnh ở giá mở tuần này)
    new_sig = (pos is None and C[last] > T[last] and C[last - 1] <= T[last - 1] and failed(C, T, last) >= 2 and d.l.values[last] < live)
    if new_sig:
        ep = live; st = d.l.values[last]; R = ep - st
        row.update(status="Tín hiệu mới", rank=1, signal_week=dstr(int(d.t.values[last])), entry=sig(ep), stop0=sig(st), stop_now=sig(st),
                   target_2r=sig(ep + 2 * R), r_now=0, risk_pct=round(R / ep, 4), tp1_done=0)
    elif pos:
        R = pos["R"]
        row.update(status="Bán phần còn lại" if pos.get("exit_next") else ("Đã chốt 2R, giữ 50%" if pos["half"] else "Đang giữ"),
                   rank=2 if pos.get("exit_next") else (3 if pos["half"] else 4),
                   signal_week=dstr(pos["sigw"]), entry_date=dstr(pos["e"]), entry=sig(pos["ep"]), stop0=sig(pos["stop0"]),
                   stop_now=sig(pos["stop"]), target_2r=sig(pos["tp"]), tp1_done=int(bool(pos["half"])),
                   r_now=round(pos["half"] * 2 + (1 - pos["half"]) * (live - pos["ep"]) / R, 2), risk_pct=round(R / pos["ep"], 4))
    else:
        f = failed(C, T, last + 1) if False else None
        armed = failed(C, T, last) >= 2 and C[last] <= T[last]
        if trades and trades[-1]["x"] >= int(d.t.values[last]) - 3 * 7 * 86400000:
            row.update(status="Vừa thoát", rank=5)
        elif armed:
            row.update(status="Chờ vượt Tenkan", rank=6)
        else:
            row.update(status="Chưa có thiết lập", rank=7)
    if trades:
        row.update(last_exit=dstr(trades[-1]["x"]), last_exit_r=round(trades[-1]["R"], 2))
    row["week_closed"] = dstr(int(d.t.values[last]))
    return row


def main(out):
    rows = []
    t = get(f"{BIN}/ticker/24hr", {})
    u = [x for x in t if x["symbol"].endswith("USDT") and x["symbol"][:-4] not in SKIP
         and not any(k in x["symbol"] for k in ("UPUSDT", "DOWNUSDT", "BULL", "BEAR")) and float(x["quoteVolume"]) > 0]
    u.sort(key=lambda x: -float(x["quoteVolume"]))
    top = [x["symbol"][:-4] for x in u[:80]]
    seen = set()
    for s in C_WATCH + top:
        if s in seen: continue
        seen.add(s)
        try:
            d, live = crypto_weekly(s)
            rows.append(analyze(s, "Crypto", "Danh sách theo dõi" if s in C_WATCH else "Top 80", d, live, 0.001))
        except Exception as e:
            print("bỏ qua", s, e, file=sys.stderr)
        time.sleep(0.05)
    plan = [("VNINDEX", "index", "Chỉ số")] + [(s, "stock", "Danh sách theo dõi") for s in V_WATCH] + [(s, "stock", "VN30") for s in VN30 if s not in V_WATCH]
    for s, kind, g in plan:
        try:
            d, live = vn_weekly(s, kind)
            rows.append(analyze(s, "Chứng khoán", g, d, live, 0.002))
        except Exception as e:
            print("bỏ qua", s, e, file=sys.stderr)
        time.sleep(0.2)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in rows: r["as_of"] = stamp
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval=""); w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} mã, {stamp} -> {out}")
    for r in rows:
        if r["rank"] in (1, 2): print("·", r["market"], r["symbol"], r["status"], "giá", r["price"], "dừng lỗ", r["stop_now"], "2R", r["target_2r"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "v2_signals.csv")
