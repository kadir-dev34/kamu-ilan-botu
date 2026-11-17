"""Kamu ilanlarıyla ilgili haber/duyuru başlıklarını toplar.

Kaynaklar haber_kaynaklari.json dosyasından okunur:
  * "rss": kamu kurumlarının kendi RSS/Atom adresleri (öncelikli kaynak)
  * "google_haber": true ise Google Haberler araması da kullanılır (yedek)
Yalnızca başlık, kaynak adı, tarih ve bağlantı saklanır; metin kopyalanmaz.
Ek paket gerekmez (standart kütüphane + supabase).
"""

import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import ortak

AYAR_DOSYASI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "haber_kaynaklari.json")
GUN = 14          # bu kadar günden eski haberler alınmaz
SAKLAMA_GUN = 30  # bu kadar günden eski haberler silinir
KAYNAK_BASI_MAX = 12
TOPLAM_MAX = 40
UA = "kamu-ilan-botu/1.0"
ANAHTAR = re.compile(
    r"alım|alim|ilan|personel|kpss|işçi|isci|memur|iskur|işkur|sınav|kadro|atama|başvuru|istihdam",
    re.IGNORECASE,
)


def ayar_oku():
    with open(AYAR_DOSYASI, encoding="utf-8") as f:
        return json.load(f)


def indir(url):
    istek = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, */*"})
    with urllib.request.urlopen(istek, timeout=30) as r:
        return r.read()


def google_url(sorgu):
    q = urllib.parse.quote(f"{sorgu} when:{GUN}d")
    return f"https://news.google.com/rss/search?q={q}&hl=tr&gl=TR&ceid=TR:tr"


def _tarih(metin):
    metin = (metin or "").strip()
    if not metin:
        raise ValueError("tarih yok")
    try:
        t = parsedate_to_datetime(metin)  # RSS: RFC 822
    except (TypeError, ValueError):
        t = datetime.fromisoformat(metin.replace("Z", "+00:00"))  # Atom: ISO 8601
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def _yerel(etiket):
    return etiket.rsplit("}", 1)[-1]


def haberleri_ayikla(xml_bytes, simdi, varsayilan_kaynak=None, filtre=True, taban_url=None):
    """RSS 2.0 ve Atom içeriğinden [{baslik, kaynak, link, yayin_tarihi}] döndürür."""
    kok = ET.fromstring(xml_bytes)
    kayitlar = [e for e in kok.iter() if _yerel(e.tag) in ("item", "entry")]
    sonuc = []
    for it in kayitlar:
        alan = {}
        for c in it:
            alan.setdefault(_yerel(c.tag), c)
        baslik = html.unescape((alan["title"].text if "title" in alan else "") or "").strip()
        # bağlantı: RSS <link>metin</link>, Atom <link href="..."/>
        link = ""
        if "link" in alan:
            link = (alan["link"].get("href") or alan["link"].text or "").strip()
        kaynak = ((alan["source"].text if "source" in alan else "") or "").strip() or varsayilan_kaynak or ""
        if kaynak and baslik.endswith(" - " + kaynak):  # Google başlığa kaynağı ekler
            baslik = baslik[: -len(kaynak) - 3].strip()
        elif varsayilan_kaynak is None and " - " in baslik and not kaynak:
            baslik, kaynak = baslik.rsplit(" - ", 1)
        if taban_url and link and not link.startswith("http"):
            link = urllib.parse.urljoin(taban_url, link)
        try:
            tarih = _tarih(
                (alan["pubDate"].text if "pubDate" in alan else None)
                or (alan["published"].text if "published" in alan else None)
                or (alan["updated"].text if "updated" in alan else None)
                or (alan["date"].text if "date" in alan else None)
            )
        except (TypeError, ValueError):
            continue
        if not baslik or not link.startswith("http"):
            continue
        if tarih < simdi - timedelta(days=GUN) or tarih > simdi + timedelta(hours=2):
            continue
        if filtre and not ANAHTAR.search(baslik):
            continue
        sonuc.append(
            {
                "baslik": baslik[:300],
                "kaynak": kaynak[:100] or None,
                "link": link,
                "yayin_tarihi": tarih.isoformat(),
            }
        )
    return sonuc


def kaynaklari_listele(ayar):
    """[(ad, url, varsayilan_kaynak, filtre)] listesi."""
    liste = []
    for r in ayar.get("rss", []):
        if r.get("aktif", True) and r.get("url", "").startswith("http"):
            liste.append((r.get("ad", r["url"]), r["url"], r.get("ad"), r.get("filtre", True)))
    if ayar.get("google_haber"):
        for s in ayar.get("google_sorgulari", []):
            liste.append((f"Google: {s}", google_url(s), None, True))
    return liste


def calistir():
    db = ortak.supabase_istemcisi()
    simdi = datetime.now(timezone.utc)
    kaynaklar = kaynaklari_listele(ayar_oku())
    if not kaynaklar:
        print("HATA: haber_kaynaklari.json içinde etkin kaynak yok.")
        sys.exit(1)

    toplanan, basarili = {}, 0
    for ad, url, varsayilan, filtre in kaynaklar:
        try:
            haberler = haberleri_ayikla(indir(url), simdi, varsayilan, filtre, url)
            basarili += 1
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: '{ad}' alınamadı: {e}")
            continue
        haberler.sort(key=lambda h: h["yayin_tarihi"], reverse=True)
        print(f"'{ad}': {len(haberler)} haber")
        for h in haberler[:KAYNAK_BASI_MAX]:
            toplanan.setdefault(h["link"], h)

    if basarili == 0:
        print("HATA: Hiçbir haber kaynağına ulaşılamadı.")
        sys.exit(1)

    gorulen, tekil = set(), []
    for h in sorted(toplanan.values(), key=lambda h: h["yayin_tarihi"], reverse=True):
        anahtar = re.sub(r"\W+", "", ortak.tr_lower(h["baslik"]))[:60]
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        tekil.append(h)
    tekil = tekil[:TOPLAM_MAX]

    if tekil:
        db.table("haberler").upsert(tekil, on_conflict="link").execute()
        print(f"{len(tekil)} haber yazıldı.")
    eski = (simdi - timedelta(days=SAKLAMA_GUN)).isoformat()
    db.table("haberler").delete().lt("yayin_tarihi", eski).execute()
    print("Eski haberler temizlendi.")


if __name__ == "__main__":
    calistir()
