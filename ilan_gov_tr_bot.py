"""ilan.gov.tr kamu ilanları botu (Kamu Personeli, Akademik, Askeri).

Akış: kategori listesi (currentPage=N) -> ilan bağlantıları -> yeni ilanların
detay sayfası -> şehir/kurum/KPSS/mezuniyet/son başvuru çıkarımı -> Supabase.
Detay metni değişmeyeceği için daha önce işlenmiş ilanlar tekrar açılmaz,
sadece "görüldü" olarak işaretlenir.
"""

import re
import sys

from playwright.sync_api import sync_playwright

import ortak

KAYNAK = "ILAN_GOV_TR"
BASE = "https://www.ilan.gov.tr"
KATEGORILER = [
    ("Kamu Personeli", f"{BASE}/ilan/kategori/44/kamu-personeli"),
    ("Akademik Personel", f"{BASE}/ilan/kategori/73/akademik-personel"),
    ("Askeri Personel", f"{BASE}/ilan/kategori/72/askeri-personel"),
]
MAX_SAYFA = 40
MAX_DETAY_PER_RUN = 400
MIN_ILAN_PASIF_ICIN = 30
ILAN_YOLU = re.compile(r"^/ilan/(\d+)(?:/|$)")

JS_LINKLER = """
() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
  href: a.getAttribute('href'),
  text: (a.innerText || '').trim()
}))
"""


def liste_oku(sayfa, ad, url):
    """Bir kategorinin tüm sayfalarını gezip {id: (baslik, link)} döndürür."""
    sonuc = {}
    for no in range(1, MAX_SAYFA + 1):
        sayfa.goto(f"{url}?currentPage={no}", wait_until="domcontentloaded")
        try:
            sayfa.wait_for_selector("a[href^='/ilan/']", timeout=20000)
        except Exception:  # noqa: BLE001
            break
        sayfa.wait_for_timeout(800)
        yeni = 0
        for a in sayfa.evaluate(JS_LINKLER):
            href = (a["href"] or "").split("?")[0].split("#")[0]
            m = ILAN_YOLU.match(href)
            if not m:
                continue
            ilan_id = m.group(1)
            satirlar = ortak.satirlar(a["text"])
            if ilan_id in sonuc:
                continue
            baslik = satirlar[0] if satirlar else ""
            if len(baslik) < 8:
                continue
            sonuc[ilan_id] = {"baslik": baslik, "link": BASE + href, "tur": ad}
            yeni += 1
        print(f"  {ad} sayfa {no}: {yeni} yeni bağlantı")
        if yeni == 0:
            break
    return sonuc


def detay_oku(sayfa, link):
    sayfa.goto(link, wait_until="domcontentloaded")
    sayfa.wait_for_timeout(1500)
    try:
        sayfa.wait_for_selector("body", timeout=10000)
        return sayfa.inner_text("body")
    except Exception:  # noqa: BLE001
        return ""


def calistir():
    baslangic = ortak.simdi_iso()
    db = ortak.supabase_istemcisi()
    mevcut = ortak.mevcut_kayitlar(db, KAYNAK)
    toplanan = {}

    with sync_playwright() as p:
        tarayici = p.chromium.launch(headless=True)
        ctx = tarayici.new_context(locale="tr-TR", viewport={"width": 1366, "height": 900})
        sayfa = ctx.new_page()
        sayfa.set_default_timeout(40000)
        try:
            for ad, url in KATEGORILER:
                print(f"Kategori: {ad}")
                toplanan.update(liste_oku(sayfa, ad, url))
        except Exception as e:  # noqa: BLE001
            print(f"HATA (liste): {e}")
            ortak.debug_kaydet(sayfa, "ilan_gov_liste_hata")
            tarayici.close()
            sys.exit(1)

        if not toplanan:
            print("HATA: Hiç ilan bulunamadı (site yapısı değişmiş olabilir).")
            ortak.debug_kaydet(sayfa, "ilan_gov_bos")
            tarayici.close()
            sys.exit(1)

        print(f"Toplam {len(toplanan)} ilan bulundu; {len(mevcut)} tanesi kayıtlı.")

        yeni_kayitlar, tekrar_gorulen, detay_sayac = [], [], 0
        for ilan_id, o in toplanan.items():
            if mevcut.get(ilan_id):
                tekrar_gorulen.append(ilan_id)
                continue
            kayit = {
                "kaynak_sistem": KAYNAK,
                "orijinal_ilan_id": ilan_id,
                "baslik": o["baslik"],
                "kurum_adi": ortak.kurum_bul(ortak.satirlar(o["baslik"])) or None,
                "ilan_turu": o["tur"],
                "sehir": "Türkiye Geneli",
                "mezuniyet_sarti": None,
                "kpss_turu": None,
                "son_basvuru_tarihi": None,
                "basvuru_linki": o["link"],
                "detay_islendi": False,
            }
            if detay_sayac < MAX_DETAY_PER_RUN:
                detay_sayac += 1
                try:
                    metin = detay_oku(sayfa, o["link"])
                    if metin:
                        satirlar = ortak.satirlar(metin)
                        kayit["kurum_adi"] = ortak.kurum_bul(satirlar) or kayit["kurum_adi"]
                        kayit["sehir"] = ortak.sehir_bul(metin[:6000])
                        kayit["mezuniyet_sarti"] = ortak.mezuniyet_bul(metin)
                        kayit["kpss_turu"] = ortak.kpss_bul(metin)
                        kayit["son_basvuru_tarihi"] = ortak.son_basvuru_bul(metin)
                        kayit["detay_islendi"] = True
                except Exception as e:  # noqa: BLE001
                    print(f"  Detay alınamadı ({ilan_id}): {e}")
            yeni_kayitlar.append(kayit)
            if len(yeni_kayitlar) % 25 == 0:
                print(f"  {len(yeni_kayitlar)} yeni ilan işlendi...")
        tarayici.close()

    if yeni_kayitlar:
        n = ortak.kayitlari_yaz(db, yeni_kayitlar, baslangic)
        print(f"{n} yeni/güncellenen ilan yazıldı.")
    if tekrar_gorulen:
        ortak.gorulenleri_isaretle(db, KAYNAK, tekrar_gorulen, baslangic)
        print(f"{len(tekrar_gorulen)} mevcut ilan 'görüldü' işaretlendi.")

    ortak.pasife_al(db, KAYNAK, baslangic, len(toplanan), MIN_ILAN_PASIF_ICIN)


if __name__ == "__main__":
    calistir()
