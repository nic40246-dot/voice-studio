import os
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from app.core.audio_processing import clean_prosody_boundaries

def _get_api_credentials() -> tuple[str, str, str]:
    """
    Resolves (base_url, api_key, model) from environment or local Hermes configuration.
    """
    env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if env_key:
        return "https://generativelanguage.googleapis.com/v1beta/openai", env_key, "gemini-2.0-flash"

    # Check local Hermes config
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    config_path = Path(local_appdata) / "hermes" / "config.yaml"
    if config_path.exists():
        try:
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            model_cfg = cfg.get("model", {})
            base_url = model_cfg.get("base_url", "http://127.0.0.1:20128/v1")
            api_key = model_cfg.get("api_key", "")
            model_name = model_cfg.get("default", "ag/gemini-3.8-flash-low")
            if "medium" in model_name or "high" in model_name:
                # Use flash-low for near-instant 2s response without heavy reasoning latency
                model_name = "ag/gemini-3.8-flash-low"
            if api_key:
                return base_url, api_key, model_name
        except Exception:
            pass

    return "http://127.0.0.1:20128/v1", "", "ag/gemini-3.8-flash-low"


TONE_STYLES = {
    "engaging": {
        "label": "🎙️ Engaging Conversational (Default)",
        "desc": "Natural pitch modulation, conversational rhythm, lively delivery",
        "exaggeration": 0.75,
        "speed": 1.00,
        "temperature": 0.82,
        "pause_ms": 250,
    },
    "energetic_hook": {
        "label": "🚀 High Energy / Title Hook",
        "desc": "Wide pitch range, enthusiastic, dynamic inflection for intros & launches",
        "exaggeration": 0.80,
        "speed": 1.04,
        "temperature": 0.82,
        "pause_ms": 220,
    },
    "deep_dive": {
        "label": "🔬 Authoritative Deep-Dive",
        "desc": "Grounded baseline, clear consonant pacing for technical specs & data",
        "exaggeration": 0.65,
        "speed": 0.95,
        "temperature": 0.78,
        "pause_ms": 300,
    },
    "key_takeaway": {
        "label": "💡 Emphatic Key Takeaway",
        "desc": "Punchy articulation with deliberate thought pauses for memorable conclusions",
        "exaggeration": 0.78,
        "speed": 0.98,
        "temperature": 0.80,
        "pause_ms": 350,
    },
}


def _parse_llm_response(raw_text: str) -> str:
    """
    Parses LLM response whether returned as standard OpenAI JSON or SSE data stream.
    """
    raw_text = raw_text.strip()
    if raw_text.startswith("{") and '"choices"' in raw_text:
        try:
            data = json.loads(raw_text)
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

    chunks = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    chunks.append(content)
        except Exception:
            pass
    if chunks:
        return "".join(chunks).strip()
    return raw_text


def _clean_markdown_code_block(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) >= 2:
            content = "\n".join(lines[1:-1]).strip()
    return content


def detect_slide_tone_heuristic(
    slide_text: str,
    slide_index: int = 0,
    total_slides: int = 1,
) -> dict:
    """
    Fast, deterministic heuristic for slide tone and cadence bounds.
    Ensures no two consecutive slides share identical pitch variance and cadence.
    """
    text_lower = slide_text.lower()

    if slide_index == 0:
        return {
            "tone_style": "energetic_hook",
            "exaggeration": 1.00,
            "speed": 1.04,
            "pause_ms": 220,
            "reason": "Opening slide: High energy & wide pitch dynamic to hook audience",
        }

    if total_slides > 1 and slide_index == total_slides - 1:
        return {
            "tone_style": "key_takeaway",
            "exaggeration": 0.90,
            "speed": 0.98,
            "pause_ms": 350,
            "reason": "Concluding slide: Deliberate pacing and emphatic pauses for memorability",
        }

    data_indicators = [
        "%", "$", "€", "latency", "throughput", "architecture", "database",
        "api", "table", "q1", "q2", "q3", "q4", "metric", "kpi", "performance",
    ]
    if any(ind in text_lower for ind in data_indicators) or (len(slide_text.splitlines()) > 4 and any(c.isdigit() for c in slide_text)):
        return {
            "tone_style": "deep_dive",
            "exaggeration": 0.65,
            "speed": 0.95,
            "pause_ms": 300,
            "reason": "Technical/data slide: Clear articulation and grounded pitch baseline",
        }

    # Alternating cadence so consecutive slides never sound identical
    cycle = slide_index % 3
    if cycle == 0:
        exag = 0.88
        spd = 1.02
    elif cycle == 1:
        exag = 0.82
        spd = 1.00
    else:
        exag = 0.85
        spd = 0.98

    return {
        "tone_style": "engaging",
        "exaggeration": exag,
        "speed": spd,
        "pause_ms": 250,
        "reason": f"Narrative slide: Conversational cadence with {exag:.2f} dynamic range",
    }


def auto_direct_slide_with_gemini(
    raw_text: str,
    slide_index: int = 0,
    total_slides: int = 1,
    language: str = "en",
) -> dict:
    """
    Automatically classifies slide context, selects the optimal tone style & prosody bounds,
    and rewrites bullet points into spoken narration in a single fast LLM turn.
    """
    base_url, api_key, model_name = _get_api_credentials()
    fallback = detect_slide_tone_heuristic(raw_text, slide_index, total_slides)

    if not api_key:
        fallback["narration"] = raw_text
        return fallback

    lang_name = "German" if language.lower().startswith("de") else "English"

    system_prompt = (
        f"You are an executive audio speech coach. "
        f"Analyze this {lang_name} presentation slide (Slide {slide_index + 1} of {total_slides}) "
        f"and decide its ideal delivery tone and spoken narration. "
        f"Output a valid JSON object with EXACTLY these keys:\n"
        f'- "tone_style": one of ["energetic_hook", "engaging", "deep_dive", "key_takeaway"]\n'
        f'- "exaggeration": float between 0.60 (steady) and 1.05 (animated)\n'
        f'- "speed": float between 0.92 and 1.06\n'
        f'- "pause_ms": int between 200 and 350\n'
        f'- "narration": the original text enhanced with oral pitch markers (..., —, !, :) and natural pauses without paraphrasing, dropping content, or expanding/altering acronyms (keep "SEFE", "GPT", "AI" exactly verbatim)\n'
        f'- "reason": one short sentence explaining why this tone fits the slide\n'
        f"Rules: Return RAW JSON only, no markdown formatting."
    )

    user_prompt = (
        f"Slide Index: {slide_index} of {total_slides}\n"
        f"Slide Content:\n{raw_text.strip()}\n"
    )

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
        "stream": False,
    }

    endpoint = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw_body = resp.read().decode("utf-8", errors="ignore")
            content = _parse_llm_response(raw_body)
            content = _clean_markdown_code_block(content)

            # Extract json substring if extra prose exists
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                tone_style = data.get("tone_style", fallback["tone_style"])
                if tone_style not in TONE_STYLES:
                    tone_style = fallback["tone_style"]
                exaggeration = float(data.get("exaggeration", fallback["exaggeration"]))
                exaggeration = max(0.40, min(1.20, exaggeration))
                speed = float(data.get("speed", fallback["speed"]))
                speed = max(0.70, min(1.40, speed))
                pause_ms = int(data.get("pause_ms", fallback["pause_ms"]))
                pause_ms = max(150, min(500, pause_ms))
                narration = str(data.get("narration", "")).strip() or raw_text
                narration = clean_prosody_boundaries(narration)
                reason = str(data.get("reason", fallback["reason"])).strip()

                return {
                    "tone_style": tone_style,
                    "exaggeration": exaggeration,
                    "speed": speed,
                    "pause_ms": pause_ms,
                    "narration": narration,
                    "reason": reason,
                }
    except Exception:
        pass

    fallback["narration"] = raw_text
    return fallback


def humanize_script_with_gemini(
    raw_text: str,
    language: str = "en",
    tone: str = "engaging",
    custom_instructions: str = "",
) -> str:
    """
    Transforms dry, written slide bullet points or notes into lively spoken narration.
    Inserts oral punctuation (ellipses, dashes, colons) that guide TTS pitch dynamics.
    """
    base_url, api_key, model_name = _get_api_credentials()
    if not api_key:
        raise RuntimeError("No Gemini API key found in environment or Hermes config.")

    lang_name = "German" if language.lower().startswith("de") else "English"
    tone_info = TONE_STYLES.get(tone, TONE_STYLES["engaging"])

    system_prompt = (
        f"You are a world-class executive speech coach and prosody director. "
        f"Your mission is to format this {lang_name} presentation text with oral prosody punctuation "
        f"so a neural Text-to-Speech engine produces rich, dynamic vocal pitch contours (melodic up-and-down intonation, "
        f"expressive clause emphasis, and natural breathing pauses) without sounding flat, monotone, or robotic. "
        f"Delivery tone: {tone_info['label']} ({tone_info['desc']}).\n"
        f"CRITICAL GUIDELINES:\n"
        f"1. SPOKEN HUMAN CADENCE & CONVERSATIONAL CONNECTORS:\n"
        f"   - Add natural conversational markers, transitions, and spoken connectors where a real presenter would pause or connect ideas (e.g. 'Now...', 'Well...', 'So...', 'Let\'s...', 'Um...', 'Why...').\n"
        f"   - Retain full grammatical sentence structures and complete text integrity—DO NOT drop articles ('a', 'the'), DO NOT compress sentences into bullet-style telegram fragments, and DO NOT delete original content.\n"
        f"   - NEVER expand, translate, hyphenate, or spell out company names or acronyms (keep 'SEFE', 'GPT', 'AI' EXACTLY as written; NEVER write 'Securing Energy for Europe', 'S.E.F.E.', 'S-E-F-E', 'G.P.T.', or 'A.I.').\n"
        f"2. SYNTACTIC PROSODIC BOUNDARY RULES (NEVER BREAK FUNCTIONAL CONSTITUENTS):\n"
        f"   - Pauses (...) and expressive emphasis (—) MUST ONLY appear at major clause boundaries, after complete thought units, or after opening conversational markers ('Now...', 'Well...').\n"
        f"   - NEVER place a pause (..., —, or ,) directly after prepositions ('by', 'to', 'in', 'at', 'on', 'with', 'for', 'about', 'before', 'after', 'from'), articles ('a', 'an', 'the'), modal verbs ('will', 'can', 'must'), or conjunctions ('whether', 'if', 'that').\n"
        f"   - Prepositional phrases MUST stay together: write 'By remaining in the meeting... you agree' NEVER 'By... remaining in the meeting'.\n"
        f"3. DYNAMIC PITCH & PROSODY FORMATTING (UP-AND-DOWN VOCAL CONTOURS):\n"
        f"   - Insert oral punctuation to force pitch movement and musicality across sentences:\n"
        f"     * Ellipses (...) for natural breath pauses and cadence drops at clause boundaries.\n"
        f"     * Em-dashes (—) for expressive pitch shifts, clause separation, and dramatic emphasis.\n"
        f"     * Exclamation points (!) on welcoming, emphatic, or action-oriented phrases to drive dynamic pitch peaks.\n"
        f"     * Question marks (?) where pitch should rise.\n"
        f"     * Commas (,) to break flat run-on phrasing into musical, rhythmic spoken phrases.\n"
        f"     * Colons (:) before key announcements or reveals.\n"
        f"4. If input is German, use natural German spoken connectors ('Nun ja...', 'Also...', 'Sehen wir uns...', 'Lassen Sie uns...') with flawless grammar.\n"
        f"5. Output ONLY the prosody-directed spoken text ready for speech synthesis. Do NOT include markdown labels, quotes, or meta commentary."
    )

    user_content = raw_text.strip()
    if custom_instructions:
        user_content += f"\n\nAdditional speaker guidance: {custom_instructions}"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "stream": False,
    }

    endpoint = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            # Clean any wrapping markdown code blocks if emitted
            if content.startswith("```") and content.endswith("```"):
                lines = content.splitlines()
                content = "\n".join(lines[1:-1]).strip()
            return clean_prosody_boundaries(content)
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini API Error (HTTP {e.code}): {err_msg}")
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Gemini: {str(e)}")


def analyze_deck_storyline(slides: list[dict], language: str = "en") -> list[dict]:
    """
    Analyzes presentation storyline arc (Opening Hook -> Narrative Story -> Deep Dive -> Conclusion).
    Assigns tone categories and cadence to each slide WITHOUT changing user script text.
    """
    total = len(slides)
    if total == 0:
        return []

    base_url, api_key, model_name = _get_api_credentials()
    script_key = "script_en" if language.lower().startswith("en") else "script_de"

    # Fallback heuristic if no API or error
    results = []
    for i, s in enumerate(slides):
        script = s.get(script_key, "").strip() or s.get("notes", "").strip() or s.get("body_text", "").strip()
        h = detect_slide_tone_heuristic(script, i, total)
        lower = script.lower()
        if any(w in lower for w in ["story", "imagine", "scenario", "customer", "journey", "problem", "challenge"]):
            h["tone_style"] = "engaging"
            h["reason"] = "Narrative Story: Conversational storytelling cadence"
        elif i == 0:
            h["tone_style"] = "energetic_hook"
            h["reason"] = "Opening Slide: Energetic hook to capture audience interest"
        elif i == total - 1:
            h["tone_style"] = "key_takeaway"
            h["reason"] = "Closing Slide: Memorable takeaway with deliberate emphasis"

        slide_copy = dict(s)
        slide_copy["tone_style"] = h["tone_style"]
        slide_copy["exaggeration"] = h["exaggeration"]
        slide_copy["speed"] = h["speed"]
        slide_copy["pause_ms"] = h["pause_ms"]
        slide_copy["tone_reason"] = h["reason"]
        results.append(slide_copy)

    if not api_key:
        return results

    outline = []
    for i, s in enumerate(slides):
        title = s.get("title", f"Slide {i+1}")
        script = s.get(script_key, "").strip() or s.get("notes", "").strip() or s.get("body_text", "").strip()
        outline.append(f"Slide {i+1}: Title: {title}\nScript/Notes: {script[:200]}")

    deck_text = "\n\n".join(outline)

    system_prompt = (
        "You are an executive speech and storytelling director. "
        "Analyze the narrative arc of this entire presentation deck. "
        "Notice what is the opening hook, what is a story/scenario, what is data/deep-dive, and what is the conclusion. "
        "For each slide, assign:\n"
        '- "slide_index": int (0-based)\n'
        '- "tone_style": "energetic_hook" (opening hook), "engaging" (narrative/story), "deep_dive" (technical/data), or "key_takeaway" (conclusion)\n'
        '- "exaggeration": float (0.60 to 1.05)\n'
        '- "speed": float (0.92 to 1.06)\n'
        '- "reason": short explanation (e.g. "Opening hook", "Customer story", "Technical architecture", "Closing summary")\n'
        "Output RAW JSON array of objects: [{\"slide_index\": 0, ...}]. Do NOT rewrite or include script text."
    )

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": deck_text},
        ],
        "temperature": 0.3,
        "stream": False,
    }

    endpoint = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw_body = resp.read().decode("utf-8", errors="ignore")
            content = _parse_llm_response(raw_body)
            content = _clean_markdown_code_block(content)
            match = re.search(r"\[.*\]", content, re.DOTALL)
            if match:
                items = json.loads(match.group(0))
                for item in items:
                    idx = int(item.get("slide_index", -1))
                    if 0 <= idx < total:
                        t = item.get("tone_style", results[idx]["tone_style"])
                        if t in TONE_STYLES:
                            results[idx]["tone_style"] = t
                        results[idx]["exaggeration"] = max(0.40, min(1.20, float(item.get("exaggeration", results[idx]["exaggeration"]))))
                        results[idx]["speed"] = max(0.70, min(1.40, float(item.get("speed", results[idx]["speed"]))))
                        results[idx]["tone_reason"] = str(item.get("reason", results[idx]["tone_reason"]))
    except Exception:
        pass

    return results
