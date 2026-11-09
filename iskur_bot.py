import os
from playwright.sync_api import sync_playwright
from supabase import Client, create_client

# Bilgisayarında çalışırken .env okur, GitHub sunucusunda ise hata vermeden geçer
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://qgdpkjkdlicqltagcsgq.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_APY9Yn4FsZL4IxGIR9ndzg_-1Xaz_-y")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def iskur_ilanlari_cek():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("İŞKUR kamu işçi ilanları taranıyor...")
        unique_ilanlar = {}
        
        try:
            # İŞKUR esube kamu ilanları arama sayfası
            url = "https://esube.iskur.gov.tr/OzelIstihdam/KamuIlanIsSorgu.aspx"
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            # İlan tablosundaki satırları tara
            satirlar = page.locator("table#dgKamuIlanlari tr").all()
            
            for satir in satirlar[1:]: # Başlık satırını atla
                try:
                    sutunlar = satir.locator("td").all()
                    if len(sutunlar) < 4:
                        continue
                    
                    ilan_no = sutunlar[0].inner_text().strip()
                    kurum_adi = sutunlar[1].inner_text().strip()
                    meslek = sutunlar[2].inner_text().strip()
                    sehir = sutunlar[3].inner_text().strip()
                    
                    link_elem = sutunlar[0].locator("a").first
                    href = link_elem.get_attribute("href") if link_elem.count() > 0 else ""
                    tam_link = href if href.startswith("http") else f"https://esube.iskur.gov.tr/OzelIstihdam/{href}" if href else url

                    if ilan_no and ilan_no not in unique_ilanlar:
                        unique_ilanlar[ilan_no] = {
                            "kaynak_sistem": "ISKUR",
                            "orijinal_ilan_id": f"iskur_{ilan_no}",
                            "baslik": meslek,
                            "kurum_adi": kurum_adi,
                            "ilan_turu": "İŞKUR İşçi",
                            "sehir": sehir if sehir else "Türkiye Geneli",
                            "basvuru_linki": tam_link
                        }
                except Exception as ex:
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