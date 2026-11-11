"""Botların ortak yardımcıları: Supabase bağlantısı, kayıt işlemleri ve
metinden bilgi çıkarma (şehir, tarih, KPSS, mezuniyet, kurum)."""

import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone

try:  # Yerelde .env okunur; GitHub Actions'ta paket/dosya olmasa da sorun çıkmaz
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

TABLO = "tum_kamu_ilanlari"
DEBUG_DIR = "debug"

ALANLAR = [
    "kaynak_sistem",
    "orijinal_ilan_id",
    "baslik",
    "kurum_adi",
    "ilan_turu",
    "sehir",
    "mezuniyet_sarti",
    "kpss_turu",
    "son_basvuru_tarihi",
    "basvuru_linki",
    "aktif_mi",
    "son_gorulme",
    "detay_islendi",
]


# --------------------------------------------------------------------------
# Supabase
# --------------------------------------------------------------------------
def supabase_istemcisi():
    """Ortam değişkenlerinden bağlanır. Eksik/yanlışsa açık bir hata ile çıkar."""
    from supabase import create_client

    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    url = re.sub(r"/rest/v1$", "", url)  # sık yapılan hata
    key = (os.environ.get("SUPABASE_KEY") or "").strip()

    if not url.startswith("https://") or not key:
        sys.exit(
            "HATA: SUPABASE_URL ve SUPABASE_KEY tanımlı değil.\n"
            "  Yerelde: .env dosyasına yazın.\n"
            "  GitHub'da: Settings > Secrets and variables > Actions"
        )
    if key.startswith("sb_publishable_") or key.startswith("eyJ") and "anon" in key[:200]:
        print(
            "UYARI: Publishable/anon key kullanıyorsunuz. RLS açıkken botlar "
            "yazamaz; 'sb_secret_...' anahtarını kullanın."
        )
    return create_client(url, key)


def simdi_iso():
    return datetime.now(timezone.utc).isoformat()


def normallestir(kayit, zaman):
    """Toplu upsert için tüm kayıtların aynı anahtarlara sahip olmasını sağlar."""
    k = {a: kayit.get(a) for a in ALANLAR}
    for alan, sinir in (("baslik", 480), ("kurum_adi", 250), ("sehir", 250),
                        ("mezuniyet_sarti", 120), ("kpss_turu", 120), ("ilan_turu", 80)):
        if isinstance(k.get(alan), str) and len(k[alan]) > sinir:
            k[alan] = k[alan][: sinir - 1].rstrip() + "…"
    if k["aktif_mi"] is None:
        k["aktif_mi"] = True
    if k["son_gorulme"] is None:
        k["son_gorulme"] = zaman
    if k["detay_islendi"] is None:
        k["detay_islendi"] = False
    return k


def mevcut_kayitlar(db, kaynak):
    """{orijinal_ilan_id: detay_islendi} sözlüğü döndürür."""
    sonuc, bas = {}, 0
    while True:
        yanit = (
            db.table(TABLO)
            .select("orijinal_ilan_id,detay_islendi")
            .eq("kaynak_sistem", kaynak)
            .range(bas, bas + 999)
            .execute()
        )
        for satir in yanit.data or []:
            sonuc[satir["orijinal_ilan_id"]] = bool(satir.get("detay_islendi"))
        if len(yanit.data or []) < 1000:
            break
        bas += 1000
    return sonuc


def kayitlari_yaz(db, kayitlar, zaman, parca=200):
    kayitlar = [normallestir(k, zaman) for k in kayitlar]
    for i in range(0, len(kayitlar), parca):
        db.table(TABLO).upsert(
            kayitlar[i : i + parca], on_conflict="kaynak_sistem,orijinal_ilan_id"
        ).execute()
    return len(kayitlar)


def gorulenleri_isaretle(db, kaynak, idler, zaman, parca=100):
    """Zaten kayıtlı olup bu taramada yine görülen ilanları 'canlı' işaretler
    (mevcut zengin verilerin üzerine yazmaz)."""
    idler = list(idler)
    for i in range(0, len(idler), parca):
        (
            db.table(TABLO)
            .update({"aktif_mi": True, "son_gorulme": zaman})
            .eq("kaynak_sistem", kaynak)
            .in_("orijinal_ilan_id", idler[i : i + parca])
            .execute()
        )


def pasife_al(db, kaynak, zaman, gorulen_sayisi, minimum):
    """Bu taramada görülmeyen ilanları pasife alır. Tarama yarım kaldıysa
    (çok az ilan geldiyse) hiçbir şeyi pasife ALMAZ."""
    if gorulen_sayisi < minimum:
        print(
            f"UYARI: Yalnızca {gorulen_sayisi} ilan görüldü (en az {minimum} bekleniyor); "
            "pasife alma atlandı."
        )
        return
    (
        db.table(TABLO)
        .update({"aktif_mi": False})
        .eq("kaynak_sistem", kaynak)
        .eq("aktif_mi", True)
        .lt("son_gorulme", zaman)
        .execute()
    )
    print("Görülmeyen eski ilanlar pasife alındı.")


def debug_kaydet(page, ad):
    """Hata anında ekran görüntüsü ve HTML kaydeder (Actions'ta artifact olur)."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        page.screenshot(path=f"{DEBUG_DIR}/{ad}.png", full_page=True)
        with open(f"{DEBUG_DIR}/{ad}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"Hata kayıtları '{DEBUG_DIR}/{ad}.png|html' olarak kaydedildi.")
    except Exception as e:  # noqa: BLE001
        print(f"Debug kaydı alınamadı: {e}")


# --------------------------------------------------------------------------
# Metin işleme
# --------------------------------------------------------------------------
def tr_lower(s):
    """Türkçe'ye uygun küçük harfe çevirme (İ->i, I->ı)."""
    return (s or "").replace("İ", "i").replace("I", "ı").lower()


def satirlar(metin):
    return [s.strip() for s in (metin or "").splitlines() if s.strip()]


_AYLAR = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}
_TARIH_SAYISAL = re.compile(r"(?<!\d)(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})(?!\d)")
_TARIH_YAZILI = re.compile(
    r"(?<!\d)(\d{1,2})\s+(" + "|".join(_AYLAR) + r")\s+(\d{4})(?!\d)"
)


def tum_tarihler(metin):
    """Metindeki tüm tarihleri (date nesnesi) döndürür."""
    t = tr_lower(metin)
    bulunanlar = []
    for g, a, y in _TARIH_SAYISAL.findall(t):
        bulunanlar.append((int(y), int(a), int(g)))
    for g, ay, y in _TARIH_YAZILI.findall(t):
        bulunanlar.append((int(y), _AYLAR[ay], int(g)))
    sonuc = []
    for y, a, g in bulunanlar:
        try:
            sonuc.append(date(y, a, g))
        except ValueError:
            continue
    return sonuc


def tarih_cevir(metin):
    """İlk tarihi 'YYYY-MM-DD' olarak döndürür; yoksa None."""
    tarihler = tum_tarihler(metin)
    return tarihler[0].isoformat() if tarihler else None


_BASVURU_ANAHTAR = re.compile(
    r"son\s+başvuru|başvuru\s+(?:süresi|tarihi|tarihleri)|"
    r"başvurular(?:ın)?[^.\n]{0,60}?(?:tarihine|tarihinde)\s+kadar"
)


def son_basvuru_bul(metin):
    """'Son başvuru' ifadesinin yakınındaki en geç tarihi bulur. Anahtar ifade
    yoksa tahmin yürütmez, None döner."""
    t = tr_lower(metin)
    bugun = date.today()
    adaylar = []
    for m in _BASVURU_ANAHTAR.finditer(t):
        pencere = t[m.start() : m.end() + 140]
        for d in tum_tarihler(pencere):
            if bugun.year - 1 <= d.year <= bugun.year + 2:
                adaylar.append(d)
    return max(adaylar).isoformat() if adaylar else None


_ILLER = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Aksaray", "Amasya", "Ankara",
    "Antalya", "Ardahan", "Artvin", "Aydın", "Balıkesir", "Bartın", "Batman",
    "Bayburt", "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur", "Bursa",
    "Çanakkale", "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Düzce", "Edirne",
    "Elazığ", "Erzincan", "Erzurum", "Eskişehir", "Gaziantep", "Giresun",
    "Gümüşhane", "Hakkari", "Hatay", "Iğdır", "Isparta", "İstanbul", "İzmir",
    "Kahramanmaraş", "Karabük", "Karaman", "Kars", "Kastamonu", "Kayseri",
    "Kırıkkale", "Kırklareli", "Kırşehir", "Kilis", "Kocaeli", "Konya", "Kütahya",
    "Malatya", "Manisa", "Mardin", "Mersin", "Muğla", "Muş", "Nevşehir", "Niğde",
    "Ordu", "Osmaniye", "Rize", "Sakarya", "Samsun", "Siirt", "Sinop", "Sivas",
    "Şanlıurfa", "Şırnak", "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Uşak",
    "Van", "Yalova", "Yozgat", "Zonguldak",
]
assert len(_ILLER) == 81

_HARF = "a-zçğıöşüâîû"
# "Ordu" (ordu) ve "Van" gündelik kelimelerle karıştığı için bağlam isteriz.
_OZEL_IL = {
    "ordu": r"(?<![" + _HARF + r"])ordu(?:\s+(?:ili|il|üniversitesi|valiliği|belediyesi|büyükşehir)|\s*[/)])",
    "van": r"(?<![" + _HARF + r"])van(?:\s+(?:ili|il|valiliği|belediyesi|büyükşehir|yüzüncü)|\s*[/)])",
}
_IL_DESENLERI = {}
for _il in _ILLER:
    _k = tr_lower(_il)
    _IL_DESENLERI[_il] = re.compile(
        _OZEL_IL.get(_k, r"(?<![" + _HARF + r"])" + re.escape(_k) + r"(?![" + _HARF + r"])")
    )


def sehir_bul(metin):
    """Metinde en çok geçen il(ler)i döndürür. Hiç yoksa ya da çok fazlaysa
    'Türkiye Geneli'."""
    t = tr_lower(metin)
    sayac = Counter()
    for il, desen in _IL_DESENLERI.items():
        n = len(desen.findall(t))
        if n:
            sayac[il] = n
    if not sayac:
        return "Türkiye Geneli"
    en_cok = max(sayac.values())
    liderler = [il for il, n in sayac.items() if n == en_cok]
    if len(liderler) > 3:
        return "Türkiye Geneli"
    return ", ".join(sorted(liderler))


def kpss_bul(metin):
    """KPSS puan türlerini döndürür (örn. 'P3, P93'). Hiç bahsedilmiyorsa None."""
    t = tr_lower(metin)
    if "kpss" not in t:
        return None
    if re.search(r"kpss[^.\n]{0,40}(?:aranmamaktadır|aranmaz|şartı yoktur|gerekmemektedir)", t):
        return "Gerekmiyor"
    turler = sorted(
        {int(n) for n in re.findall(r"(?<![a-zçğıöşü0-9])p\s?(\d{1,3})(?![0-9])", t) if 1 <= int(n) <= 123}
    )
    return ", ".join(f"P{n}" for n in turler) if turler else None


def mezuniyet_bul(metin):
    """Metinde geçen öğrenim düzeylerini döndürür (Lise, Önlisans, Lisans)."""
    t = tr_lower(metin)
    seviyeler = []
    if re.search(r"(?<![" + _HARF + r"])lise(?![" + _HARF + r"])|lise\s+mezun|ortaöğretim", t):
        seviyeler.append("Lise")
    if re.search(r"ön\s?lisans", t):
        seviyeler.append("Önlisans")
    kalan = re.sub(r"ön\s?lisans|yüksek\s?lisans", " ", t)
    if "lisans" in kalan:
        seviyeler.append("Lisans")
    return ", ".join(seviyeler) if seviyeler else None


_KURUM_ANAHTARLARI = (
    "üniversitesi", "bakanlığı", "başkanlığı", "müdürlüğü", "belediyesi",
    "valiliği", "komutanlığı", "rektörlüğü", "kurumu", "hastanesi",
    "başhekimliği", "dekanlığı", "başsavcılığı", "kaymakamlığı", "birliği",
    "başkanlığına", "müdürlüğüne",
)


def kurum_bul(satir_listesi):
    """Satırlar arasında kurum adına benzeyen ilk kısa satırı döndürür."""
    for s in satir_listesi:
        if 6 <= len(s) <= 120 and any(a in tr_lower(s) for a in _KURUM_ANAHTARLARI):
            return s
    return None
