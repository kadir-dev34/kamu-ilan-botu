"""Kamu kurumlarının sitelerinde RSS/Atom beslemesi arar (yalnızca keşif amaçlı).

Her siteye az sayıda ve kibar istek atar (robots.txt'e uyar, 1 sn bekler). Çıktıda
bulunan ve çalışan besleme adreslerini listeler; bunları haber_kaynaklari.json
dosyasındaki "rss" listesine siz ekleyin. Veritabanına yazmaz.
"""

import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET

UA = "kamu-ilan-botu/1.0 (RSS kesfi; iletisim: site sahibi)"
SITELER = [
    ("ÖSYM", "https://www.osym.gov.tr"),
    ("Devlet Personel Başkanlığı", "https://www.dpb.gov.tr"),
    ("İŞKUR", "https://www.iskur.gov.tr"),
    ("Resmî Gazete", "https://www.resmigazete.gov.tr"),
    ("İlan.gov.tr", "https://www.ilan.gov.tr"),
    ("Milli Eğitim Bakanlığı", "https://www.meb.gov.tr"),
    ("Sağlık Bakanlığı", "https://www.saglik.gov.tr"),
    ("Sayıştay", "https://www.sayistay.gov.tr"),
    ("YÖK", "https://www.yok.gov.tr"),
    ("İçişleri Bakanlığı", "https://www.icisleri.gov.tr"),
    ("Adalet Bakanlığı", "https://www.adalet.gov.tr"),
    ("Millî Savunma Bakanlığı", "https://www.msb.gov.tr"),
    ("Aile ve Sosyal Hizmetler Bak.", "https://www.aile.gov.tr"),
    ("Çalışma ve Sosyal Güv. Bak.", "https://www.csgb.gov.tr"),
    ("Tarım ve Orman Bakanlığı", "https://www.tarimorman.gov.tr"),
    ("Gençlik ve Spor Bakanlığı", "https://www.gsb.gov.tr"),
    ("Hazine ve Maliye Bakanlığı", "https://www.hmb.gov.tr"),
    ("Diyanet İşleri Başkanlığı", "https://www.diyanet.gov.tr"),
    ("Jandarma Genel Komutanlığı", "https://www.jandarma.gov.tr"),
    ("Emniyet Genel Müdürlüğü", "https://www.egm.gov.tr"),
    ("SGK", "https://www.sgk.gov.tr"),
    ("TBMM", "https://www.tbmm.gov.tr"),
    # Ticari haber sitesi: yalnızca kendi sundukları RSS varsa (başlık + bağlantı) kullanılır.
    ("Memurlar.net (yalnızca RSS varsa)", "https://www.memurlar.net"),
]
YOLLAR = ["/rss", "/rss.xml", "/feed", "/feed.xml", "/rss/duyurular", "/tr/rss", "/Rss"]
ALT_LINK = re.compile(
    r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", re.IGNORECASE
)
HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)


def al(url, sinir=400_000):
    istek = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(istek, timeout=20) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read(sinir)


def izinli(taban, yol):
    rp = urllib.robotparser.RobotFileParser()
    try:
        _, _, govde = al(taban + "/robots.txt", 100_000)
        rp.parse(govde.decode("utf-8", "ignore").splitlines())
    except Exception:  # noqa: BLE001  (robots.txt yoksa serbest kabul edilir)
        return True
    return rp.can_fetch(UA, taban + yol)


def besleme_mi(veri):
    try:
        kok = ET.fromstring(veri)
    except ET.ParseError:
        return None
    etiket = kok.tag.lower()
    if etiket.endswith("rss") or etiket.endswith("feed") or etiket.endswith("rdf"):
        sayi = len(list(kok.iter("item"))) or len([e for e in kok.iter() if e.tag.endswith("}entry")])
        return sayi
    return None


def kesfet(ad, taban):
    bulunan = []
    adaylar = []
    if izinli(taban, "/"):
        try:
            _, _, govde = al(taban + "/")
            for etiket in ALT_LINK.findall(govde.decode("utf-8", "ignore")):
                m = HREF.search(etiket)
                if m:
                    adaylar.append(urllib.parse.urljoin(taban + "/", m.group(1)))
        except Exception as e:  # noqa: BLE001
            print(f"  ana sayfa alınamadı: {e}")
    else:
        print("  robots.txt ana sayfaya izin vermiyor, atlandı.")
        return bulunan
    adaylar += [taban + y for y in YOLLAR]
    gorulen = set()
    for url in adaylar:
        if url in gorulen:
            continue
        gorulen.add(url)
        yol = urllib.parse.urlparse(url).path or "/"
        if not izinli(taban, yol):
            continue
        time.sleep(1)
        try:
            kod, _, veri = al(url)
        except urllib.error.HTTPError:
            continue
        except Exception:  # noqa: BLE001
            continue
        n = besleme_mi(veri) if kod == 200 else None
        if n:
            bulunan.append((url, n))
    return bulunan


def main():
    toplam = 0
    for ad, taban in SITELER:
        print(f"\n== {ad}  ({taban})")
        try:
            sonuc = kesfet(ad, taban)
        except Exception as e:  # noqa: BLE001
            print(f"  hata: {e}")
            continue
        if not sonuc:
            print("  besleme bulunamadı")
        for url, n in sonuc:
            toplam += 1
            print(f'  BULUNDU: {url}  ({n} kayıt)')
            print(f'  -> {{ "ad": "{ad}", "url": "{url}", "filtre": true, "aktif": true }}')
        time.sleep(1)
    print(f"\nToplam {toplam} çalışan besleme bulundu.")


if __name__ == "__main__":
    main()
