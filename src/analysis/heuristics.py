"""Model çağırmayan, deterministik sinyal ölçümleri (TR + EN)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+\s+|\n+")
_WORD_RE = re.compile(r"\w+", re.UNICODE)

POLITENESS_MARKERS = (
    "lütfen", "rica", "teşekkür", "tesekkur", "sağ ol", "sagol", "eyvallah", "zahmet",
    "please", "thank", "thanks", "appreciate", "kindly", "would you", "could you",
)
# Türkçe'de kibar istek biçimi: "... eder misin / yapar mısın / ekleyebilir misin"
_POLITE_REQUEST_RE = re.compile(r"\b(mısın|misin|musun|müsün|misiniz|mısınız|musunuz|müsünüz|olur mu|mümkün mü)\b", re.I)

# Emir kipi: cümle sonundaki fiil biçimleri (TR) ve cümle başı emir fiilleri (EN)
_TR_IMPERATIVE_END_RE = re.compile(
    r"\b(yap|et|ekle|sil|kaldır|kaldir|yaz|değiştir|degistir|düzelt|duzelt|koy|hazırla|hazirla|"
    r"çevir|cevir|göster|goster|bul|aç|ac|kapat|gönder|gonder|at|ver|al|başlat|baslat|durdur|"
    r"oluştur|olustur|kullan|yükle|yukle|güncelle|guncelle|kur|çalıştır|calistir|bak|anlat|"
    r"özetle|ozetle|listele|tut|bırak|birak|geç|gec|dön|don|yapma|ekleme|silme|değiştirme|"
    r"olsun|olmasın|olmasin|gel|git|çıkar|cikar|taşı|tasi|indir|artır|artir|azalt|küçült|kucult|"
    r"büyüt|buyut|ayır|ayir|birleştir|birlestir|temizle|kontrol et|test et|dene|çalış|calis|"
    r"\w+sana|\w+sene|\w+ın|\w+in|\w+un|\w+ün)\s*[.!]*$",
    re.I,
)
_EN_IMPERATIVE_START_RE = re.compile(
    r"^(add|remove|delete|make|fix|write|create|update|change|put|run|move|rename|show|explain|"
    r"list|check|test|build|implement|refactor|convert|translate|generate|use|set|open|close|"
    r"stop|start|install|deploy|don't|do not|never|always)\b",
    re.I,
)

DISAGREEMENT_MARKERS = (
    "hayır", "hayir", "yanlış", "yanlis", "değil", "degil", "olmadı", "olmadi", "olmamış", "olmamis",
    "istemiyorum", "sen ciddi misin", "ne alaka", "saçma", "sacma", "hatalı", "hatali", "bozuk",
    "çalışmıyor", "calismiyor", "böyle olmaz", "boyle olmaz", "hala", "hâlâ", "yine", "geri al",
    "no,", "no.", "wrong", "not what", "incorrect", "doesn't work", "does not work", "broken", "undo", "revert",
)
ACCEPTANCE_MARKERS = (
    "tamam", "teşekkür", "tesekkur", "süper", "super", "harika", "güzel", "guzel", "evet", "oldu",
    "olur", "peki", "mükemmel", "mukemmel", "aynen", "eyvallah", "sağ ol", "ok", "okay", "thanks",
    "great", "perfect", "good", "nice", "works", "çalıştı", "calisti",
)
VERIFY_MARKERS = (
    "kontrol et", "test et", "emin misin", "doğru mu", "dogru mu", "çalışıyor mu", "calisiyor mu",
    "dene", "doğrula", "dogrula", "gözden geçir", "gozden gecir", "verify", "check", "make sure",
    "are you sure", "double check", "validate", "confirm", "test",
)
INSTRUCTION_HINTS = ("yap", "ekle", "değiştir", "degistir", "olsun", "istiyorum", "lazım", "lazim", "gerek", "please", "should", "make", "add", "change")

WRITING_HINTS = (
    "readme", "sunum", "metin", "yazı", "yazi", "çevir", "cevir", "doküman", "dokuman", "döküman",
    "mail", "e-posta", "slayt", "özet", "ozet", "makale", "blog", "cümle", "cumle", "paragraf",
    "translate", "document", "presentation", "essay", "draft", "rewrite", "wording",
)
ANALYSIS_HINTS = (
    "neden", "nasıl", "nasil", "anlat", "açıkla", "acikla", "karşılaştır", "karsilastir", "analiz",
    "fark", "hangisi", "ne demek", "nedir", "değerlendir", "degerlendir", "why", "how", "explain",
    "compare", "analy", "what is", "difference", "should i", "which",
)
CODE_HINTS = (
    "kod", "fonksiyon", "bug", "hata", "api", "endpoint", "test", "docker", "tablo", "sql", "migration",
    "class", "metod", "method", "script", "dashboard", "sekme", "buton", "css", "html", "python",
    "refactor", "import", "compile", "deploy", "commit", "repo", "veritaban", "database", "query",
)
CODE_FILE_RE = re.compile(r"\.(py|js|ts|tsx|jsx|java|cs|go|rs|sql|yaml|yml|toml|json|sh|ps1|html|css|ipynb|dockerfile)$", re.I)
DOC_FILE_RE = re.compile(r"\.(md|txt|docx|pptx|rst)$", re.I)
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch"}


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text or "") if p and p.strip()]
    return parts


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


@dataclass
class TextStats:
    sentence_count: int
    word_count: int
    avg_sentence_length: float
    exclamation_density: float
    politeness_marker_count: int
    directive_language_ratio: float
    question_count: int


def text_stats(text: str) -> TextStats:
    sents = sentences(text)
    n = max(1, len(sents))
    w = words(text)
    lowered = (text or "").lower()
    politeness = sum(lowered.count(m) for m in POLITENESS_MARKERS) + len(_POLITE_REQUEST_RE.findall(lowered))
    directive = 0
    for s in sents:
        s_l = s.lower().strip()
        if _POLITE_REQUEST_RE.search(s_l) or s_l.endswith("?"):
            continue
        if _EN_IMPERATIVE_START_RE.search(s_l) or _TR_IMPERATIVE_END_RE.search(s_l):
            directive += 1
    return TextStats(
        sentence_count=len(sents),
        word_count=len(w),
        avg_sentence_length=round(len(w) / n, 2),
        exclamation_density=round(min(1.0, (text or "").count("!") / n), 3),
        politeness_marker_count=int(politeness),
        directive_language_ratio=round(min(1.0, directive / n), 3) if sents else 0.0,
        question_count=(text or "").count("?"),
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(m in lowered for m in markers)


def classify_task(prompt: str, tool_calls: list[dict]) -> str:
    targets = " ".join(str(t.get("target") or "") for t in tool_calls)
    names = {t.get("name") for t in tool_calls}
    if names & EDIT_TOOLS and CODE_FILE_RE.search(targets or ""):
        return "code"
    if names & EDIT_TOOLS and DOC_FILE_RE.search(targets or ""):
        return "writing"
    if _contains_any(prompt, WRITING_HINTS):
        return "writing"
    if _contains_any(prompt, CODE_HINTS) or (names & EDIT_TOOLS):
        return "code"
    if _contains_any(prompt, ANALYSIS_HINTS):
        return "analysis"
    return "other"


def classify_feedback(feedback: str | None, interrupted: bool, tool_calls: list[dict]) -> dict:
    """Bir sonraki prompt (geri bildirim) + araç red/kesinti sinyallerinden
    action_type / had_disagreement / persuasion_direction türetir."""
    denied = any(t.get("denied") for t in tool_calls)
    fb = feedback or ""
    disagree = _contains_any(fb, DISAGREEMENT_MARKERS)
    accept = _contains_any(fb, ACCEPTANCE_MARKERS)
    has_instruction = len(words(fb)) >= 6 and (
        _contains_any(fb, INSTRUCTION_HINTS) or text_stats(fb).directive_language_ratio > 0
    )

    if interrupted or denied:
        action = "rejected"
    elif disagree and has_instruction:
        action = "edited"
    elif disagree:
        action = "rejected"
    else:
        action = "accepted"

    if disagree:
        persuasion = "user_persuaded_ai"
    elif accept and not disagree:
        persuasion = "none"
    else:
        persuasion = "none"
    return {
        "action_type": action,
        "had_disagreement": bool(disagree or interrupted or denied),
        "persuasion_direction": persuasion,
        "feedback_accepts": accept,
    }


def classify_outcome(action_type: str, tool_calls: list[dict]) -> str:
    names = [t.get("name") for t in tool_calls]
    targets = " ".join(str(t.get("target") or "").lower() for t in tool_calls)
    if action_type == "rejected":
        return "abandoned"
    if "git commit" in targets or "git push" in targets:
        return "production"
    if any(n in EDIT_TOOLS for n in names) and not any(t.get("is_error") for t in tool_calls if t.get("name") in EDIT_TOOLS):
        return "production"
    return "test_only"


def critical_check(prompt: str, feedback: str | None, tool_calls: list[dict]) -> bool:
    targets = " ".join(str(t.get("target") or "").lower() for t in tool_calls)
    return (
        _contains_any(prompt, VERIFY_MARKERS)
        or _contains_any(feedback or "", VERIFY_MARKERS)
        or "pytest" in targets
    )


def heuristic_signals(prompt: str, response: str, feedback: str | None, tool_calls: list[dict], interrupted: bool) -> dict:
    stats = text_stats(prompt)
    fb = classify_feedback(feedback, interrupted, tool_calls)
    action = fb["action_type"]
    return {
        "action_type": action,
        "had_disagreement": fb["had_disagreement"],
        "persuasion_direction": fb["persuasion_direction"],
        "directive_language_ratio": stats.directive_language_ratio,
        "politeness_marker_count": stats.politeness_marker_count,
        "avg_sentence_length": stats.avg_sentence_length,
        "exclamation_density": stats.exclamation_density,
        "outcome_status": classify_outcome(action, tool_calls),
        "critical_check_flag": critical_check(prompt, feedback, tool_calls),
        "task_category": classify_task(prompt, tool_calls),
        "_stats": {
            "sentence_count": stats.sentence_count,
            "word_count": stats.word_count,
            "question_count": stats.question_count,
            "feedback_accepts": fb["feedback_accepts"],
            "tool_call_count": len(tool_calls),
            "edit_count": sum(1 for t in tool_calls if t.get("name") in EDIT_TOOLS),
            "denied_count": sum(1 for t in tool_calls if t.get("denied")),
            "error_count": sum(1 for t in tool_calls if t.get("is_error")),
            "response_words": len(words(response)),
        },
    }
