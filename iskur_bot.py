import os
import re
from playwright.sync_api import sync_playwright
from supabase import Client, create_client

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

raw_url = (os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_URL = raw_url if raw_url.startswith("http") else "https://qgdpkjkdlicqltagcsgq.supabase.co"

raw_key = (os.getenv("SUPABASE_KEY") or "").strip()
SUPABASE_KEY = raw_key or "sb_publishable_APY9Yn4FsZL4IxGIR9ndzg_-1Xaz_-y"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def iskur_ilanlari_cek():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            locale="tr-TR",
            timezone_id="Europe/Istanbul"
        )
        page = context.new_page()
        
        print("İŞKUR kamu işçi ilanları taranıyor...")
        unique_ilanlar = {}
        
        try:
            # 1. ADIM: Oturum başlatmak için ana sayfaya git
            print("İŞKUR ana sayfasına bağlanılıyor (Oturum başlatılıyor)...")
            page.goto("https://esube.iskur.gov.tr/", timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            
            # 2. ADIM: Açık İş İlanları arama sayfasına geç
            search_url = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx"
            print(f"Arama sayfasına gidiliyor: {search_url}")
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            
            # 3. ADIM: "Kamu" radyo butonunu seç
            try:
                kamu_elem = page.locator("input[value='Kamu'], input[id*='Kamu'], label:has-text('Kamu')").first
                if kamu_elem.is_visible():
                    print("Kamu ilan filtresi seçiliyor...")
                    kamu_elem.click()
                    page.wait_for_timeout(1500)
            except Exception as e:
                print(f"Kamu filtresi uyarısı: {e}")

            # 4. ADIM: "Ara" butonuna tıkla ve bekle
            ara_btn = page.locator("input[type='submit'][value='Ara'], input[id*='btnAra'], input[name*='btnAra'], button:has-text('Ara')").first
            if ara_btn.is_visible():
                print("Ara butonuna basılıyor ve sonuçlar bekleniyor...")
                ara_btn.click()
                page.wait_for_timeout(6000)
            else:
                print("Ara butonu doğrudan bulunamadı, Enter tuşu ile form tetikleniyor...")
                page.keyboard.press("Enter")
                page.wait_for_timeout(6000)

            # 5. ADIM: İlanları ayrıştır (Yöntem 1: Tablo ve Metin Taraması)
            satirlar = page.locator("table tr").all()
            print(f"Sayfada okunan toplam tablo satırı sayısı: {len(satirlar)}")
            
            for index, satir in enumerate(satirlar):
                try:
                    satir_metni = satir.inner_text().strip()
                    if not satir_metni or len(satir_metni) < 15:
                        continue
                    
                    # 11 haneli İlan No kontrolü (Örn: 00008983736)[cite: 5]
                    ilan_no_match = re.search(r'\b0\d{10}\b|\b\d{7,11}\b', satir_metni)
                    if not ilan_no_match:
                        continue
                        
                    ilan_no = ilan_no_match.group(0)
                    
                    sutunlar = satir.locator("td").all()
                    metinler = [td.inner_text().strip() for td in sutunlar if td.inner_text().strip()]
                    
                    baslik = metinler[0].split('\n')[0] if metinler else "Kamu İşçisi"
                    kurum_adi = metinler[1].split('\n')[0] if len(metinler) > 1 else "İŞKUR Kamu Kurumu"
                    sehir = metinler[2].split('\n')[0] if len(metinler) > 2 else "Türkiye Geneli"
                    
                    link_elem = satir.locator("a").first
                    href = link_elem.get_attribute("href") if link_elem.count() > 0 else ""
                    tam_link = href if href.startswith("http") else f"https://esube.iskur.gov.tr/Istihdam/{href}" if href else search_url

                    if ilan_no not in unique_ilanlar:
                        unique_ilanlar[ilan_no] = {
                            "kaynak_sistem": "ISKUR",
                            "orijinal_ilan_id": f"iskur_{ilan_no}",
                            "baslik": baslik,
                            "kurum_adi": kurum_adi,
                            "ilan_turu": "İŞKUR İşçi",
                            "sehir": sehir if sehir else "Türkiye Geneli",
                            "basvuru_linki": tam_link
                        }
                except Exception:
                    continue

            # Yöntem 2: Esnek İlan Kartı / Link Taraması (Tablodan çekilemeyen durumlar için yedek)
            if not unique_ilanlar:
                print("Yedek ilan kartı tarama yöntemine geçiliyor...")
                links = page.locator("a[href*='Ilan'], a[href*='uiID']").all()
                for link in links:
                    try:
                        href = link.get_attribute("href") or ""
                        text = link.inner_text().strip()
                        ilan_no_match = re.search(r'\b0\d{10}\b|\b\d{7,11}\b', href + " " + text)
                        if ilan_no_match and len(text) > 3:
                            ilan_no = ilan_no_match.group(0)
                            tam_link = href if href.startswith("http") else f"https://esube.iskur.gov.tr/Istihdam/{href}"
                            if ilan_no not in unique_ilanlar:
                                unique_ilanlar[ilan_no] = {
                                    "kaynak_sistem": "ISKUR",
                                    "orijinal_ilan_id": f"iskur_{ilan_no}",
                                    "baslik": text,
                                    "kurum_adi": "İŞKUR Kamu Kurumu",
                                    "ilan_turu": "İŞKUR İşçi",
                                    "sehir": "Türkiye Geneli",
                                    "basvuru_linki": tam_link
                                }
                    except Exception:
                        continue

            ilanlar = list(unique_ilanlar.values())
            print(f"Toplam {len(ilanlar)} adet İŞKUR ilanı çekildi. Supabase'e işleniyor...")
            
            if ilanlar:
                supabase.table("tum_kamu_ilanlari").upsert(ilanlar, on_conflict="kaynak_sistem,orijinal_ilan_id").execute()
                print("İŞKUR ilanları başarıyla veritabanına kaydedildi!")
            else:
                print("İŞKUR ilanı bulunamadı.")
                
        except Exception as e:
            print(f"İŞKUR bot hatası: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    iskur_ilanlari_cek()