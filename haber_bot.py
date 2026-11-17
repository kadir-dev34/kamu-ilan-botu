"""Kamu ilanlarıyla ilgili haber başlıklarını toplar (Google Haberler RSS).

Yalnızca başlık, kaynak adı, tarih ve bağlantı saklanır; haber metni kopyalanmaz,
kullanıcı yayıncının sitesine yönlendirilir. Ek paket gerekmez (yalnızca
standart kütüphane + supabase).
"""

import html
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import ortak

SORGULAR = [
    "kamu personel alımı",
    "KPSS alım ilanı",
    "İŞKUR kamu işçi alımı",
    "memur alımı",
    "sözleşmeli personel alımı",
    "akademik personel alımı",
]
GUN = 14          # bu kadar günden eski haberler alınmaz
SAKLAMA_GUN = 30  # bu kadar günden eski haberler silinir
SORGU_BASI_MAX = 12
TOPLAM_MAX = 40
ANAHTAR = re.compile(
    r"alım|alim|ilan|personel|kpss|işçi|isci|memur|iskur|işkur|sınav|kadro|atama|başvuru|istihdam",
    re.IGNORECASE,
)


def feed_url(sorgu):
    q = urllib.parse.quote(f"{sorgu} when:{GUN}d")
    return f"https://news.google.com/rss/search?q={q}&hl=tr&gl=TR&ceid=TR:tr"


def indir(url):
    istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (kamu-ilan-botu)"})
    with urllib.request.urlopen(istek, timeout=30) as r:
        return r.read()


def haberleri_ayikla(xml_bytes, simdi):
    """RSS içeriğinden [{baslik, kaynak, link, yayin_tarihi}] döndürür."""
    kok = ET.fromstring(xml_bytes)
    sonuc = []
    for it in kok.iter("item"):
        baslik = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        kaynak = (it.findtext("source") or "").strip()
        if kaynak and baslik.endswith(" - " + kaynak):  # Google başlığa kaynağı ekler
            baslik = baslik[: -len(kaynak) - 3].strip()
        elif " - " in baslik and not kaynak:
            baslik, kaynak = baslik.rsplit(" - ", 1)
        try:
            tarih = parsedate_to_datetime(it.findtext("pubDate") or "")
            if tarih.tzinfo is None:
                tarih = tarih.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if not baslik or not link.startswith("http"):
            continue
        if tarih < simdi - timedelta(days=GUN) or tarih > simdi + timedelta(hours=2):
            continue
        if not ANAHTAR.search(baslik):
            continue
        sonuc.append(
            {
                "baslik": baslik[:300],
                "kaynak": kaynak[:100] or None,
                "link": link,
                "yayin_tarihi": tarih.astimezone(timezone.utc).isoformat(),
            }
        )
    return sonuc


def calistir():
    db = ortak.supabase_istemcisi()
    simdi = datetime.now(timezone.utc)
    toplanan, basarili = {}, 0

    for sorgu in SORGULAR:
        try:
            haberler = haberleri_ayikla(indir(feed_url(sorgu)), simdi)
            basarili += 1
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: '{sorgu}' alınamadı: {e}")
            continue
        haberler.sort(key=lambda h: h["yayin_tarihi"], reverse=True)
        print(f"'{sorgu}': {len(haberler)} haber")
        for h in haberler[:SORGU_BASI_MAX]:
            toplanan.setdefault(h["link"], h)
            # aynı başlıklı farklı bağlantıları ele
    gorulen, tekil = set(), []
    for h in sorted(toplanan.values(), key=lambda h: h["yayin_tarihi"], reverse=True):
        anahtar = re.sub(r"\W+", "", ortak.tr_lower(h["baslik"]))[:60]
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        tekil.append(h)
    tekil = tekil[:TOPLAM_MAX]

    if basarili == 0:
        print("HATA: Hiçbir haber kaynağına ulaşılamadı.")
        sys.exit(1)

    if tekil:
        db.table("haberler").upsert(tekil, on_conflict="link").execute()
        print(f"{len(tekil)} haber yazıldı.")
    eski = (simdi - timedelta(days=SAKLAMA_GUN)).isoformat()
    db.table("haberler").delete().lt("yayin_tarihi", eski).execute()
    print("Eski haberler temizlendi.")


if __name__ == "__main__":
    calistir()
