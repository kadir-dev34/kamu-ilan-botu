import os
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
            response = page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            status = response.status if response else 0
            title = page.title().strip()
            print(f" -> Yanıt: HTTP {status} | Başlık: '{title}'")
            
            page.wait_for_timeout(2000)
            
            # 3. ADIM: "Kamu" radyo butonunu seç (varsa)
            try:
                kamu_elem = page.locator("label:has-text('Kamu'), input[value='Kamu'], input[id*='Kamu']").first
                if kamu_elem.is_visible():
                    print("Kamu ilan filtresi seçiliyor...")
                    kamu_elem.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

            # 4. ADIM: "Ara" butonuna bas ve ASP.NET PostBack yüklemesini bekle
            ara_btn = page.locator("input[type='submit'][value='Ara'], input#btnAra, input[name*='btnAra'], button:has-text('Ara')").first
            if ara_btn.is_visible():
                print("Ara butonuna basılıyor ve ilan tablosu bekleniyor...")
                ara_btn.click()
                # ASP.NET ağ trafiğinin ve tablo re-render işleminin bitmesini bekle
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    page.wait_for_timeout(5000)
            else:
                print("Ara butonu bulunamadı, mevcut sayfa taranıyor...")

            # 5. ADIM: İlan tablosundaki tüm satırları tara
            satirlar = page.locator("table tr").all()
            print(f"Sayfada okunan toplam tablo satırı sayısı: {len(satirlar)}")
            
            for satir in satirlar:
                try:
                    sutunlar = satir.locator("td").all()
                    if len(sutunlar) < 3:
                        continue
                    
                    metinler = [td.inner_text().strip() for td in sutunlar]
                    
                    # Satırdaki ilan no veya başlık bilgilerini yakala
                    ilan_no = metinler[0]
                    
                    # Başlık satırlarını veya boş hücreleri atla
                    if not ilan_no or "İlan" in ilan_no or "No" in ilan_no:
                        continue
                        
                    kurum_adi = metinler[1] if len(metinler) > 1 else "İŞKUR Kamu Kurumu"
                    meslek = metinler[2] if len(metinler) > 2 else "Kamu İşçisi"
                    sehir = metinler[3] if len(metinler) > 3 else "Türkiye Geneli"
                    
                    link_elem = satir.locator("a").first
                    href = link_elem.get_attribute("href") if link_elem.count() > 0 else ""
                    tam_link = href if href.startswith("http") else f"https://esube.iskur.gov.tr/Istihdam/{href}" if href else search_url

                    key_id = ilan_no if ilan_no.isdigit() else f"iskur_{len(unique_ilanlar)+1}"

                    if key_id not in unique_ilanlar:
                        unique_ilanlar[key_id] = {
                            "kaynak_sistem": "ISKUR",
                            "orijinal_ilan_id": f"iskur_{key_id}",
                            "baslik": meslek if meslek else kurum_adi,
                            "kurum_adi": kurum_adi,
                            "ilan_turu": "İŞKUR İşçi",
                            "sehir": sehir if sehir else "Türkiye Geneli",
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