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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        print("İŞKUR kamu işçi ilanları taranıyor...")
        unique_ilanlar = {}
        
        try:
            url = "https://esube.iskur.gov.tr/OzelIstihdam/KamuIlanIsSorgu.aspx"
            page.goto(url, timeout=60000, wait_until="networkidle")
            page.wait_for_timeout(3000)
            
            # ASP.NET "Ara" butonunu tetikle
            ara_btn = page.locator("input[value='Ara'], input#btnAra, input[name*='btnAra']").first
            if ara_btn.is_visible():
                ara_btn.click()
                page.wait_for_timeout(5000)
            
            # Tablo satırlarını esnek şekilde tara
            satirlar = page.locator("table[id*='KamuIlanlari'] tr, table tr").all()
            
            for satir in satirlar:
                try:
                    sutunlar = satir.locator("td").all()
                    if len(sutunlar) < 4:
                        continue
                    
                    metinler = [td.inner_text().strip() for td in sutunlar]
                    ilan_no = metinler[0]
                    
                    # Sadece sayısal İlan Numarası barındıran geçerli satırları al
                    if not ilan_no.isdigit():
                        continue
                        
                    kurum_adi = metinler[1]
                    meslek = metinler[2]
                    sehir = metinler[3] if len(metinler) > 3 else "Türkiye Geneli"
                    
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