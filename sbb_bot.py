from playwright.sync_api import sync_playwright
from supabase import create_client, Client
import os
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def sbb_ilanlarini_cek():
    with sync_playwright() as p:
        # TR Lokasyonlu Proxy Ayarı
        proxy_settings = {
            "server": "http://TURKISH_PROXY_IP:PORT",
        }

        browser = p.chromium.launch(
            headless=True,
            proxy=proxy_settings
        )
        page = browser.new_page()
        
        print("Türkiye Proxy üzerinden SBB İlanları sayfasına gidiliyor...")
        try:
            page.goto("https://kamuilan.sbb.gov.tr/", timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            
            ilan_linkleri = page.locator('a').all()
            benzersiz_ilanlar = {}
            
            for link in ilan_linkleri:
                href = link.get_attribute("href")
                if not href or len(href) < 10: continue
                
                baslik = link.inner_text().strip()
                if len(baslik) < 8: continue 
                
                if "kamuilan.sbb.gov.tr/ilan/" in href or href.startswith("/ilan/"):
                    tam_link = href if href.startswith("http") else f"https://kamuilan.sbb.gov.tr{href}"
                    ilan_id = tam_link.split("/")[-1].split("?")[0][:50] 
                    
                    if ilan_id not in benzersiz_ilanlar:
                        benzersiz_ilanlar[ilan_id] = {
                            "kaynak_sistem": "SBB",
                            "orijinal_ilan_id": ilan_id,
                            "baslik": baslik.replace('\n', ' '),
                            "kurum_adi": "SBB İlanı",
                            "ilan_turu": "Kamu Personeli",
                            "sehir": "Türkiye Geneli",
                            "basvuru_linki": tam_link
                        }

            ilanlar_listesi = list(benzersiz_ilanlar.values())
            print(f"Toplam {len(ilanlar_listesi)} SBB ilanı bulundu. Supabase'e yazılıyor...")
            
            if ilanlar_listesi:
                supabase.table("tum_kamu_ilanlari").upsert(ilanlar_listesi, on_conflict="kaynak_sistem,orijinal_ilan_id").execute()
                print("SBB ilanları başarıyla kaydedildi!")
            else:
                print("0 ilan bulundu.")
                
        except Exception as e:
            print(f"SBB Hata: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    sbb_ilanlarini_cek()