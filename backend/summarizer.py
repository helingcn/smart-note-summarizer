import json
import math
import re
import time
from collections import Counter

from google import genai
from google.genai import errors, types

GEMINI_MODEL = "gemini-flash-lite-latest"

SYSTEM_PROMPT = """Sen SmartDigest'in titiz Türkçe özetleme asistanısın.
Yalnızca verilen kaynak metindeki bilgilere dayan. Kaynakta olmayan kişi,
kurum, tarih, sebep, sayı veya sonuç uydurma. Emin olmadığın bilgiyi ekleme.
Metnin ana amacını, en önemli sonuçlarını, sayısal bulgularını, sınırlılıklarını
ve gelecek planlarını önceliklendir; küçük teknik ayrıntıları ancak ana sonucu
anlamak için gerekliyse kullan. Açık, doğal ve tarafsız Türkçe yaz."""


_client_instance = None


def _client() -> genai.Client:
    """API anahtarını yalnızca ilk gerçek çağrıda okuyan tembel (lazy) istemci.
    Bu sayede `GEMINI_API_KEY` ayarlı olmadan da modül import edilebilir
    (ör. testlerde), hata yalnızca gerçek bir API çağrısı yapılınca oluşur."""
    global _client_instance
    if _client_instance is None:
        _client_instance = genai.Client()
    return _client_instance


def _finish_reason(response) -> str:
    try:
        reason = response.candidates[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        return ""
    return getattr(reason, "name", str(reason))


GEMINI_TIMEOUT_MS = 35_000
GEMINI_SERVER_ERROR_RETRIES = 2


def _generate_content(contents: str, config: types.GenerateContentConfig):
    """generate_content'i çağırır; 504 DEADLINE_EXCEEDED gibi geçici Gemini
    sunucu hatalarında (5xx) kısa bir bekleme sonrası yeniden dener. Bu hatalar
    genelde anlık yük/gecikmeden kaynaklanır ve bir sonraki denemede geçer;
    tek seferde vazgeçmek tüm özetleme işini gereksiz yere başarısız kılıyordu."""
    last_error: errors.ServerError | None = None
    for attempt in range(GEMINI_SERVER_ERROR_RETRIES + 1):
        try:
            return _client().models.generate_content(
                model=GEMINI_MODEL, contents=contents, config=config
            )
        except errors.ServerError as error:
            last_error = error
            if attempt < GEMINI_SERVER_ERROR_RETRIES:
                time.sleep(2 * (attempt + 1))
                continue
    raise last_error


def ask_model(prompt: str) -> str:
    response = _generate_content(
        prompt,
        types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.15,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
        ),
    )
    return (response.text or "").strip()


def bullet_limit(text_length: int, length: str = "balanced") -> int:
    if length == "detailed":
        return 8
    if text_length <= 1_000:
        return 0
    if text_length <= 3_500:
        return 3
    if text_length <= 8_000:
        return 5
    return 7


def word_target(text_length: int, length: str = "balanced") -> tuple[int, int]:
    """Uzunluk ayarına göre hedeflenen (min, max) kelime sayısını döndürür."""
    if length == "detailed":
        return 300, 420
    if text_length <= 1_000:
        return 0, 60
    if text_length <= 3_500:
        return 100, 160
    if text_length <= 8_000:
        return 180, 260
    return 280, 380


def max_output_tokens(text_length: int, length: str = "balanced") -> int:
    """Kelime hedefinden, üretimi gereksiz uzatmayı önleyecek bir token tavanı türetir."""
    _, max_words = word_target(text_length, length)
    return int(max_words * 3) + 200


NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers_in(text: str) -> set[str]:
    return set(NUMBER_PATTERN.findall(text))


def _drop_unverified_numbers(
    overview: str, highlights: list[str], source_text: str
) -> tuple[str, list[str]]:
    """Kaynakta birebir geçmeyen sayıları maskeler; modelin uydurduğu veya
    bozduğu rakamların (ör. '10,5' yerine '4,25') özete sızmasına karşı
    model boyutundan bağımsız bir güvenlik ağıdır. Maddeyi tamamen atmak
    yerine yalnızca şüpheli sayıyı bir yer tutucuyla değiştiririz; aksi hâlde
    birden fazla madde aynı anda (ör. modelin sayı biçimlendirmesindeki küçük
    bir farktan dolayı) yanlışlıkla şüpheli sayılırsa `highlights` tamamen
    boş kalabilir."""
    source_numbers = _numbers_in(source_text)

    def unverified_numbers(text: str) -> list[str]:
        return [
            number
            for number in _numbers_in(text)
            if len(re.sub(r"[.,]", "", number)) >= 2 and number not in source_numbers
        ]

    def sanitize(sentence: str) -> str:
        for number in unverified_numbers(sentence):
            sentence = re.sub(
                rf"%?\s?{re.escape(number)}\s?%?", " [doğrulanamayan değer] ", sentence
            )
        return re.sub(r"\s{2,}", " ", sentence).strip()

    sentences = re.split(r"(?<=[.!?])\s+", overview.strip())
    clean_overview = " ".join(sanitize(sentence) for sentence in sentences)

    clean_highlights = [sanitize(item) for item in highlights]
    clean_highlights = [item for item in clean_highlights if len(_normalize(item)) >= 15]

    return clean_overview, clean_highlights


def _word_count(overview: str, highlights: list[str]) -> int:
    return len(overview.split()) + sum(len(item.split()) for item in highlights)


LABEL_PREFIX = re.compile(r"^\[(Kritik|Önemli|Detay)\]\s*")


def _normalize(text: str) -> str:
    text = LABEL_PREFIX.sub("", text)
    text = re.sub(r"[^\wçğıöşüÇĞİÖŞÜ\s]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _drop_duplicate_highlights(overview: str, highlights: list[str]) -> list[str]:
    """`highlights`'ta, `overview`'daki bir cümleyle neredeyse birebir aynı olan
    maddeleri çıkarır. Kelime hedefini tutturmak için yapılan genişletme
    denemesi bazen en kolay yolu seçip overview cümlesini highlight'a aynen
    kopyalıyor; bu, prompt kuralından bağımsız deterministik bir güvenlik ağı."""
    overview_sentences = [_normalize(s) for s in re.split(r"(?<=[.!?])\s+", overview.strip())]

    def is_duplicate(item: str) -> bool:
        normalized = _normalize(item)
        if len(normalized) < 15:
            return False
        for sentence in overview_sentences:
            if len(sentence) < 15:
                continue
            shorter, longer = sorted([normalized, sentence], key=len)
            if shorter in longer and len(shorter) / len(longer) > 0.8:
                return True
        return False

    return [item for item in highlights if not is_duplicate(item)]


SENTENCE_END = re.compile(r"[.!?][\"'’”)]?$")


def _drop_incomplete_highlights(highlights: list[str]) -> list[str]:
    """Cümle sonu noktalamasıyla bitmeyen maddeleri çıkarır. Bu genelde modelin
    token tavanına takılmadan, kendi kararıyla bir cümleyi yarıda bırakmasının
    işaretidir (ör. '...3.400 çalışanını yeni'); `finish_reason` kontrolü bu
    tür kesilmeleri yakalamaz çünkü üretim normal şekilde tamamlanmış sayılır."""
    return [item for item in highlights if SENTENCE_END.search(item.strip())]


def ask_for_summary(
    prompt: str, max_bullets: int, max_tokens: int, source_text: str, min_words: int = 0
) -> str:
    """Özeti JSON olarak alır ve arayüz için tekdüze Markdown'a dönüştürür."""
    schema = {
        "type": "object",
        "properties": {
            "overview": {"type": "string"},
            "highlights": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": max_bullets,
            },
        },
        "required": ["overview", "highlights"],
    }

    def build_prompt(base_prompt: str) -> str:
        return f"""{base_prompt}

Yanıtını yalnızca geçerli JSON olarak ver. Şema: {{"overview": "kısa özet",
"highlights": ["önemli bulgu"]}}. `highlights` dizisinde en fazla {max_bullets}
öğe olsun. Her önemli bulgu `[Kritik]`, `[Önemli]` veya `[Detay]` etiketiyle
başlasın; başlık, Markdown veya ek alan kullanma.

Etiket kriteri:
- [Kritik]: risk, sınırlılık, kritik uyarı veya olumsuz sonuç bildiren bulgular
- [Önemli]: ana bulgu, sonuç veya kaynağın önerdiği temel strateji/değişim
- [Detay]: yukarıdakileri destekleyen bağlam, örnek veya ikincil bilgi

Maddeleri kaynaktaki farklı bölümlerden seç; aynı temayı iki maddeyle tekrar
etme ve tek bir bölüme yoğunlaşma. `highlights`, `overview`'da zaten anlatılan
temayı tekrar özetlemesin; overview'un değinmediği yeni bilgi eklesin.
`highlights`'taki hiçbir madde, `overview`'daki herhangi bir cümleyi kelimesi
kelimesine veya neredeyse aynı ifadeyle tekrar etmesin. `overview`'daki hiçbir
cümle, kaynakta farklı bağlamlarda geçen birden fazla farklı olayı veya kurumu
zorla birbirine bağlamasın; her cümle tek bir ana fikre/kaynağa dayansın."""

    def call(prompt_text: str, num_predict: int):
        return _generate_content(
            build_prompt(prompt_text),
            types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.15,
                max_output_tokens=num_predict,
                response_mime_type="application/json",
                response_schema=schema,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
                http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
            ),
        )

    def parse(response) -> tuple[str, list[str]] | None:
        try:
            data = json.loads(response.text)
            overview = str(data["overview"]).strip()
            highlights = data.get("highlights", [])[:max_bullets]
            highlights = [re.sub(r"^[-*•\s]+", "", str(item)).strip() for item in highlights]
            highlights = [item for item in highlights if item]
            return overview, highlights
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            # API bazen şemayı tam izlemeyebilir; bu durumda ham yanıtı yine
            # uygulamanın standart özet biçimine getiririz.
            raw_text = response.text or ""
            raw_lines = [line.strip() for line in raw_text.splitlines()]
            content_lines = [
                re.sub(r"^[#*\-\s]+|[*]+$", "", line).strip()
                for line in raw_lines
                if line.strip()
                and not re.fullmatch(
                    r"[#*\s]*(Özet|Öne çıkanlar|Ana amaç.*|Sonuçlar|Riskler.*|Gelecek plan.*)[#*\s:]*",
                    line,
                    re.IGNORECASE,
                )
            ]
            if not content_lines:
                return None
            return content_lines[0], content_lines[1 : max_bullets + 1]

    response = call(prompt, max_tokens)
    if _finish_reason(response) == "MAX_TOKENS":
        # Üretim, token tavanına takılıp JSON yarıda kesilmiş olabilir; ham metni
        # bozuk parçalara ayırmak yerine daha geniş bir bütçeyle bir kez daha dene.
        response = call(prompt, max_tokens * 2)

    parsed = parse(response)
    if parsed is None:
        return ask_model(prompt)
    overview, highlights = parsed

    if min_words and _word_count(overview, highlights) < min_words:
        # Çıktı hedeflenen kelime sayısının altında kaldıysa, mevcut
        # olguları daha ayrıntılı anlatmasını isteyerek bir kez daha dene. Daha
        # fazla kelime istediğimiz için orijinal bütçe yetersiz kalabilir; bu
        # yüzden burada da geniş bir bütçe ayırıp kesilme olursa sonucu kullanmıyoruz.
        expand_prompt = f"""{prompt}

Önceki yanıtın çok kısa kaldı (yaklaşık {_word_count(overview, highlights)}
kelime, hedef en az {min_words} kelime). Önceki yanıtın (JSON): {response.text}

Aynı JSON şemasıyla, kaynakta olmayan hiçbir bilgi eklemeden, mevcut olguları
daha ayrıntılı anlatarak ve madde bütçesini daha iyi kullanarak toplamda en az
{min_words} kelimeye çıkan bir versiyon üret. Bunu overview ile highlights'ı
birbirinin kopyası hâline getirerek yapma: highlights'taki hiçbir madde
overview'daki bir cümleyi kelimesi kelimesine veya neredeyse aynı ifadeyle
tekrar etmesin. Genişletmeyi overview'a yeni bir bağlam cümlesi ekleyerek veya
highlights maddelerine daha fazla sayı/ayrıntı katarak sağla, cümle
kopyalayarak değil."""
        expand_response = call(expand_prompt, max_tokens * 2)
        if _finish_reason(expand_response) != "MAX_TOKENS":
            expand_parsed = parse(expand_response)
            if expand_parsed and _word_count(*expand_parsed) > _word_count(overview, highlights):
                overview, highlights = expand_parsed

    highlights = _drop_duplicate_highlights(overview, highlights)
    highlights = _drop_incomplete_highlights(highlights)
    overview, highlights = _drop_unverified_numbers(overview, highlights, source_text)

    output = f"### Özet\n{overview}"
    if highlights:
        labeled = [
            item if re.match(r"^\[(Kritik|Önemli|Detay)\]", item) else f"[Önemli] {item}"
            for item in highlights
        ]
        output += "\n\n### Öne çıkanlar\n" + "\n".join(f"- {item}" for item in labeled)
    return output


NUMBER_RULE = """Kaynakta somut sayı, yüzde veya tutar geçiyorsa `overview` bunlardan en az
ikisini rakamla yazmalı; "ciddi oranda", "önemli ölçüde", "belirgin şekilde" gibi
belirsiz ifadelerle geçiştirmemeli."""


def summary_format(text_length: int, length: str = "balanced") -> str:
    """Kaynak uzunluğuna uygun, okunabilir çıktı hedefini döndürür."""
    min_words, max_words = word_target(text_length, length)
    if length == "detailed":
        return f"""`overview` alanında 4-6 açıklayıcı cümle; `highlights` alanında 6-8 kısa
madde üret. Amaç, kapsam, yöntem, sonuç, önemli sayılar, sınırlılıklar, riskler ve
sonraki planlar arasında denge kur; önemli ayrıntıları yalnızca kısa olmak için atlama.
En az {min_words}, en fazla {max_words} kelime kullan. {NUMBER_RULE}"""
    if text_length <= 1_000:
        return f"""`overview` alanında en fazla 3 cümlelik tek bir paragraf yaz;
`highlights` alanını boş bırak. {NUMBER_RULE}"""
    if text_length <= 3_500:
        return f"""`overview` alanında kısa bir paragraf; `highlights` alanında en
fazla 3 kısa madde üret. En az {min_words}, en fazla {max_words} kelime kullan.
{NUMBER_RULE}"""
    if text_length <= 8_000:
        return f"""`overview` alanında 1-2 cümle; `highlights` alanında en fazla 5
kısa madde üret. En az {min_words}, en fazla {max_words} kelime kullan. {NUMBER_RULE}"""
    return f"""`overview` alanında 2-3 cümle; `highlights` alanında en fazla 7 kısa
madde üret. En az {min_words}, en fazla {max_words} kelime kullan;
aynı bilgiyi tekrarlama. {NUMBER_RULE}"""


def summarize_text(text: str, length: str = "balanced") -> str:
    prompt = f"""Aşağıdaki metni Türkçe özetle.

Çıktı kuralları:
- {summary_format(len(text), length)}
- Madde içinde alt başlık, kalın yazı veya numaralandırma kullanma.
- Metindeki anlamlı sayıları, tarihleri ve koşulları koru.
- Ana konu dışındaki ayrıntıları çıkar.
- "Metin şöyle diyor" gibi girişler ve kaynakta olmayan yorumlar kullanma.

KAYNAK METİN:
{text}"""
    min_words, _ = word_target(len(text), length)
    return ask_for_summary(
        prompt,
        bullet_limit(len(text), length),
        max_output_tokens(len(text), length),
        text,
        min_words,
    )


def split_text(text: str, chunk_size: int = 3500) -> list[str]:
    """Metni mümkün olduğunda cümle sonlarından bölerek parçalara ayırır."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current = [], ""

    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > chunk_size:
            chunks.append(current)
            current = sentence
        elif len(sentence) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(sentence[i : i + chunk_size] for i in range(0, len(sentence), chunk_size))
        else:
            current = f"{current} {sentence}".strip()

    if current:
        chunks.append(current)
    return chunks


def extract_key_facts(text: str) -> str:
    return ask_model(
        f"""Bu metin parçasından yalnızca nihai özette korunması gereken doğrulanabilir
bilgileri çıkar. Her maddede özeti yapma; bunun yerine açık bir olgu ve onu
destekleyen kaynak cümlesini birlikte ver.

Öncelik sırası: ana amaç ve kapsam, bütçe/finansman, uygulama miktarları,
ölçülebilir sonuçlar, sınırlılıklar-riskler-eleştiriler, gelecek planları.
Benzer sayıları yanlış birleştirme: örneğin toplam katılımcı sayısı ile hizmet
alan katılımcı sayısını ayrı maddeler olarak koru. Kaynakta olmayan yorum ekleme.

Her madde şu biçimde olsun:
- Olgu: ... | Kanıt: "kaynak metinden kısa, aynen alınmış cümle/parça"

METİN PARÇASI:
{text}"""
    )


def verify_summary(
    candidate: str, source: str, max_bullets: int, max_tokens: int, min_words: int = 0
) -> str:
    """Özetteki iddiaları kaynakla karşılaştırıp hatalı olanları düzeltir."""
    verification_source = source
    if len(source) > 16_000:
        verification_source = (
            "Belge çok uzun olduğu için aşağıdaki, kaynak cümle kanıtlarıyla çıkarılmış "
            "notlar doğrulama kaynağıdır:\n\n" + source
        )

    prompt = f"""Aşağıdaki aday özeti doğrula ve gerekirse düzelt.

Kurallar:
- Her iddia, sayı, oran, tarih ve özne ilişkisi doğrulama kaynağında açıkça yer almalı.
- Kaynakta olmayan veya yanlış bağlanan bilgiyi çıkar ya da doğru hâliyle değiştir.
- Özellikle toplam sayılar ile alt küme sayılarını karıştırma.
- Kritik bilgileri koru: amaç/kapsam, ölçülebilir sonuç, önemli sınırlılık veya
eleştiri ve varsa gelecek planı.
- Kaynakta yer alan ama özette hiç geçmeyen önemli bir bulgu, risk, sınırlılık
veya sonuç varsa, en az önemli veya tekrarcı maddenin yerine bunu ekle.
- Yeni yorum ekleme.
- {NUMBER_RULE}

ADAY ÖZET:
{candidate}

DOĞRULAMA KAYNAĞI:
{verification_source}"""
    return ask_for_summary(prompt, max_bullets, max_tokens, source, min_words)


def _report(on_progress, percent: int, message: str) -> None:
    if on_progress is not None:
        on_progress(percent, message)


def summarize_long_text(
    text: str,
    chunk_size: int = 7_000,
    verified: bool = True,
    length: str = "balanced",
    on_progress=None,
) -> str:
    """`on_progress`, verilirse `(yüzde, mesaj)` ile gerçek ilerleme adımlarında
    çağrılır (ör. iş kuyruğunu arayüze yansıtmak için); vermek zorunlu değildir."""
    # Hızlı mod her zaman tek çağrıda işler ve en yüksek hızı hedefler. Doğrulanmış
    # modda, kapsamı artırmak için orta uzunluktaki metinler de önce olgu çıkarma
    # adımından geçer; bu adım ek çağrı gerektirdiğinden yalnızca doğrulanmış modda
    # devreye girer.
    direct_limit = 12_000 if not verified else chunk_size
    if verified:
        direct_limit = min(direct_limit, 3_000)
    if len(text) <= direct_limit:
        _report(on_progress, 20, "Taslak özet oluşturuluyor…")
        candidate = summarize_text(text, length=length)
        max_tokens = max_output_tokens(len(text), length)
        min_words, _ = word_target(len(text), length)
        if not verified:
            _report(on_progress, 80, "Özet tamamlandı, sonuçlar hazırlanıyor…")
            return candidate
        _report(on_progress, 55, "Kaynaklarla doğrulanıyor…")
        verified_candidate = verify_summary(
            candidate, text, bullet_limit(len(text), length), max_tokens, min_words
        )
        _report(on_progress, 80, "Kaynak eşleştirmeleri hazırlanıyor…")
        return annotate_summary_sources(verified_candidate, text)

    chunks = split_text(text, chunk_size)
    facts = []
    for index, chunk in enumerate(chunks, 1):
        _report(
            on_progress,
            15 + int(40 * index / len(chunks)),
            f"Bölüm {index}/{len(chunks)} inceleniyor…",
        )
        facts.append(extract_key_facts(chunk))
    combined_facts = "\n\n".join(facts)
    prompt = f"""Aşağıda uzun bir belgeden çıkarılmış doğrulanabilir notlar var. Bunları
birleştirerek Türkçe, tutarlı bir nihai özet yaz.

Çıktı kuralları:
- {summary_format(len(text), length)}
- Madde içinde alt başlık, kalın yazı veya numaralandırma kullanma.
- Tek bir ayrıntıya aşırı odaklanma; amaç, sonuç, kritik sayı, sınırlılık ve
gelecek planı arasında denge kur.
- Notlarda yer almayan hiçbir bilgi ekleme.
- Notlarda geçen her farklı kurum, ülke veya bölümden mümkün olduğunca en az
bir madde `highlights`'a dahil et; aynı kurum veya bölümden birden fazla
madde seçme, madde bütçesi yetmiyorsa en çarpıcı olanı değil en çeşitli
kapsamı sağlayanları tercih et.

DOĞRULANMIŞ NOTLAR:
{combined_facts}"""
    max_tokens = max_output_tokens(len(text), length)
    min_words, _ = word_target(len(text), length)
    _report(on_progress, 60, "Notlar birleştirilip özetleniyor…")
    candidate = ask_for_summary(
        prompt, bullet_limit(len(text), length), max_tokens, combined_facts, min_words
    )
    if not verified:
        _report(on_progress, 80, "Özet tamamlandı, sonuçlar hazırlanıyor…")
        return candidate
    _report(on_progress, 72, "Kaynaklarla doğrulanıyor…")
    verified_candidate = verify_summary(
        candidate, combined_facts, bullet_limit(len(text), length), max_tokens, min_words
    )
    _report(on_progress, 85, "Kaynak eşleştirmeleri hazırlanıyor…")
    return annotate_summary_sources(verified_candidate, text)


_STOP_WORDS = {
    "acaba",
    "ama",
    "ancak",
    "artık",
    "bir",
    "biri",
    "biz",
    "bu",
    "buna",
    "bunu",
    "da",
    "daha",
    "de",
    "diye",
    "en",
    "gibi",
    "hem",
    "ile",
    "ise",
    "için",
    "kadar",
    "ki",
    "mı",
    "mi",
    "mu",
    "mü",
    "nasıl",
    "ne",
    "neden",
    "o",
    "olan",
    "olarak",
    "oldu",
    "şu",
    "ve",
    "veya",
    "ya",
    "çok",
}
_SYNONYMS = {
    "maliyet": {"harcama", "gider", "ücret", "bütçe"},
    "harcama": {"maliyet", "gider", "ücret"},
    "gelir": {"kazanç", "hasılat"},
    "çalışan": {"personel", "işçi", "çalışanlar"},
    "risk": {"tehlike", "belirsizlik"},
    "hedef": {"amaç", "plan"},
}


def _tokens(value: str) -> list[str]:
    value = value.replace("İ", "i").replace("I", "ı").lower()
    words = re.findall(r"[a-zçğıöşü0-9]+", value)
    result = []
    for word in words:
        if len(word) < 3 or word in _STOP_WORDS:
            continue
        for suffix in ("ları", "leri", "ların", "lerin", "dan", "den", "dır", "dir", "tır", "tir"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
        result.append(word)
    return result


def _passages(text: str) -> list[tuple[int, int, str]]:
    matches = list(re.finditer(r"\[Sayfa\s+(\d+)\]", text, flags=re.IGNORECASE))
    pages = []
    if matches:
        for position, match in enumerate(matches):
            end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
            pages.append((int(match.group(1)), text[match.end() : end]))
    else:
        pages = [(1, text)]
    output = []
    for page_no, page_text in pages:
        chunks = [
            part.strip() for part in re.split(r"\n\s*\n|(?<=[.!?])\s+", page_text) if part.strip()
        ]
        output.extend((page_no, index, chunk) for index, chunk in enumerate(chunks, 1))
    return output


def _bm25_scores(query: str, passages: list[tuple[int, int, str]]) -> list[float]:
    query_tokens = _tokens(query)
    expanded = list(query_tokens)
    for token in query_tokens:
        expanded.extend(_SYNONYMS.get(token, ()))
    documents = [_tokens(item[2]) for item in passages]
    if not documents:
        return []
    avgdl = sum(map(len, documents)) / max(1, len(documents))
    frequencies = Counter(token for document in documents for token in set(document))
    scores = []
    for document in documents:
        counts = Counter(document)
        score = 0.0
        for token in set(expanded):
            if not counts[token]:
                continue
            idf = math.log(
                1 + (len(documents) - frequencies[token] + 0.5) / (frequencies[token] + 0.5)
            )
            score += (
                idf
                * (counts[token] * 2.5)
                / (counts[token] + 1.5 * (0.25 + 0.75 * len(document) / max(avgdl, 1)))
            )
        scores.append(score)
    return scores


def _best_source(claim: str, text: str) -> tuple[int, int, str, int] | None:
    passages = _passages(text)
    scores = _bm25_scores(claim, passages)
    if not scores or max(scores) <= 0:
        return None
    index = max(range(len(scores)), key=scores.__getitem__)
    claim_tokens, source_tokens = set(_tokens(claim)), set(_tokens(passages[index][2]))
    support = int(100 * len(claim_tokens & source_tokens) / max(1, len(claim_tokens)))
    claim_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", claim))
    source_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", passages[index][2]))
    if claim_numbers - source_numbers:
        support = min(support, 25)
    return (*passages[index], support)


def annotate_summary_sources(summary: str, source_text: str) -> str:
    lines = []
    for line in summary.splitlines():
        if line.lstrip().startswith("-") and "Kaynak: s." not in line:
            match = _best_source(line.lstrip("- "), source_text)
            if match:
                line += f" _(Kaynak: s. {match[0]} · destek %{match[3]})_"
        lines.append(line)
    return "\n".join(lines)


def _clean_claim_text(value: str) -> str:
    value = re.sub(r"^\s*[-*•]\s*", "", value).strip()
    value = re.sub(r"^\[(?:Kritik|Önemli|Detay)\]\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(
        r"\s*_?\(Kaynak:\s*s\.\s*\d+\s*·\s*destek\s*%\d+\)_?\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value.strip()


def _summary_claims(summary: str) -> list[str]:
    """Başlıkları atlayıp özet ve madde içeriklerini bağımsız iddialara ayırır."""
    claims: list[str] = []
    for line in summary.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cleaned = _clean_claim_text(stripped)
        for sentence in re.split(r"(?<!\d\.)(?<=[.!?])\s+", cleaned):
            sentence = sentence.strip()
            if len(sentence) >= 20 and sentence not in claims:
                claims.append(sentence)
    return claims


def build_summary_evidence(summary: str, source_text: str) -> list[dict]:
    """Arayüz için her özet iddiasına kısa ve izlenebilir bir kaynak kanıtı bağlar."""
    evidence = []
    for claim in _summary_claims(summary):
        match = _best_source(claim, source_text)
        if not match:
            continue
        page, paragraph, quote, support = match
        status = "supported" if support >= 50 else "review" if support >= 30 else "weak"
        evidence.append(
            {
                "claim": claim,
                "page": page,
                "paragraph": paragraph,
                "quote": quote.strip()[:900],
                "support": support,
                "status": status,
            }
        )
    return evidence


def answer_question(text: str, question: str) -> tuple[str, list[str]]:
    """Türkçe normalize edilmiş BM25 ve eş anlamlı genişletmeyle kaynak getirir."""
    passages = _passages(text)
    scores = _bm25_scores(question, passages)
    ranked = sorted(
        ((score, item) for score, item in zip(scores, passages, strict=False) if score > 0),
        key=lambda pair: pair[0],
        reverse=True,
    )[:4]
    if not ranked:
        return "Bu soruyu yanıtlayacak açık bir bilgi belgede bulunamadı.", []
    sources = [
        f"Sayfa {page}, paragraf {paragraph}: {chunk[:360].strip()}"
        for _, (page, paragraph, chunk) in ranked
    ]
    context = "\n\n".join(
        f"[Sayfa {page}, paragraf {paragraph}]\n{chunk}" for _, (page, paragraph, chunk) in ranked
    )
    answer = ask_model(
        f"""Yalnızca aşağıdaki belge parçalarına dayanarak soruyu Türkçe cevapla.
Belgede cevap yoksa bunu açıkça söyle. Kaynak dışı bilgi, tahmin veya genel bilgi ekleme.
Kısa ve doğrudan yaz.

SORU: {question}

BELGE PARÇALARI:
{context}"""
    )
    return answer, sources
