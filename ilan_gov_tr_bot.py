"""ilan.gov.tr kamu ilanları botu (Kamu Personeli, Akademik, Askeri).

Akış:
 1. Kategori listesi (currentPage=N): her satırda kurum, başlık, ilan no ve şehir
    doğrudan listeden okunur.
 2. Yeni ilanların detay sayfası açılıp son başvuru tarihi, mezuniyet ve KPSS
    çıkarılır (akademik ilanlarda mezuniyet/KPSS yazılmaz).
 3. Zaten işlenmiş ilanların liste alanları (kurum, şehir, başlık) güncellenir,
    detaydan gelen alanlara dokunulmaz.
 4. Bu taramada görülmeyen ilanlar pasife alınır.
"Düzeltme ve İptal İlanı" başlıklı duyurular listelenmez.
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
SATIR_SEC = "a[href^='/ilan/'] .search-results-row"

JS_SATIRLAR = """
() => Array.from(document.querySelectorAll("a[href^='/ilan/']")).map(a => {
  const row = a.querySelector('.search-results-row');
  if (!row) return null;
  const t = (e) => (e ? (e.innerText || '').trim() : '');
  const cols = Array.from(row.children).filter(c => c.classList.contains('col'));
  return { href: a.getAttribute('href'), title: a.getAttribute('title') || '', cols: cols.map(t) };
}).filter(x => x)
"""


def temizle(s):
    return " ".join((s or "").split())


def sehir_cevir(metin):
    """Liste hücresindeki şehir metnini normalleştirir."""
    metin = temizle(metin)
    if not metin:
        return None
    s = ortak.sehir_bul(metin)
    if s != "Türkiye Geneli":
        return s
    return ortak.tr_title(metin) if len(metin) <= 40 else "Türkiye Geneli"


def liste_oku(sayfa, ad, url):
    """Bir kategorinin tüm sayfalarını gezip {id: bilgi} döndürür."""
    sonuc = {}
    for no in range(1, MAX_SAYFA + 1):
        sayfa.goto(f"{url}?currentPage={no}", wait_until="domcontentloaded")
        try:
            sayfa.wait_for_selector(SATIR_SEC, timeout=20000)
        except Exception:  # noqa: BLE001
            break
        sayfa.wait_for_timeout(800)
        yeni = 0
        for r in sayfa.evaluate(JS_SATIRLAR):
            href = (r["href"] or "").split("?")[0].split("#")[0]
            m = ILAN_YOLU.match(href)
            if not m or m.group(1) in sonuc:
                continue
            c = [temizle(x) for x in r["cols"]]
            baslik = c[1] if len(c) > 1 and c[1] else temizle(r["title"])
            if len(baslik) < 5:
                continue
            sonuc[m.group(1)] = {
                "baslik": baslik,
                "kurum": ortak.tr_title(c[0]) if c and c[0] else None,
                "sehir": sehir_cevir(c[3]) if len(c) > 3 else None,
                "link": BASE + href,
                "tur": ad,
            }
            yeni += 1
        print(f"  {ad} sayfa {no}: {yeni} yeni satır")
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

        # İptal/düzeltme duyurularını ayıkla
        iptal = [i for i, o in toplanan.items() if "iptal" in ortak.tr_lower(o["baslik"])]
        for i in iptal:
            del toplanan[i]
        if iptal:
            print(f"{len(iptal)} iptal/düzeltme duyurusu atlandı.")

        if not toplanan:
            print("HATA: Hiç ilan bulunamadı (site yapısı değişmiş olabilir).")
            ortak.debug_kaydet(sayfa, "ilan_gov_bos")
            tarayici.close()
            sys.exit(1)

        print(f"Toplam {len(toplanan)} ilan bulundu; {len(mevcut)} tanesi kayıtlı.")

        yeni_kayitlar, guncellenecek, detay_sayac = [], [], 0
        for ilan_id, o in toplanan.items():
            akademik = o["tur"] == "Akademik Personel"
            if mevcut.get(ilan_id):  # detayı daha önce işlenmiş: yalnız liste alanları
                g = {
                    "kaynak_sistem": KAYNAK,
                    "orijinal_ilan_id": ilan_id,
                    "baslik": o["baslik"],
                    "kurum_adi": o["kurum"],
                    "ilan_turu": o["tur"],
                    "sehir": o["sehir"] or "Türkiye Geneli",
                    "basvuru_linki": o["link"],
                    "aktif_mi": True,
                    "son_gorulme": baslangic,
                }
                if akademik:
                    g["mezuniyet_sarti"] = None
                    g["kpss_turu"] = None
                guncellenecek.append(g)
                continue

            kayit = {
                "kaynak_sistem": KAYNAK,
                "orijinal_ilan_id": ilan_id,
                "baslik": o["baslik"],
                "kurum_adi": o["kurum"],
                "ilan_turu": o["tur"],
                "sehir": o["sehir"] or "Türkiye Geneli",
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
                        kayit["son_basvuru_tarihi"] = ortak.son_basvuru_bul(metin)
                        if not akademik:
                            kayit["mezuniyet_sarti"] = ortak.mezuniyet_bul(metin)
                            kayit["kpss_turu"] = ortak.kpss_bul(metin)
                        if not o["sehir"]:
                            kayit["sehir"] = ortak.sehir_bul(metin[:6000])
                        if not o["kurum"]:
                            kayit["kurum_adi"] = ortak.kurum_bul(ortak.satirlar(metin))
                        kayit["detay_islendi"] = True
                except Exception as e:  # noqa: BLE001
                    print(f"  Detay alınamadı ({ilan_id}): {e}")
            yeni_kayitlar.append(kayit)
            if len(yeni_kayitlar) % 25 == 0:
                print(f"  {len(yeni_kayitlar)} yeni ilan işlendi...")
        tarayici.close()

    if yeni_kayitlar:
        n = ortak.kayitlari_yaz(db, yeni_kayitlar, baslangic)
        print(f"{n} yeni ilan yazıldı.")
    if guncellenecek:
        n = ortak.liste_alanlarini_guncelle(db, guncellenecek)
        print(f"{n} mevcut ilanın kurum/şehir/başlık alanı güncellendi.")

    ortak.pasife_al(db, KAYNAK, baslangic, len(toplanan), MIN_ILAN_PASIF_ICIN)


if __name__ == "__main__":
    calistir()
