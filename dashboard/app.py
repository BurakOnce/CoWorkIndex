"""CoWork Index - Streamlit Dashboard.

Bu dashboard veritabanına doğrudan bağlanmaz; tüm veriyi FastAPI servisinden
`httpx` ile çeker. Bu, mimari tutarlılığı korur: dashboard da API'nin bir
diğer istemcisidir, ayrıcalıklı bir arka kapı değildir.

Dil desteği: tüm kullanıcıya görünen metinler `STRINGS` sözlüğünde
("en"/"tr") tutulur ve sayfanın sağ üstündeki seçiciyle değiştirilir.
Varsayılan dil İngilizce'dir.
"""

import os
from datetime import date, datetime, timedelta, timezone

import httpx
import pandas as pd
import plotly.express as px
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="CoWork Index", layout="wide")


@st.cache_data(ttl=30)
def api_get(path: str, params: dict | None = None):
    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
        resp = client.get(path, params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


def api_post(path: str, json: dict | None = None, params: dict | None = None):
    with httpx.Client(base_url=API_BASE_URL, timeout=60.0) as client:
        resp = client.post(path, json=json, params=params)
        resp.raise_for_status()
        return resp.json()


@st.cache_data(ttl=300)
def api_get_bytes(path: str) -> bytes | None:
    try:
        with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
            resp = client.get(path)
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError:
        return None


# ---------------------------------------------------------------------------
# i18n: dil seçici (sağ üst, Deploy butonunun solunda, küçültülmüş) + çeviri sözlüğü
# ---------------------------------------------------------------------------
LANG_OPTIONS = {"English": "en", "Türkçe": "tr"}

st.markdown(
    """
    <style>
    .element-container:has(.lang-marker) {
        display: none;
    }
    .element-container:has(.lang-marker) + div.element-container {
        position: fixed !important;
        top: 0.7rem;
        right: 8rem;
        z-index: 1000000;
        width: 6rem !important;
        transition: right 0.15s ease;
    }
    /* Streamlit'in "Running..." göstergesi Deploy'un hemen soluna açılıp
       kutumuzla çakışabiliyor -- gösterge görünürken kutuyu daha sola kaydır. */
    body:has([data-testid="stStatusWidget"]) .element-container:has(.lang-marker) + div.element-container {
        right: 22rem;
    }
    .element-container:has(.lang-marker) + div.element-container [style*="width"] {
        width: 100% !important;
    }
    .element-container:has(.lang-marker) + div.element-container div[data-baseweb="select"] > div {
        min-height: 1.9rem;
        font-size: 0.75rem;
        padding-top: 1px;
        padding-bottom: 1px;
    }
    </style>
    <div class="lang-marker"></div>
    """,
    unsafe_allow_html=True,
)
_lang_label = st.selectbox(
    "Language / Dil",
    list(LANG_OPTIONS.keys()),
    index=0,
    label_visibility="collapsed",
    key="lang_selector",
)
LANG = LANG_OPTIONS[_lang_label]


def S(key: str, **kwargs) -> str:
    """Seçili dildeki metni döndürür; kwargs verilirse `.format()` uygular."""
    template = STRINGS[LANG].get(key, STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


STRINGS = {
    "en": {
        "app_caption": (
            "An enterprise analytics platform that measures how employees use "
            "AI tools -- based on behavior, not content."
        ),
        "tab_company": "Company Overview",
        "tab_teams": "Team Comparison",
        "tab_employees": "Employee Analysis",
        "tab_archetypes": "Archetype Distribution",
        "tab_trends": "Time Trends",
        "tab_cost": "Cost & Efficiency",
        "tab_quality": "Data Quality",
        "tab_methodology": "Methodology & Data Dictionary",
        "tab_ingestion": "Data Ingestion",
        "tab_live": "Live: Claude",
        "project_filter_label": "Project",
        "project_all": "All projects",
        "trend_no_project_note": "Time trends are computed from stored score snapshots and are not filtered by project.",
        # Live connector feed
        "live_intro": (
            "Real interactions streaming in from **Claude Code** through the connector hook. "
            "Every prompt/response pair becomes one interaction event: deterministic signals "
            "(tokens, turn index, sentence stats) are measured locally; judgment signals "
            "(accept/reject, disagreement, outcome, task type, tone) are classified by Claude "
            "when an API key is configured, otherwise by rule-based heuristics."
        ),
        "live_no_data": (
            "No connector data yet. Install the hook (`python -m connectors.claude_code.install_hook`) "
            "or import history (`python -m connectors.claude_code.backfill`)."
        ),
        "live_metric_events": "Interactions",
        "live_metric_sessions": "Sessions",
        "live_metric_last": "Last Interaction",
        "live_metric_classifier": "Classifier",
        "live_capture_on": "Content capture: ON (full-access mode)",
        "live_capture_off": "Content capture: OFF (behavior only)",
        "live_limit_label": "Rows",
        "live_employee_label": "Employee",
        "live_all_employees": "All",
        "live_refresh": "Refresh",
        "col_time": "Time",
        "col_turn": "Turn",
        "col_task": "Task",
        "col_action": "Action",
        "col_disagreement": "Disagreement",
        "col_outcome": "Outcome",
        "col_check": "Verified",
        "col_tokens": "Tokens",
        "col_cost": "Cost (USD)",
        "col_project": "Project",
        "col_classifier": "Classifier",
        "live_detail_header": "Interaction detail",
        "live_select_label": "Select an interaction",
        "live_prompt": "User prompt",
        "live_response": "Assistant response",
        "live_feedback": "User's next prompt (feedback used for classification)",
        "live_tools": "Tools used",
        "live_signals": "Extracted signals (heuristic vs. Claude)",
        "live_no_content": "Content not captured for this interaction (capture disabled).",
        "live_what_header": "What can be extracted from a Claude interaction?",
        "live_what_markdown": """
| Signal family | Examples | How |
|---|---|---|
| **Content** (optional layer) | prompt text, response text, next prompt | captured verbatim when `CAPTURE_CONTENT=true` |
| **Volume & cost** | input/output tokens, cache reads, cost in USD, model used | from Claude Code's own usage records |
| **Dialogue dynamics** | turn index in session, interruptions, session length | transcript structure |
| **Approval** | accepted / edited / rejected, tool permission denials | next prompt + tool results |
| **Tone** | directive (imperative) ratio, politeness markers, exclamation density, sentence length | text statistics (TR + EN) |
| **Critical usage** | asked to verify/test, ran tests, questioned correctness | keywords + tool calls |
| **Outcome** | files edited & kept, committed/pushed, exploration only, abandoned | tool calls (Edit/Write/Bash git) |
| **Task type** | code / writing / analysis / other | edited file types + prompt intent |
| **Context** | project folder, git branch, timestamps, duration | transcript metadata |

Everything above *can* be captured. The product decides what to keep: with content capture off, only the behavioral rows survive.
""",
        # Company overview
        "date_range_label": "Date Range",
        "date_range_help": "Default: last 30 days. Pick a different range to look at the past.",
        "warn_no_company_data": (
            "No company-wide score data for this date range yet. Use the "
            "'Data Ingestion' tab to generate demo data or import real data via Excel."
        ),
        "metric_employee_count": "Employee Count",
        "metric_avg_composite": "Average Composite Score",
        "metric_period_start": "Period Start",
        "metric_period_end": "Period End",
        "subheader_dimension_avg": "Average by Dimension",
        "axis_score": "Score",
        "axis_dimension": "Dimension",
        # Teams
        "warn_no_team_data": "No team data yet.",
        "col_team": "Team",
        "col_employee_count": "Employee Count",
        "col_avg_composite": "Average Composite Score",
        "col_ai_used": "AI Used",
        "info_no_team_scores": "Scores have not been computed for teams yet.",
        # Employees
        "warn_no_employee_scores": "No employee scores have been computed yet.",
        "col_employee": "Employee",
        "col_composite": "Composite Score",
        "col_archetype": "Archetype",
        "subheader_all_employees": "All Employees",
        "filter_team_label": "Filter by team",
        "filter_archetype_label": "Filter by archetype",
        "subheader_employee_detail": "Employee Detail",
        "select_employee_label": "Employee to inspect",
        "metric_composite": "Composite Score",
        "metric_archetype": "Archetype",
        "metric_team": "Team",
        "caption_period_computed": "Period: {start} — {end} · Last computed: {computed}",
        # Archetypes
        "warn_no_archetype_data": "No archetype distribution data yet.",
        # Trends
        "radio_period_label": "Period",
        "period_monthly": "Monthly",
        "period_weekly": "Weekly",
        "axis_period_end": "Period End",
        "axis_avg_composite": "Average Composite Score",
        "col_start": "Start",
        "col_end": "End",
        "warn_no_trend_data": "Not enough historical score data yet for a trend.",
        # Cost & efficiency
        "caption_tokens_intro": (
            "Token counts are also a behavioral usage signal (not content -- "
            "a purely numeric measurement, like a file size). Cost is always "
            "computed in **USD** (pricing: `config/pricing.yaml`)."
        ),
        "select_window_label": "Period",
        "window_30": "Last 30 days",
        "window_90": "Last 90 days",
        "window_all": "All time",
        "warn_no_cost_data": "No cost data yet.",
        "metric_total_tokens": "Total Tokens",
        "metric_total_cost": "Total Cost",
        "metric_avg_cost_per_event": "Average Cost per Event",
        "metric_efficient_ratio": "Efficient Token Ratio",
        "caption_efficient_ratio_explain": (
            "Efficient token ratio: the share of spent tokens that belong to "
            "accepted interactions -- a low ratio means tokens were spent on "
            "rejected/abandoned attempts, i.e. unreasonable/inefficient usage."
        ),
        "subheader_cost_by_tool": "Cost by Tool",
        "col_tool": "Tool",
        "col_input_tokens": "Input Tokens",
        "col_output_tokens": "Output Tokens",
        "col_cost_usd": "Cost (USD)",
        "subheader_cost_by_employee": "Cost by Employee",
        "col_total_tokens": "Total Tokens",
        "col_efficient_ratio_pct": "Efficient Token Ratio (%)",
        "info_no_employee_cost": "No employee-level cost data yet.",
        # Quality
        "button_run_quality": "Run Quality Checks Now",
        "success_quality_triggered": "Quality checks triggered.",
        "metric_overall_status": "Overall Status",
        "col_check": "Check",
        "col_status": "Status",
        "col_affected_rows": "Affected Rows",
        "col_details": "Details",
        "col_run_at": "Run At",
        "info_no_quality_run": "No quality check run yet. Trigger one with the button above.",
        # Methodology
        "methodology_markdown": """
### Core Principle: Behavior, Not Content

This system never sees, transmits, or stores the text of prompts or AI
outputs. The `interaction_events` table has no content/text field; the API
schema rejects such fields (`content`, `text`, `prompt`, `response`, ...)
at the code level.

### 6 Score Dimensions

| Dimension | Weight | What it measures |
|---|---|---|
| Usage Intensity & Diversity | 15% | Event volume, diversity of tools/tasks used |
| Approval/Rejection Dynamics | 15% | Balance of accept/reject/edit (extremes penalized, healthy balance rewarded) |
| Dialogue/Negotiation Behavior | 20% | Average dialogue turns, mutual persuasion balance |
| Communication Tone | 15% | Politeness markers, directive-language ratio, exclamation density |
| Outcome Tracking | 20% | Share of work reaching production vs. abandoned |
| Critical Usage Index | 15% | Critical-check ratio, healthy disagreement ratio |

### 5 Behavior Archetypes

- **Copy-Paster**: High acceptance rate, shallow dialogue, low critical checking.
- **Dialogue Partner**: Deep, multi-turn dialogue; balanced persuasion; high production rate.
- **Skeptic**: High rejection/disagreement rate, high critical checking.
- **Commander**: High directive-language ratio, low politeness markers.
- **Passive User**: Very low usage volume and dialogue depth.

### How Are Scores Updated?

Scores are not updated by a batch job -- they refresh near-real-time as
events arrive: after every `POST /events`, the affected employee's
trailing 30-day window is recomputed immediately. A background scheduler
(APScheduler) also periodically recomputes everything and runs data
quality checks as a safety net.

### Cost & Efficiency (Complementary Layer)

Every interaction also records input/output token counts (not content --
a purely numeric usage measurement). These are converted to cost using the
per-tool USD prices in `config/pricing.yaml`. **This does not change the
weights of the 6-dimension composite score above** -- by design, cost and
efficiency are presented as a separate, complementary analysis layer. The
"efficient token ratio" shows what share of spent tokens went to accepted
(i.e. genuinely useful) interactions.
""",
        # Ingestion
        "subheader_quick_demo": "Quick Demo Data",
        "caption_quick_demo": (
            "Adds synthetic usage data (events) to the fixed 50-person roster -- "
            "does not create new employees, only generates history for the "
            "period you choose. Intended for demos and development."
        ),
        "slider_months_label": "How many months of history to generate?",
        "select_ai_tool_label": "AI Used",
        "select_ai_tool_help": "For now, all demo data is generated through a single tool.",
        "button_generate_demo": "Generate Demo Data",
        "spinner_generating": "Generating synthetic data, this may take a few seconds...",
        "success_demo_generated": (
            "Added {events} new usage events for {employees} employees. "
            "Quality status: {status}"
        ),
        "error_generation_failed": "Generation failed: {error}",
        "subheader_excel_import": "Real Data Import (Excel)",
        "caption_excel_import": (
            "The roster is fixed -- this only adds usage data to existing "
            "employees, it does not create new ones. In a real company this "
            "data typically comes from an AI gateway/extension exporting "
            "behavioral logs periodically. Download the template, fill in the "
            "'events' sheet (choosing employee names from the 'Employees "
            "(reference)' sheet), then upload it. **No prompt/output text is "
            "present in any column and none will be accepted.**"
        ),
        "button_download_template": "Download Template (.xlsx)",
        "file_uploader_label": "Choose the filled-in Excel file",
        "button_import": "Import",
        "spinner_importing": "Processing Excel file...",
        "success_import": "Events: {accepted} accepted, {rejected} rejected.",
        "warning_import_errors": "Some rows had issues:",
        "col_error": "Error",
        "error_import_failed": "Import failed: {error}",
    },
    "tr": {
        "app_caption": (
            "Çalışanların AI araçlarını nasıl kullandığını, içerik değil "
            "davranış üzerinden ölçen kurumsal analiz platformu."
        ),
        "tab_company": "Şirket Genel Görünüm",
        "tab_teams": "Takım Karşılaştırma",
        "tab_employees": "Çalışan Bazlı Analiz",
        "tab_archetypes": "Arketip Dağılımı",
        "tab_trends": "Zaman Trendleri",
        "tab_cost": "Maliyet & Verimlilik",
        "tab_quality": "Veri Kalitesi",
        "tab_methodology": "Metodoloji & Veri Sözlüğü",
        "tab_ingestion": "Veri Yükleme",
        "tab_live": "Canlı: Claude",
        "project_filter_label": "Proje",
        "project_all": "Tüm projeler",
        "trend_no_project_note": "Zaman trendleri saklanan skor snapshot'larından hesaplanır; proje filtresi uygulanmaz.",
        "live_intro": (
            "**Claude Code**'dan bağlayıcı hook'u üzerinden canlı akan gerçek etkileşimler. "
            "Her prompt/cevap çifti bir etkileşim event'i olur: deterministik sinyaller "
            "(token, tur sırası, cümle istatistikleri) yerelde ölçülür; yorum gerektiren "
            "sinyaller (kabul/red, itiraz, sonuç, görev tipi, üslup) API anahtarı varsa "
            "Claude tarafından, yoksa kural tabanlı heuristikle sınıflandırılır."
        ),
        "live_no_data": (
            "Henüz bağlayıcı verisi yok. Hook'u kurun (`python -m connectors.claude_code.install_hook`) "
            "ya da geçmişi içe aktarın (`python -m connectors.claude_code.backfill`)."
        ),
        "live_metric_events": "Etkileşim",
        "live_metric_sessions": "Oturum",
        "live_metric_last": "Son Etkileşim",
        "live_metric_classifier": "Sınıflandırıcı",
        "live_capture_on": "İçerik yakalama: AÇIK (tam erişim modu)",
        "live_capture_off": "İçerik yakalama: KAPALI (yalnızca davranış)",
        "live_limit_label": "Satır",
        "live_employee_label": "Çalışan",
        "live_all_employees": "Tümü",
        "live_refresh": "Yenile",
        "col_time": "Zaman",
        "col_turn": "Tur",
        "col_task": "Görev",
        "col_action": "Aksiyon",
        "col_disagreement": "İtiraz",
        "col_outcome": "Sonuç",
        "col_check": "Doğrulama",
        "col_tokens": "Token",
        "col_cost": "Maliyet (USD)",
        "col_project": "Proje",
        "col_classifier": "Sınıflandırıcı",
        "live_detail_header": "Etkileşim detayı",
        "live_select_label": "Bir etkileşim seçin",
        "live_prompt": "Kullanıcı promptu",
        "live_response": "Asistan cevabı",
        "live_feedback": "Kullanıcının sonraki promptu (sınıflandırmada geri bildirim olarak kullanıldı)",
        "live_tools": "Kullanılan araçlar",
        "live_signals": "Çıkarılan sinyaller (heuristik vs. Claude)",
        "live_no_content": "Bu etkileşim için içerik yakalanmadı (yakalama kapalı).",
        "live_what_header": "Bir Claude etkileşiminden neler çıkarılabilir?",
        "live_what_markdown": """
| Sinyal ailesi | Örnekler | Nasıl |
|---|---|---|
| **İçerik** (opsiyonel katman) | prompt metni, cevap metni, sonraki prompt | `CAPTURE_CONTENT=true` iken birebir yakalanır |
| **Hacim & maliyet** | girdi/çıktı token, cache okuma, USD maliyet, kullanılan model | Claude Code'un kendi kullanım kayıtlarından |
| **Diyalog dinamiği** | oturumdaki tur sırası, kesintiler, oturum uzunluğu | transcript yapısı |
| **Onay** | kabul / düzenleme / red, araç izni reddi | sonraki prompt + araç sonuçları |
| **Üslup** | emir kipi oranı, nezaket işaretleri, ünlem yoğunluğu, cümle uzunluğu | metin istatistikleri (TR + EN) |
| **Eleştirel kullanım** | doğrulama/test istedi mi, test koştu mu, doğruluğu sorguladı mı | anahtar kelimeler + araç çağrıları |
| **Sonuç** | dosya düzenlendi ve kaldı, commit/push, salt keşif, terk | araç çağrıları (Edit/Write/Bash git) |
| **Görev tipi** | kod / yazı / analiz / diğer | düzenlenen dosya tipleri + prompt niyeti |
| **Bağlam** | proje klasörü, git dalı, zaman damgaları, süre | transcript meta verisi |

Yukarıdakilerin hepsi *yakalanabilir*. Neyin tutulacağına ürün karar verir: içerik yakalama kapalıyken yalnızca davranışsal satırlar kalır.
""",
        "date_range_label": "Tarih Aralığı",
        "date_range_help": "Varsayılan: son 1 ay. Farklı bir aralık seçerek geçmişe bakabilirsiniz.",
        "warn_no_company_data": (
            "Bu tarih aralığında şirket genelinde skor verisi yok. 'Veri "
            "Yükleme' sekmesinden test verisi oluşturabilir ya da gerçek "
            "veriyi Excel ile içe aktarabilirsiniz."
        ),
        "metric_employee_count": "Çalışan Sayısı",
        "metric_avg_composite": "Ortalama Kompozit Skor",
        "metric_period_start": "Dönem Başlangıcı",
        "metric_period_end": "Dönem Sonu",
        "subheader_dimension_avg": "Boyut Bazlı Ortalamalar",
        "axis_score": "Skor",
        "axis_dimension": "Boyut",
        "warn_no_team_data": "Henüz takım verisi yok.",
        "col_team": "Takım",
        "col_employee_count": "Çalışan Sayısı",
        "col_avg_composite": "Ortalama Kompozit Skor",
        "col_ai_used": "Kullanılan Yapay Zeka",
        "info_no_team_scores": "Takımlar için henüz skor hesaplanmamış.",
        "warn_no_employee_scores": "Henüz hiçbir çalışan için skor hesaplanmamış.",
        "col_employee": "Çalışan",
        "col_composite": "Kompozit Skor",
        "col_archetype": "Arketip",
        "subheader_all_employees": "Tüm Çalışanlar",
        "filter_team_label": "Takıma göre filtrele",
        "filter_archetype_label": "Arketipe göre filtrele",
        "subheader_employee_detail": "Çalışan Detayı",
        "select_employee_label": "İncelenecek çalışan",
        "metric_composite": "Kompozit Skor",
        "metric_archetype": "Arketip",
        "metric_team": "Takım",
        "caption_period_computed": "Dönem: {start} — {end} · Son hesaplama: {computed}",
        "warn_no_archetype_data": "Arketip dağılımı için henüz veri yok.",
        "radio_period_label": "Periyot",
        "period_monthly": "Aylık",
        "period_weekly": "Haftalık",
        "axis_period_end": "Dönem Sonu",
        "axis_avg_composite": "Ortalama Kompozit Skor",
        "col_start": "Başlangıç",
        "col_end": "Bitiş",
        "warn_no_trend_data": "Trend verisi için henüz yeterli geçmiş skor yok.",
        "caption_tokens_intro": (
            "Token sayıları da davranışsal bir kullanım meta-sinyalidir "
            "(içerik değil, bir dosyanın boyutu gibi salt sayısal bir ölçüm). "
            "Maliyet her zaman **USD** olarak hesaplanır (fiyatlandırma: "
            "`config/pricing.yaml`)."
        ),
        "select_window_label": "Dönem",
        "window_30": "Son 30 gün",
        "window_90": "Son 90 gün",
        "window_all": "Tüm zamanlar",
        "warn_no_cost_data": "Henüz maliyet verisi yok.",
        "metric_total_tokens": "Toplam Token",
        "metric_total_cost": "Toplam Maliyet",
        "metric_avg_cost_per_event": "Event Başı Ortalama Maliyet",
        "metric_efficient_ratio": "Verimli Token Oranı",
        "caption_efficient_ratio_explain": (
            "Verimli token oranı: harcanan token'ların ne kadarının kabul "
            "edilen (accepted) etkileşimlere ait olduğunu gösterir -- düşük "
            "oran, reddedilen/terk edilen denemelere token harcandığı, yani "
            "mantıksız/verimsiz kullanım anlamına gelir."
        ),
        "subheader_cost_by_tool": "Araca Göre Maliyet Dağılımı",
        "col_tool": "Araç",
        "col_input_tokens": "Girdi Token",
        "col_output_tokens": "Çıktı Token",
        "col_cost_usd": "Maliyet (USD)",
        "subheader_cost_by_employee": "Çalışan Bazlı Maliyet",
        "col_total_tokens": "Toplam Token",
        "col_efficient_ratio_pct": "Verimli Token Oranı (%)",
        "info_no_employee_cost": "Çalışan bazlı maliyet verisi yok.",
        "button_run_quality": "Kalite Kontrollerini Şimdi Çalıştır",
        "success_quality_triggered": "Kalite kontrolleri tetiklendi.",
        "metric_overall_status": "Genel Durum",
        "col_check": "Kontrol",
        "col_status": "Durum",
        "col_affected_rows": "Etkilenen Satır",
        "col_details": "Detaylar",
        "col_run_at": "Koşu Tarihi",
        "info_no_quality_run": "Henüz bir kalite kontrolü koşusu yok. Yukarıdaki butonla tetikleyebilirsiniz.",
        "methodology_markdown": """
### Temel İlke: İçerik Değil, Davranış

Bu sistem hiçbir zaman prompt veya AI çıktısının metnini görmez, göndermez
ya da saklamaz. `interaction_events` tablosunda içerik/metin alanı yoktur;
API şeması bu tür alanları (`content`, `text`, `prompt`, `response`, ...)
kod seviyesinde reddeder.

### 6 Skor Boyutu

| Boyut | Ağırlık | Ne ölçer? |
|---|---|---|
| Kullanım Yoğunluğu & Çeşitliliği | %15 | Event hacmi, kullanılan araç/görev çeşitliliği |
| Onay/Red Dinamiği | %15 | Kabul/red/düzenleme dengesi (aşırı uçlar değil, sağlıklı denge ödüllendirilir) |
| Diyalog/Müzakere Davranışı | %20 | Ortalama diyalog turu, karşılıklı ikna dengesi |
| İletişim Üslubu | %15 | Nezaket işaretleri, emir dili oranı, ünlem yoğunluğu |
| Sonuç Takibi | %20 | Üretime giden iş oranı, terk edilen iş oranı |
| Eleştirel Kullanım Endeksi | %15 | Kritik kontrol oranı, sağlıklı itiraz oranı |

### 5 Davranış Arketipi

- **Kopyala-Yapıştırcı**: Yüksek kabul oranı, düşük diyalog derinliği, düşük kritik kontrol.
- **Diyalog Ortağı**: Derin, çok turlu diyalog; dengeli ikna; yüksek üretim oranı.
- **Şüpheci**: Yüksek red/itiraz oranı, yüksek kritik kontrol.
- **Emir Verici**: Yüksek emir dili oranı, düşük nezaket işareti.
- **Pasif Kullanıcı**: Çok düşük kullanım hacmi ve diyalog derinliği.

### Skorlar Nasıl Güncellenir?

Skorlar toplu (batch) bir job ile değil, event geldikçe neredeyse gerçek
zamanlı olarak güncellenir: her `POST /events` sonrası ilgili çalışanın son
30 günlük penceresi yeniden hesaplanır. Ayrıca arka planda çalışan bir
zamanlayıcı (APScheduler), güvenlik ağı olarak periyodik tam yeniden
hesaplama ve veri kalitesi denetimi yapar.

### Maliyet & Verimlilik (Tamamlayıcı Katman)

Her etkileşimin girdi/çıktı token sayısı da (içerik değil, salt sayısal bir
kullanım ölçümü olarak) tutulur. Bu, `config/pricing.yaml`'daki araç başına
USD fiyatlarıyla maliyete çevrilir. **Bu, yukarıdaki 6 boyutlu kompozit
skorun ağırlıklarını değiştirmez** -- bilinçli bir tasarım kararı olarak
maliyet/verimlilik ayrı, tamamlayıcı bir analiz katmanı olarak sunulur.
"Verimli token oranı", harcanan token'ların ne kadarının kabul edilen
(mantıklı sonuç üreten) etkileşimlere ait olduğunu gösterir.
""",
        "subheader_quick_demo": "Hızlı Demo Verisi",
        "caption_quick_demo": (
            "Sabit 50 kişilik kadroya sentetik kullanım verisi (event) ekler -- "
            "yeni çalışan oluşturmaz, yalnızca seçtiğiniz süre kadar geçmiş "
            "event üretir. Sunum ve geliştirme amaçlıdır."
        ),
        "slider_months_label": "Kaç aylık geçmiş üretilsin?",
        "select_ai_tool_label": "Kullanılan Yapay Zeka",
        "select_ai_tool_help": "Şimdilik tüm demo verisi tek bir araç üzerinden üretiliyor.",
        "button_generate_demo": "Test Verisi Oluştur",
        "spinner_generating": "Sentetik veri üretiliyor, bu birkaç saniye sürebilir...",
        "success_demo_generated": (
            "{employees} çalışan için {events} yeni kullanım verisi eklendi. "
            "Kalite durumu: {status}"
        ),
        "error_generation_failed": "Üretim başarısız: {error}",
        "subheader_excel_import": "Gerçek Veri İçe Aktarma (Excel)",
        "caption_excel_import": (
            "Kadro sabittir -- bu, yalnızca mevcut çalışanlara kullanım verisi "
            "ekler, yeni çalışan oluşturmaz. Gerçek bir şirkette bu veri "
            "genelde bir AI gateway/extension'ın periyodik olarak dışa "
            "aktardığı davranışsal log'dan gelir. Şablonu indirip 'events' "
            "sayfasını (çalışan adlarını 'Çalışanlar (referans)' sayfasından "
            "seçerek) doldurun, sonra geri yükleyin. **Prompt/çıktı metni "
            "hiçbir kolonda yoktur ve kabul edilmez.**"
        ),
        "button_download_template": "Şablon İndir (.xlsx)",
        "file_uploader_label": "Doldurulmuş Excel dosyasını seçin",
        "button_import": "İçe Aktar",
        "spinner_importing": "Excel dosyası işleniyor...",
        "success_import": "Event: {accepted} kabul, {rejected} red.",
        "warning_import_errors": "Bazı satırlarda sorun bulundu:",
        "col_error": "Hata",
        "error_import_failed": "İçe aktarma başarısız: {error}",
    },
}

ARCHETYPE_LABELS = {
    "en": {
        "kopyala_yapistirci": "Copy-Paster",
        "diyalog_ortagi": "Dialogue Partner",
        "supheci": "Skeptic",
        "emir_verici": "Commander",
        "pasif_kullanici": "Passive User",
    },
    "tr": {
        "kopyala_yapistirci": "Kopyala-Yapıştırcı",
        "diyalog_ortagi": "Diyalog Ortağı",
        "supheci": "Şüpheci",
        "emir_verici": "Emir Verici",
        "pasif_kullanici": "Pasif Kullanıcı",
    },
}

DIMENSION_LABELS = {
    "en": {
        "usage_score": "Usage Intensity & Diversity",
        "approval_score": "Approval/Rejection Dynamics",
        "dialogue_score": "Dialogue/Negotiation",
        "tone_score": "Communication Tone",
        "outcome_score": "Outcome Tracking",
        "critical_thinking_score": "Critical Thinking",
    },
    "tr": {
        "usage_score": "Kullanım Yoğunluğu & Çeşitliliği",
        "approval_score": "Onay/Red Dinamiği",
        "dialogue_score": "Diyalog/Müzakere",
        "tone_score": "İletişim Üslubu",
        "outcome_score": "Sonuç Takibi",
        "critical_thinking_score": "Eleştirel Kullanım",
    },
}

STATUS_LABELS = {
    "en": {"passed": "✅ Passed", "warning": "⚠️ Warning", "failed": "❌ Failed"},
    "tr": {"passed": "✅ Geçti", "warning": "⚠️ Uyarı", "failed": "❌ Başarısız"},
}

CHECK_NAME_LABELS = {
    "en": {
        "referential_integrity": "Referential Integrity",
        "duplicate_events": "Duplicate Events",
        "freshness": "Freshness",
        "daily_volume_anomaly": "Daily Volume Anomaly",
    },
    "tr": {
        "referential_integrity": "Referans Bütünlüğü",
        "duplicate_events": "Tekrar Eden Event",
        "freshness": "Tazelik",
        "daily_volume_anomaly": "Günlük Hacim Anomalisi",
    },
}


def _load_display_tz():
    """Gösterim saat dilimi. Veritabanı ve API her zaman UTC'dir; yalnızca
    ekranda çevrilir. Varsayılan Europe/Istanbul (UTC+3, yaz saati yok);
    tzdata bulunamazsa sabit +3 kullanılır."""
    name = os.environ.get("DISPLAY_TIMEZONE", "Europe/Istanbul")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 -- tzdata yoksa
        return timezone(timedelta(hours=3))


DISPLAY_TZ = _load_display_tz()


def to_local(value):
    """API'den gelen naive-UTC zaman damgasını gösterim saat dilimine çevirir.
    Saf tarihler (saat bileşeni olmayan) olduğu gibi döner."""
    ts = pd.to_datetime(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(DISPLAY_TZ)


def fmt_date(value) -> str:
    """Formats dates without time/seconds, as DD/MM/YYYY (local time zone)."""
    if not value:
        return "-"
    try:
        text = str(value)
        if "T" in text or " " in text.strip():
            return to_local(value).strftime("%d/%m/%Y")
        return pd.to_datetime(value).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(value)


def fmt_datetime(value, fmt: str = "%d/%m/%Y %H:%M") -> str:
    """Formats a UTC timestamp as local date + time."""
    if not value:
        return "-"
    try:
        return to_local(value).strftime(fmt)
    except (ValueError, TypeError):
        return str(value)


AI_TOOL_OPTIONS = ["ChatGPT", "Copilot", "Claude", "Cursor", "Antigravity"]
DEFAULT_AI_TOOL = "Copilot"


def dominant_tool(by_tool: list[dict] | None) -> str:
    """Returns the most-used tool (by event count) from a cost summary's
    `by_tool` list -- used for the "AI Used" column in tables."""
    if not by_tool:
        return "-"
    return max(by_tool, key=lambda t: t["event_count"])["tool_name"]


st.title("CoWork Index")
st.caption(S("app_caption"))

# ---------------------------------------------------------------------------
# Global proje filtresi: bağlayıcı verisindeki projelerden biri seçilirse skor,
# maliyet ve canlı akış uçlarına ?project= geçilir (skorlar o projenin
# event'leri üzerinden anlık hesaplanır).
# ---------------------------------------------------------------------------
_projects = api_get("/connectors/projects") or []
_project_options = {S("project_all"): None}
_project_options.update({f"{p['project']} ({p['event_count']})": p["project"] for p in _projects})
_pf1, _pf2 = st.columns([1, 3])
with _pf1:
    _project_choice = st.selectbox(S("project_filter_label"), list(_project_options.keys()), key="project_filter")
PROJECT = _project_options[_project_choice]


def P(params: dict | None = None) -> dict:
    """API parametrelerine seçili proje filtresini ekler."""
    merged = dict(params or {})
    if PROJECT:
        merged["project"] = PROJECT
    return merged


# Veri Yükleme sekmesi (demo veri + Excel) gerçek Claude entegrasyonu
# geldiğinden beri varsayılan olarak gizli; kod duruyor, SHOW_INGESTION_TAB=true
# ile geri açılır.
SHOW_INGESTION_TAB = os.environ.get("SHOW_INGESTION_TAB", "false").lower() in ("1", "true", "yes")

_TAB_KEYS = [
    "tab_company",
    "tab_live",
    "tab_teams",
    "tab_employees",
    "tab_archetypes",
    "tab_trends",
    "tab_cost",
    "tab_quality",
    "tab_methodology",
]
if SHOW_INGESTION_TAB:
    _TAB_KEYS.append("tab_ingestion")
_tab_objs = dict(zip(_TAB_KEYS, st.tabs([S(k) for k in _TAB_KEYS])))
# Mevcut sekme kodu tabs[0..8] indeksleriyle yazıldı; "Live: Claude" sekmesi
# görsel olarak ikinci sırada dursun ama eski indeksler değişmesin.
tabs = [_tab_objs[k] for k in _TAB_KEYS if k != "tab_live"]
live_tab = _tab_objs["tab_live"]
ingestion_tab = _tab_objs.get("tab_ingestion")

# ---------------------------------------------------------------------------
# 0. Company Overview
# ---------------------------------------------------------------------------
with tabs[0]:
    default_end = datetime.now(DISPLAY_TZ).date()
    default_start = default_end - timedelta(days=30)
    date_range = st.date_input(
        S("date_range_label"),
        value=(default_start, default_end),
        max_value=default_end,
        format="DD/MM/YYYY",
        help=S("date_range_help"),
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        range_start, range_end = date_range
    else:
        range_start, range_end = default_start, default_end

    company = api_get(
        "/scores/company",
        params=P({"period_start": range_start.isoformat(), "period_end": range_end.isoformat()}),
    )
    if company is None:
        st.warning(S("warn_no_company_data"))
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric(S("metric_employee_count"), company["employee_count"])
        col2.metric(S("metric_avg_composite"), f"{company['avg_composite_score']:.1f}")
        col3.metric(S("metric_period_start"), fmt_date(company["period_start"]))
        col4.metric(S("metric_period_end"), fmt_date(company["period_end"]))

        st.subheader(S("subheader_dimension_avg"))
        dims = {
            DIMENSION_LABELS[LANG]["usage_score"]: company["avg_usage_score"],
            DIMENSION_LABELS[LANG]["approval_score"]: company["avg_approval_score"],
            DIMENSION_LABELS[LANG]["dialogue_score"]: company["avg_dialogue_score"],
            DIMENSION_LABELS[LANG]["tone_score"]: company["avg_tone_score"],
            DIMENSION_LABELS[LANG]["outcome_score"]: company["avg_outcome_score"],
            DIMENSION_LABELS[LANG]["critical_thinking_score"]: company["avg_critical_thinking_score"],
        }
        dims_df = pd.DataFrame({S("axis_dimension"): list(dims.keys()), S("axis_score"): list(dims.values())})
        fig = px.bar(dims_df, x=S("axis_score"), y=S("axis_dimension"), orientation="h", range_x=[0, 100])
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# 1. Team Comparison
# ---------------------------------------------------------------------------
with tabs[1]:
    teams = api_get("/teams") or []
    if not teams:
        st.warning(S("warn_no_team_data"))
    else:
        rows = []
        for team in teams:
            score = api_get(f"/scores/teams/{team['id']}", params=P())
            cost = api_get(f"/costs/teams/{team['id']}", params=P())
            if score:
                rows.append(
                    {
                        S("col_team"): score["team_name"],
                        S("col_employee_count"): score["employee_count"],
                        S("col_avg_composite"): score["avg_composite_score"],
                        S("col_ai_used"): dominant_tool(cost["by_tool"] if cost else None),
                    }
                )
        if rows:
            team_df = pd.DataFrame(rows).sort_values(S("col_avg_composite"), ascending=False)
            st.dataframe(team_df, use_container_width=True, hide_index=True)
            fig = px.bar(team_df, x=S("col_team"), y=S("col_avg_composite"), range_y=[0, 100])
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(S("info_no_team_scores"))

# ---------------------------------------------------------------------------
# 3. Archetype Distribution
# ---------------------------------------------------------------------------
with tabs[3]:
    company = api_get("/scores/company", params=P())
    if company and company.get("archetype_distribution"):
        dist = company["archetype_distribution"]
        dist_df = pd.DataFrame(
            {
                S("col_archetype"): [ARCHETYPE_LABELS[LANG].get(k, k) for k in dist.keys()],
                S("col_employee_count"): list(dist.values()),
            }
        )
        fig = px.pie(dist_df, names=S("col_archetype"), values=S("col_employee_count"), hole=0.4)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(dist_df, use_container_width=True, hide_index=True)
    else:
        st.warning(S("warn_no_archetype_data"))

# ---------------------------------------------------------------------------
# 4. Time Trends
# ---------------------------------------------------------------------------
with tabs[4]:
    period_options = [S("period_monthly"), S("period_weekly")]
    period_label = st.radio(S("radio_period_label"), period_options, horizontal=True, index=0)
    period = "monthly" if period_label == period_options[0] else "weekly"
    if PROJECT:
        st.caption(S("trend_no_project_note"))
    trend = api_get("/scores/trend", params={"period": period})
    if trend:
        trend_df = pd.DataFrame(trend)
        trend_df["period_end_dt"] = pd.to_datetime(trend_df["period_end"])
        fig = px.line(
            trend_df,
            x="period_end_dt",
            y="avg_composite_score",
            markers=True,
            range_y=[0, 100],
            labels={"period_end_dt": S("axis_period_end"), "avg_composite_score": S("axis_avg_composite")},
        )
        fig.update_xaxes(tickformat="%d/%m/%Y")
        st.plotly_chart(fig, use_container_width=True)

        display_df = trend_df.drop(columns=["period_end_dt"]).copy()
        display_df["period_start"] = display_df["period_start"].apply(fmt_date)
        display_df["period_end"] = display_df["period_end"].apply(fmt_date)
        display_df = display_df.rename(
            columns={
                "period_start": S("col_start"),
                "period_end": S("col_end"),
                "avg_composite_score": S("col_avg_composite"),
                "employee_count": S("col_employee_count"),
            }
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.warning(S("warn_no_trend_data"))

# ---------------------------------------------------------------------------
# 5. Cost & Efficiency
# ---------------------------------------------------------------------------
with tabs[5]:
    st.caption(S("caption_tokens_intro"))
    window_options = [S("window_30"), S("window_90"), S("window_all")]
    window_label = st.selectbox(S("select_window_label"), window_options, index=2)
    window_days = {window_options[0]: 30, window_options[1]: 90, window_options[2]: None}[window_label]
    cost_params = P({"window_days": window_days} if window_days else {})

    company_cost = api_get("/costs/company", params=cost_params)
    if not company_cost or company_cost["event_count"] == 0:
        st.warning(S("warn_no_cost_data"))
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric(S("metric_total_tokens"), f"{company_cost['total_tokens']:,}")
        col2.metric(S("metric_total_cost"), f"${company_cost['total_cost_usd']:,.2f}")
        col3.metric(S("metric_avg_cost_per_event"), f"${company_cost['avg_cost_per_event_usd']:.4f}")
        col4.metric(S("metric_efficient_ratio"), f"%{company_cost['efficient_token_ratio'] * 100:.1f}")
        st.caption(S("caption_efficient_ratio_explain"))

        st.subheader(S("subheader_cost_by_tool"))
        tool_cost_df = pd.DataFrame(company_cost["by_tool"])
        if not tool_cost_df.empty:
            tool_cost_df = tool_cost_df.rename(
                columns={
                    "tool_name": S("col_tool"),
                    "event_count": S("col_employee_count"),
                    "input_tokens": S("col_input_tokens"),
                    "output_tokens": S("col_output_tokens"),
                    "cost_usd": S("col_cost_usd"),
                }
            )
            fig = px.bar(tool_cost_df, x=S("col_tool"), y=S("col_cost_usd"))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(tool_cost_df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader(S("subheader_cost_by_employee"))
        employee_costs = api_get("/costs/employees", params=cost_params) or []
        teams = api_get("/teams") or []
        team_name_by_id = {t["id"]: t["name"] for t in teams}
        employees = api_get("/employees") or []
        team_by_employee_id = {e["id"]: team_name_by_id.get(e["team_id"], "-") for e in employees}

        if employee_costs:
            emp_cost_df = pd.DataFrame(
                [
                    {
                        S("col_employee"): e["scope_name"],
                        S("col_team"): team_by_employee_id.get(e["scope_id"], "-"),
                        S("col_employee_count"): e["event_count"],
                        S("col_total_tokens"): e["total_tokens"],
                        S("col_cost_usd"): e["total_cost_usd"],
                        S("col_efficient_ratio_pct"): round(e["efficient_token_ratio"] * 100, 1),
                        S("col_ai_used"): dominant_tool(e["by_tool"]),
                    }
                    for e in employee_costs
                ]
            )
            st.dataframe(
                emp_cost_df.sort_values(S("col_cost_usd"), ascending=False),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info(S("info_no_employee_cost"))

# ---------------------------------------------------------------------------
# 6. Data Quality Panel
# ---------------------------------------------------------------------------
with tabs[6]:
    if st.button(S("button_run_quality")):
        api_post("/quality/run")
        st.cache_data.clear()
        st.success(S("success_quality_triggered"))

    report = api_get("/quality/report")
    if report and report.get("checks"):
        st.metric(
            S("metric_overall_status"),
            STATUS_LABELS[LANG].get(report["overall_status"], report["overall_status"]),
        )
        checks_df = pd.DataFrame(report["checks"])
        checks_df["check_name"] = checks_df["check_name"].map(CHECK_NAME_LABELS[LANG]).fillna(
            checks_df["check_name"]
        )
        checks_df["status"] = checks_df["status"].map(STATUS_LABELS[LANG]).fillna(checks_df["status"])
        checks_df["run_at"] = checks_df["run_at"].apply(fmt_date)
        checks_df = checks_df.rename(
            columns={
                "check_name": S("col_check"),
                "status": S("col_status"),
                "affected_row_count": S("col_affected_rows"),
                "details": S("col_details"),
                "run_at": S("col_run_at"),
            }
        )
        st.dataframe(
            checks_df[[S("col_check"), S("col_status"), S("col_affected_rows"), S("col_details"), S("col_run_at")]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(S("info_no_quality_run"))

# ---------------------------------------------------------------------------
# 2. Employee Analysis
# ---------------------------------------------------------------------------
with tabs[2]:
    employee_scores = api_get("/scores/employees", params=P()) or []
    teams = api_get("/teams") or []
    team_name_by_id = {t["id"]: t["name"] for t in teams}
    employee_costs = api_get("/costs/employees", params=P()) or []
    tool_by_employee_id = {e["scope_id"]: dominant_tool(e["by_tool"]) for e in employee_costs}

    if not employee_scores:
        st.warning(S("warn_no_employee_scores"))
    else:
        table_df = pd.DataFrame(
            [
                {
                    S("col_employee"): e["full_name"],
                    S("col_team"): team_name_by_id.get(e["team_id"], "-"),
                    S("col_composite"): e["composite_score"],
                    S("col_archetype"): ARCHETYPE_LABELS[LANG].get(e["archetype"], e["archetype"]),
                    "_employee_id": e["employee_id"],
                    S("col_ai_used"): tool_by_employee_id.get(e["employee_id"], "-"),
                }
                for e in employee_scores
            ]
        )

        st.subheader(S("subheader_all_employees"))
        col1, col2 = st.columns(2)
        with col1:
            team_filter = st.multiselect(S("filter_team_label"), sorted(table_df[S("col_team")].unique()))
        with col2:
            archetype_filter = st.multiselect(
                S("filter_archetype_label"), sorted(table_df[S("col_archetype")].unique())
            )

        filtered_df = table_df
        if team_filter:
            filtered_df = filtered_df[filtered_df[S("col_team")].isin(team_filter)]
        if archetype_filter:
            filtered_df = filtered_df[filtered_df[S("col_archetype")].isin(archetype_filter)]

        st.dataframe(
            filtered_df.drop(columns=["_employee_id"]).sort_values(S("col_composite"), ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.subheader(S("subheader_employee_detail"))
        selected_name = st.selectbox(S("select_employee_label"), sorted(table_df[S("col_employee")]))
        selected = next(e for e in employee_scores if e["full_name"] == selected_name)

        col1, col2, col3 = st.columns(3)
        col1.metric(S("metric_composite"), f"{selected['composite_score']:.1f}")
        col2.metric(S("metric_archetype"), ARCHETYPE_LABELS[LANG].get(selected["archetype"], selected["archetype"]))
        col3.metric(S("metric_team"), team_name_by_id.get(selected["team_id"], "-"))

        detail_df = pd.DataFrame(
            {
                S("axis_dimension"): list(DIMENSION_LABELS[LANG].values()),
                S("axis_score"): [selected[key] for key in DIMENSION_LABELS[LANG]],
            }
        )
        fig = px.bar(detail_df, x=S("axis_score"), y=S("axis_dimension"), orientation="h", range_x=[0, 100])
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            S(
                "caption_period_computed",
                start=fmt_date(selected["period_start"]),
                end=fmt_date(selected["period_end"]),
                computed=fmt_date(selected["computed_at"]),
            )
        )

# ---------------------------------------------------------------------------
# 7. Methodology & Data Dictionary
# ---------------------------------------------------------------------------
with tabs[7]:
    st.markdown(S("methodology_markdown"))

# ---------------------------------------------------------------------------
# 8. Data Ingestion (yalnızca SHOW_INGESTION_TAB açıkken render edilir)
# ---------------------------------------------------------------------------
def _render_ingestion_tab() -> None:
    st.subheader(S("subheader_quick_demo"))
    st.caption(S("caption_quick_demo"))
    col1, col2 = st.columns(2)
    with col1:
        months = st.slider(S("slider_months_label"), min_value=1, max_value=12, value=6)
    with col2:
        selected_ai_tool = st.selectbox(
            S("select_ai_tool_label"),
            AI_TOOL_OPTIONS,
            index=AI_TOOL_OPTIONS.index(DEFAULT_AI_TOOL),
            help=S("select_ai_tool_help"),
        )
    if st.button(S("button_generate_demo"), type="primary"):
        with st.spinner(S("spinner_generating")):
            try:
                result = api_post(
                    "/ingestion/seed-demo-data",
                    params={"months": months, "tool_name": selected_ai_tool},
                )
                st.cache_data.clear()
                st.success(
                    S(
                        "success_demo_generated",
                        employees=result["employees_total"],
                        events=result["events_added"],
                        status=STATUS_LABELS[LANG].get(result["quality_status"], result["quality_status"]),
                    )
                )
            except httpx.HTTPStatusError as exc:
                st.error(S("error_generation_failed", error=exc.response.text))

    st.divider()

    st.subheader(S("subheader_excel_import"))
    st.caption(S("caption_excel_import"))

    col1, col2 = st.columns([1, 2])
    with col1:
        template_bytes = api_get_bytes("/ingestion/template")
        if template_bytes:
            st.download_button(
                S("button_download_template"),
                data=template_bytes,
                file_name="cowork_index_template.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"
                ),
            )

    uploaded_file = st.file_uploader(S("file_uploader_label"), type=["xlsx"])
    if uploaded_file is not None and st.button(S("button_import")):
        with st.spinner(S("spinner_importing")):
            try:
                with httpx.Client(base_url=API_BASE_URL, timeout=120.0) as client:
                    resp = client.post(
                        "/ingestion/import-excel",
                        files={
                            "file": (
                                uploaded_file.name,
                                uploaded_file.getvalue(),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        },
                    )
                    resp.raise_for_status()
                    result = resp.json()
                st.cache_data.clear()
                st.success(
                    S("success_import", accepted=result["events_accepted"], rejected=result["events_rejected"])
                )
                if result["errors"]:
                    st.warning(S("warning_import_errors"))
                    st.dataframe(pd.DataFrame({S("col_error"): result["errors"]}), hide_index=True)
            except httpx.HTTPStatusError as exc:
                st.error(S("error_import_failed", error=exc.response.text))


if ingestion_tab is not None:
    with ingestion_tab:
        _render_ingestion_tab()

# ---------------------------------------------------------------------------
# Live: Claude -- bağlayıcıdan gelen gerçek etkileşimler
# ---------------------------------------------------------------------------
with live_tab:
    top_left, top_right = st.columns([5, 1])
    with top_right:
        if st.button(S("live_refresh"), key="live_refresh"):
            st.cache_data.clear()

    status = api_get("/connectors/status") or {}
    sources = status.get("sources") or []
    if not sources:
        st.info(S("live_no_data"))
    else:
        total_events = sum(s["event_count"] for s in sources)
        total_sessions = sum(s["session_count"] for s in sources)
        last_at = max((s["last_occurred_at"] or "" for s in sources), default="")
        classifier_label = (
            f"claude ({status.get('classifier_mode')})" if status.get("claude_available") else f"heuristic ({status.get('classifier_mode')})"
        )
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(S("live_metric_events"), f"{total_events:,}")
        m2.metric(S("live_metric_sessions"), f"{total_sessions:,}")
        m3.metric(S("live_metric_last"), fmt_datetime(last_at) if last_at else "-")
        m4.metric(S("live_metric_classifier"), classifier_label)
        st.caption(S("live_capture_on") if status.get("capture_content") else S("live_capture_off"))

    f1, f2 = st.columns([1, 1])
    with f1:
        live_limit = st.select_slider(S("live_limit_label"), options=[25, 50, 100, 200, 500], value=100, key="live_limit")
    employees_all = api_get("/employees") or []
    connector_employee_ids = {
        e["employee_id"]
        for e in (api_get("/connectors/interactions", params=P({"limit": 500, "include_content": "false"})) or [])
    }
    employee_options = {S("live_all_employees"): None}
    employee_options.update({e["full_name"]: e["id"] for e in employees_all if e["id"] in connector_employee_ids})
    with f2:
        chosen_employee = st.selectbox(S("live_employee_label"), list(employee_options.keys()), key="live_employee")

    params = P({"limit": live_limit})
    if employee_options[chosen_employee] is not None:
        params["employee_id"] = employee_options[chosen_employee]
    feed = api_get("/connectors/interactions", params=params) or []

    if feed:
        def _short_project(path: str | None) -> str:
            if not path:
                return "-"
            return path.replace("\\", "/").rstrip("/").split("/")[-1]

        feed_df = pd.DataFrame(
            [
                {
                    S("col_time"): fmt_datetime(row["occurred_at"]),
                    S("col_employee"): row["employee_full_name"],
                    S("col_project"): _short_project(row.get("project")),
                    S("col_turn"): row["dialogue_turn_count"],
                    S("col_task"): row["task_category"],
                    S("col_action"): row["action_type"],
                    S("col_disagreement"): "✓" if row["had_disagreement"] else "",
                    S("col_outcome"): row["outcome_status"],
                    S("col_check"): "✓" if row["critical_check_flag"] else "",
                    S("col_tokens"): row["input_tokens"] + row["output_tokens"],
                    S("col_cost"): round(row["cost_usd"], 4),
                    S("col_classifier"): row.get("classifier") or "-",
                    "_event_id": row["event_id"],
                }
                for row in feed
            ]
        )
        st.dataframe(feed_df.drop(columns=["_event_id"]), use_container_width=True, hide_index=True)

        st.divider()
        st.subheader(S("live_detail_header"))
        labels = {
            f"#{row['event_id']} · {fmt_datetime(row['occurred_at'], '%d/%m %H:%M')} · "
            f"{(row.get('prompt_text') or '')[:70].replace(chr(10), ' ')}": row
            for row in feed
        }
        chosen = st.selectbox(S("live_select_label"), list(labels.keys()), key="live_detail")
        row = labels[chosen]
        d1, d2, d3, d4 = st.columns(4)
        d1.metric(S("col_action"), row["action_type"])
        d2.metric(S("col_outcome"), row["outcome_status"])
        d3.metric(S("col_task"), row["task_category"])
        d4.metric(S("col_tokens"), f"{row['input_tokens'] + row['output_tokens']:,}")
        if row.get("prompt_text") is None and row.get("response_text") is None:
            st.info(S("live_no_content"))
        else:
            st.markdown(f"**{S('live_prompt')}**")
            st.text_area("prompt", row.get("prompt_text") or "", height=140, label_visibility="collapsed", key=f"p{row['event_id']}")
            st.markdown(f"**{S('live_response')}**")
            st.text_area("response", row.get("response_text") or "", height=160, label_visibility="collapsed", key=f"r{row['event_id']}")
            if row.get("feedback_text"):
                st.markdown(f"**{S('live_feedback')}**")
                st.text_area("feedback", row.get("feedback_text") or "", height=90, label_visibility="collapsed", key=f"f{row['event_id']}")
            if row.get("tool_calls"):
                st.markdown(f"**{S('live_tools')}**")
                st.dataframe(pd.DataFrame(row["tool_calls"]), use_container_width=True, hide_index=True)
            if row.get("signals"):
                st.markdown(f"**{S('live_signals')}**")
                sig = row["signals"]
                cmp_rows = []
                for key in sig.get("final", {}):
                    cmp_rows.append(
                        {
                            "signal": key,
                            "heuristic": sig.get("heuristic", {}).get(key),
                            "claude": (sig.get("claude") or {}).get(key),
                            "final": sig["final"].get(key),
                        }
                    )
                st.dataframe(pd.DataFrame(cmp_rows), use_container_width=True, hide_index=True)
                if sig.get("claude") and sig["claude"].get("rationale"):
                    st.caption(f"Claude: {sig['claude']['rationale']}")
                with st.expander("raw"):
                    st.json(sig)

    st.divider()
    st.subheader(S("live_what_header"))
    st.markdown(S("live_what_markdown"))
