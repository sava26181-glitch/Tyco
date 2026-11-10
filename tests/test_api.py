"""Сквозные тесты: настоящий сервер + подставной Telegram API. Запуск: pytest -q"""
import base64
import hashlib
import hmac
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode

import pytest
import requests

TOKEN, HOOK, ADS = "123:T", "hook", "ads"
ROOT = pathlib.Path(__file__).parent.parent
calls = []


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeTG(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        method = self.path.rsplit("/", 1)[1]
        body = json.loads(raw) if self.headers.get("Content-Type", "").startswith("application/json") else {"multipart": len(raw)}
        calls.append((method, body))
        out = json.dumps({"ok": True, "result": "https://t.me/$inv" if method == "createInvoiceLink" else True}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def signed(uid, start=None):
    f = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid, "first_name": "Тест"}, ensure_ascii=False)}
    if start:
        f["start_param"] = start
    check = "\n".join(f"{k}={f[k]}" for k in sorted(f))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    f["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(f)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    tg = free_port()
    fake = HTTPServer(("127.0.0.1", tg), FakeTG)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    port = free_port()
    env = {**os.environ, "BOT_TOKEN": TOKEN, "WEBHOOK_SECRET": HOOK, "ADSGRAM_SECRET": ADS, "ADMIN_ID": "1",
           "TG_API_BASE": f"http://127.0.0.1:{tg}", "PUBLIC_URL": f"http://127.0.0.1:{port}", "APP_LINK": "https://t.me/b/a",
           "SQLITE_PATH": str(tmp_path_factory.mktemp("d") / "t.db"), "DATABASE_URL": ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            if requests.get(url + "/health", timeout=1).ok:
                break
        except requests.RequestException:
            time.sleep(.2)
    yield url
    proc.terminate()
    fake.shutdown()


def post(base, path, uid, body=None, start=None):
    return requests.post(f"{base}/api/{path}", json=body or {}, headers={"X-Init-Data": signed(uid, start)}, timeout=5)


def pay(base, uid, pack, charge, stars):
    return requests.post(base + "/tg/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": HOOK}, timeout=5, json={
        "message": {"from": {"id": uid}, "chat": {"id": uid}, "successful_payment": {
            "invoice_payload": pack, "telegram_payment_charge_id": charge, "total_amount": stars, "currency": "XTR"}}})


HERO = {"g": "m", "name": "Вася", "skin": "#eec3a0", "hair": "messy", "hc": "#2a2028", "eyes": "#3a2618", "want": "f"}


def make(base, uid, **kw):
    return post(base, "create", uid, {**HERO, **kw}).json()["me"]


def aura(base, uid):
    return post(base, "me", uid).json()["me"]["aura"]


def test_auth_required(base):
    assert requests.post(base + "/api/me", json={}, timeout=5).status_code == 401


def test_create_and_validation(base):
    assert post(base, "create", 10, {**HERO, "hair": "pony"}).status_code == 400
    assert post(base, "act", 10, {"id": "gym"}).status_code == 400
    me = make(base, 10)
    assert me["char"]["name"] == "Вася" and me["tier"] in ("Новичок", "Курьер") and me["event"]


def test_actions_energy_and_days(base):
    make(base, 11)
    days = set()
    for i in range(6):
        r = post(base, "act", 11, {"id": "client"}).json()
        days.add(r["me"]["day"])
    assert days == {1, 2, 3}
    assert post(base, "act", 11, {"id": "client"}).status_code == 400  # энергия кончилась


def test_work_pays_and_paid_action_charges(base):
    make(base, 12)
    r = post(base, "act", 12, {"id": "work"}).json()
    assert 200 <= r["aura"] <= 700 and r["me"]["aura"] == 300 + r["aura"]
    before = r["me"]["aura"]
    assert post(base, "act", 12, {"id": "course"}).json()["me"]["aura"] == before - 150


def test_event_once_per_day(base):
    make(base, 13)
    r = post(base, "choose", 13, {"i": 1})
    assert r.status_code in (200, 400)
    assert post(base, "choose", 13, {"i": 0}).status_code == 400


def test_stats_capped(base):
    import sys as _s
    _s.path.insert(0, str(ROOT))
    from app import game
    v = 50
    for _ in range(400):
        v = game.grow(v, 4)
    assert v == 100 and game.grow(90, 4) == 91 and game.rating({k: 100 for k in game.STATS}) == 100


def test_shop_and_insufficient(base):
    make(base, 14)
    assert post(base, "shop", 14, {"id": "hoodie"}).json()["error"] == "Не хватает денег"
    pay(base, 14, "aura_s", "s1", 25)
    r = post(base, "shop", 14, {"id": "hoodie"}).json()
    assert r["me"]["wear"] == "hoodie" and r["me"]["aura"] == 1400 and "hoodie" in r["me"]["clothes"]
    assert post(base, "shop", 14, {"id": "hoodie"}).json()["me"]["aura"] == 1400
    r = post(base, "shop", 14, {"id": "scooter"}).json()
    assert r["me"]["ride"] == "scooter" and r["me"]["aura"] == 600
    pay_before = post(base, "act", 14, {"id": "work"}).json()["aura"]
    assert pay_before >= 200 + 80


def test_business_flow(base):
    make(base, 15)
    assert post(base, "biz/buy", 15, {"id": "coffee"}).status_code == 400
    pay(base, 15, "aura_m", "b1", 100)
    r = post(base, "biz/buy", 15, {"id": "coffee"}).json()
    coffee = next(b for b in r["me"]["biz"] if b["id"] == "coffee")
    assert r["me"]["aura"] == 6300 and coffee["lvl"] == 1
    assert post(base, "biz/buy", 15, {"id": "coffee"}).status_code == 400
    r = post(base, "biz/up", 15, {"id": "coffee"}).json()
    assert next(b for b in r["me"]["biz"] if b["id"] == "coffee")["lvl"] == 2 and r["me"]["aura"] == 6300 - 1200


def test_payment_idempotent_and_refund(base):
    make(base, 16)
    pay(base, 16, "aura_m", "p1", 100)
    pay(base, 16, "aura_m", "p1", 100)
    assert aura(base, 16) == 8300
    requests.post(base + "/tg/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": HOOK}, timeout=5, json={
        "message": {"from": {"id": 16}, "chat": {"id": 16}, "refunded_payment": {"telegram_payment_charge_id": "p1"}}})
    assert aura(base, 16) == 300


def test_gifts_mint_upgrade_market(base):
    make(base, 17)
    make(base, 18)
    pay(base, 17, "aura_m", "g1", 100)
    pay(base, 18, "aura_m", "g2", 100)
    r = post(base, "gift/buy", 17, {"kind": "rose"}).json()
    g = r["mine"][0]
    assert g["num"] >= 1 and aura(base, 17) == 8300 - 1200
    r = post(base, "gift/up", 17, {"id": g["id"]}).json()
    assert r["gift"]["model"] and r["gift"]["rare"]["model"] > 0
    assert post(base, "gift/up", 17, {"id": g["id"]}).status_code == 400
    assert post(base, "gift/sell", 18, {"id": g["id"], "price": 500}).status_code == 400  # чужой
    post(base, "gift/sell", 17, {"id": g["id"], "price": 5000})
    items = post(base, "market", 18).json()["items"]
    assert any(i["id"] == g["id"] for i in items)
    assert post(base, "market/buy", 18, {"id": g["id"], "price": 1}).status_code == 400
    assert post(base, "market/buy", 18, {"id": g["id"], "price": 5000}).json()["ok"]
    assert aura(base, 18) == 8300 - 5000
    assert aura(base, 17) == 8300 - 1200 - 720 + 4750
    assert post(base, "market/buy", 18, {"id": g["id"], "price": 5000}).status_code == 400
    prof = post(base, "profile", 17, {"id": 18}).json()
    assert prof["gifts"][0]["id"] == g["id"]


def test_dating_flow(base):
    make(base, 19)
    cards = post(base, "deck", 19).json()["cards"]
    assert len(cards) == 10 and all(19 <= c["age"] <= 29 for c in cards)
    matched = None
    for c in cards:
        r = post(base, "swipe", 19, {"id": c["id"], "like": True}).json()
        if r["match"]:
            matched = c["id"]
            break
    assert post(base, "swipe", 19, {"id": cards[0]["id"], "like": True}).status_code == 400
    if matched:
        for _ in range(4):
            r = post(base, "chat", 19, {"id": matched, "i": 0})
            assert r.status_code == 200
        m = next(x for x in r.json()["me"]["matches"] if x["id"] == matched)
        assert m["status"] in ("date", "cold")
        if m["status"] == "date":
            r = post(base, "date", 19, {"id": matched, "place": "park"}).json()
            assert r["ok"] in (True, False)


def test_photo_sent_to_chat(base):
    make(base, 20)
    png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()
    calls.clear()
    assert post(base, "photo", 20, {"png": png}).json()["ok"]
    assert any(m == "sendPhoto" for m, _ in calls)
    assert post(base, "photo", 20, {"png": "data:image/png;base64,AAAA"}).status_code == 400


def test_referral_bonus(base):
    make(base, 21)
    post(base, "me", 22, start="r21")
    make(base, 22)
    assert aura(base, 21) == 700 and aura(base, 22) == 700


def test_ads_refill(base):
    make(base, 23)
    assert post(base, "ad/claim", 23).status_code == 400
    requests.get(base + "/adsgram/reward", params={"userid": 23, "secret": ADS}, timeout=5)
    assert post(base, "ad/claim", 23).json()["me"]["energy"] == 6


def test_invoice_and_stats(base):
    calls.clear()
    assert post(base, "invoice", 24, {"pack": "vip"}).json()["link"]
    requests.post(base + "/tg/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": HOOK}, timeout=5,
                  json={"message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "/stats"}})
    assert any("Игроков" in b.get("text", "") for m, b in calls if m == "sendMessage")
