# -*- coding: utf-8 -*-
"""台股在地化啟動器：繁體中文輸出 + 台股中文名稱，然後執行 main.py。

用法（取代 `python main.py ...`）：python tw_run.py [main.py 的參數]
"""
import json
import logging
import runpy
import sys
import urllib.request

log = logging.getLogger("tw_run")

# 備用名稱表（抓不到證交所/櫃買中心資料時使用）
TW_NAMES = {
    "2221": "大甲", "2643": "捷迅", "5202": "力新", "5209": "新鼎", "5465": "富驊",
    "5490": "同亨", "6291": "沛亨", "7767": "仁大資訊", "8432": "東生華",
}


def _fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _load_names():
    try:
        for x in _fetch_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"):
            if x.get("Code") and x.get("Name"):
                TW_NAMES[x["Code"].strip()] = x["Name"].strip()
    except Exception as e:  # noqa: BLE001
        print(f"[tw_run] 證交所名稱抓取失敗，使用備用表: {e}")
    try:
        for x in _fetch_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"):
            c, n = x.get("SecuritiesCompanyCode"), x.get("CompanyName")
            if c and n:
                TW_NAMES[c.strip()] = n.strip()
    except Exception as e:  # noqa: BLE001
        print(f"[tw_run] 櫃買中心名稱抓取失敗，使用備用表: {e}")


def tw_name(code):
    """'2330.TW' / '6291.TWO' / 'TW2330' -> 中文名；非台股回傳 None。"""
    if not code:
        return None
    c = str(code).strip().upper()
    for suf in (".TWO", ".TW"):
        if c.endswith(suf):
            return TW_NAMES.get(c[: -len(suf)])
    return None


# ---------- 簡轉繁 ----------
try:
    from opencc import OpenCC
    _cc = OpenCC("s2twp")
except Exception as e:  # noqa: BLE001
    print(f"[tw_run] OpenCC 無法載入，維持原文字: {e}")
    _cc = None

_REPLACE = [("A股", "台股")]


def to_tw(text):
    if not isinstance(text, str) or not text:
        return text
    if _cc is not None:
        try:
            text = _cc.convert(text)
        except Exception:  # noqa: BLE001
            pass
    for a, b in _REPLACE:
        text = text.replace(a, b)
    return text


def _patch():
    # 1) 靜態名稱表
    try:
        from src.data import stock_mapping
        for k, v in list(TW_NAMES.items()):
            stock_mapping.STOCK_NAME_MAP[f"{k}.TW"] = v
            stock_mapping.STOCK_NAME_MAP[f"{k}.TWO"] = v
    except Exception as e:  # noqa: BLE001
        print(f"[tw_run] 名稱表注入失敗: {e}")

    # 2) yfinance 即時行情名稱
    try:
        from data_provider import yfinance_fetcher as yf
        cls = next(getattr(yf, n) for n in dir(yf)
                   if isinstance(getattr(yf, n), type) and hasattr(getattr(yf, n), "get_realtime_quote")
                   and getattr(yf, n).__module__ == yf.__name__)
        orig_q = cls.get_realtime_quote

        def get_realtime_quote(self, stock_code, *a, **kw):
            q = orig_q(self, stock_code, *a, **kw)
            n = tw_name(stock_code)
            if q is not None and n:
                try:
                    q.name = n
                except Exception:  # noqa: BLE001
                    pass
            return q
        cls.get_realtime_quote = get_realtime_quote
    except Exception as e:  # noqa: BLE001
        print(f"[tw_run] yfinance 名稱修補失敗: {e}")

    # 3) DataFetcherManager.get_stock_name
    try:
        from data_provider import base
        orig_n = base.DataFetcherManager.get_stock_name

        def get_stock_name(self, stock_code, *a, **kw):
            return tw_name(stock_code) or orig_n(self, stock_code, *a, **kw)
        base.DataFetcherManager.get_stock_name = get_stock_name

        # 任何資料源回來的即時行情，台股一律換成中文名
        orig_rq = base.DataFetcherManager.get_realtime_quote

        def get_realtime_quote_mgr(self, stock_code, *a, **kw):
            q = orig_rq(self, stock_code, *a, **kw)
            n = tw_name(stock_code)
            if q is not None and n:
                try:
                    q.name = n
                except Exception:  # noqa: BLE001
                    pass
            return q
        base.DataFetcherManager.get_realtime_quote = get_realtime_quote_mgr
    except Exception as e:  # noqa: BLE001
        print(f"[tw_run] get_stock_name 修補失敗: {e}")

    # 3b) 最後一道保險：分析結果物件的名稱一律用中文
    try:
        from src import analyzer as _an
        _cls = _an.AnalysisResult
        _orig_setattr = _cls.__setattr__

        def _setattr(self, key, value):
            if key == "name":
                n = tw_name(getattr(self, "code", None))
                if n:
                    value = n
            elif key == "code":
                _orig_setattr(self, key, value)
                n = tw_name(value)
                if n:
                    _orig_setattr(self, "name", n)
                return
            _orig_setattr(self, key, value)
        _cls.__setattr__ = _setattr
    except Exception as e:  # noqa: BLE001
        print(f"[tw_run] AnalysisResult 名稱修補失敗: {e}")

    # 4) analyzer.get_stock_name_multi_source
    try:
        from src import analyzer
        orig_m = analyzer.get_stock_name_multi_source

        def get_stock_name_multi_source(stock_code, *a, **kw):
            return tw_name(stock_code) or orig_m(stock_code, *a, **kw)
        analyzer.get_stock_name_multi_source = get_stock_name_multi_source
    except Exception as e:  # noqa: BLE001
        print(f"[tw_run] analyzer 名稱修補失敗: {e}")

    # 5) 推送前轉繁體：Telegram / Email
    try:
        from src.notification_sender import telegram_sender as ts
        orig_t = ts.TelegramSender.send_to_telegram

        def send_to_telegram(self, content, *a, **kw):
            return orig_t(self, to_tw(content), *a, **kw)
        ts.TelegramSender.send_to_telegram = send_to_telegram
    except Exception as e:  # noqa: BLE001
        print(f"[tw_run] Telegram 繁體修補失敗: {e}")
    try:
        from src.notification_sender import email_sender as es
        orig_e = es.EmailSender.send_to_email

        def send_to_email(self, content, subject=None, *a, **kw):
            return orig_e(self, to_tw(content), to_tw(subject), *a, **kw)
        es.EmailSender.send_to_email = send_to_email
    except Exception as e:  # noqa: BLE001
        print(f"[tw_run] Email 繁體修補失敗: {e}")

    # 6) 存檔的報告也轉繁體
    try:
        from src import notification as nt
        orig_s = nt.NotificationService.save_report_to_file

        def save_report_to_file(self, content, *a, **kw):
            return orig_s(self, to_tw(content), *a, **kw)
        nt.NotificationService.save_report_to_file = save_report_to_file
    except Exception as e:  # noqa: BLE001
        print(f"[tw_run] 報告存檔修補失敗: {e}")


if __name__ == "__main__":
    _load_names()
    _patch()
    print(f"[tw_run] 台股在地化已啟用（名稱 {len(TW_NAMES)} 筆，繁體轉換 {'開' if _cc else '關'}）")
    sys.argv = ["main.py"] + sys.argv[1:]
    runpy.run_path("main.py", run_name="__main__")
