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
            timezone_id="Europe/Istanbul",
            ignore_https_errors=True
        )
        page = context.new_page()
        
        print("İŞKUR kamu işçi ilanları taranıyor...")
        unique_ilanlar = {}
        
        # İŞKUR kamu ilanları için olası tüm aktif URL rotaları
        target_urls = [
            "https://esube.iskur.gov.tr/Istihdam/KamuIlanKurumIsSorgu.aspx",
            "https://esube.iskur.gov.tr/Istihdam/KamuIlanIsSorgu.aspx",
            "https://esube.iskur.gov.tr/OzelIstihdam/KamuIlanIsSorgu.aspx",
            "https://esube.iskur.gov.tr/Istihdam/JobsSearch.aspx"
        ]
        
        working_url = None
        for url in target_urls:
            try:
                print(f"Deneniyor: {url}")
                response = page.goto(url, timeout=25000, wait_until="domcontentloaded")
                status = response.status if response else 0
                title = page.title().strip()
                print(f" -> Yanıt: HTTP {status} | Başlık: '{title}'")
                
                # Başarılı sayfa kontrolü (404/Bulunamadı sayfalarını atla)
                if status == 200 and "cannot be found" not in title.lower() and "bulunamadı" not in title.lower():
                    working_url = url
                    print(f"✓ Geçerli adres bulundu: {working_url}")
                    break
            except Exception as ex:
                print(f" -> Bağlantı hatası: {ex}")
                continue
        
        if not working_url:
            print("İŞKUR geçerli bir kamu ilan adresi yanıt vermedi.")
            browser.close()
            return

        try:
            page.wait_for_timeout(3000)
            
            # Form üzerindeki "Ara" butonunu bulup tetikle
            ara_btn = page.locator("input[type='submit'], input[value='Ara'], input[name*='btnAra'], button:has-text('Ara')").first
            if ara_btn.is_visible():
                print("Ara butonuna basılıyor...")
                ara_btn.click()
                page.wait_for_timeout(4000)
            
            # Tablodaki verileri çek
            satirlar = page.locator("table tr").all()
            print(f"Sayfada okunan tablo satırı sayısı: {len(satirlar)}")
            
            for satir in satirlar:
                try:
                    sutunlar = satir.locator("td").all()
                    if len(sutunlar) < 4:
                        continue
                    
                    metinler = [td.inner_text().strip() for td in sutunlar]
                    ilan_no = metinler[0]
                    
                    # Sadece sayısal İlan Numarası barındıran satırları al
                    if not ilan_no.isdigit():
                        continue
                        
                    kurum_adi = metinler[1]
                    meslek = metinler[2]
                    sehir = metinler[3] if len(metinler) > 3 else "Türkiye Geneli"
                    
                    link_elem = sutunlar[0].locator("a").first
                    href = link_elem.get_attribute("href") if link_elem.count() > 0 else ""
                    tam_link = href if href.startswith("http") else f"https://esube.iskur.gov.tr/Istihdam/{href}" if href else working_url

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