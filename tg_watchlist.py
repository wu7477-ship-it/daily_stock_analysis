# -*- coding: utf-8 -*-
"""用 Telegram 管理分析清單（stock_list.txt）。

由 GitHub Actions 定時執行：讀取 bot 收到的新指令 → 更新 stock_list.txt → 回覆。
指令：/add 2330 6291   /del 2330   /list   /help
只接受 TELEGRAM_CHAT_ID 那個聊天室傳來的指令。
"""
import json
import os
import re
import urllib.parse
import urllib.request

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = str(os.environ["TELEGRAM_CHAT_ID"]).strip()
LIST_FILE = "stock_list.txt"
OFFSET_FILE = ".tg_offset"
API = f"https://api.telegram.org/bot{TOKEN}"


def http_json(url, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def send(text):
    try:
        http_json(f"{API}/sendMessage", {"chat_id": CHAT_ID, "text": text})
    except Exception as e:  # noqa: BLE001
        print("回覆失敗:", e)


# ---------- 台股代號 → 市場與名稱 ----------
TWSE, TPEX = {}, {}


def load_names():
    try:
        for x in http_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"):
            if x.get("Code"):
                TWSE[x["Code"].strip()] = (x.get("Name") or "").strip()
    except Exception as e:  # noqa: BLE001
        print("證交所清單抓取失敗:", e)
    try:
        for x in http_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"):
            c = x.get("SecuritiesCompanyCode")
            if c:
                TPEX[c.strip()] = (x.get("CompanyName") or "").strip()
    except Exception as e:  # noqa: BLE001
        print("櫃買中心清單抓取失敗:", e)


def resolve(token):
    """'2330' / '2330.TW' / '6291.TWO' -> ('2330.TW', '台積電')；查不到回傳 (None, None)。"""
    t = token.strip().upper()
    if t.endswith(".TWO") or t.endswith(".TW"):
        code = t.rsplit(".", 1)[0]
        return t, TWSE.get(code) or TPEX.get(code) or ""
    if t in TWSE:
        return f"{t}.TW", TWSE[t]
    if t in TPEX:
        return f"{t}.TWO", TPEX[t]
    return None, None


def name_of(sym):
    code = sym.rsplit(".", 1)[0]
    return TWSE.get(code) or TPEX.get(code) or ""


def read_list():
    if not os.path.exists(LIST_FILE):
        return []
    with open(LIST_FILE, encoding="utf-8") as f:
        items = re.split(r"[,\s]+", "\n".join(l for l in f if not l.startswith("#")))
    return [s.strip().upper() for s in items if s.strip()]


def write_list(items):
    with open(LIST_FILE, "w", encoding="utf-8") as f:
        f.write("# 由 Telegram 指令管理（/add /del /list），也可以直接編輯，一行一檔\n")
        f.write("\n".join(items) + "\n")


def fmt_list(items):
    if not items:
        return "分析清單目前是空的。"
    lines = [f"{i}. {name_of(s)} {s}".replace("  ", " ") for i, s in enumerate(items, 1)]
    return f"分析清單（{len(items)} 檔）：\n" + "\n".join(lines)


HELP = ("分析清單指令：\n"
        "/add 2330 6291　加入股票\n"
        "/del 2330　刪除股票\n"
        "/list　看目前清單\n"
        "（約 30 分鐘內處理並回覆，隔天早上的分析就會套用）")


def main():
    offset = 0
    if os.path.exists(OFFSET_FILE):
        try:
            offset = int(open(OFFSET_FILE).read().strip() or 0)
        except ValueError:
            offset = 0
    res = http_json(f"{API}/getUpdates?offset={offset}&timeout=0&allowed_updates=%5B%22message%22%5D")
    updates = res.get("result", [])
    if not updates:
        print("沒有新指令")
        return

    items = read_list()
    original = list(items)
    names_loaded = False

    for u in updates:
        offset = max(offset, u["update_id"] + 1)
        msg = u.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != CHAT_ID:
            continue
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            continue
        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        args = parts[1:]
        if not names_loaded:
            load_names()
            names_loaded = True

        if cmd in ("/add", "/a"):
            added, bad, dup = [], [], []
            for a in args:
                sym, nm = resolve(a)
                if not sym:
                    bad.append(a)
                elif sym in items:
                    dup.append(f"{nm} {sym}")
                else:
                    items.append(sym)
                    added.append(f"{nm} {sym}")
            out = []
            if added:
                out.append("已加入：" + "、".join(added))
            if dup:
                out.append("本來就在清單：" + "、".join(dup))
            if bad:
                out.append("查不到代號：" + "、".join(bad))
            send("\n".join(out) or "用法：/add 2330 6291")
        elif cmd in ("/del", "/d", "/remove", "/rm"):
            removed, miss = [], []
            for a in args:
                sym, nm = resolve(a)
                cands = [s for s in items if s == (sym or "") or s.rsplit(".", 1)[0] == a.strip().upper()]
                if cands:
                    for s in cands:
                        items.remove(s)
                        removed.append(f"{name_of(s)} {s}")
                else:
                    miss.append(a)
            out = []
            if removed:
                out.append("已刪除：" + "、".join(removed))
            if miss:
                out.append("清單裡沒有：" + "、".join(miss))
            send("\n".join(out) or "用法：/del 2330")
        elif cmd in ("/list", "/l"):
            send(fmt_list(items))
        elif cmd in ("/help", "/start"):
            send(HELP)

    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))
    if items != original:
        write_list(items)
        print("清單已更新:", ",".join(items))


if __name__ == "__main__":
    main()
