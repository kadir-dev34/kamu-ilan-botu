"""İŞKUR açık kamu iş ilanları botu.

Sayfa: https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx
Akış: "Kamu" seç -> "Ara" -> sonuçlardaki a.share-toggle öğelerinin data-*
özniteliklerini oku -> Supabase'e yaz. 0 sonuçta hata koduyla çıkar.
"""

import sys

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

import ortak

KAYNAK = "ISKUR"
URL = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx"
MAX_SAYFA = 60
MIN_ILAN_PASIF_ICIN = 3

JS_TOPLA = """
() => Array.from(document.querySelectorAll('a.share-toggle')).map(a => ({
  no: a.getAttribute('data-ilanno'),
  meslek: a.getAttribute('data-meslekler'),
  il: a.getAttribute('data-il'),
  sontarih: a.getAttribute('data-sontarih'),
  url: a.getAttribute('data-url'),
  acik: a.getAttribute('data-acikissayi'),
  tur: a.getAttribute('data-isverentur'),
  sekil: a.getAttribute('data-calismasekli'),
}))
"""


def temizle(s):
    return " ".join((s or "").split())


PAGER = "#ctl04_ctlDataPagerDetay"


def ilan_nolari(page):
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('a.share-toggle')).map(a => a.getAttribute('data-ilanno'))"
    )


def sonraki_sayfa(page, su_an):
    """Sayfalayıcıda bir sonraki sayfaya (su_an+1) geçer. Geçtiyse True döner.
    Sayfalayıcı yoksa ya da son sayfadaysak False."""
    oncekiler = ilan_nolari(page)
    linkler = page.locator(f"{PAGER} a")
    hedef = None
    for i in range(linkler.count()):
        metin = " ".join((linkler.nth(i).inner_text() or "").split())
        if metin == str(su_an + 1):
            hedef = linkler.nth(i)
            break
    if hedef is None:
        for i in range(linkler.count()):
            metin = " ".join((linkler.nth(i).inner_text() or "").split()).lower()
            if metin in (">", "›", "»", "sonraki", "next", "ileri"):
                hedef = linkler.nth(i)
                break
    if hedef is None:
        return False
    hedef.click(force=True)
    for _ in range(30):  # en çok ~30 sn: liste değişene kadar bekle
        page.wait_for_timeout(1000)
        try:
            simdiki = ilan_nolari(page)
        except Exception:  # noqa: BLE001  (sayfa yenilenirken)
            continue
        if simdiki and simdiki != oncekiler:
            return True
    return False


def calistir():
    baslangic = ortak.simdi_iso()
    db = ortak.supabase_istemcisi()
    ilanlar = {}

    with sync_playwright() as p:
        tarayici = p.chromium.launch(headless=True)
        sayfa = tarayici.new_context(
            locale="tr-TR", viewport={"width": 1366, "height": 900}
        ).new_page()
        sayfa.set_default_timeout(45000)
        try:
            sayfa.goto(URL, wait_until="networkidle")
            sayfa.get_by_text("Kamu", exact=True).click(force=True)
            sayfa.wait_for_timeout(3000)
            ara = sayfa.locator("#ctl04_ctlAcikIsPageCommand_CommandItem_Search")
            ara.click(force=True)
            try:
                sayfa.wait_for_selector("a.share-toggle", timeout=40000)
            except PWTimeout:
                # Tıklama tetiklemediyse sayfadaki postback'i doğrudan çalıştır
                print("Tıklama sonuç getirmedi, postback doğrudan çağrılıyor...")
                sayfa.evaluate(
                    "__doPostBack('ctl04$ctlAcikIsPageCommand$CommandItem_Search','')"
                )
                sayfa.wait_for_selector("a.share-toggle", timeout=60000)

            for no in range(1, MAX_SAYFA + 1):
                satirlar = sayfa.evaluate(JS_TOPLA)
                yeni = 0
                for s in satirlar:
                    ilan_no = temizle(s["no"])
                    if not ilan_no or ilan_no in ilanlar:
                        continue
                    yeni += 1
                    meslek = temizle(s["meslek"]) or "Kamu İşçisi Alımı"
                    il = temizle(s["il"]) or "Türkiye Geneli"
                    ilanlar[ilan_no] = {
                        "kaynak_sistem": KAYNAK,
                        "orijinal_ilan_id": ilan_no,
                        "baslik": meslek,
                        "kurum_adi": temizle(s["tur"]) or "İŞKUR (Kamu)",
                        "ilan_turu": "Kamu İşçisi",
                        "sehir": il,
                        "mezuniyet_sarti": None,
                        "kpss_turu": None,
                        "son_basvuru_tarihi": ortak.tarih_cevir(s["sontarih"]),
                        "basvuru_linki": (s["url"] or "").strip() or URL,
                        "detay_islendi": True,
                    }
                print(f"Sayfa {no}: {len(satirlar)} satır, {yeni} yeni ilan")
                if yeni == 0 or not sonraki_sayfa(sayfa, no):
                    break
        except (PWTimeout, Exception) as e:  # noqa: BLE001
            print(f"HATA: {e}")
            ortak.debug_kaydet(sayfa, "iskur_hata")
            tarayici.close()
            sys.exit(1)
        tarayici.close()

    if not ilanlar:
        print("HATA: Hiç ilan bulunamadı (site yapısı değişmiş olabilir).")
        sys.exit(1)

    n = ortak.kayitlari_yaz(db, list(ilanlar.values()), baslangic)
    print(f"{n} İŞKUR ilanı yazıldı.")
    ortak.pasife_al(db, KAYNAK, baslangic, len(ilanlar), MIN_ILAN_PASIF_ICIN)


if __name__ == "__main__":
    calistir()
