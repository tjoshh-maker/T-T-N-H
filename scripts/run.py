"""Chạy các bộ quét, cập nhật dữ liệu cho dashboard (docs/data) và gửi thông báo Telegram.

Cách dùng:
    python scripts/run.py                 # tự chọn: Ichimoku mỗi ngày, thêm V2 + Mua đáy vào thứ Hai (giờ VN)
    python scripts/run.py --jobs all      # chạy cả 3
    python scripts/run.py --jobs ichi,v2  # chỉ chạy những bộ được nêu
    python scripts/run.py --no-send       # không gửi Telegram, chỉ in tin nhắn ra màn hình

Biến môi trường (tùy chọn): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ZALO_BOT_TOKEN, ZALO_CHAT_ID, DASHBOARD_URL.
Có ZALO_BOT_TOKEN mà chưa có ZALO_CHAT_ID: nhật ký sẽ in ra chat id của người vừa nhắn cho bot Zalo.
"""
import argparse, csv, json, os, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
DATA = os.path.join(ROOT, "docs", "data")
META = os.path.join(DATA, "meta.json")
VN = timezone(timedelta(hours=7))
NOTE = "Chỉ là công cụ theo dõi, không phải khuyến nghị đầu tư."

JOBS = {
    "ichi": dict(name="Ichimoku 3D & tuần", script="build_ichi.py", args=["{tmp}"],
                 files=["signals_3d.csv", "trades_3d.csv", "signals_1w.csv", "trades_1w.csv"],
                 check=("signals_3d.csv", 3)),
    "v2": dict(name="Tín hiệu V2 khung tuần", script="v2scan.py", args=["{tmp}/v2_signals.csv"],
               files=["v2_signals.csv"], check=("v2_signals.csv", 50)),
    "bh": dict(name="Mua đáy và giữ", script="bhscan.py", args=["{tmp}/bh_status.csv", "{tmp}/bh_buys.csv"],
               files=["bh_status.csv", "bh_buys.csv"], check=("bh_status.csv", 20)),
}


# ---------- tiện ích ----------
def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt(v):
    x = num(v)
    if x is None:
        return str(v or "–")
    if abs(x) >= 1000:
        return f"{x:,.0f}" if abs(x) >= 10000 else f"{x:,.1f}"
    return f"{x:.6g}"


def pct(v):
    """Tỷ lệ dạng 0.123 -> '12.3%' (bỏ dấu âm)."""
    x = num(v)
    return "–" if x is None else f"{abs(x) * 100:.1f}%"


def mk(r):
    return "crypto" if r.get("market") == "Crypto" else "CK, nghìn đ"


# ---------- tin nhắn ----------
def msg_ichi(d, today):
    s3, s1 = read_csv(os.path.join(d, "signals_3d.csv")), read_csv(os.path.join(d, "signals_1w.csv"))
    out, new = [], False
    closed3 = [r for r in s3 if r["nen_dong_luc"][:10] == today]
    # Luật 3D: bán toàn bộ ở lần test Tenkan thứ 2 (giá đóng nến); lưới an toàn: nến 3D đóng dưới Kijun.
    if closed3:
        buys = [r for r in closed3 if r["trang_thai"] == "Mua mới"]
        exits = [r for r in closed3 if r["trang_thai"] == "Thoát lệnh"]
        warns = [r for r in closed3 if r["trang_thai"] == "Đang giữ" and r.get("canh_bao")]
        if buys:
            new = True
            out.append("3D BÁO MUA: " + "; ".join(
                f"{r['coin']} giá vào {fmt(r['gia_vao'])}, dừng lỗ {fmt(r['dung_lo'])}, rủi ro {fmt(r['rui_ro_pct'])}%"
                for r in buys))
        if exits:
            new = True
            out.append("3D THOÁT: " + "; ".join(f"{r['coin']} – {r['ghi_chu']}" for r in exits))
        if warns:
            new = True
            out.append("3D CẢNH BÁO: " + "; ".join(
                f"{r['coin']} {r['canh_bao']} (Tenkan {fmt(r['nguong_tenkan'])}, {fmt(r['R_hien_tai'])}R)"
                for r in warns))
    hold3 = [r for r in s3 if r["trang_thai"] in ("Đang giữ", "Mua mới")]
    if hold3:
        out.append("3D đang giữ: " + ", ".join(
            f"{r['coin']} ({fmt(r['R_hien_tai'])}R, đã test Tenkan {r.get('test_tenkan') or 0} lần)" for r in hold3))
    if s1 and s1[0]["nen_dong_luc"][:10] == today:
        groups = [("TUẦN BÁO MUA", "Mua mới", lambda r: f"{r['coin']} giá vào {fmt(r['gia_vao'])}, dừng lỗ {fmt(r['dung_lo'])}, chốt 50% tại {fmt(r['chot_loi_1_2R'])}, rủi ro {fmt(r['rui_ro_pct'])}%"),
                  ("TUẦN VỪA CHỐT 50%", "Vừa chốt 50%", lambda r: f"{r['coin']} (dời dừng lỗ phần còn lại về giá vào {fmt(r['gia_vao'])})"),
                  ("TUẦN THOÁT", "Thoát lệnh", lambda r: f"{r['coin']} – {r['ghi_chu']}")]
        for label, st, f in groups:
            rows = [r for r in s1 if r["trang_thai"] == st]
            if rows:
                new = True
                out.append(f"{label}: " + "; ".join(f(r) for r in rows))
        held = [r for r in s1 if r["trang_thai"] in ("Mua mới", "Đang giữ", "Vừa chốt 50%", "Đã chốt 50%")]
        out.append(f"Khung tuần đang giữ {len(held)} coin" + (": " + ", ".join(r["coin"] for r in held) if held else "."))
    if not new:
        nxt3 = min((r["nen_tiep_luc"] for r in s3), default="–")
        nxt1 = s1[0]["nen_tiep_luc"] if s1 else "–"
        out.insert(0, f"Không có tín hiệu mới hôm nay. Nến 3D tiếp theo đóng {nxt3}, nến tuần {nxt1}.")
    return out


def msg_v2(d, today):
    rows = read_csv(os.path.join(d, "v2_signals.csv"))
    by = lambda st: [r for r in rows if r["status"] == st]
    out = []
    if by("Tín hiệu mới"):
        out.append("MUA MỚI: " + "; ".join(
            f"{r['symbol']} ({mk(r)}) giá {fmt(r['price'])}, dừng lỗ {fmt(r['stop_now'])}, chốt 50% tại {fmt(r['target_2r'])}, rủi ro {pct(r['risk_pct'])}"
            for r in by("Tín hiệu mới")))
    if by("Bán phần còn lại"):
        out.append("BÁN NỐT 50%: " + ", ".join(f"{r['symbol']} ({mk(r)})" for r in by("Bán phần còn lại")))
    d0 = datetime.strptime(today, "%Y-%m-%d").date()
    recent = [r for r in by("Vừa thoát") if r["last_exit"] and (d0 - datetime.strptime(r["last_exit"], "%Y-%m-%d").date()).days <= 7]
    if recent:
        out.append("VỪA THOÁT: " + ", ".join(f"{r['symbol']} ({fmt(r['last_exit_r'])}R)" for r in recent))
    st = {r["symbol"]: r["status"] for r in rows}
    status = (f"BTC: {st.get('BTC', '–')}; VNINDEX: {st.get('VNINDEX', '–')}. "
              f"Đang giữ {len(by('Đang giữ'))} mã, đã chốt 2R giữ 50%: {len(by('Đã chốt 2R, giữ 50%'))} mã.")
    if not out:
        out.append("Tuần này không có tín hiệu V2 mới.")
    out.append(status)
    return out


def msg_bh(d, today):
    rows = read_csv(os.path.join(d, "bh_status.csv"))
    by = lambda st: [r for r in rows if r["status"] == st]
    out = []
    if by("Báo mua"):
        out.append("MUA ĐÁY: " + "; ".join(
            f"{r['symbol']} ({mk(r)}) giá {fmt(r['price'])}, giảm {pct(r['dd'])} từ đỉnh, {r['failed_52w']} lần vượt hỏng"
            for r in by("Báo mua")) + ". Quy tắc: mua và giữ, không dừng lỗ.")
    if by("Chờ lần 3"):
        out.append("CHỜ LẦN 3: " + "; ".join(
            f"{r['symbol']} ({mk(r)}) cần tuần đóng trên Tenkan {fmt(r['tenkan'])}, giá hiện {fmt(r['price'])}"
            for r in by("Chờ lần 3")))
    if by("Đang tích lũy"):
        out.append("ĐANG TÍCH LŨY: " + ", ".join(r["symbol"] for r in by("Đang tích lũy")))
    if not out:
        out.append("Tuần này chưa có mã nào gần điểm mua đáy.")
    return out


MSG = {"ichi": msg_ichi, "v2": msg_v2, "bh": msg_bh}


# ---------- Gửi tin: Telegram và Zalo ----------
def _post(url, data, as_json=False, http_timeout=30):
    """Gửi POST, trả về (ok, nội dung phản hồi)."""
    import urllib.request, urllib.parse, urllib.error
    if as_json:
        body, headers = json.dumps(data).encode(), {"Content-Type": "application/json"}
    else:
        body, headers = urllib.parse.urlencode(data).encode(), {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=http_timeout) as r:
            return True, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
    except Exception as e:
        return False, str(e)


def chunks(text, size):
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def send_telegram(text):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("(chưa cài TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID: bỏ qua Telegram)")
        return
    for part in chunks(text, 3900):
        ok, res = _post(f"https://api.telegram.org/bot{token}/sendMessage",
                        {"chat_id": chat, "text": part, "disable_web_page_preview": "true"})
        if not ok:
            print("Gửi Telegram lỗi:", res, file=sys.stderr)
            if "chat not found" in res:
                print("  -> TELEGRAM_CHAT_ID sai: hãy nhắn cho bot rồi lấy lại 'chat':{'id':...} trong getUpdates", file=sys.stderr)
            return


def zalo_chat_ids(token):
    """In ra chat id của những ai vừa nhắn cho bot Zalo (dùng khi chưa có ZALO_CHAT_ID)."""
    base = f"https://bot-api.zaloplatforms.com/bot{token}"
    _post(base + "/deleteWebhook", {}, as_json=True)
    found = set()
    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("chat"), dict) and o["chat"].get("id"):
                found.add((str(o["chat"]["id"]), o["chat"].get("display_name") or o["chat"].get("name") or ""))
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    # Zalo chỉ trả về tin đến trong lúc đang chờ, nên chờ liên tục khoảng 5 phút
    print(">>> Đang chờ tin nhắn tới bot Zalo (tối đa ~5 phút): hãy gửi 'hi' cho bot ngay bây giờ")
    res = ""
    for _ in range(10):
        ok, res = _post(base + "/getUpdates", {"timeout": 30}, as_json=True, http_timeout=45)
        if not ok and "408" not in res:
            print("Zalo getUpdates lỗi:", res, file=sys.stderr)
            print(f"::warning title=Zalo::getUpdates lỗi: {res[:200]}")
            return
        try:
            walk(json.loads(res))
        except Exception:
            pass
        if found:
            break
    if found:
        for cid, name in found:
            print(f">>> ZALO_CHAT_ID tìm được: {cid}  {name}")
            print(f"::notice title=ZALO_CHAT_ID::{cid} {name}")   # hiện ở trang tóm tắt của lần chạy
    else:
        print(">>> Chưa thấy tin nhắn nào gửi tới bot Zalo. Hãy mở bot trong Zalo, gửi 'hi' rồi chạy lại. Phản hồi:", res[:300])
        print(f"::warning title=Zalo::Chưa thấy tin nhắn tới bot. Phản hồi: {res[:200]}")


def send_zalo(text):
    token, chat = os.environ.get("ZALO_BOT_TOKEN"), os.environ.get("ZALO_CHAT_ID")
    if not token:
        return
    if not chat:
        print("(đã có ZALO_BOT_TOKEN nhưng chưa có ZALO_CHAT_ID: đang dò chat id…)")
        zalo_chat_ids(token)
        return
    for part in chunks(text, 1900):          # Zalo giới hạn 2000 ký tự mỗi tin
        ok, res = _post(f"https://bot-api.zaloplatforms.com/bot{token}/sendMessage",
                        {"chat_id": chat, "text": part}, as_json=True)
        if not ok or '"ok":false' in res.replace(" ", ""):
            print("Gửi Zalo lỗi:", res, file=sys.stderr)
            return


def send_all(text):
    send_telegram(text)
    send_zalo(text)


def dashboard_url():
    if os.environ.get("DASHBOARD_URL"):
        return os.environ["DASHBOARD_URL"]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


# ---------- chạy ----------
def run_job(key, meta, today):
    job = JOBS[key]
    tmp = tempfile.mkdtemp(prefix=key + "_")
    args = [a.format(tmp=tmp) for a in job["args"]]
    print(f"\n=== {job['name']} ===", flush=True)
    entry = meta["datasets"].setdefault(key, {})
    try:
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, job["script"])] + args,
                           capture_output=True, text=True, timeout=1500)
        print(p.stdout[-4000:]); print(p.stderr[-2000:], file=sys.stderr)
        if p.returncode != 0:
            if "bỏ qua" in p.stderr:
                raise RuntimeError("không lấy được dữ liệu giá; nguồn giá có thể đang lỗi hoặc chặn truy cập")
            raise RuntimeError("mã quét bị lỗi: " + (p.stderr.strip().splitlines() or ["không rõ"])[-1][:200])
        fname, need = job["check"]
        n = len(read_csv(os.path.join(tmp, fname)))
        if n < need:
            raise RuntimeError(f"{fname} chỉ có {n} dòng (cần ít nhất {need}); có thể nguồn giá không truy cập được")
        lines = MSG[key](tmp, today)
        for f in job["files"]:
            shutil.copyfile(os.path.join(tmp, f), os.path.join(DATA, f))
        stamp = now_utc()
        entry.update(updated=stamp, lastAttempt={"at": stamp, "ok": True})
        text = "\n".join(lines)
        meta["messages"][key] = {"at": stamp, "text": text}
        return f"📊 {job['name']}\n{text}"
    except Exception as e:
        entry["lastAttempt"] = {"at": now_utc(), "ok": False, "error": str(e)}
        return f"⚠️ {job['name']}: không cập nhật được – {e}. Dữ liệu cũ vẫn giữ nguyên trên dashboard."
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default="auto")
    ap.add_argument("--no-send", action="store_true")
    a = ap.parse_args()
    vn_now = datetime.now(VN)
    today = vn_now.strftime("%Y-%m-%d")
    if a.jobs == "auto":
        keys = ["ichi"] + (["v2", "bh"] if vn_now.weekday() == 0 else [])
    elif a.jobs == "all":
        keys = list(JOBS)
    else:
        keys = [k.strip() for k in a.jobs.split(",") if k.strip() in JOBS]
    os.makedirs(DATA, exist_ok=True)
    try:
        meta = json.load(open(META, encoding="utf-8"))
    except Exception:
        meta = {}
    meta.setdefault("datasets", {}); meta.setdefault("messages", {})
    url = dashboard_url()
    for k in keys:
        text = run_job(k, meta, today)
        if url:
            text += f"\nXem dashboard: {url}"
        text += f"\n{NOTE}"
        print("\n--- Tin nhắn ---\n" + text)
        if not a.no_send:
            send_all(text)
    meta["lastRun"] = {"at": now_utc(), "jobs": keys}
    with open(META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    if all(not meta["datasets"].get(k, {}).get("lastAttempt", {}).get("ok") for k in keys):
        sys.exit(1)   # tất cả đều lỗi -> báo đỏ trên GitHub


if __name__ == "__main__":
    main()
