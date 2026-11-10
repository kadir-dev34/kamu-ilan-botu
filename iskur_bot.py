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
            page.wait_for_timeout(3000)
            
            # 3. ADIM: "Kamu" radyo butonunu seç ve PostBack işleminin bitmesini bekle
            try:
                kamu_elem = page.locator("input[value='Kamu'], input[value='2'], input[id*='rblIsyeriTuru_1'], input[id*='Kamu']").first
                if not kamu_elem.is_visible():
                    kamu_elem = page.locator("label:has-text('Kamu')").first

                if kamu_elem.is_visible():
                    print("Kamu ilan filtresi seçiliyor...")
                    kamu_elem.click()
                    page.wait_for_timeout(3000) # ASP.NET PostBack beklemesi
            except Exception as e:
                print(f"Kamu filtresi uyarısı: {e}")

            # 4. ADIM: "Ara" butonunu esnek seçicilerle bul ve tıkla
            print("Ara butonu taranıyor...")
            selectors = [
                "input[value='Ara']",
                "input[id*='btnAra']",
                "input[name*='btnAra']",
                "button:has-text('Ara')",
                "a:has-text('Ara')",
                "input[type='submit']"
            ]

            ara_clicked = False
            for sel in selectors:
                btn = page.locator(sel).first
                if btn.is_visible():
                    print(f"Ara butonu bulundu ({sel}), tıklanıyor...")
                    btn.click()
                    ara_clicked = True
                    break

            if ara_clicked:
                print("Sonuçların yüklenmesi bekleniyor...")
                page.wait_for_timeout(6000)
            else:
                print("Ara butonu bulunamadı, Enter tuşu ile form tetikleniyor...")
                page.keyboard.press("Enter")
                page.wait_for_timeout(6000)

            # 5. ADIM: Tablodaki ilan kartlarını tara
            satirlar = page.locator("table tr").all()
            print(f"Sayfada okunan toplam tablo satırı sayısı: {len(satirlar)}")
            
            for index, satir in enumerate(satirlar):
                try:
                    satir_metni = satir.inner_text().strip()
                    if not satir_metni or len(satir_metni) < 15:
                        continue
                    
                    # 11 haneli İlan Numarasını yakala (Örn: 00008983736)
                    ilan_no_match = re.search(r'\b0\d{10}\b|\b\d{7,11}\b', satir_metni)
                    if not ilan_no_match:
                        continue
                        
                    ilan_no = ilan_no_match.group(0)
                    satir_satirlari = [line.strip() for line in satir_metni.split('\n') if line.strip()]
                    
                    baslik = satir_satirlari[0] if satir_satirlari else "Kamu İşçisi"
                    kurum_adi = satir_satirlari[1] if len(satir_satirlari) > 1 else "İŞKUR Kamu Kurumu"
                    
                    sehir = "Türkiye Geneli"
                    for line in satir_satirlari:
                        if "Çalışma Yeri:" in line or "İl Geneli" in line:
                            sehir = line.replace("Çalışma Yeri:", "").strip()
                            break
                    
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
                            "sehir": sehir,
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