"""
Translation endpoint for the mobile app UI.

POST /translate
  Body: { "language": "es", "strings": ["Submit", "Retry", ...] }
  Returns: { "Submit": "Enviar", "Retry": "Reintentar", ... }

Claude translates all strings in a single call. Results are meant to be
cached on the device by language code.
"""

import json
import os

import anthropic
from dotenv import load_dotenv
from fastapi import APIRouter
from pydantic import BaseModel

load_dotenv()

router = APIRouter()

ANTHROPIC_LLM_MODEL = os.getenv("ANTHROPIC_LLM_MODEL")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


class TranslateRequest(BaseModel):
    language: str        # ISO 639-1 code, e.g. "es", "fr", "zh"
    strings: list[str]   # list of English UI strings to translate


@router.post("/translate")
def translate_ui(body: TranslateRequest):
    """
    Translate a batch of UI strings into the requested language using Claude.
    Returns a JSON object mapping each original string to its translation.
    """
    if body.language == "en":
        # No translation needed — return strings as-is
        return {s: s for s in body.strings}

    strings_json = json.dumps(body.strings, ensure_ascii=False)

    prompt = (
        f"Translate the following JSON array of English UI strings into {body.language} "
        f"(ISO 639-1 code). Return ONLY a valid JSON object where each key is the original "
        f"English string and each value is the translation. Do not add any explanation.\n\n"
        f"{strings_json}"
    )

    resp = client.messages.create(
        model=ANTHROPIC_LLM_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = resp.content[0].text.strip()

    # Strip markdown code fences if Claude wraps the response
    if raw.startswith("```"):
        # Remove opening fence (```json or ```)
        raw = raw[raw.index("\n") + 1:]
        # Remove closing fence
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]
        raw = raw.strip()

    try:
        translations: dict = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: return all strings untranslated rather than crashing
        return {s: s for s in body.strings}

    # Ensure every requested string has a fallback to English if Claude missed it
    for s in body.strings:
        if s not in translations:
            translations[s] = s

    return translations
