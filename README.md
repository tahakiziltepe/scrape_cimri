# Stok Fiyat Kontrol

Cimri üzerindeki bir ürün sayfasında, "Fiyatlar" bölümünde listelenen tüm teklifleri requests + BeautifulSoup ile çeker, fiyata göre küçükten büyüğe sıralar, konsola yazdırır ve belirli koşullar sağlanırsa Telegram mesajı gönderir.

## Özellikler
- Yalnızca `<section id="fiyatlar">` altında görünen teklifleri toplar.
- Her teklif için:
  - Site (merchant-logos görselinin alt yazısı)
  - Satıcı (`div.zp61l`)
  - Fiyat (`div.rTdMX`)
  - Mağaza linki ("Mağazaya Git")
- Fiyatları artan sırada listeler; Hepsiburada/Amazon satırlarını kalın ve ⭐ ile vurgular.
- Telegram mesajı gönderimi için 2 koşul:
  1. En ucuz fiyat 50.000 TL’nin altındaysa
  2. Site=Hepsiburada & Satıcı=Hepsiburada veya Site=Amazon & Satıcı=Amazon satırlarından herhangi birinin fiyatı 50.500 TL’nin altındaysa
- Telegram mesajının en sonunda kontrol edilen ürün linkini gösterir.

## Gereksinimler
- Python 3.10+
- `requirements.txt` içindeki paketler: requests, beautifulsoup4, lxml, python-dotenv, colorama (opsiyonel)

## Kurulum (Windows / cmd.exe)
1. Sanal ortam (önerilir):
   ```cmd
   python -m venv venv
   venv\Scripts\activate
   ```
2. Bağımlılıkları yükleyin:
   ```cmd
   pip install -r requirements.txt
   ```
3. .env dosyası oluşturun ve değerleri girin:
   ```env
   TELEGRAM_BOT_TOKEN=123456:ABCDEF...
   TELEGRAM_CHAT_ID=1234...
   ```

## Kullanım
- Varsayılan URL ile çalıştırma:
  ```cmd
  python scrape_cimri.py
  ```
- Farklı bir Cimri ürün URL’si ile:
  ```cmd
  python scrape_cimri.py "https://www.cimri.com/..."
  ```
- Chat ID’yi komut satırından geçmek (ENV yerine):
  ```cmd
  python scrape_cimri.py --chat=1234...
  ```

Notlar:
- Telegram gönderimi, yalnızca yukarıdaki koşullardan en az biri sağlanırsa yapılır. Aksi halde konsola bilgi yazar ve mesaj göndermez.
- Token, `.env` dosyasından `TELEGRAM_BOT_TOKEN` olarak okunur. Boşsa gönderim yapılmaz.
- Chat ID önceliği: `--chat` argümanı > `TELEGRAM_CHAT_ID` (.env) > Bot `getUpdates` ile keşif (son çare).
- Sayfa yapısı (özellikle CSS sınıf adları) değişirse seçiciler güncellenmelidir.

## Çalışma Mantığı (Kısaca)
- HTML `requests` ile çekilir ve BeautifulSoup (`lxml` parser) ile parse edilir.
- `section#fiyatlar` içinde her fiyat düğümü (`div.rTdMX`) için kart kökü bulunur. Aynı karttan site, satıcı ve mağazaya git linki alınır.
- Teklifler link veya (site|satıcı|fiyat) üçlüsüne göre basitçe tekilleştirilir.
- Fiyatlar sayıya çevrilip (51.299,00 TL → 51299.00) sıralanır.
- Konsola yazdırılır ve koşullar sağlanırsa Telegram’a HTML formatında mesaj gönderilir.

## Sık Karşılaşılan Sorular
- Türkçe ondalık ayracı vs. için fiyat dönüştürme: Nokta binlik, virgül ondalık kabul edilerek sayıya çevrilir.
- Konsolda kalın yazı: Windows’ta colorama ile, yoksa ANSI fallback kullanılır.

## Planlanan Geliştirmeler
- Sonuçların bir veritabanına yazılması (site, satıcı, fiyat_raw, fiyat_num, url, scraped_at).
- Zamanlayıcı ile periyodik çalıştırma, hata/yedekleme logları.

## Uyarı
- Bu proje yalnızca eğitim/deneme amaçlıdır. İlgili sitelerin kullanım şartlarına uyduğunuzdan emin olun.
