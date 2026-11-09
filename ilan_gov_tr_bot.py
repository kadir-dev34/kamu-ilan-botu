from playwright.sync_api import sync_playwright
from supabase import create_client, Client
import os
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def ilan_gov_tr_cek():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Basın İlan Kurumu (ilan.gov.tr) ana sayfasına gidiliyor...")
        kategoriler = []
        
        try:
            # 1. ADIM: Ana kategoriye gidip sol menüden güncel alt kategori linklerini topluyoruz
            print("Sol menüdeki güncel kategori linkleri keşfediliyor...")
            page.goto("https://www.ilan.gov.tr/ilan/kategori/8/kamu-akademik-personel", timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            # Sayfadaki kategori menü linklerini bul
            link_elementleri = page.locator('a[href*="/ilan/kategori/"]').all()
            
            for el in link_elementleri:
                href = el.get_attribute("href")
                metin = el.inner_text().strip()
                
                if not href: continue
                tam_url = href if href.startswith("http") else f"https://www.ilan.gov.tr{href}"
                
                # Menüdeki isimlere göre doğru URL'leri çek
                if "Kamu Personel Alım" in metin and not any(k['isim'] == 'Kamu Personeli' for k in kategoriler):
                    kategoriler.append({"isim": "Kamu Personeli", "url": tam_url})
                elif "Akademik Personel Alım" in metin and not any(k['isim'] == 'Akademik Personel' for k in kategoriler):
                    kategoriler.append({"isim": "Akademik Personel", "url": tam_url})
                elif "Askeri Personel Alım" in metin and not any(k['isim'] == 'Askeri Personel' for k in kategoriler):
                    kategoriler.append({"isim": "Askeri Personel", "url": tam_url})

            # Eğer menüden okuyamazsa bildiğimiz sağlam ID'leri (44 ve 73) yedek olarak ekle
            if not any(k['isim'] == 'Kamu Personeli' for k in kategoriler):
                kategoriler.append({"isim": "Kamu Personeli", "url": "https://www.ilan.gov.tr/ilan/kategori/44/kamu-personel-alim-ve-sinavlari"})
            if not any(k['isim'] == 'Akademik Personel' for k in kategoriler):
                kategoriler.append({"isim": "Akademik Personel", "url": "https://www.ilan.gov.tr/ilan/kategori/73/akademik-personel-alimlari"})

            print(f"Bulunan Kategoriler: {[k['isim'] for k in kategoriler]}")
            
            unique_ilanlar = {}
            
            # 2. ADIM: Keşfedilen doğru linkleri sayfa sayfa gez
            for kategori in kategoriler:
                print(f"\n[{kategori['isim']}] taranıyor... ({kategori['url']})")
                page.goto(kategori['url'], timeout=60000, wait_until="domcontentloaded")
                
                sayfa_no = 1
                
                while True:
                    print(f"  -> Sayfa {sayfa_no} okunuyor...")
                    page.wait_for_timeout(4000) 
                    
                    links = page.locator('a[href*="/ilan/"]').all()
                    
                    for link in links:
                        href = link.get_attribute("href")
                        if not href or "kategori" in href or "sayfa" in href or "currentPage" in href:
                            continue
                        
                        baslik = link.inner_text().strip()
                        if len(baslik) < 15:
                            continue
                        
                        tam_link = href if href.startswith("http") else f"https://www.ilan.gov.tr{href}"
                        
                        try:
                            ilan_id = tam_link.split("/ilan/")[1].split("/")[0]
                        except:
                            ilan_id = tam_link.split("/")[-1][:50]
                        
                        if ilan_id not in unique_ilanlar:
                            unique_ilanlar[ilan_id] = {
                                "kaynak_sistem": "ILAN_GOV_TR",
                                "orijinal_ilan_id": ilan_id,
                                "baslik": baslik.replace('\n', ' '),
                                "kurum_adi": "Basın İlan Kurumu",
                                "ilan_turu": kategori['isim'], 
                                "sehir": "Türkiye Geneli",
                                "basvuru_linki": tam_link
                            }
                    
                    # Sonraki sayfaya geç
                    try:
                        sonraki_buton = page.locator("a:has-text('Sonraki')").first
                        if sonraki_buton.is_visible():
                            sonraki_buton.click()
                            sayfa_no += 1
                            page.wait_for_load_state("domcontentloaded")
                        else:
                            print(f"  [{kategori['isim']}] için son sayfaya ulaşıldı.")
                            break
                    except Exception as e:
                        print(f"  [{kategori['isim']}] için sayfalama bitti.")
                        break

            ilanlar = list(unique_ilanlar.values())
            print(f"\n====== TARAMA BİTTİ ======")
            print(f"Toplam {len(ilanlar)} adet (Kamu, Akademik ve Askeri) ilan başarıyla çıkarıldı.")
            print("Supabase'e yazılıyor...")
            
            if ilanlar:
                supabase.table("tum_kamu_ilanlari").upsert(ilanlar, on_conflict="kaynak_sistem,orijinal_ilan_id").execute()
                print("Tüm ilanlar başarıyla veritabanına kaydedildi!")
            else:
                print("Hiç ilan bulunamadı.")
                
        except Exception as e:
            print(f"Hata oluştu: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    ilan_gov_tr_cek()