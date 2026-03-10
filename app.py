import html
import json
import os
import re
from typing import Any, Iterable, Optional
from urllib.parse import quote
from urllib.request import urlopen

import fugashi
import streamlit as st
from pykakasi import kakasi


st.set_page_config(page_title="Japanese Reader", page_icon=":book:", layout="wide")

# Basic styling to keep ruby text legible and prevent overlap.
st.markdown(
    """
    <style>
        .reader-output {
            background: #f9fafb;
            border: 1px solid #d1d5db;
            border-radius: 0.75rem;
            padding: 1rem;
            color: #111827;
            word-break: break-word;
        }

        .line-block {
            margin-bottom: 0.9rem;
        }

        .jp-line {
            font-size: 1.45rem;
            line-height: 2.4;
        }

        .en-line {
            margin-top: 0.2rem;
            font-size: 1.02rem;
            line-height: 1.5;
            color: #1f2937;
            border-left: 3px solid #d1d5db;
            padding-left: 0.6rem;
        }

        ruby {
            ruby-position: over;
            margin: 0 0.05em;
        }

        rt {
            font-size: 0.55em;
            letter-spacing: 0.03em;
            color: #374151;
            line-height: 1.05;
        }

        .jp-token {
            cursor: help;
            border-bottom: 1px dotted #9ca3af;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_tagger() -> fugashi.Tagger:
    errors = []

    try:
        return fugashi.Tagger()
    except RuntimeError as exc:
        errors.append(f"default: {exc}")

    # Common Linux/WSL path when mecab is installed via apt.
    if os.path.exists("/etc/mecabrc"):
        try:
            return fugashi.Tagger("-r /etc/mecabrc")
        except RuntimeError as exc:
            errors.append(f"/etc/mecabrc: {exc}")

    # Self-contained fallback that does not require system mecabrc.
    try:
        import unidic_lite

        return fugashi.Tagger(f"-r /dev/null -d {unidic_lite.DICDIR}")
    except Exception as exc:
        errors.append(f"unidic-lite: {exc}")

    raise RuntimeError(
        "Failed to initialize MeCab/fugashi. "
        "Install one of these options: "
        "1) pip install unidic-lite, or "
        "2) sudo apt install mecab libmecab-dev mecab-ipadic-utf8. "
        f"Details: {' | '.join(errors)}"
    )


@st.cache_resource
def get_kakasi_converter() -> Any:
    return kakasi()


def decode_uploaded_text(raw: bytes) -> str:
    encodings = ["utf-8-sig", "utf-8", "cp932", "shift_jis", "euc_jp"]
    for enc in encodings:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clean_feature_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    val = str(value).strip()
    if not val or val == "*":
        return None
    return val


def extract_reading(token: fugashi.fugashi.UnidicNode) -> Optional[str]:
    feature = token.feature

    # Works for UniDic/IPADic where these attrs may exist.
    for attr in ("reading", "kana", "pron", "pronBase"):
        if hasattr(feature, attr):
            cleaned = _clean_feature_value(getattr(feature, attr))
            if cleaned:
                return cleaned

    # Fallback for tuple/list features (e.g., IPADic index 7 is often reading).
    if isinstance(feature, (tuple, list)):
        if len(feature) > 7:
            cleaned = _clean_feature_value(feature[7])
            if cleaned:
                return cleaned
        for item in feature:
            cleaned = _clean_feature_value(item)
            if cleaned and re.search(r"[ァ-ンぁ-ん]", cleaned):
                return cleaned

    return None


def to_romaji(reading: str, converter: Any) -> str:
    chunks: Iterable[dict] = converter.convert(reading)
    return "".join(chunk.get("hepburn") or chunk.get("kunrei") or "" for chunk in chunks)


def token_to_romaji(surface: str, reading: Optional[str], converter: Any) -> str:
    # Prefer morphological reading when available; otherwise transliterate surface.
    source = reading if reading else surface
    # Tokenizers sometimes split after a small tsu (e.g. 亡くなっ + た),
    # where converting this token alone can produce "...tsu" artifacts.
    if source.endswith(("ッ", "っ")) and surface.endswith(("ッ", "っ")):
        source = source[:-1]
    return to_romaji(source, converter).strip()


def has_japanese(text: str) -> bool:
    return bool(re.search(r"[一-龯ぁ-んァ-ン々ー]", text))


def has_kanji(text: str) -> bool:
    return bool(re.search(r"[一-龯々]", text))


def render_ruby_line(
    line: str,
    tagger: fugashi.Tagger,
    converter: Any,
    show_inline_meaning: bool,
) -> str:
    ruby_parts = []
    for token in tagger(line):
        surface = token.surface
        safe_surface = html.escape(surface)

        # Keep plain text for punctuation/ASCII-only segments.
        if not has_japanese(surface):
            ruby_parts.append(safe_surface)
            continue

        reading = extract_reading(token)
        romaji = token_to_romaji(surface, reading, converter)
        if not romaji:
            ruby_parts.append(safe_surface)
            continue

        safe_romaji = html.escape(romaji)
        ruby_html = f"<ruby>{safe_surface}<rt>{safe_romaji}</rt></ruby>"

        if show_inline_meaning and has_kanji(surface):
            gloss = lookup_word_meaning(surface)
            safe_gloss = html.escape(gloss, quote=True)
            ruby_html = f"<span class='jp-token' title='{safe_gloss}'>{ruby_html}</span>"

        ruby_parts.append(ruby_html)

    return "".join(ruby_parts)


@st.cache_resource
def get_translator() -> Any:
    try:
        from deep_translator import GoogleTranslator

        return GoogleTranslator(source="ja", target="en")
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def translate_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""

    translator = get_translator()
    if translator is not None:
        try:
            return str(translator.translate(stripped)).strip()
        except Exception:
            pass

    # Lightweight fallback using Google public endpoint.
    try:
        encoded = quote(stripped, safe="")
        url = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=ja&tl=en&dt=t&q={encoded}"
        )
        with urlopen(url, timeout=10) as response:
            payload = response.read().decode("utf-8", errors="replace")
        matches = re.findall(r'\[\[\["(.*?)"', payload)
        if matches:
            return " ".join(m.replace("\\n", " ").strip() for m in matches if m.strip())
    except Exception:
        pass

    return "[Translation unavailable]"


def build_line_block(ruby_line: str, translation: Optional[str]) -> str:
    if translation is None:
        return (
            "<div class='line-block'>"
            f"<div class='jp-line'>{ruby_line}</div>"
            "</div>"
        )

    safe_translation = html.escape(translation)
    return (
        "<div class='line-block'>"
        f"<div class='jp-line'>{ruby_line}</div>"
        f"<div class='en-line'>{safe_translation}</div>"
        "</div>"
    )


def build_reader_html(text: str, tagger: fugashi.Tagger, converter: Any, show_translation: bool) -> str:
    blocks = []
    for line in text.splitlines():
        if not line.strip():
            blocks.append("<div class='line-block'><br></div>")
            continue

        ruby_line = render_ruby_line(line, tagger, converter, show_inline_meaning=True)
        translation = translate_line(line) if show_translation else None
        blocks.append(build_line_block(ruby_line, translation))

    return "".join(blocks)


def collect_lookup_tokens(text: str, tagger: fugashi.Tagger) -> list[str]:
    seen = set()
    result = []
    for line in text.splitlines():
        for token in tagger(line):
            surface = token.surface.strip()
            if not surface or not has_japanese(surface):
                continue
            if re.fullmatch(r"[\W_]+", surface):
                continue
            if surface not in seen:
                seen.add(surface)
                result.append(surface)
    return result


@st.cache_data(show_spinner=False)
def lookup_word_meaning(word: str) -> str:
    query = quote(word, safe="")
    url = f"https://jisho.org/api/v1/search/words?keyword={query}"

    try:
        with urlopen(url, timeout=12) as response:
            payload = response.read().decode("utf-8", errors="replace")
        data = json.loads(payload)
        entries = data.get("data", [])
        if not entries:
            return "No dictionary result found."

        top = entries[0]
        japanese = top.get("japanese", [])
        senses = top.get("senses", [])

        headword = ""
        if japanese:
            first = japanese[0]
            word_text = first.get("word") or ""
            reading_text = first.get("reading") or ""
            if word_text and reading_text:
                headword = f"{word_text} ({reading_text})"
            else:
                headword = word_text or reading_text

        meaning_chunks = []
        for sense in senses[:3]:
            defs = sense.get("english_definitions", [])
            if defs:
                meaning_chunks.append(", ".join(str(d) for d in defs[:4]))

        meaning_text = " | ".join(meaning_chunks) if meaning_chunks else "Meaning unavailable."

        if headword:
            return f"{headword}: {meaning_text}"
        return meaning_text
    except Exception:
        return "Dictionary lookup is unavailable right now."


def main() -> None:
    st.title("Japanese Reader")
    st.write("Upload a Japanese `.txt` file and view Romaji plus optional English translation.")
    st.caption("Run on local network: `python3 -m streamlit run app.py --server.address 0.0.0.0`")

    uploaded_file = st.file_uploader("Upload a text file", type=["txt"])

    if not uploaded_file:
        st.info("Please upload a `.txt` file to begin.")
        return

    raw = uploaded_file.getvalue()
    text = decode_uploaded_text(raw)

    if not text.strip():
        st.warning("The uploaded file appears to be empty.")
        return

    try:
        tagger = get_tagger()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    converter = get_kakasi_converter()

    col1, col2 = st.columns([1, 1])
    with col1:
        show_translation = st.toggle("Show English translation", value=True)
    with col2:
        stream_translation = st.toggle(
            "Stream translation line by line",
            value=True,
            disabled=not show_translation,
        )

    st.subheader("Reader")

    if show_translation and stream_translation:
        lines = text.splitlines()
        render_box = st.empty()
        progress = st.progress(0)
        status = st.empty()
        blocks = []

        total = len(lines) if lines else 1
        for idx, line in enumerate(lines):
            if not line.strip():
                blocks.append("<div class='line-block'><br></div>")
            else:
                ruby_line = render_ruby_line(line, tagger, converter, show_inline_meaning=True)
                translation = translate_line(line)
                blocks.append(build_line_block(ruby_line, translation))

            render_box.markdown(
                f"<div class='reader-output'>{''.join(blocks)}</div>",
                unsafe_allow_html=True,
            )
            progress.progress((idx + 1) / total)
            status.caption(f"Translating line {idx + 1}/{total}...")

        status.caption("Translation complete.")
    else:
        reader_html = build_reader_html(text, tagger, converter, show_translation)
        st.markdown(f"<div class='reader-output'>{reader_html}</div>", unsafe_allow_html=True)

    if get_translator() is None:
        st.caption(
            "Tip: install `deep-translator` for more reliable translation: "
            "`python3 -m pip install --user deep-translator`"
        )

    st.caption("Hover over Kanji words to see in-place meanings.")


if __name__ == "__main__":
    main()