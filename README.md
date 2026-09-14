# CoWork Index

Çalışanların AI araçlarını nasıl kullandığını, içerik değil davranış
üzerinden ölçen kurumsal analiz platformu -- **prompt içeriğini hiç
okumadan/saklamadan**, yalnızca davranışsal meta-sinyalleri kullanarak bir
kullanım olgunluk skoru ve davranış arketipi üreten API + dashboard.

## Neden Bu Proje?

Şirketler çalışanlarına ChatGPT, Copilot, Claude, Cursor gibi AI araçlarını
hızla yayıyor, ama "bu araçlara yaptığımız yatırımın karşılığını alıyor
muyuz, kim gerçekten verimli kullanıyor, kim yüzeysel kopyala-yapıştır
yapıyor" sorusuna cevap verecek bir yöntemleri yok. Bunu ölçmenin en
doğrudan yolu -- prompt loglarını okumak -- hem ciddi bir gizlilik ihlali
hem de ölçeklenebilir değil.

CoWork Index bu soruyu, **prompt veya AI çıktısının tek bir karakterini bile
görmeden** cevaplamak için var: yalnızca kabul/red oranı, diyalog derinliği,
harcanan token, sonucun üretime mi gittiği yoksa terk mi edildiği gibi
davranışsal meta-sinyalleri toplayıp her çalışan için 0-100 arası bir
**kullanım olgunluk skoru** ve 5 davranış arketipinden birini üretir. Hedef
kitle İK/People Analytics ekipleri, mühendislik yöneticileri ve AI adoption'ı
takip eden herkes.

## Ne Sunuyor?

- **Kullanım Olgunluk Skoru**: 6 boyutta (kullanım yoğunluğu, onay/red
  dinamiği, diyalog derinliği, iletişim üslubu, sonuç takibi, eleştirel
  kullanım) ağırlıklı bir kompozit skor.
- **5 Davranış Arketipi**: Kopyala-Yapıştırcı, Diyalog Ortağı, Şüpheci, Emir
  Verici, Pasif Kullanıcı -- kurallar `config/archetype_rules.yaml`'da.
- **Şirket / Takım / Çalışan bazlı dashboard**: genel görünüm, takım
  karşılaştırma, çalışan detayı, arketip dağılımı, zaman içi trendler.
- **Maliyet & Verimlilik katmanı**: token/USD bazlı maliyet ve "verimli
  token oranı" -- hangi kullanımın gerçekten sonuç ürettiği, hangisinin
  israf olduğu.
- **Veri kalitesi denetimleri**: write-time doğrulama + periyodik audit.
- **Toplu veri girişi**: tek tıkla demo verisi veya Excel ile gerçek veri
  içe aktarma.
- **EN/TR dil desteği**: dashboard sağ üstten dil değiştirilebilir.

Skorlar bir batch job ile değil, event geldikçe (near-real-time) güncellenir
-- bu proje bir veri ambarı değil, bir **servistir**. Mimari kararların
gerekçesi (neden medalyon/batch değil de event-driven OLTP mimarisi
seçildiği dahil) için [docs/architecture.md](docs/architecture.md)'e bakın.

## Veri Nasıl Girer? (Dashboard > "Veri Yükleme")

Şirket kadrosu şimdilik sabit boyutlu: **50 çalışan** (`src/demo_data.py`
içindeki `FIXED_EMPLOYEE_COUNT`). "Veri Yükleme" sekmesi (dashboard'da en
sağdaki sekme) bu 50 çalışana yalnızca *kullanım verisi* (event) ekler --
yeni çalışan oluşturmaz. İki yoldan:

1. **Hızlı Demo Verisi** -- tek tıkla sentetik/test kullanım verisi üretir
   (seçilen ay sayısı kadar geçmiş, haftalık çözünürlükte). Sunum ve
   geliştirme amaçlıdır; `POST /ingestion/seed-demo-data` uç noktasını
   kullanır ve DB'ye doğrudan yazdığı için (HTTP round-trip olmadan) hızlıdır.
2. **Gerçek Veri İçe Aktarma (Excel)** -- "Şablon İndir" ile mevcut 50
   çalışanı referans sayfasında listeleyen, doldurulacak tek bir `events`
   sayfası içeren bir `.xlsx` şablonu indirilir, doldurulup geri yüklenir
   (`POST /ingestion/import-excel`). Bu, gerçek bir şirkette bu verinin
   genelde bir AI gateway/tarayıcı eklentisinin periyodik olarak dışa
   aktardığı davranışsal logdan geldiği senaryoyu temsil eder --
   **şablonda da hiçbir içerik/metin kolonu yoktur**. Çalışanlar yalnızca
   mevcut kadro içinden ada göre eşleştirilir (bulunamazsa satır hata
   olarak raporlanır, yeni çalışan oluşturulmaz).

## Maliyet & Verimlilik (Token/USD)

Her event'in girdi/çıktı token sayısı da tutulur -- bu içerik değil, bir
dosyanın boyutu gibi salt sayısal bir kullanım ölçümüdür. Maliyet, araç
başına `config/pricing.yaml`'daki USD fiyatlarından (1 milyon token başına)
hesaplanır ve **her zaman USD** olarak gösterilir. Dashboard'daki "Maliyet
& Verimlilik" sekmesi şirket/araç/çalışan bazlı toplam maliyeti ve
"verimli token oranı"nı (harcanan token'ların ne kadarının kabul edilen
etkileşimlere ait olduğu) gösterir. Bu, mevcut 6 boyutlu olgunluk skorunun
ağırlıklarını değiştirmez -- bilinçli olarak ayrı, tamamlayıcı bir analiz
katmanıdır (gerekçe: [docs/architecture.md](docs/architecture.md)).

**Kullanılan AI aracı**: `tools` tablosunda beş seçenek tanımlı --
ChatGPT, Copilot, Claude, Cursor, Antigravity (bkz. `src/demo_data.py::TOOLS`,
fiyatlandırma `config/pricing.yaml`). "Veri Yükleme" sekmesinde demo verisi
üretirken hangi aracın kullanılacağı seçilebilir; **şimdilik tüm örnek/demo
veri tek bir araçla (Copilot) üretiliyor** -- gerçek çeşitlilik gerçek
entegrasyonla gelecek. Bu bilgi, ilgili dashboard tablolarında (Takım
Karşılaştırma, Çalışan Bazlı Analiz, Maliyet & Verimlilik) en son sütun
olarak ("Kullanılan Yapay Zeka") gösterilir.

## Proje Yapısı

```
cowork-index/
├── docker-compose.yml         # SQL Server + API + Dashboard (3 servis)
├── Dockerfile                  # API ve dashboard için ortak imaj (ODBC Driver 18 dahil)
├── scripts/
│   ├── ensure_database.py       # Hedef veritabanı yoksa oluşturur
│   └── generate_sample_company_excel.py  # Doldurulmuş örnek "şirket verisi" üretir
├── alembic/                    # Şema migration'ları (kademeli)
├── src/
│   ├── main.py                  # FastAPI app + lifespan (scheduler)
│   ├── models.py                 # SQLAlchemy modelleri (3NF)
│   ├── schemas.py                 # Pydantic şemaları (gizlilik ilkesi burada zorlanır)
│   ├── db.py                     # engine/session
│   ├── utils.py                    # utcnow() -- naive-UTC zaman damgası kuralı
│   ├── demo_data.py                # Sentetik veri üretim mantığı (paylaşılan)
│   ├── ingestion_service.py         # Demo veri üretimi + Excel toplu içe aktarma
│   ├── routers/                   # events, scores, quality, ingestion, costs, reference-data
│   ├── scoring_service.py          # 6 boyut + kompozit skor + arketip
│   ├── cost_service.py             # Token/USD maliyet + verimlilik hesabı
│   ├── quality_checks.py           # Periyodik veri kalitesi denetimleri
│   ├── scheduler.py                # APScheduler job tanımları
│   └── event_simulator.py          # Sentetik veri üretici (HTTP tabanlı CLI)
├── config/
│   ├── weights.yaml                 # Skor ağırlıkları
│   ├── archetype_rules.yaml         # Arketip kuralları
│   └── pricing.yaml                 # Araç başına USD fiyatlandırma (1M token)
├── dashboard/app.py             # Streamlit (API tüketicisi)
├── docs/                        # architecture.md, data_dictionary.md
└── tests/                       # pytest
```

## API Uç Noktaları

| Metod & Yol | Açıklama |
|---|---|
| `POST /events` | Tek bir interaction event kaydeder, senkron skor günceller |
| `POST /events/batch` | Toplu event kaydı |
| `GET /scores/employees` | Skoru hesaplanmış tüm çalışanların güncel skorları |
| `GET /scores/employees/{id}` | Çalışanın güncel skoru ve arketipi |
| `POST /scores/employees/{id}/recompute` | Belirli bir dönem için manuel/geçmiş skor hesabı |
| `GET /scores/teams/{id}` | Takım roll-up |
| `GET /scores/company` | Şirket geneli özet |
| `GET /scores/trend?period=monthly` | Zaman içi skor trendi |
| `GET /quality/report` | Son kalite kontrol koşusu |
| `POST /quality/run` | Kalite kontrollerini manuel tetikler |
| `POST /ingestion/seed-demo-data` | Tek tıkla sentetik/test verisi üretir |
| `GET /ingestion/template` | Toplu içe aktarma için Excel şablonu indirir |
| `POST /ingestion/import-excel` | Doldurulmuş Excel'i toplu olarak sisteme işler |
| `GET /costs/company?window_days=` | Şirket geneli token/maliyet (USD) ve verimlilik özeti |
| `GET /costs/employees` | Tüm çalışanların maliyet/verimlilik özeti |
| `GET /costs/employees/{id}`, `/costs/teams/{id}` | Çalışan/takım bazlı maliyet özeti |
| `POST/GET /teams`, `/employees`, `/tools` | Referans veri CRUD |

## Temel İlke

**İçerik değil, davranış analiz edilir.** `interaction_events` tablosunda
hiçbir içerik/metin kolonu yoktur; API şeması (`extra="forbid"`) bu tür
alanları kod seviyesinde reddeder. Detaylar ve **veritabanı şemasının görsel
ER diyagramı** için [docs/data_dictionary.md](docs/data_dictionary.md).
