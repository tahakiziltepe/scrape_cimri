import re
import sys
import json
import requests
import asyncio
import os
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# Bold output support (ANSI / colorama fallback)
try:
    from colorama import init as _colorama_init, Style as _Style
    _colorama_init()
    BOLD_ON = _Style.BRIGHT
    BOLD_OFF = _Style.RESET_ALL
except Exception:
    BOLD_ON = "\033[1m"
    BOLD_OFF = "\033[0m"

URL = "https://www.cimri.com/cep-telefonlari/en-ucuz-apple-iphone-15-5g-128gb-siyah-fiyatlari,2237451716"

# Telegram bot ayarları .env üzerinden alınır
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


Offer = Dict[str, Optional[str]]


def looks_like_price(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return bool(re.search(r"\d+[\d\.,]*\s*TL", value, flags=re.I)) or bool(
            re.fullmatch(r"\d+[\d\.,]*", value)
        )
    return False


def coerce_price_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{value:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(value, str):
        m = re.search(r"(\d+[\d\.,]*)\s*TL", value, flags=re.I)
        if m:
            return m.group(1).strip() + " TL"
        m = re.search(r"\d+[\d\.,]*", value)
        if m:
            return m.group(0).strip() + " TL"
        return None
    return None


def extract_offers_from_json(obj: Any) -> List[Offer]:
    results: List[Offer] = []

    def visit(node: Any):
        if isinstance(node, dict):
            keys_lower = {k.lower(): k for k in node.keys()}
            price_val = None
            for pk in [
                "price", "pricenew", "pricevalue", "displayprice", "pricetext", "fiyat", "amount",
            ]:
                k = keys_lower.get(pk)
                if k and looks_like_price(node.get(k)):
                    price_val = coerce_price_text(node.get(k))
                    break
            if not price_val:
                p = node.get(keys_lower.get("price")) if keys_lower.get("price") else None
                if isinstance(p, dict):
                    for pk in ["raw", "value", "text", "amount"]:
                        if pk in p and looks_like_price(p[pk]):
                            price_val = coerce_price_text(p[pk])
                            break

            seller_val: Optional[str] = None
            site_val: Optional[str] = None

            for sk in [
                "seller", "sellername", "merchant", "merchantname", "store", "storename", "satici", "magaza",
            ]:
                k = keys_lower.get(sk)
                if k and isinstance(node.get(k), (str, dict)):
                    v = node.get(k)
                    if isinstance(v, str) and v.strip():
                        seller_val = v.strip()
                        break
                    elif isinstance(v, dict):
                        for nk in ["name", "displayname", "merchantname", "sellername", "storename"]:
                            if nk in {kk.lower(): kk for kk in v.keys()}:
                                key = {kk.lower(): kk for kk in v.keys()}[nk]
                                val = v.get(key)
                                if isinstance(val, str) and val.strip():
                                    seller_val = val.strip()
                                    break

            for mk in [
                "market", "marketname", "platform", "platformname", "site", "sitename", "channel", "channelname",
            ]:
                k = keys_lower.get(mk)
                if k and isinstance(node.get(k), (str, dict)):
                    v = node.get(k)
                    if isinstance(v, str) and v.strip():
                        site_val = v.strip()
                        break
                    elif isinstance(v, dict):
                        for nk in ["name", "displayname", "marketname", "platformname"]:
                            if nk in {kk.lower(): kk for kk in v.keys()}:
                                key = {kk.lower(): kk for kk in v.keys()}[nk]
                                val = v.get(key)
                                if isinstance(val, str) and val.strip():
                                    site_val = val.strip()
                                    break

            if price_val and (seller_val or site_val):
                url_val: Optional[str] = None
                for uk in ["url", "deeplink", "link", "producturl", "offerurl"]:
                    ku = keys_lower.get(uk)
                    if ku and isinstance(node.get(ku), str) and node[ku].startswith("http"):
                        url_val = node[ku]
                        break
                results.append({
                    "site": site_val or "",
                    "seller": seller_val or "",
                    "price": price_val,
                    "url": url_val or "",
                })
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(obj)

    dedup: Dict[Tuple[str, str, str], Offer] = {}
    for r in results:
        key = (r.get("site") or "", r.get("seller") or "", r.get("price") or "")
        if key not in dedup and all(key):
            dedup[key] = r
    return list(dedup.values())


def parse_html_for_offers(html: str) -> List[Offer]:
    # <section id="fiyatlar"> altında görünen TÜM teklifleri requests ile çıkar
    offers: List[Offer] = []
    soup = BeautifulSoup(html, "lxml")

    section = soup.find("section", id="fiyatlar")
    if not section:
        return []

    def text(el) -> str:
        try:
            return el.get_text(" ", strip=True)
        except Exception:
            return ""

    # Teklif kartını, fiyat elemanından yukarı tırmanarak bul: ebeveyni birden fazla fiyat barındırıyorsa dur
    def ascend_card_from_price(price_el):
        cur = price_el
        last = price_el
        for _ in range(12):
            parent = getattr(cur, "parent", None)
            if not parent:
                break
            try:
                cnt = len(parent.select("div.rTdMX"))
            except Exception:
                cnt = 0
            if cnt == 1:
                last = parent
                cur = parent
                continue
            break
        return last

    # Fiyat alanları (ör: <div class="rTdMX">51.299,00 TL</div>)
    price_nodes = section.select("div.rTdMX")

    base = "https://www.cimri.com"
    seen_keys = set()

    for pnode in price_nodes:
        price_text = text(pnode)
        m = re.search(r"(\d+[\d\.,]*)\s*TL", price_text)
        price = (m.group(1) + " TL") if m else None
        if not price:
            continue

        card = ascend_card_from_price(pnode)
        if not card:
            continue

        # Satıcı: <div class="zp61l">Alisgidis</div>
        seller_el = card.find("div", class_="zp61l")
        seller = text(seller_el) if seller_el else ""

        # Site: merchant-logos görselinin alt metninden
        site = ""
        site_img = card.find("img", src=re.compile(r"merchant-logos"))
        if site_img:
            alt = (site_img.get("alt") or "").strip()
            if alt:
                site = alt

        # Link: "Mağazaya Git" düğmesinin href'i
        href = ""
        cta = card.find(lambda t: t and t.name in ("a", "button") and re.search(r"Mağazaya Git", text(t), re.I))
        if cta and hasattr(cta, "get"):
            href = cta.get("href") or ""
            if href.startswith("/"):
                href = base + href

        key = href or f"{site}|{seller}|{price}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        if price and (site or seller):
            offers.append({
                "site": site,
                "seller": seller,
                "price": price,
                "url": href,
            })

    return offers


def fetch(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.google.com/",
        "Cache-Control": "no-cache",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def print_offers(offers: List[Offer]) -> None:
    if not offers:
        print("Hiç teklif bulunamadı. Sayfa yapısı değişmiş olabilir.")
        return
    for idx, o in enumerate(offers, start=1):
        site = (o.get("site") or "-").strip()
        seller = (o.get("seller") or "-").strip()
        price = (o.get("price") or "-").strip()
        highlight = site.lower() in ("hepsiburada", "amazon") or seller.lower() in ("hepsiburada", "amazon")
        prefix = f"{_num_emoji(idx)} {'⭐ ' if highlight else ''}".rstrip()
        line = f"{prefix} Site: {site} | Satıcı: {seller} | Fiyat: {price}"
        if o.get("url"):
            line += f" | Link: {o['url']}"
        if highlight:
            print(f"{BOLD_ON}{line}{BOLD_OFF}")
        else:
            print(line)


def _price_to_float(price: Optional[str]) -> float:
    """Convert '51.299,00 TL' -> 51299.00 for sorting. Returns +inf if not parseable."""
    if not price:
        return float("inf")
    s = price
    s = s.replace("TL", "").replace("tl", "").strip()
    # Remove thousands separators (.) and use comma as decimal -> dot
    s = s.replace(".", "").replace(",", ".")
    # Extract first numeric token
    m = re.search(r"\d+(?:\.\d+)?", s)
    if m:
        try:
            return float(m.group(0))
        except Exception:
            pass
    # Fallback: strip non-numeric
    s2 = re.sub(r"[^0-9\.]", "", s)
    try:
        return float(s2) if s2 else float("inf")
    except Exception:
        return float("inf")


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _offers_to_telegram_messages(offers: List[Offer], source_url: str) -> List[str]:
    # 4096 karakter sınırını aşmamak için böl
    lines: List[str] = []
    for idx, o in enumerate(offers, start=1):
        site_raw = (o.get("site") or "-").strip()
        seller_raw = (o.get("seller") or "-").strip()
        highlight = (site_raw.lower() == "hepsiburada" and seller_raw.lower() == "hepsiburada") or \
                    (site_raw.lower() == "amazon" and seller_raw.lower() == "amazon")
        site = _escape_html(site_raw)
        seller = _escape_html(seller_raw)
        price = _escape_html((o.get("price") or "-").strip())
        url = (o.get("url") or "").strip()
        prefix = (_num_emoji(idx) + (" ⭐" if highlight else ""))
        line = f"{prefix} Site: {site} | Satıcı: {seller} \n💲 Fiyat: {price}"
        if url:
            line += f" | Link: {url}"
        if highlight:
            line = f"<b>{line}</b>"
        lines.append(line)

    header = "<b>-------> 📱 Apple iPhone 15 128GB Siyah</b>"
    msgs: List[str] = []
    cur = header
    for ln in lines:
        if len(cur) + 1 + len(ln) > 3800:  # güvenli tampon
            msgs.append(cur)
            cur = header + "\n" + ln
        else:
            cur = (cur + "\n" + ln) if cur else ln
    if cur:
        msgs.append(cur)

    # Mesajın en sonuna kontrol edilen linki ekle
    if msgs:
        src = _escape_html(source_url or "")
        if src:
            msgs[-1] = msgs[-1] + f"\n\n🔗 Kaynak: {src}"

    return msgs


def _telegram_send(token: str, chat_id: str, text: str) -> bool:
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=20)
        return resp.ok
    except Exception:
        return False


def _telegram_get_chat_id(token: str) -> Optional[str]:
    # Son güncellemelerden bir kişisel sohbet id’si bulmayı dener
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        resp = requests.get(url, timeout=20)
        if not resp.ok:
            return None
        data = resp.json()
        for upd in reversed(data.get("result", [])):
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat") or {}
            cid = chat.get("id")
            if cid is not None:
                return str(cid)
        return None
    except Exception:
        return None


def _num_emoji(n: int) -> str:
    # 1-9 -> 1️⃣..9️⃣, 10 -> 🔟, diğerleri -> her rakamın keycap versiyonu
    digits = {
        '0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣',
        '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣',
    }
    if n == 10:
        return '🔟'
    if 1 <= n <= 9:
        return digits[str(n)]
    return ''.join(digits.get(ch, ch) for ch in str(n))


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else URL
    html = fetch(url)
    offers = parse_html_for_offers(html)
    # Fiyata göre küçükten büyüğe sırala
    offers = sorted(offers, key=lambda o: _price_to_float(o.get("price")))

    # Konsola yaz
    print_offers(offers)

    # Telegram bildirim koşulları
    COND1_THRESHOLD = 51000.0  # en ucuz < 50.000 TL
    COND2_THRESHOLD = 50500.0  # HB/HB veya Amazon/Amazon satırlarından biri < 50.500 TL

    cond1 = False
    cond2 = False
    if offers:
        # En ucuz fiyat kontrolü (list already sorted)
        min_price = _price_to_float(offers[0].get("price"))
        cond1 = min_price < COND1_THRESHOLD

        # Hepsiburada/Hepsiburada veya Amazon/Amazon ve fiyat < 50.500 TL kontrolü
        for o in offers:
            site_raw = (o.get("site") or "").strip().lower()
            seller_raw = (o.get("seller") or "").strip().lower()
            strict_highlight = (
                (site_raw == "hepsiburada" and seller_raw == "hepsiburada") or
                (site_raw == "amazon" and seller_raw == "amazon")
            )
            if strict_highlight:
                if _price_to_float(o.get("price")) < COND2_THRESHOLD:
                    cond2 = True
                    break

    should_notify = cond1 or cond2

    if not should_notify:
        print("Telegram: Koşullar sağlanmadı, mesaj gönderilmeyecek.")
        return

    # Telegram gönderim için token kontrolü
    if not TELEGRAM_TOKEN:
        print("Telegram: TELEGRAM_BOT_TOKEN bulunamadı (.env). Mesaj gönderilmeyecek.")
        return

    # Telegram gönderim (chat_id öncelik: argüman > env > getUpdates)
    chat_id = None
    for i, arg in enumerate(sys.argv[1:], start=1):
        if arg.startswith("--chat="):
            chat_id = arg.split("=", 1)[1].strip()
            break
    if not chat_id:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        chat_id = _telegram_get_chat_id(TELEGRAM_TOKEN)

    if chat_id:
        messages = _offers_to_telegram_messages(offers, url)
        ok_all = True
        for msg in messages:
            ok = _telegram_send(TELEGRAM_TOKEN, chat_id, msg)
            ok_all = ok_all and ok
        if ok_all:
            print("Telegram: Mesaj gönderildi.")
        else:
            print("Telegram: Bir veya daha fazla mesaj gönderilemedi.")
    else:
        print("Telegram: chat_id bulunamadı. Lütfen --chat=<id> parametresi verin veya TELEGRAM_CHAT_ID ortam değişkenini ayarlayın.")


if __name__ == "__main__":
    main()
