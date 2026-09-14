# Mülakat Notları

Bu proje "Veri Yönetimi ve Uygulamaları Uzman Yardımcısı" pozisyonu için
istenen iki case study'den biri: **"Vibe Coding ile Ürün Geliştirme"**.
İkinci case (medalyon mimarisi, satış/satınalma/ERP, Power BI) ayrı ve
bilinçli olarak farklı bir mimariyle ele alınıyor -- gerekçesi
[architecture.md](architecture.md) içinde detaylı anlatıldı.

## Bu Projede Savunulacak Temel Kararlar

1. **Neden OLTP/normalize şema, neden yıldız şema değil?**
   Bu bir servis, bir veri ambarı değil. Yazma trafiği (event ingest) okuma
   trafiğinden en az onun kadar önemli. Yıldız şema/surrogate key/star
   schema optimizasyonları analitik okuma için tasarlanmıştır; burada asıl
   önceliğimiz transaction bütünlüğü ve düşük gecikmeli yazmadır.

2. **Neden skorlar batch değil, event-driven hesaplanıyor?**
   Ürün vaadi "AI kullanımınızın olgunluğunu görün" ise, bu skorun dünkü
   veriyle değil bugünkü davranışla güncel olması gerekir. `POST /events`
   sonrası senkron recompute + APScheduler güvenlik ağı bunu sağlıyor.

3. **Gizlilik ilkesi nasıl "gerçek" hale getirildi?**
   Sadece dokümantasyonda değil, kod seviyesinde: `InteractionEventCreate`
   şeması `extra="forbid"` ile `content`/`text`/`prompt` gibi alanları
   kabul etmiyor, veri modelinde böyle bir kolon hiç yok. Bu, "biz prompt
   saklamıyoruz" iddiasını mimari olarak doğrulanabilir kılıyor.

4. **Neden write-time validasyon + periyodik audit birlikte?**
   Write-time (Pydantic + CHECK constraint) kirli veriyi baştan reddeder;
   ama referans bütünlüğü, duplicate, freshness gibi zamana yayılan
   sorunlar tek bir yazma anında görülemez. İkisi tamamlayıcı.

5. **Dashboard neden DB'ye değil API'ye bağlanıyor?**
   Servis katmanının tek gerçek kaynak olmasını korumak için. Aksi halde
   iş kuralları (örn. "en güncel skor snapshot'ı hangisi") iki yerde
   (API ve dashboard) ayrı ayrı yazılır ve zamanla birbirinden sapar.

## "Veriyi Buraya Gerçekte Nasıl Sokarsınız?" Sorusuna Cevap

Dashboard'un ilk sekmesi ("Veri Yükleme") bu soruyu doğrudan canlı
gösterebilmek için var, iki yoldan:

1. **Demo/test verisi** (`POST /ingestion/seed-demo-data`) -- sunum ve
   geliştirme için, tek tıkla.
2. **Excel ile toplu içe aktarma** (`GET /ingestion/template`,
   `POST /ingestion/import-excel`) -- gerçek şirket senaryosunu temsil eder.
   Gerçek hayatta bu veri genelde bir kurumsal AI gateway'in (LiteLLM proxy,
   Azure API Management vb.) ya da tarayıcı eklentisinin periyodik olarak
   dışa aktardığı davranışsal log'dan gelir; Excel burada "zaten dışa
   aktarılmış veriyi toplu yükleme" adımını temsil ediyor -- **prompt/çıktı
   metni şablonda da yok**, sadece davranışsal meta-sinyaller var.

Mülakatta göstermek için kurgusal bir şirketin doldurulmuş örneği hazır:
`python -m scripts.generate_sample_company_excel` ("Anka Yazılım A.Ş.",
~24 çalışan, ~3 aylık gerçekçi event geçmişi).

**Dürüst olunması gereken nokta**: gerçek AI araçları (ChatGPT, Copilot)
bu davranışsal sinyalleri (directive_language_ratio, dialogue_turn_count
vb.) hazır vermez -- bunları ham etkileşimden çıkaracak bir "sinyal
çıkarma" katmanı (gateway/extension seviyesinde) ayrı bir mühendislik
problemidir ve bu projenin kapsamında değildir. Bu proje "sinyal geldiğinde
ne yaparım" sorusunu çözüyor.

## Mülakatta Canlı Gösterilebilecekler

- `uvicorn src.main:app --reload` + tarayıcıda `/docs` (Swagger) -- API-first
  yaklaşımın somut kanıtı, şemanın gizlilik ilkesini nasıl zorladığı canlı
  gösterilebilir (content alanıyla POST denemesi -> 422).
- `python -m src.event_simulator` çalışırken terminal çıktısı -- gerçek
  zamanlı event trafiğinin nasıl aktığı.
- Streamlit dashboard'da "Veri Kalitesi" sekmesinden manuel audit tetikleme.
- "Veri Yükleme" sekmesinden canlı olarak demo veri üretme ya da örnek
  Excel'i (Anka Yazılım A.Ş.) yükleyip sonuçların anında değişmesini gösterme.
- `alembic history` ile şema evriminin adım adım nasıl ilerlediği.

## Bilinen Sınırlamalar (Sorulursa Dürüstçe Cevap)

- Skor formülleri (ağırlıklar, eşikler) demo amaçlı makul varsayımlardır;
  gerçek bir üründe bu ağırlıklar A/B testi ve HR geri bildirimiyle
  kalibre edilirdi.
- Senkron recompute, çok yüksek event hacminde (binlerce event/saniye)
  ölçeklenmez; o noktada mesaj kuyruğu (Kafka/SQS) + ayrı bir consumer
  servisine geçmek gerekirdi -- bu, ürün olgunlaştıkça atılacak bir sonraki
  adım olarak bilinçli şekilde kapsam dışı bırakıldı.
- `interaction_events` tablosu zamanla büyüdükçe (yıllar içinde) partition
  stratejisi (örn. `occurred_at` üzerinden aylık partition) gerekebilir;
  bu prototipte eklenmedi.
- `config/pricing.yaml`'daki USD fiyatları gösterge niteliğindedir (kamuya
  açık liste fiyatlarına yakın); gerçek bir şirket bunu kendi sözleşme
  fiyatlarıyla güncellerdi. Gerçek AI araçları token sayısını her zaman API
  yanıtında vermez -- bu proje "token sayısı geldiğinde maliyeti nasıl
  hesaplarım" sorusunu çözüyor, token sayımının kendisi (tıpkı davranışsal
  sinyal çıkarma gibi) gateway/entegrasyon katmanının sorumluluğunda.
- **Gerçek bir hata, gerçek veriyle test edilirken bulundu**: `VARCHAR`
  kolonları Türkçe `ş`/`ğ`/`ı`/`İ` karakterlerini sessizce kaybediyordu
  ("Mühendisliği" -> "Mühendisligi"). Bu, "neden gerçek veriyle (sadece
  İngilizce test fixture'larıyla değil) test etmek önemli" sorusuna somut
  bir örnek olarak anlatılabilir -- düzeltme: `Unicode`/`UnicodeText`
  (bkz. [architecture.md](architecture.md)).
