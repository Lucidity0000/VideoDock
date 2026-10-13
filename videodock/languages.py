"""BCP-47 labels are retained at the boundary; M2M100 uses base language codes."""

M2M_LANGUAGES = (
    "af am ar ast az ba be bg bn br bs ca ceb cs cy da de el en es et fa ff fi fr fy ga gd gl gu "
    "ha he hi hr ht hu hy id ig ilo is it ja jv ka kk km kn ko lb lg ln lo lt lv mg mk ml mn mr "
    "ms my ne nl no ns oc or pa pl ps pt ro ru sd si sk sl so sq sr ss su sv sw ta th tl tn tr "
    "uk ur uz vi wo xh yi yo zh zu"
).split()

NAMES = {
    "en": "English",
    "ja": "Japanese",
    "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "he": "Hebrew",
    "uk": "Ukrainian",
    "nl": "Dutch",
    "zh": "Chinese (unspecified script)",
}
NAMES.update({
    "af": "Afrikaans", "am": "Amharic", "ast": "Asturian", "az": "Azerbaijani",
    "ba": "Bashkir", "be": "Belarusian", "bg": "Bulgarian", "bn": "Bengali",
    "br": "Breton", "bs": "Bosnian", "ca": "Catalan", "ceb": "Cebuano", "cs": "Czech",
    "cy": "Welsh", "da": "Danish", "el": "Greek", "et": "Estonian", "fa": "Persian",
    "ff": "Fulah", "fi": "Finnish", "fy": "Western Frisian", "ga": "Irish", "gd": "Scottish Gaelic",
    "gl": "Galician", "gu": "Gujarati", "ha": "Hausa", "hr": "Croatian", "ht": "Haitian Creole",
    "hu": "Hungarian", "hy": "Armenian", "ig": "Igbo", "ilo": "Iloko", "is": "Icelandic",
    "jv": "Javanese", "ka": "Georgian", "kk": "Kazakh", "km": "Khmer", "kn": "Kannada",
    "lb": "Luxembourgish", "lg": "Ganda", "ln": "Lingala", "lo": "Lao", "lt": "Lithuanian",
    "lv": "Latvian", "mg": "Malagasy", "mk": "Macedonian", "ml": "Malayalam", "mn": "Mongolian",
    "mr": "Marathi", "ms": "Malay", "my": "Burmese", "ne": "Nepali", "no": "Norwegian",
    "ns": "Northern Sotho", "oc": "Occitan", "or": "Odia", "pa": "Punjabi", "pl": "Polish",
    "ps": "Pashto", "ro": "Romanian", "sd": "Sindhi", "si": "Sinhala", "sk": "Slovak",
    "sl": "Slovenian", "so": "Somali", "sq": "Albanian", "sr": "Serbian", "ss": "Swati",
    "su": "Sundanese", "sv": "Swedish", "sw": "Swahili", "ta": "Tamil", "tl": "Filipino",
    "tn": "Tswana", "tr": "Turkish", "ur": "Urdu", "uz": "Uzbek", "wo": "Wolof",
    "xh": "Xhosa", "yi": "Yiddish", "yo": "Yoruba", "zu": "Zulu", "yue": "Cantonese",
})


def model_language(tag: str) -> str:
    base = tag.replace("_", "-").split("-")[0].lower()
    base = {"iw": "he", "nb": "no", "fil": "tl"}.get(base, base)
    if base not in M2M_LANGUAGES:
        raise ValueError(f"Unsupported translation source language: {tag}. Override the source language.")
    return base


def source_tag(tag: str) -> str:
    tag = tag.replace("_", "-").removesuffix("-orig")
    if tag.lower() in {"zh-cn", "zh-sg", "zh-hans"}:
        return "zh-Hans"
    if tag.lower() in {"zh-tw", "zh-hk", "zh-mo", "zh-hant"}:
        return "zh-Hant"
    return tag


def supported_targets() -> tuple[str, ...]:
    return tuple(code for code in M2M_LANGUAGES if code != "zh") + ("zh-Hans", "zh-Hant")


def language_name(tag: str) -> str:
    return NAMES.get(tag, tag)


ISO639_2 = {
    "af": "afr",
    "am": "amh",
    "ar": "ara",
    "ast": "ast",
    "az": "aze",
    "ba": "bak",
    "be": "bel",
    "bg": "bul",
    "bn": "ben",
    "br": "bre",
    "bs": "bos",
    "ca": "cat",
    "ceb": "ceb",
    "cs": "ces",
    "cy": "cym",
    "da": "dan",
    "de": "deu",
    "el": "ell",
    "en": "eng",
    "es": "spa",
    "et": "est",
    "fa": "fas",
    "ff": "ful",
    "fi": "fin",
    "fr": "fra",
    "fy": "fry",
    "ga": "gle",
    "gd": "gla",
    "gl": "glg",
    "gu": "guj",
    "ha": "hau",
    "he": "heb",
    "hi": "hin",
    "hr": "hrv",
    "ht": "hat",
    "hu": "hun",
    "hy": "hye",
    "id": "ind",
    "ig": "ibo",
    "ilo": "ilo",
    "is": "isl",
    "it": "ita",
    "ja": "jpn",
    "jv": "jav",
    "ka": "kat",
    "kk": "kaz",
    "km": "khm",
    "kn": "kan",
    "ko": "kor",
    "lb": "ltz",
    "lg": "lug",
    "ln": "lin",
    "lo": "lao",
    "lt": "lit",
    "lv": "lav",
    "mg": "mlg",
    "mk": "mkd",
    "ml": "mal",
    "mn": "mon",
    "mr": "mar",
    "ms": "msa",
    "my": "mya",
    "ne": "nep",
    "nl": "nld",
    "no": "nob",
    "ns": "nso",
    "oc": "oci",
    "or": "ori",
    "pa": "pan",
    "pl": "pol",
    "ps": "pus",
    "pt": "por",
    "ro": "ron",
    "ru": "rus",
    "sd": "snd",
    "si": "sin",
    "sk": "slk",
    "sl": "slv",
    "so": "som",
    "sq": "sqi",
    "sr": "srp",
    "ss": "ssw",
    "su": "sun",
    "sv": "swe",
    "sw": "swa",
    "ta": "tam",
    "th": "tha",
    "tl": "tgl",
    "tn": "tsn",
    "tr": "tur",
    "uk": "ukr",
    "ur": "urd",
    "uz": "uzb",
    "vi": "vie",
    "wo": "wol",
    "xh": "xho",
    "yi": "yid",
    "yo": "yor",
    "zh": "zho",
    "zu": "zul",
}


def container_language(tag: str) -> str:
    base = tag.split("+")[0].split("-")[0]
    return ISO639_2.get(base, "und")


def chinese_text(text: str, script: str) -> str:
    if script not in {"zh-Hans", "zh-Hant"}:
        return text
    from opencc import OpenCC

    return OpenCC("t2s" if script == "zh-Hans" else "s2t").convert(text)
