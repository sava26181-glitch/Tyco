import base64
import hmac
import json
import logging
import os
import pathlib
import random
import time
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.middleware.gzip import GZipMiddleware
from starlette.routing import Route

from . import db, game, telegram

log = logging.getLogger("courier")
STATIC = pathlib.Path(__file__).parent.parent / "static"
PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
ADSGRAM_SECRET = os.environ.get("ADSGRAM_SECRET", "")
ADSGRAM_BLOCK_ID = os.environ.get("ADSGRAM_BLOCK_ID", "")
APP_LINK = os.environ.get("APP_LINK", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID") or 0)
SUPPORT_CONTACT = os.environ.get("SUPPORT_CONTACT", "администратору бота")
HAIRS = {"m": {"short", "messy", "bald", "long"}, "f": {"pony", "bob", "pigtails", "long"}}
EYES = {"#3a2618", "#3f6fb0", "#3f8a4a", "#6b6b6b"}


class GameError(Exception):
    pass


def now():
    return int(time.time())


def today():
    return now() // 86400


def new_state():
    return {"char": None, "st": {}, "energy": game.ENERGY_MAX, "energy_t": now(), "day": 1, "acts": 0,
            "event": None, "biz": {}, "clothes": [], "wear": "", "ride": "", "swipe_day": 0, "swipes": 0,
            "swiped": [], "matches": {}, "best": 0}


def regen(st):
    t = now()
    if st["energy"] >= game.ENERGY_MAX:
        st["energy_t"] = t
        return
    gained = (t - st["energy_t"]) // game.ENERGY_REGEN
    if gained > 0:
        st["energy"] = min(game.ENERGY_MAX, st["energy"] + gained)
        st["energy_t"] += gained * game.ENERGY_REGEN


def rnd_for(uid, *salt):
    return random.Random(f"{uid}:" + ":".join(map(str, salt)))


def new_event(uid, st):
    rnd = rnd_for(uid, "ev", st["day"])
    ev = game.event_for(rnd, st["day"])
    npc = rnd.choice(game.NAMES_F + game.NAMES_M)
    st["event"] = {"id": ev["id"], "npc": npc}


# ---------- Чтение и запись игрока ----------

def load(t, user):
    uid = user["id"]
    row = t.one("SELECT * FROM users WHERE id=?", (uid,))
    if row:
        if user.get("first_name"):
            t.run("UPDATE users SET seen=?, name=? WHERE id=?", (now(), str(user["first_name"])[:24], uid))
        return row
    referrer = None
    param = user.get("start_param", "")
    if param.startswith("r") and param[1:].isdigit() and len(param) <= 16 and int(param[1:]) != uid:
        if t.one("SELECT id FROM users WHERE id=?", (int(param[1:]),)):
            referrer = int(param[1:])
    t.run("INSERT INTO users (id, name, aura, state, referrer, created, seen) VALUES (?,?,?,?,?,?,?) "
          "ON CONFLICT (id) DO NOTHING",
          (uid, str(user.get("first_name", ""))[:24], game.START_AURA, json.dumps(new_state()), referrer, now(), now()))
    return t.one("SELECT * FROM users WHERE id=?", (uid,))


def change(user, fn):
    """Меняет состояние игрока. fn(st, row) возвращает (результат, изменение ауры)."""
    for _ in range(6):
        with db.tx() as t:
            row = load(t, user)
            st = {**new_state(), **json.loads(row["state"])}
            regen(st)
            result, delta = fn(st, row)
            if row["aura"] + delta < 0:
                raise GameError("Не хватает денег")
            score = game.rating(st["st"]) if st["char"] else 0
            st["best"] = max(st.get("best", 0), score)
            done = t.run("UPDATE users SET state=?, ver=ver+1, aura=aura+?, rating=? "
                         "WHERE id=? AND ver=? AND aura+?>=0",
                         (json.dumps(st, ensure_ascii=False), delta, score, row["id"], row["ver"], delta)).rowcount
            if done:
                if isinstance(result, dict) and "me" in result:
                    result["me"] = view({**row, "aura": row["aura"] + delta}, st)
                return result
    raise GameError("Попробуйте ещё раз")


def apply_fx(st, fx):
    out = []
    for k, v in fx.items():
        if isinstance(v, tuple):
            v = random.randint(*v)
        if not v:
            continue
        old = st["st"].get(k, 0)
        st["st"][k] = game.grow(old, v) if k != "health" else game.clamp(old + v)
        diff = st["st"][k] - old
        if diff:
            out.append([game.STAT_NAMES[k], diff])
    return out


def view(row, st):
    score = game.rating(st["st"]) if st["char"] else 0
    biz = []
    for bid, b in game.BIZ.items():
        mine = st["biz"].get(bid)
        item = {"id": bid, "name": b["name"], "cost": b["cost"], "lvl": 0}
        if mine:
            inc, cap = game.biz_ups(bid, mine.get("ups", []))
            hours = min(cap, (now() - mine["t"]) / 3600)
            rate = int(game.biz_income(bid, mine["lvl"]) * (1 + inc) * (2 if row["vip"] else 1))
            item.update(lvl=mine["lvl"], rate=rate, ready=int(rate * hours), cap=cap, max=game.BIZ_MAX,
                        up=game.biz_upgrade_cost(bid, mine["lvl"]) if mine["lvl"] < game.BIZ_MAX else None,
                        items=[{"id": u[0], "name": u[1], "cost": int(b["cost"] * u[2]), "kind": u[3], "value": u[4],
                                "own": u[0] in mine.get("ups", [])} for u in game.BIZ_UPS[bid]])
        else:
            item["rate"] = game.BIZ[bid]["income"] * (2 if row["vip"] else 1)
        biz.append(item)
    event = None
    if st["event"]:
        ev = next(e for e in game.EVENTS if e["id"] == st["event"]["id"])
        event = {"text": ev["text"].replace("{npc}", st["event"]["npc"]),
                 "ch": [{"l": c[0], "aura": c[2] if c[2] > 0 else 0} for c in ev["ch"]]}
    matches = [{**{k: m[k] for k in ("id", "name", "age", "g", "look", "status", "aff", "log", "bio")},
                "opts": chat_options(m)} for m in st["matches"].values()]
    return {"id": row["id"], "name": row["name"], "aura": row["aura"], "vip": bool(row["vip"]), "friends": row["friends"],
            "char": st["char"], "st": st["st"], "rating": score, "tier": game.tier(score), "best": st.get("best", 0),
            "energy": st["energy"], "energyMax": game.ENERGY_MAX,
            "nextEnergy": max(0, game.ENERGY_REGEN - (now() - st["energy_t"])) if st["energy"] < game.ENERGY_MAX else 0,
            "day": st["day"], "acts": st["acts"], "event": event, "biz": biz, "clothes": st["clothes"], "wear": st["wear"], "ride": st.get("ride", ""),
            "swipesLeft": game.SWIPES_PER_DAY - (st["swipes"] if st["swipe_day"] == today() else 0), "matches": matches}


def config(row):
    return {
        "actions": [{"id": k, "name": v["name"], "desc": v["desc"], "aura": v["aura"]} for k, v in game.ACTIONS.items()],
        "shop": [{"id": k, **v} for k, v in game.SHOP.items()],
        "gifts": [{"id": k, **v} for k, v in game.GIFTS.items()],
        "packs": [{"id": k, **v} for k, v in game.PACKS.items()],
        "dates": [{"id": k, **v} for k, v in game.DATES.items()],
        "tiers": game.TIERS, "pay": game.WORK_PAY, "adsBlock": ADSGRAM_BLOCK_ID, "refBonus": game.REF_BONUS,
        "invite": f"{APP_LINK}?startapp=r{row['id']}" if APP_LINK else "",
    }


def me(user, _body):
    holder = {}

    def fn(st, row):
        holder["row"] = row
        return view(row, st), 0
    data = change(user, fn)
    return {"me": data, "config": config(holder["row"])}


# ---------- Персонаж ----------

def create(user, body):
    g = body.get("g")
    if g not in ("m", "f"):
        raise GameError("Выберите пол")
    look = {"g": g, "skin": body.get("skin"), "hair": body.get("hair"), "hc": body.get("hc"),
            "eyes": body.get("eyes"), "want": body.get("want"), "name": str(body.get("name", "")).strip()[:16]}
    if look["skin"] not in game.SKINS or look["hc"] not in game.HAIRC or look["hair"] not in HAIRS[g] \
            or look["eyes"] not in EYES or look["want"] not in ("m", "f", "any") or len(look["name"]) < 2:
        raise GameError("Заполните все поля")

    def fn(st, row):
        first = st["char"] is None
        st["char"] = look
        if first:
            rnd = rnd_for(row["id"], "start")
            st["st"] = {"stamina": rnd.randint(14, 22), "charm": rnd.randint(8, 16), "smart": rnd.randint(6, 12),
                        "rep": rnd.randint(8, 14), "net": rnd.randint(2, 8), "health": 80}
            new_event(row["id"], st)
        return view(row, st), 0
    result = change(user, fn)
    with db.tx() as t:
        row = t.one("SELECT referrer, ref_paid FROM users WHERE id=?", (user["id"],))
        if row["referrer"] and t.run("UPDATE users SET ref_paid=1 WHERE id=? AND ref_paid=0", (user["id"],)).rowcount:
            t.run("UPDATE users SET aura=aura+? WHERE id=?", (game.REF_BONUS, user["id"]))
            t.run("UPDATE users SET aura=aura+?, friends=friends+1 WHERE id=?", (game.REF_BONUS, row["referrer"]))
            result["aura"] += game.REF_BONUS
    return {"me": result}


def need_char(st):
    if not st["char"]:
        raise GameError("Сначала создайте персонажа")


def finish_act(row, st):
    st["acts"] += 1
    if st["acts"] >= game.ACTS_PER_DAY:
        st["acts"] = 0
        st["day"] += 1
        if not st["event"]:
            new_event(row["id"], st)
        return True
    return False


def act(user, body):
    aid = str(body.get("id", ""))
    action = game.ACTIONS.get(aid)
    if not action:
        raise GameError("Нет такого дела")

    def fn(st, row):
        need_char(st)
        if st["energy"] <= 0:
            raise GameError("Нет энергии. Она восстанавливается со временем")
        st["energy"] -= 1
        if st["energy"] == game.ENERGY_MAX - 1:
            st["energy_t"] = now()
        if aid == "work" and st["st"].get("health", 0) < 15:
            raise GameError("Слишком мало здоровья для смены. Выспись")
        delta = -action["aura"]
        text = action["name"] + ": готово."
        if aid == "work":
            ride = game.SHOP.get(st.get("ride", ""), {})
            delta = random.randint(*game.WORK_PAY) + ride.get("pay", 0) + game.rating(st["st"]) * 4
            text = f"Смена закрыта: +{delta}."
        changes = apply_fx(st, action["fx"])
        newday = finish_act(row, st)
        return {"text": text, "changes": changes, "aura": delta, "newDay": newday, "me": None}, delta
    result = change(user, fn)
    return with_me(user, result)


def with_me(user, result):
    return result


def choose(user, body):
    index = int(body.get("i", -1))

    def fn(st, row):
        need_char(st)
        if not st["event"]:
            raise GameError("Сегодня событий больше нет")
        ev = next(e for e in game.EVENTS if e["id"] == st["event"]["id"])
        if not 0 <= index < len(ev["ch"]):
            raise GameError("Нет такого варианта")
        c = ev["ch"][index]
        label, fx, money = c[0], c[1], c[2]
        odds = c[3] if len(c) > 3 else 1
        if odds == -1:
            odds = 1 if game.rating(st["st"]) >= 55 else 0
        ok = random.random() < odds
        delta = -money if money > 0 else 0
        if money > 0 and row["aura"] < money:
            raise GameError("Не хватает денег")
        if ok:
            changes = apply_fx(st, fx)
            if money < 0:
                delta += -money
            delta += game.EVENT_WIN.get(ev["id"], 0) if index == 0 else 0
            text = "Получилось!" if len(c) > 3 else "Сделано."
            if ev["id"] == "pitch":
                text = "Ты победил(а) в конкурсе стартапов! Деньги на развитие твои."
        else:
            changes = apply_fx(st, c[5] if len(c) > 5 else {})
            text = c[4]
        st["event"] = None
        return {"text": text, "ok": ok, "label": label, "changes": changes, "aura": delta, "me": None}, delta
    return with_me(user, change(user, fn))


def shop_buy(user, body):
    item_id = str(body.get("id", ""))
    item = game.SHOP.get(item_id)
    if not item:
        raise GameError("Нет такого товара")

    def fn(st, row):
        need_char(st)
        slot = "ride" if item["kind"] == "ride" else "wear"
        if item_id in st["clothes"]:
            st[slot] = item_id
            return {"text": "Выбрано", "me": None}, 0
        st["clothes"].append(item_id)
        st[slot] = item_id
        changes = apply_fx(st, {"charm": item["charm"]})
        return {"text": f"Куплено: {item['name']}", "changes": changes, "me": None}, -item["aura"]
    return with_me(user, change(user, fn))


# ---------- Знакомства ----------

def deck(user, _body):
    def fn(st, row):
        need_char(st)
        rnd = rnd_for(row["id"], "deck", today())
        cards = [game.make_profile(rnd, st["char"]["want"], f"{today()}", i) for i in range(30)]
        cards = [c for c in cards if c["id"] not in st["swiped"]][:10]
        return {"cards": cards}, 0
    return change(user, fn)


def swipe(user, body):
    pid, like = str(body.get("id", "")), bool(body.get("like"))

    def fn(st, row):
        need_char(st)
        if st["swipe_day"] != today():
            st["swipe_day"], st["swipes"], st["swiped"] = today(), 0, []
        if st["swipes"] >= game.SWIPES_PER_DAY:
            raise GameError("Свайпы закончились до завтра")
        rnd = rnd_for(row["id"], "deck", today())
        cards = {c["id"]: c for c in (game.make_profile(rnd, st["char"]["want"], f"{today()}", i) for i in range(30))}
        card = cards.get(pid)
        if not card or pid in st["swiped"]:
            raise GameError("Анкета недоступна")
        st["swipes"] += 1
        st["swiped"].append(pid)
        match = False
        if like:
            mine = game.rating(st["st"])
            p = game.clamp(.4 + (mine - card["rate"]) / 130 + st["st"]["charm"] / 300, .15, .92)
            match = random.random() < p
            if match:
                st["matches"][pid] = {**card, "status": "chat", "aff": 0, "step": 0,
                                      "log": [["them", game.CHAT[0][0]]]}
                if len(st["matches"]) > 20:
                    oldest = next(iter(st["matches"]))
                    st["matches"].pop(oldest)
        return {"match": match, "card": card, "me": None}, 0
    return with_me(user, change(user, fn))


def chat_options(m):
    if m["status"] != "chat" or m["step"] >= len(game.CHAT):
        return []
    return [o[1] for o in game.CHAT[m["step"]][1]]


def chat_reply(user, body):
    pid, index = str(body.get("id", "")), int(body.get("i", -1))

    def fn(st, row):
        m = st["matches"].get(pid)
        if not m or m["status"] != "chat":
            raise GameError("Чат недоступен")
        options = game.CHAT[m["step"]][1]
        if not 0 <= index < len(options):
            raise GameError("Нет такого ответа")
        kind, text = options[index]
        liked = game.PERSONAS[m["persona"]]
        gain = 3 if kind == liked else 1 if kind != "bold" or st["st"]["charm"] > 40 else -1
        m["aff"] += gain
        m["log"].append(["me", text])
        m["step"] += 1
        reacts = {3: ["Ахах, ты мне нравишься", "Вот это ответ", "Мне это откликается"],
                  1: ["Хм, ладно", "Окей)", "Неплохо"], -1: ["Ммм… странно", "Ты всегда так напираешь?", "Понятно"]}
        m["log"].append(["them", random.choice(reacts[gain])])
        if m["step"] < len(game.CHAT):
            m["log"].append(["them", game.CHAT[m["step"]][0]])
        elif m["aff"] >= 6:
            m["status"] = "date"
            m["log"].append(["them", "Слушай, может встретимся?"])
        else:
            m["status"] = "cold"
            m["log"].append(["them", "Мне пора, было приятно поболтать!"])
        return {"gain": gain, "me": None}, 0
    return with_me(user, change(user, fn))


def date_go(user, body):
    pid, place = str(body.get("id", "")), str(body.get("place", ""))
    spot = game.DATES.get(place)
    if not spot:
        raise GameError("Нет такого места")

    def fn(st, row):
        m = st["matches"].get(pid)
        if not m or m["status"] != "date":
            raise GameError("Свидание недоступно")
        p = game.clamp(.35 + m["aff"] / 30 + spot["bonus"] / 100 + (game.rating(st["st"]) - m["rate"]) / 150, .1, .95)
        ok = random.random() < p
        m["status"] = "couple" if ok else "friend"
        m["log"].append(["them", "Это был лучший вечер" if ok else "Ты классный человек, но давай останемся друзьями"])
        changes = apply_fx(st, {"charm": 4 if ok else -2})
        if ok:
            for other in st["matches"].values():
                if other is not m and other["status"] == "couple":
                    other["status"] = "friend"
        return {"ok": ok, "changes": changes, "name": m["name"], "me": None}, -spot["aura"]
    return with_me(user, change(user, fn))


# ---------- Бизнес ----------

def biz_buy(user, body):
    bid = str(body.get("id", ""))
    if bid not in game.BIZ:
        raise GameError("Нет такого бизнеса")

    def fn(st, row):
        need_char(st)
        if bid in st["biz"]:
            raise GameError("Уже куплено")
        st["biz"][bid] = {"lvl": 1, "t": now()}
        return {"text": f"Теперь у тебя есть: {game.BIZ[bid]['name']}", "me": None}, -game.BIZ[bid]["cost"]
    return with_me(user, change(user, fn))


def collect_one(row, st, bid):
    b = st["biz"][bid]
    inc, cap = game.biz_ups(bid, b.get("ups", []))
    hours = min(cap, (now() - b["t"]) / 3600)
    got = int(game.biz_income(bid, b["lvl"]) * (1 + inc) * (2 if row["vip"] else 1) * hours)
    b["t"] = now()
    return got


def biz_collect(user, _body):
    def fn(st, row):
        total = sum(collect_one(row, st, bid) for bid in list(st["biz"]))
        if total <= 0:
            raise GameError("Пока нечего собирать")
        return {"text": f"Собрано: +{total}", "aura": total, "me": None}, total
    return with_me(user, change(user, fn))


def biz_upgrade(user, body):
    bid = str(body.get("id", ""))

    def fn(st, row):
        if bid not in st["biz"]:
            raise GameError("Сначала купите бизнес")
        b = st["biz"][bid]
        if b["lvl"] >= game.BIZ_MAX:
            raise GameError("Максимальный уровень")
        got = collect_one(row, st, bid)
        cost = game.biz_upgrade_cost(bid, b["lvl"])
        b["lvl"] += 1
        return {"text": f"{game.BIZ[bid]['name']}: уровень {b['lvl']}", "me": None}, got - cost
    return with_me(user, change(user, fn))


def biz_item(user, body):
    bid, iid = str(body.get("id", "")), str(body.get("item", ""))
    up = next((u for u in game.BIZ_UPS.get(bid, []) if u[0] == iid), None)
    if not up:
        raise GameError("Нет такого улучшения")

    def fn(st, row):
        b = st["biz"].get(bid)
        if not b:
            raise GameError("Сначала купите бизнес")
        b.setdefault("ups", [])
        if iid in b["ups"]:
            raise GameError("Уже куплено")
        got = collect_one(row, st, bid)
        b["ups"].append(iid)
        return {"text": up[1] + ": готово", "me": None}, got - int(game.BIZ[bid]["cost"] * up[2])
    return change(user, fn)


# ---------- NFT-подарки и маркет ----------

def gift_view(g):
    info = game.GIFTS[g["kind"]]
    out = {"id": g["id"], "kind": g["kind"], "name": info["name"], "emoji": info["emoji"], "num": g["num"],
           "supply": info["supply"], "owner": g["owner"], "price": g["price"], "shown": bool(g["shown"])}
    if g["model"]:
        out.update(model=g["model"], backdrop=g["backdrop"], pattern=g["pattern"],
                   rare={"model": game.chance(game.MODELS, g["model"]), "backdrop": game.chance(game.BACKDROPS, g["backdrop"]),
                         "pattern": game.chance(game.PATTERNS, g["pattern"])})
    return out


def gifts_store(user, _body):
    with db.tx() as t:
        load(t, user)
        counts = {r["kind"]: r["n"] for r in t.all("SELECT kind, COUNT(*) AS n FROM gifts GROUP BY kind")}
        mine = t.all("SELECT * FROM gifts WHERE owner=? ORDER BY id DESC", (user["id"],))
    store = [{"id": k, **v, "left": v["supply"] - counts.get(k, 0)} for k, v in game.GIFTS.items()]
    return {"store": store, "mine": [gift_view(g) for g in mine], "upgrade": game.GIFT_UPGRADE}


def gift_buy(user, body):
    kind = str(body.get("kind", ""))
    info = game.GIFTS.get(kind)
    if not info:
        raise GameError("Нет такого подарка")
    for _ in range(5):
        try:
            with db.tx() as t:
                load(t, user)
                n = t.one("SELECT COUNT(*) AS n FROM gifts WHERE kind=?", (kind,))["n"]
                if n >= info["supply"]:
                    raise GameError("Тираж распродан. Ищи на маркете")
                if not t.run("UPDATE users SET aura=aura-? WHERE id=? AND aura>=?",
                             (info["price"], user["id"], info["price"])).rowcount:
                    raise GameError("Не хватает денег")
                t.run("INSERT INTO gifts (kind, num, owner, created) VALUES (?,?,?,?)", (kind, n + 1, user["id"], now()))
            return {"num": n + 1, **gifts_store(user, {})}
        except GameError:
            raise
        except Exception as error:  # номер заняли одновременно: пробуем следующий
            if "unique" not in str(error).lower() and "duplicate" not in str(error).lower():
                raise
    raise GameError("Попробуйте ещё раз")


def owned_gift(t, user, gid):
    g = t.one("SELECT * FROM gifts WHERE id=? AND owner=?", (gid, user["id"]))
    if not g:
        raise GameError("Это не ваш подарок")
    return g


def gift_upgrade(user, body):
    gid = int(body.get("id", 0))
    with db.tx() as t:
        g = owned_gift(t, user, gid)
        if g["model"]:
            raise GameError("Подарок уже улучшен")
        cost = int(game.GIFTS[g["kind"]]["price"] * game.GIFT_UPGRADE)
        if not t.run("UPDATE users SET aura=aura-? WHERE id=? AND aura>=?", (cost, user["id"], cost)).rowcount:
            raise GameError("Не хватает денег")
        rnd = random.Random()
        t.run("UPDATE gifts SET model=?, backdrop=?, pattern=? WHERE id=? AND model=''",
              (game.roll(game.MODELS, rnd), game.roll(game.BACKDROPS, rnd), game.roll(game.PATTERNS, rnd), gid))
        g = t.one("SELECT * FROM gifts WHERE id=?", (gid,))
    return {"gift": gift_view(g), **gifts_store(user, {})}


def gift_sell(user, body):
    gid, price = int(body.get("id", 0)), body.get("price")
    with db.tx() as t:
        owned_gift(t, user, gid)
        if price is None:
            t.run("UPDATE gifts SET price=NULL WHERE id=?", (gid,))
        else:
            price = int(price)
            if not 10 <= price <= 10_000_000:
                raise GameError("Цена от 10 до 10 000 000")
            t.run("UPDATE gifts SET price=? WHERE id=?", (price, gid))
    return gifts_store(user, {})


def gift_show(user, body):
    gid = int(body.get("id", 0))
    with db.tx() as t:
        g = owned_gift(t, user, gid)
        t.run("UPDATE gifts SET shown=? WHERE id=?", (0 if g["shown"] else 1, gid))
    return gifts_store(user, {})


def market(user, body):
    kind = str(body.get("kind", ""))
    sql = "SELECT g.*, u.name AS seller FROM gifts g JOIN users u ON u.id=g.owner WHERE g.price IS NOT NULL"
    params = []
    if kind in game.GIFTS:
        sql += " AND g.kind=?"
        params.append(kind)
    sql += " ORDER BY g.price ASC LIMIT 60"
    with db.tx() as t:
        load(t, user)
        rows = t.all(sql, tuple(params))
    return {"items": [{**gift_view(r), "seller": r["seller"] or "Игрок", "mine": r["owner"] == user["id"]} for r in rows],
            "fee": game.MARKET_FEE}


def market_buy(user, body):
    gid, price = int(body.get("id", 0)), int(body.get("price", 0))
    with db.tx() as t:
        load(t, user)
        g = t.one("SELECT * FROM gifts WHERE id=? AND price=?", (gid, price))
        if not g:
            raise GameError("Лот уже продан или цена изменилась")
        if g["owner"] == user["id"]:
            raise GameError("Это ваш лот")
        if not t.run("UPDATE users SET aura=aura-? WHERE id=? AND aura>=?", (price, user["id"], price)).rowcount:
            raise GameError("Не хватает денег")
        if not t.run("UPDATE gifts SET owner=?, price=NULL, shown=1 WHERE id=? AND price=? AND owner=?",
                     (user["id"], gid, price, g["owner"])).rowcount:
            raise GameError("Лот уже продан")
        t.run("UPDATE users SET aura=aura+? WHERE id=?", (int(price * (1 - game.MARKET_FEE)), g["owner"]))
    return {"ok": True, **gifts_store(user, {})}


def profile(user, body):
    uid = int(body.get("id") or user["id"])
    with db.tx() as t:
        load(t, user)
        row = t.one("SELECT id, name, rating, state FROM users WHERE id=?", (uid,))
        if not row:
            raise GameError("Игрок не найден")
        gifts = t.all("SELECT * FROM gifts WHERE owner=? AND shown=1 ORDER BY id DESC LIMIT 30", (uid,))
    st = json.loads(row["state"])
    return {"id": uid, "name": (st.get("char") or {}).get("name") or row["name"], "rating": row["rating"],
            "tier": game.tier(row["rating"]), "char": st.get("char"), "wear": st.get("wear", ""),
            "body": (st.get("st") or {}).get("body", 0), "gifts": [gift_view(g) for g in gifts]}


def top(user, _body):
    with db.tx() as t:
        load(t, user)
        rows = t.all("SELECT id, name, rating, state FROM users WHERE rating>0 ORDER BY rating DESC LIMIT 50")
        me_row = t.one("SELECT rating FROM users WHERE id=?", (user["id"],))
        rank = t.one("SELECT COUNT(*) AS n FROM users WHERE rating>?", (me_row["rating"],))["n"] + 1
    out = []
    for r in rows:
        ch = json.loads(r["state"]).get("char") or {}
        out.append({"id": r["id"], "name": ch.get("name") or r["name"], "rating": r["rating"], "tier": game.tier(r["rating"])})
    return {"top": out, "rank": rank, "me": user["id"]}


# ---------- Фото персонажа ----------

def photo(user, body):
    data = str(body.get("png", ""))
    if not data.startswith("data:image/png;base64,"):
        raise GameError("Неверная картинка")
    raw = base64.b64decode(data.split(",", 1)[1], validate=True)
    if len(raw) > 900_000 or not raw.startswith(b"\x89PNG"):
        raise GameError("Картинка слишком большая")
    telegram.send_photo(user["id"], raw, "Фото твоего персонажа. Открой его и поставь на аватарку.")
    return {"ok": True}


# ---------- Реклама ----------

def ad_claim(user, _body):
    with db.tx() as t:
        load(t, user)
        if not t.run("UPDATE users SET ad_credits=ad_credits-1 WHERE id=? AND ad_credits>0", (user["id"],)).rowcount:
            raise GameError("Просмотр ещё не подтверждён")

    def refill(st, row):
        st["energy"] = game.ENERGY_MAX
        return {"text": "Энергия восполнена", "me": None}, 0
    return with_me(user, change(user, refill))


async def adsgram_reward(request):
    secret = request.query_params.get("secret", "")
    if not ADSGRAM_SECRET or not hmac.compare_digest(secret, ADSGRAM_SECRET):
        return PlainTextResponse("forbidden", status_code=403)
    try:
        uid = int(request.query_params.get("userid", ""))
    except ValueError:
        return PlainTextResponse("bad user", status_code=400)

    def credit():
        with db.tx() as t:
            t.run("UPDATE users SET ad_day=?, ad_today=0 WHERE id=? AND ad_day<?", (today(), uid, today()))
            t.run("UPDATE users SET ad_today=ad_today+1, ad_credits=ad_credits+1 WHERE id=? AND ad_today<? AND ad_credits<3",
                  (uid, game.AD_DAILY_CAP))
    await run_in_threadpool(credit)
    return PlainTextResponse("ok")


# ---------- Покупки за Stars ----------

def invoice(user, body):
    pid = str(body.get("pack", ""))
    pack = game.PACKS.get(pid)
    if not pack:
        raise GameError("Нет такого набора")
    with db.tx() as t:
        if pack.get("vip") and load(t, user)["vip"]:
            raise GameError("VIP уже куплен")
    link = telegram.call("createInvoiceLink", title=pack["title"],
                         description=pack["title"] + (f": {pack['aura']} ауры" if pack["aura"] else ""),
                         payload=pid, provider_token="", currency="XTR",
                         prices=[{"label": pack["title"], "amount": pack["stars"]}])
    return {"link": link}


def apply_payment(uid, payment):
    pid = payment.get("invoice_payload", "")
    pack = game.PACKS.get(pid)
    if not pack:
        log.error("unknown pack %s", pid)
        return
    with db.tx() as t:
        load(t, {"id": uid})
        fresh = t.run("INSERT INTO payments (charge_id, user_id, pack, stars, created) VALUES (?,?,?,?,?) "
                      "ON CONFLICT (charge_id) DO NOTHING",
                      (payment["telegram_payment_charge_id"], uid, pid, payment.get("total_amount", 0), now())).rowcount
        if not fresh:
            return
        t.run("UPDATE users SET aura=aura+?, vip=CASE WHEN ?=1 THEN 1 ELSE vip END WHERE id=?",
              (pack["aura"], 1 if pack.get("vip") else 0, uid))
    if pack.get("energy"):
        def refill(st, row):
            st["energy"] = game.ENERGY_MAX
            return None, 0
        change({"id": uid}, refill)


def apply_refund(refund):
    charge = refund.get("telegram_payment_charge_id", "")
    with db.tx() as t:
        p = t.one("SELECT * FROM payments WHERE charge_id=?", (charge,))
        if not p or not t.run("UPDATE payments SET refunded=1 WHERE charge_id=? AND refunded=0", (charge,)).rowcount:
            return
        pack = game.PACKS.get(p["pack"], {"aura": 0})
        t.run("UPDATE users SET aura=CASE WHEN aura>=? THEN aura-? ELSE 0 END, "
              "vip=CASE WHEN ?=1 THEN 0 ELSE vip END WHERE id=?",
              (pack["aura"], pack["aura"], 1 if pack.get("vip") else 0, p["user_id"]))


def stats_text():
    day = now() - 86400
    with db.tx() as t:
        q = lambda sql, *a: list(t.one(sql, a).values())[0]
        return (f"Игроков: {q('SELECT COUNT(*) AS n FROM users')}\n"
                f"Активных за сутки: {q('SELECT COUNT(*) AS n FROM users WHERE seen>?', day)}\n"
                f"Новых за сутки: {q('SELECT COUNT(*) AS n FROM users WHERE created>?', day)}\n"
                f"Подарков выпущено: {q('SELECT COUNT(*) AS n FROM gifts')}\n"
                f"Звёзд за сутки: {q('SELECT COALESCE(SUM(stars),0) AS s FROM payments WHERE refunded=0 AND created>?', day)}\n"
                f"Звёзд всего: {q('SELECT COALESCE(SUM(stars),0) AS s FROM payments WHERE refunded=0')}")


def handle_update(update):
    if query := update.get("pre_checkout_query"):
        pack = game.PACKS.get(query.get("invoice_payload", ""))
        ok = bool(pack) and query.get("currency") == "XTR" and query.get("total_amount") == pack["stars"]
        args = {"pre_checkout_query_id": query["id"], "ok": ok}
        if not ok:
            args["error_message"] = "Набор устарел. Откройте магазин ещё раз."
        telegram.call("answerPreCheckoutQuery", **args)
        return
    msg = update.get("message") or {}
    if pay := msg.get("successful_payment"):
        apply_payment(msg["from"]["id"], pay)
    elif refund := msg.get("refunded_payment"):
        apply_refund(refund)
    elif (text := msg.get("text", "")).startswith("/"):
        cmd, chat = text.split()[0].split("@")[0].lower(), msg["chat"]["id"]
        if cmd == "/start":
            reply = {"chat_id": chat, "text": "Начни курьером и стань магнатом: работай, учись, знакомься, открывай бизнесы и собирай редкие подарки."}
            if PUBLIC_URL:
                reply["reply_markup"] = {"inline_keyboard": [[{"text": "Играть", "web_app": {"url": PUBLIC_URL + "/"}}]]}
            telegram.call("sendMessage", **reply)
        elif cmd == "/paysupport":
            telegram.call("sendMessage", chat_id=chat, text=f"Вопрос по оплате? Напишите {SUPPORT_CONTACT}.")
        elif cmd == "/terms":
            telegram.call("sendMessage", chat_id=chat, text="Игровые деньги, подарки и VIP — внутриигровые предметы. Они не выводятся и не обмениваются на деньги.")
        elif cmd == "/stats" and ADMIN_ID and msg.get("from", {}).get("id") == ADMIN_ID:
            telegram.call("sendMessage", chat_id=chat, text=stats_text())


async def webhook(request):
    token = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not WEBHOOK_SECRET or not hmac.compare_digest(token, WEBHOOK_SECRET):
        return PlainTextResponse("forbidden", status_code=403)
    update = await request.json()
    try:
        await run_in_threadpool(handle_update, update)
    except RuntimeError as error:
        log.error("update failed: %s", error)
    return PlainTextResponse("ok")


def api(handler):
    async def endpoint(request):
        user = telegram.verify_init_data(request.headers.get("x-init-data", ""))
        if not user:
            return JSONResponse({"error": "Откройте игру через Telegram"}, status_code=401)
        try:
            raw = await request.body()
            if len(raw) > 1_300_000:
                raise ValueError
            body = json.loads(raw) if raw else {}
            if not isinstance(body, dict):
                raise ValueError
            return JSONResponse(await run_in_threadpool(handler, user, body))
        except GameError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        except (ValueError, TypeError):
            return JSONResponse({"error": "Неверный запрос"}, status_code=400)
        except RuntimeError as error:
            log.error("api failed: %s", error)
            return JSONResponse({"error": "Сервис занят, попробуйте ещё раз"}, status_code=502)
    return endpoint


async def index(_request):
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


async def gifts_js(_request):
    return FileResponse(STATIC / "gifts.js", media_type="text/javascript", headers={"Cache-Control": "public, max-age=3600"})


async def health(_request):
    return PlainTextResponse("ok")


def setup_bot():
    if not PUBLIC_URL or not WEBHOOK_SECRET:
        log.warning("PUBLIC_URL или WEBHOOK_SECRET не заданы, вебхук не настроен")
        return
    telegram.call("setWebhook", url=f"{PUBLIC_URL}/tg/webhook", secret_token=WEBHOOK_SECRET,
                  allowed_updates=["message", "pre_checkout_query"])
    telegram.call("setChatMenuButton", menu_button={"type": "web_app", "text": "Играть", "web_app": {"url": PUBLIC_URL + "/"}})


@asynccontextmanager
async def lifespan(_app):
    if not os.environ.get("BOT_TOKEN"):
        raise SystemExit("Не задан BOT_TOKEN")
    await run_in_threadpool(db.init)
    try:
        await run_in_threadpool(setup_bot)
    except RuntimeError as error:
        log.error("bot setup failed: %s", error)
    yield


ROUTES = {"me": me, "create": create, "act": act, "choose": choose, "shop": shop_buy, "deck": deck, "swipe": swipe,
          "chat": chat_reply, "date": date_go, "biz/buy": biz_buy, "biz/collect": biz_collect, "biz/up": biz_upgrade, "biz/item": biz_item,
          "gifts": gifts_store, "gift/buy": gift_buy, "gift/up": gift_upgrade, "gift/sell": gift_sell,
          "gift/show": gift_show, "market": market, "market/buy": market_buy, "profile": profile, "top": top,
          "photo": photo, "ad/claim": ad_claim, "invoice": invoice}
app = Starlette(lifespan=lifespan, routes=[
    Route("/", index), Route("/health", health), Route("/gifts.js", gifts_js),
    Route("/tg/webhook", webhook, methods=["POST"]), Route("/adsgram/reward", adsgram_reward),
] + [Route(f"/api/{k}", api(v), methods=["POST"]) for k, v in ROUTES.items()])
app.add_middleware(GZipMiddleware, minimum_size=800)
