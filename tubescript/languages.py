"""The Whisper language catalogue.

Whisper recognises 99 spoken languages. Each entry keeps the ISO-ish code that
whisper.cpp expects, the name in its own language (what most people recognise)
and the English name (used for sorting and as a fallback label).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    native: str
    english: str

    @property
    def label(self) -> str:
        return self.native


#: Sentinel entry pinned to the top of the language menu.
AUTO = Language("auto", "Auto-detect", "Automatic detection")

#: Every language Whisper can transcribe, sorted by English name.
LANGUAGES: tuple[Language, ...] = tuple(
    sorted(
        [
            Language("af", "Afrikaans", "Afrikaans"),
            Language("am", "አማርኛ", "Amharic"),
            Language("ar", "العربية", "Arabic"),
            Language("as", "অসমীয়া", "Assamese"),
            Language("az", "Azərbaycan", "Azerbaijani"),
            Language("ba", "Башҡортса", "Bashkir"),
            Language("be", "Беларуская", "Belarusian"),
            Language("bg", "Български", "Bulgarian"),
            Language("bn", "বাংলা", "Bengali"),
            Language("bo", "བོད་ཡིག", "Tibetan"),
            Language("br", "Brezhoneg", "Breton"),
            Language("bs", "Bosanski", "Bosnian"),
            Language("ca", "Català", "Catalan"),
            Language("cs", "Čeština", "Czech"),
            Language("cy", "Cymraeg", "Welsh"),
            Language("da", "Dansk", "Danish"),
            Language("de", "Deutsch", "German"),
            Language("el", "Ελληνικά", "Greek"),
            Language("en", "English", "English"),
            Language("es", "Español", "Spanish"),
            Language("et", "Eesti", "Estonian"),
            Language("eu", "Euskara", "Basque"),
            Language("fa", "فارسی", "Persian"),
            Language("fi", "Suomi", "Finnish"),
            Language("fo", "Føroyskt", "Faroese"),
            Language("fr", "Français", "French"),
            Language("gl", "Galego", "Galician"),
            Language("gu", "ગુજરાતી", "Gujarati"),
            Language("ha", "هَوُسَه", "Hausa"),
            Language("haw", "ʻŌlelo Hawaiʻi", "Hawaiian"),
            Language("he", "עברית", "Hebrew"),
            Language("hi", "हिन्दी", "Hindi"),
            Language("hr", "Hrvatski", "Croatian"),
            Language("ht", "Kreyòl ayisyen", "Haitian Creole"),
            Language("hu", "Magyar", "Hungarian"),
            Language("hy", "Հայերեն", "Armenian"),
            Language("id", "Bahasa Indonesia", "Indonesian"),
            Language("is", "Íslenska", "Icelandic"),
            Language("it", "Italiano", "Italian"),
            Language("ja", "日本語", "Japanese"),
            Language("jw", "Basa Jawa", "Javanese"),
            Language("ka", "ქართული", "Georgian"),
            Language("kk", "Қазақша", "Kazakh"),
            Language("km", "ភាសាខ្មែរ", "Khmer"),
            Language("kn", "ಕನ್ನಡ", "Kannada"),
            Language("ko", "한국어", "Korean"),
            Language("la", "Latina", "Latin"),
            Language("lb", "Lëtzebuergesch", "Luxembourgish"),
            Language("ln", "Lingála", "Lingala"),
            Language("lo", "ລາວ", "Lao"),
            Language("lt", "Lietuvių", "Lithuanian"),
            Language("lv", "Latviešu", "Latvian"),
            Language("mg", "Malagasy", "Malagasy"),
            Language("mi", "Te Reo Māori", "Maori"),
            Language("mk", "Македонски", "Macedonian"),
            Language("ml", "മലയാളം", "Malayalam"),
            Language("mn", "Монгол", "Mongolian"),
            Language("mr", "मराठी", "Marathi"),
            Language("ms", "Bahasa Melayu", "Malay"),
            Language("mt", "Malti", "Maltese"),
            Language("my", "မြန်မာ", "Burmese"),
            Language("ne", "नेपाली", "Nepali"),
            Language("nl", "Nederlands", "Dutch"),
            Language("nn", "Nynorsk", "Nynorsk"),
            Language("no", "Norsk", "Norwegian"),
            Language("oc", "Occitan", "Occitan"),
            Language("pa", "ਪੰਜਾਬੀ", "Punjabi"),
            Language("pl", "Polski", "Polish"),
            Language("ps", "پښتو", "Pashto"),
            Language("pt", "Português", "Portuguese"),
            Language("ro", "Română", "Romanian"),
            Language("ru", "Русский", "Russian"),
            Language("sa", "संस्कृतम्", "Sanskrit"),
            Language("sd", "سنڌي", "Sindhi"),
            Language("si", "සිංහල", "Sinhala"),
            Language("sk", "Slovenčina", "Slovak"),
            Language("sl", "Slovenščina", "Slovenian"),
            Language("sn", "Shona", "Shona"),
            Language("so", "Soomaali", "Somali"),
            Language("sq", "Shqip", "Albanian"),
            Language("sr", "Српски", "Serbian"),
            Language("su", "Basa Sunda", "Sundanese"),
            Language("sv", "Svenska", "Swedish"),
            Language("sw", "Kiswahili", "Swahili"),
            Language("ta", "தமிழ்", "Tamil"),
            Language("te", "తెలుగు", "Telugu"),
            Language("tg", "Тоҷикӣ", "Tajik"),
            Language("th", "ไทย", "Thai"),
            Language("tk", "Türkmen", "Turkmen"),
            Language("tl", "Tagalog", "Tagalog"),
            Language("tr", "Türkçe", "Turkish"),
            Language("tt", "Татарча", "Tatar"),
            Language("uk", "Українська", "Ukrainian"),
            Language("ur", "اردو", "Urdu"),
            Language("uz", "Oʻzbek", "Uzbek"),
            Language("vi", "Tiếng Việt", "Vietnamese"),
            Language("yi", "ייִדיש", "Yiddish"),
            Language("yo", "Yorùbá", "Yoruba"),
            Language("zh", "中文", "Chinese"),
        ],
        key=lambda lang: lang.english.lower(),
    )
)

#: The codes whisper.cpp recognises, ``auto`` aside.
SUPPORTED_CODES: frozenset[str] = frozenset(lang.code for lang in LANGUAGES)

#: The full menu, auto-detection first.
MENU: tuple[Language, ...] = (AUTO,) + LANGUAGES

_BY_CODE: dict[str, Language] = {lang.code: lang for lang in MENU}


def find(code: str) -> Language | None:
    """Look up a language by code, case-insensitively."""
    return _BY_CODE.get(code.strip().lower())


def is_supported(code: str) -> bool:
    return code.strip().lower() in SUPPORTED_CODES or code.strip().lower() == AUTO.code
