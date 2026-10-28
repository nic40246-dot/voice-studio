import json
import re
from pathlib import Path
from app.config import DATA_DIR

PRONUNCIATION_FILE = DATA_DIR / "pronunciation_rules.json"

DEFAULT_RULES = {
    "en": {
      "API": "A P I",
      "SaaS": "Sass",
      "GUI": "Gooey",
      "SQL": "Sequel",
      "AI": "Ay-Eye",
      "GPT": "Gee Pee Tee",
      "Gpt": "Gee Pee Tee",
      "PPTX": "P P T X",
      "Teams": "Teems",
      "B2B": "B to B",
      "e.g.": "for example",
      "i.e.": "that is",
      "etc.": "et cetera",
      "vs.": "versus",
      "Dr.": "Doctor",
      "Mr.": "Mister",
      "Ms.": "Miss",
      "Mrs.": "Missus",
      "Prof.": "Professor",
      "SEFE": "Sefe",
      "Sefe": "Sefe",
      "sefe": "Sefe",
      "%": " percent",
      "$": " dollar ",
      "€": " euro ",
    },
    "de": {
      "API": "A P I",
      "AI": "Ay-Eye",
      "GPT": "Gee Pee Tee",
      "Gpt": "Gee Pee Tee",
      "KI": "K I",
      "SaaS": "Sass",
      "B2B": "B to B",
      "Teams": "Teems",
      "PowerPoint": "Pauer Point",
      "SEFE": "Sefe",
      "Sefe": "Sefe",
      "sefe": "Sefe",
        "z.B.": "zum Beispiel",
        "bzw.": "beziehungsweise",
        "d.h.": "das heißt",
        "usw.": "und so weiter",
        "ca.": "circa",
        "Nr.": "Nummer",
        "Dr.": "Doktor",
        "Prof.": "Professor",
        "%": " Prozent",
        "€": " Euro",
        "$": " Dollar ",
    }
}


def expand_acronyms(text: str) -> str:
    """
    Expands consecutive uppercase letters (acronyms of 2+ letters) into individual spaced characters
    so that TTS models enunciate each letter by its alphabet name (e.g. AI -> A I, CPU -> C P U, APIs -> A P I s).
    """
    if not text:
        return text

    # Dotted or hyphenated acronyms like A.I., S.E.F.E., G.P.T., S-E-F-E, G-P-T, A-I
    text = re.sub(r"\bS[.\-]E[.\-]F[.\-]E\b", "Sefe", text, flags=re.IGNORECASE)
    text = re.sub(r"\bG[.\-]P[.\-]T\b", "Gee Pee Tee", text, flags=re.IGNORECASE)
    text = re.sub(r"\bA[.\-]I\b", "Ay-Eye", text, flags=re.IGNORECASE)

    dotted_pattern = re.compile(r"\b(?:[A-Z]\.)+(?:[A-Z]\.?|\b)")
    def _repl_dotted(m):
        clean = m.group(0).replace(".", "").upper()
        if clean == "AI":
            return "Ay-Eye"
        if clean == "SEFE":
            return "Sefe"
        if clean == "GPT":
            return "Gee Pee Tee"
        return re.sub(r"\s+", " ", m.group(0).replace(".", " ").strip())

    text = dotted_pattern.sub(_repl_dotted, text)

    # Exclude words handled by specific pronunciation overrides
    EXCLUDED_ACRONYMS = {"SEFE", "AI", "GPT"}

    # Consecutive uppercase letters (2 or more), with optional 's or s suffix
    def _repl_caps(m):
        word = m.group(1)
        if word in EXCLUDED_ACRONYMS:
            return m.group(0)
        letters = " ".join(list(word))
        suffix = m.group(2)
        if suffix in ("s", "'s"):
            return f"{letters} {suffix}"
        return letters

    text = re.sub(r"\b([A-Z]{2,})(\'?s)?\b", _repl_caps, text)
    return text


class PronunciationManager:
    def __init__(self, file_path: Path = PRONUNCIATION_FILE):
        self.file_path = file_path
        self.rules = self._load_rules()

    def _load_rules(self) -> dict:
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        self._save_rules(DEFAULT_RULES)
        return DEFAULT_RULES

    def _save_rules(self, data: dict):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_rules_for_language(self, lang: str) -> dict:
        return self.rules.get(lang.lower(), {})

    def set_rule(self, lang: str, term: str, replacement: str):
        lang = lang.lower()
        if lang not in self.rules:
            self.rules[lang] = {}
        self.rules[lang][term] = replacement
        self._save_rules(self.rules)

    def remove_rule(self, lang: str, term: str):
        lang = lang.lower()
        if lang in self.rules and term in self.rules[lang]:
            del self.rules[lang][term]
            self._save_rules(self.rules)

    def apply(self, text: str, lang: str) -> str:
        self.rules = self._load_rules()
        lang = lang.lower()
        lang_rules = self.rules.get(lang, {})
        result = text
        if lang_rules:
            for term, replacement in sorted(lang_rules.items(), key=lambda x: len(x[0]), reverse=True):
                if re.match(r"^\w.*\w$", term):
                    # Standard alphanumeric word
                    pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
                    result = pattern.sub(replacement, result)
                else:
                    # Punctuation or symbol (e.g. z.B., e.g., %, €)
                    pattern = re.compile(rf"(^|\s){re.escape(term)}(?=\s|[.,!?:;]|$)", re.IGNORECASE)
                    result = pattern.sub(rf"\g<1>{replacement}", result)

        # Expand acronyms / consecutive uppercase letters (e.g. AI -> A I, CPU -> C P U, APIs -> A P I s)
        result = expand_acronyms(result)
        return result
