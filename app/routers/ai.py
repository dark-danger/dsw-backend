import asyncio
import hashlib
import json
import random
import re
import ssl
import time
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import settings, _get_gemini_key
from app.core.deps import get_current_user
from app.models.all_models import User

router = APIRouter(prefix="/api/ai", tags=["AI Assistance"])

# In-memory prompt cache: hash -> (improved_text, timestamp)
_AI_CACHE: Dict[str, Tuple[str, float]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour
_MAX_CACHE_ENTRIES = 1000

# Primary and fallback Gemini models ordered by throughput and availability
GEMINI_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-pro-latest",
]

class ImproveEnglishRequest(BaseModel):
    text: str
    context: Optional[str] = None

class ImproveEnglishResponse(BaseModel):
    original_text: str
    improved_text: str


def _get_cache_key(prompt: str) -> str:
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()


def _get_cached_improvement(prompt: str) -> Optional[str]:
    key = _get_cache_key(prompt)
    if key in _AI_CACHE:
        val, ts = _AI_CACHE[key]
        if time.time() - ts < _CACHE_TTL_SECONDS:
            return val
        else:
            del _AI_CACHE[key]
    return None


def _set_cached_improvement(prompt: str, improved_text: str):
    if len(_AI_CACHE) > _MAX_CACHE_ENTRIES:
        # Evict oldest 20%
        sorted_keys = sorted(_AI_CACHE.keys(), key=lambda k: _AI_CACHE[k][1])
        for k in sorted_keys[: int(_MAX_CACHE_ENTRIES * 0.2)]:
            _AI_CACHE.pop(k, None)
    key = _get_cache_key(prompt)
    _AI_CACHE[key] = (improved_text, time.time())


def _clean_ai_output(raw_text: str) -> str:
    cleaned = raw_text.strip()
    # Remove markdown code fences if present
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.split("\n")
        if len(lines) >= 2:
            cleaned = "\n".join(lines[1:-1]).strip()

    # Remove typical conversational prefixes if model was talkative
    prefixes_to_strip = [
        r"^Here(?: is|'s) (?:the |an )?(?:improved|corrected|refined|polished) (?:version|text|sentence|output):\s*",
        r"^Improved(?: version| text)?:\s*",
        r"^Corrected(?: version| text)?:\s*",
        r"^Refined(?: version| text)?:\s*",
    ]
    for pattern in prefixes_to_strip:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    # Strip surrounding quotes if the entire text is wrapped in single/double quotes or blockquote
    if cleaned.startswith(">"):
        cleaned = re.sub(r"^>\s*", "", cleaned, flags=re.MULTILINE).strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1].strip()
    if cleaned.startswith("**") and cleaned.endswith("**") and len(cleaned) > 4:
        cleaned = cleaned[2:-2].strip()

    return cleaned


def _offline_polish_english(text: str) -> str:
    """
    Robust heuristic polisher as a safety fallback in case of total API quota/rate exhaustion.
    Fixes capitalization, spacing, common contractions, and punctuation.
    """
    s = text.strip()
    if not s:
        return s

    # Common typo and abbreviation corrections
    typo_map = {
        r"\bi\b": "I",
        r"\bim\b": "I'm",
        r"\bi am\b": "I am",
        r"\bive\b": "I've",
        r"\bid\b": "I'd",
        r"\bill\b": "I'll",
        r"\bdont\b": "don't",
        r"\bcant\b": "can't",
        r"\bwont\b": "won't",
        r"\bdoesnt\b": "doesn't",
        r"\bisnt\b": "isn't",
        r"\barent\b": "aren't",
        r"\bwasnt\b": "wasn't",
        r"\bwerent\b": "weren't",
        r"\bhavent\b": "haven't",
        r"\bhasnt\b": "hasn't",
        r"\bhadnt\b": "hadn't",
        r"\bteh\b": "the",
        r"\brecieve\b": "receive",
        r"\brecieved\b": "received",
        r"\bseperate\b": "separate",
        r"\bdefinately\b": "definitely",
        r"\boccured\b": "occurred",
        r"\buntill\b": "until",
        r"\btommorow\b": "tomorrow",
        r"\btmrw\b": "tomorrow",
        r"\bplz\b": "please",
        r"\bpls\b": "please",
        r"\bthx\b": "thanks",
        r"\bu\b": "you",
        r"\bur\b": "your",
        r"\br\b": "are",
    }
    for pattern, replacement in typo_map.items():
        s = re.sub(pattern, replacement, s, flags=re.IGNORECASE)

    # Normalize multiple whitespaces
    s = re.sub(r"[ \t]+", " ", s)
    # Fix spaces before punctuation
    s = re.sub(r"\s+([,.!?;:])", r"\1", s)
    # Ensure space after punctuation if followed by letters
    s = re.sub(r"([,.!?;:])([A-Za-z])", r"\1 \2", s)

    # Capitalize the start of each sentence
    sentences = re.split(r"([.!?]+\s*)", s)
    capitalized_chunks = []
    for chunk in sentences:
        if chunk and chunk[0].isalpha():
            chunk = chunk[0].upper() + chunk[1:]
        capitalized_chunks.append(chunk)
    s = "".join(capitalized_chunks)

    # Capitalize standalone 'i'
    s = re.sub(r"\b(i)\b", "I", s)

    # Ensure ending punctuation if it looks like a full sentence without ending punctuation
    if s and s[-1] not in ".!?":
        s += "."

    return s


def _call_gemini_api_with_retry(api_key: str, prompt: str) -> str:
    cached = _get_cached_improvement(prompt)
    if cached:
        return cached

    last_err = None
    max_retries = 3

    for attempt in range(max_retries):
        for model in GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 1024,
                },
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=12) as response:
                    res = json.loads(response.read().decode("utf-8"))
                    candidates = res.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            raw_text = parts[0].get("text", "").strip()
                            improved = _clean_ai_output(raw_text)
                            if improved:
                                _set_cached_improvement(prompt, improved)
                                return improved
            except urllib.error.HTTPError as e:
                last_err = e
                # 429: Too Many Requests, 503: Service Unavailable
                if e.code in (429, 503):
                    # Continue to next model or next attempt with brief backoff
                    time.sleep(0.3 + random.uniform(0.1, 0.3))
                    continue
                else:
                    # Other HTTP errors (404, 400, etc.) -> try next model
                    continue
            except Exception as e:
                last_err = e
                continue

        # If all models failed in this attempt, do an exponential delay before next attempt
        if attempt < max_retries - 1:
            backoff = (0.5 * (1.8 ** attempt)) + random.uniform(0.1, 0.4)
            time.sleep(backoff)

    if last_err:
        print(f"[Gemini AI Warning] All remote models exhausted with error: {last_err}. Using offline polisher fallback.")
    return ""


@router.post("/improve-english", response_model=ImproveEnglishResponse)
async def improve_english(
    payload: ImproveEnglishRequest,
    current_user: User = Depends(get_current_user),
):
    text_to_improve = payload.text.strip()
    if not text_to_improve:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    if len(text_to_improve) > 5000:
        raise HTTPException(
            status_code=400, detail="Text exceeds maximum allowed length (5000 characters)."
        )

    api_key = settings.GEMINI_API_KEY or _get_gemini_key()
    context_clause = f"Field Context: {payload.context}\n" if payload.context else ""
    prompt = (
        "You are an expert English communications editor for Geeta University Dean of Student Welfare (DSW) portal.\n"
        "Your task is to refine, correct, and improve the user's English text while STRICTLY preserving its exact meaning, tone, specific names, numbers, dates, and factual details without inventing or hallucinating any extra information.\n"
        "Fix all grammar, spelling, punctuation, capitalization, and awkward sentence structures to make it articulate, polite, and professional.\n"
        f"{context_clause}"
        "CRITICAL INSTRUCTION: Return ONLY the final improved text directly. Do NOT include any intro, markdown block quotes, explanations, options, or conversational commentary.\n\n"
        f"Original Text to improve:\n{text_to_improve}"
    )

    improved = ""
    if api_key:
        try:
            improved = await asyncio.to_thread(_call_gemini_api_with_retry, api_key, prompt)
        except Exception as e:
            print(f"[AI Improve English Error] {e}")

    # If Gemini returned empty or failed, use graceful offline polish fallback
    if not improved:
        improved = _offline_polish_english(text_to_improve)

    return ImproveEnglishResponse(
        original_text=text_to_improve,
        improved_text=improved or text_to_improve,
    )
