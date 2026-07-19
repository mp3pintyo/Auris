"""LLM-backed literary character and dialogue-speaker analysis.

The client intentionally uses only the Python standard library.  LM Studio,
Ollama, llama.cpp and other local servers can all expose the OpenAI-compatible
``/v1`` API without adding a hosted service or another runtime dependency.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from core import characters
from core.enrichment import build_speaker_units

log = logging.getLogger(__name__)

_GENDERS = {"male", "female", "unknown"}
_NON_SPEAKERS = {
    "", "narrator", "narrátor", "narration", "elbeszélő", "unknown",
    "ismeretlen", "none", "null",
}


class LLMAnalysisError(RuntimeError):
    """Raised when the configured local language-model endpoint cannot analyze."""


@dataclass
class CharacterInfo:
    name: str
    gender: str = "unknown"
    aliases: set[str] = field(default_factory=set)


def _api_url(base_url: str, suffix: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise LLMAnalysisError("The LLM base URL is empty.")
    if base.endswith("/chat/completions") and suffix == "chat/completions":
        return base
    if base.endswith("/models") and suffix == "models":
        return base
    return f"{base}/{suffix}"


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    api_key: str = "",
    timeout: float = 30,
) -> dict:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise LLMAnalysisError(
            f"LLM HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMAnalysisError(f"Cannot reach the LLM endpoint: {exc}") from exc
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMAnalysisError("The LLM endpoint returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise LLMAnalysisError("The LLM endpoint returned an unexpected response.")
    return result


def list_models(base_url: str, api_key: str = "", timeout: float = 15) -> list[str]:
    response = _request_json(
        _api_url(base_url, "models"), api_key=api_key, timeout=timeout
    )
    models = response.get("data")
    if not isinstance(models, list):
        raise LLMAnalysisError("The endpoint did not return an OpenAI-compatible model list.")
    return [
        str(item.get("id")).strip()
        for item in models
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]


def _response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "dialogues": {
                "type": "array",
                "items": {"type": "string"},
            },
            "characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "gender": {
                            "type": "string",
                            "enum": ["male", "female", "unknown"],
                        },
                        "aliases": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["name", "gender", "aliases"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["dialogues", "characters"],
        "additionalProperties": False,
    }


_SYSTEM_PROMPT = """You are a meticulous literary dialogue-attribution engine.
Identify who actually speaks each candidate dialogue unit using the surrounding
narration, alternating turns, attribution clauses, aliases, titles and scene
continuity.

Hard rules:
- Return an assignment only for a [D id] unit that contains spoken dialogue.
- Never assign [N id] narration and never use Narrator as a character.
- Use one stable canonical name per person throughout the book.
- Reuse the exact spelling of names found in the supplied text or known roster.
- Never invent, expand or "correct" a person's forename or surname.
- A role such as Professor, Waiter or Police Officer is allowed only when the
  text gives no name. Keep distinct anonymous roles distinct when the context is
  clear.
- If the speaker truly cannot be inferred, use an empty speaker string and low
  confidence instead of guessing.
- Gender is male, female or unknown. Do not infer gender from stereotypes.
- Include in characters only non-empty speakers used in this numbered text,
  not the entire known roster.
- Include at most five aliases per character, and only aliases literally
  present in this numbered text.
"""


def _known_roster(infos: dict[str, CharacterInfo]) -> str:
    if not infos:
        return "(none yet)"
    # A full-book roster can become large enough that some local models copy it
    # into every answer or lose focus on the actual chapter. The first twenty
    # canonical names retain continuity for the main cast without that failure
    # mode; chapter text remains the source of truth.
    return "\n".join(f"- {info.name}" for info in list(infos.values())[:20])


def _batch_prompt(
    *,
    title: str,
    author: str,
    chapter_blocks: list[dict],
    infos: dict[str, CharacterInfo],
) -> str:
    rendered_chapters = []
    for block in chapter_blocks:
        rendered = "\n".join(
            f"[{'D' if unit['dialogue_candidate'] else 'N'} {unit['global_id']}] "
            f"{unit['text']}"
            for unit in block["units"]
        )
        rendered_chapters.append(
            f"\n=== CHAPTER: {block['chapter']['title']} ===\n{rendered}"
        )
    return f"""BOOK: {title}
AUTHOR: {author}

KNOWN CANONICAL ROSTER FROM EARLIER CHAPTERS:
{_known_roster(infos)}

Return JSON matching the supplied schema. Analyze every [D id], but include only
actual spoken dialogue in dialogues. Preserve exact source names. An attribution
fragment such as "- he said" or "- felelte Gorcsev" is narration, not dialogue.
Use one compact string per spoken unit, ordered by id: "12|Canonical Name".
Do not group non-consecutive turns and do not omit an inferable spoken unit.
The exact JSON shape is:
{{"dialogues":["12|Canonical Name"],"characters":[{{"name":"Canonical Name",
"gender":"male|female|unknown","aliases":["literal alias"]}}]}}

NUMBERED TEXT UNITS:
{''.join(rendered_chapters)}
"""


def _parse_message_json(response: dict) -> dict:
    try:
        message = response["choices"][0]["message"]
        content = message.get("content")
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise LLMAnalysisError("The LLM response has no assistant message.") from exc
    if isinstance(content, list):
        content = "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        )
    content = str(content or "").strip()
    if not content:
        reasoning = str(message.get("reasoning_content") or "").strip()
        if reasoning:
            raise LLMAnalysisError(
                "The model spent the output budget on reasoning and returned no JSON. "
                "Use reasoning_effort=none or increase the output-token limit."
            )
        raise LLMAnalysisError("The model returned an empty response.")
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMAnalysisError(f"The model returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMAnalysisError("The model response must be a JSON object.")
    return parsed


def _chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: float,
    max_tokens: int,
) -> dict:
    base_payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    schema_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "speaker_attribution",
            "strict": True,
            "schema": _response_schema(),
        },
    }
    attempts = [
        {**base_payload, "reasoning_effort": "none", "response_format": schema_format},
        {**base_payload, "response_format": schema_format},
        base_payload,
    ]
    last_error: Exception | None = None
    for payload in attempts:
        try:
            response = _request_json(
                _api_url(base_url, "chat/completions"),
                method="POST",
                payload=payload,
                api_key=api_key,
                timeout=timeout,
            )
            return _parse_message_json(response)
        except LLMAnalysisError as exc:
            last_error = exc
            # Retry only request-compatibility failures. Re-running a completed
            # but malformed/empty generation can multiply a long import by
            # three without improving the answer.
            message = str(exc).lower()
            if "llm http 400" not in message and "llm http 422" not in message:
                break
    raise LLMAnalysisError(str(last_error or "LLM request failed."))


def _clean_name(name: object) -> str:
    value = re.sub(r"\s+", " ", str(name or "")).strip(" \t\r\n.,;:!?\"'„”")
    # Some models append an unsolicited compact gender field despite the
    # requested ``id|name`` format.
    value = value.split("|", 1)[0].strip()
    comma_parts = [part.strip() for part in value.split(",")]
    if (
        len(comma_parts) == 2
        and len(comma_parts[0].split()) > 1
        and 1 <= len(comma_parts[1].split()) <= 3
    ):
        # E.g. "Ide figyelj, Jázmin" is an utterance fragment, not a name.
        value = comma_parts[1]
    if value.casefold() in _NON_SPEAKERS:
        return ""
    return value[:120]


def _lookup_canonical(
    name: str,
    infos: dict[str, CharacterInfo],
    source_text: str,
) -> str:
    folded = name.casefold()
    for info in infos.values():
        if folded == info.name.casefold() or any(
            folded == alias.casefold() for alias in info.aliases
        ):
            return info.name

    # Never accept a newly invented multi-part proper name. If its exact text
    # does not occur in the source, reduce it to a unique known/source token.
    if " " in name and folded not in source_text.casefold():
        tokens = [token for token in re.split(r"\s+", name) if len(token) > 2]
        matches = {
            info.name
            for token in tokens
            for info in infos.values()
            if token.casefold() in {
                info.name.casefold(),
                *(alias.casefold() for alias in info.aliases),
                *(part.casefold() for part in info.name.split()),
            }
        }
        if len(matches) == 1:
            return matches.pop()
        source_tokens = [
            token for token in tokens
            if re.search(rf"\b{re.escape(token)}\b", source_text, re.IGNORECASE)
        ]
        if len(source_tokens) == 1:
            return source_tokens[0]
    return name


def _merge_character(
    infos: dict[str, CharacterInfo],
    *,
    name: str,
    gender: str = "unknown",
    aliases: list | None = None,
    source_text: str = "",
) -> str:
    cleaned = _clean_name(name)
    if not cleaned:
        return ""
    repaired = cleaned.translate(str.maketrans({"õ": "ő", "Õ": "Ő", "û": "ű", "Û": "Ű"}))
    if (
        repaired != cleaned
        and (
            repaired.casefold() in source_text.casefold()
            or bool(re.search(r"[őűŐŰ]", source_text))
        )
    ):
        cleaned = repaired
    canonical = _lookup_canonical(cleaned, infos, source_text)
    key = canonical.casefold()
    existing_key = next(
        (item_key for item_key, info in infos.items() if info.name.casefold() == key),
        None,
    )
    if existing_key is None:
        existing_key = key
        infos[existing_key] = CharacterInfo(name=canonical)
    info = infos[existing_key]
    normalized_gender = str(gender or "unknown").strip().lower()
    if normalized_gender not in _GENDERS:
        normalized_gender = "unknown"
    if info.gender == "unknown" and normalized_gender != "unknown":
        info.gender = normalized_gender
    if cleaned.casefold() != info.name.casefold():
        info.aliases.add(cleaned)
    for alias in aliases or []:
        alias_clean = _clean_name(alias)
        if alias_clean and alias_clean.casefold() != info.name.casefold():
            info.aliases.add(alias_clean)
    return info.name


def _valid_assignment_count(parsed: dict, candidates: dict) -> int:
    seen: set[int] = set()
    for assignment in parsed.get("dialogues") or []:
        match = re.match(r"^\s*(\d+)\s*\|\s*(.*?)\s*$", str(assignment or ""))
        if not match or not _clean_name(match.group(2)):
            continue
        dialogue_id = int(match.group(1))
        if dialogue_id in candidates:
            seen.add(dialogue_id)
    return len(seen)


def _consolidate_canonical_names(
    infos: dict[str, CharacterInfo],
    frequencies: Counter[str],
    annotations: list[dict],
) -> None:
    """Merge an unambiguous short name into its single fuller book name."""
    for short_info in sorted(list(infos.values()), key=lambda item: len(item.name)):
        if short_info.name not in frequencies:
            continue
        short_tokens = {
            token.casefold()
            for token in re.findall(r"[\wÀ-ž]+", short_info.name)
            if token
        }
        if not short_tokens:
            continue
        matches = []
        for longer in infos.values():
            if longer is short_info or len(longer.name) <= len(short_info.name):
                continue
            longer_tokens = {
                token.casefold()
                for token in re.findall(r"[\wÀ-ž]+", longer.name)
                if token
            }
            if short_tokens.issubset(longer_tokens):
                matches.append(longer)
        if not matches:
            continue
        if len(matches) == 1:
            target = matches[0]
        else:
            ranked = sorted(
                matches,
                key=lambda item: frequencies.get(item.name, 0),
                reverse=True,
            )
            top_count = frequencies.get(ranked[0].name, 0)
            second_count = frequencies.get(ranked[1].name, 0)
            # Merge only when one fuller form is clearly dominant. This joins
            # Gorcsev -> Gorcsev Iván but keeps an ambiguous family label such
            # as Würfli separate from Würfli Egon and Würfli Fedor.
            if top_count < max(3, second_count * 2):
                continue
            target = ranked[0]
        target.aliases.add(short_info.name)
        target.aliases.update(short_info.aliases)
        if target.gender == "unknown" and short_info.gender != "unknown":
            target.gender = short_info.gender
        frequencies[target.name] += frequencies.pop(short_info.name, 0)
        for annotation in annotations:
            if annotation["speaker_name"] == short_info.name:
                annotation["speaker_name"] = target.name
        infos.pop(short_info.name.casefold(), None)


def analyze_book(
    *,
    title: str,
    author: str,
    chapters: list[dict],
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 600,
    max_tokens: int = 8192,
    max_characters: int = 60,
    batch_chars: int = 10_000,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Analyze chapters sequentially and return characters plus annotations."""
    if not str(model or "").strip():
        raise LLMAnalysisError("The LLM model name is empty.")

    infos: dict[str, CharacterInfo] = {}
    annotations: list[dict] = []
    errors: list[dict] = []
    frequencies: Counter[str] = Counter()
    total = len(chapters)
    prepared: list[dict] = []
    for chapter_no, chapter in enumerate(chapters, start=1):
        chapter_text = str(chapter.get("content") or "")
        units = build_speaker_units(chapter_text)
        prepared.append(
            {
                "chapter_no": chapter_no,
                "chapter": chapter,
                "units": units,
                "char_count": sum(len(unit["text"]) for unit in units),
            }
        )

    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_chars = 0
    safe_batch_chars = max(10_000, int(batch_chars))
    for block in prepared:
        if current_batch and current_chars + block["char_count"] > safe_batch_chars:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(block)
        current_chars += block["char_count"]
    if current_batch:
        batches.append(current_batch)

    for batch in batches:
        request_id = 0
        for block in batch:
            for unit in block["units"]:
                unit["global_id"] = request_id
                request_id += 1
        candidates = {
            unit["global_id"]: (block, unit)
            for block in batch
            for unit in block["units"]
            if unit["dialogue_candidate"]
        }
        if not candidates:
            continue
        first_no = batch[0]["chapter_no"]
        last_no = batch[-1]["chapter_no"]
        if progress:
            label = (
                str(batch[0]["chapter"].get("title") or "")
                if first_no == last_no
                else f"chapters {first_no}–{last_no}"
            )
            progress(last_no, total, label)
        source_text = "\n".join(
            str(block["chapter"].get("content") or "") for block in batch
        )

        prompt = _batch_prompt(
            title=title,
            author=author,
            chapter_blocks=batch,
            infos=infos,
        )
        try:
            parsed = _chat(
                base_url=base_url,
                api_key=api_key,
                model=model,
                prompt=prompt,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        except LLMAnalysisError as exc:
            chapter_names = [
                str(block["chapter"].get("title") or block["chapter_no"])
                for block in batch
            ]
            # A long accumulated roster can occasionally derail a model. Retry
            # once with chapter-local context only before marking the batch bad.
            try:
                parsed = _chat(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    prompt=_batch_prompt(
                        title=title,
                        author=author,
                        chapter_blocks=batch,
                        infos={},
                    ),
                    timeout=timeout,
                    max_tokens=max_tokens,
                )
            except LLMAnalysisError as retry_exc:
                errors.append(
                    {
                        "chapters": chapter_names,
                        "message": str(retry_exc),
                    }
                )
                log.error(
                    "Skipping failed LLM speaker batch (%s): %s (first: %s)",
                    ", ".join(chapter_names),
                    retry_exc,
                    exc,
                )
                continue

        minimum_expected = max(3, int(len(candidates) * 0.20))
        if infos and _valid_assignment_count(parsed, candidates) < minimum_expected:
            try:
                retry_parsed = _chat(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    prompt=_batch_prompt(
                        title=title,
                        author=author,
                        chapter_blocks=batch,
                        infos={},
                    ),
                    timeout=timeout,
                    max_tokens=max_tokens,
                )
                if _valid_assignment_count(retry_parsed, candidates) > _valid_assignment_count(
                    parsed, candidates
                ):
                    parsed = retry_parsed
            except LLMAnalysisError as exc:
                log.warning("Low-coverage chapter-local retry failed: %s", exc)

        chapter_characters: dict[str, dict] = {}
        for item in parsed.get("characters") or []:
            if not isinstance(item, dict):
                continue
            canonical = _merge_character(
                infos,
                name=item.get("name"),
                gender=item.get("gender", "unknown"),
                aliases=item.get("aliases") if isinstance(item.get("aliases"), list) else [],
                source_text=source_text,
            )
            if canonical:
                chapter_characters[canonical.casefold()] = item

        seen_ids: set[int] = set()
        for assignment in parsed.get("dialogues") or []:
            match = re.match(r"^\s*(\d+)\s*\|\s*(.*?)\s*$", str(assignment or ""))
            if not match:
                continue
            dialogue_id = int(match.group(1))
            if dialogue_id not in candidates or dialogue_id in seen_ids:
                continue
            raw_speaker = _clean_name(match.group(2))
            if not raw_speaker:
                continue
            meta = chapter_characters.get(raw_speaker.casefold(), {})
            speaker = _merge_character(
                infos,
                name=raw_speaker,
                gender=meta.get("gender", "unknown"),
                aliases=meta.get("aliases") if isinstance(meta.get("aliases"), list) else [],
                source_text=source_text,
            )
            if not speaker:
                continue
            seen_ids.add(dialogue_id)
            block, unit = candidates[dialogue_id]
            annotations.append(
                {
                    "chapter_id": block["chapter"]["id"],
                    "unit_index": unit["index"],
                    "unit_text": unit["text"],
                    "speaker_name": speaker,
                    "confidence": 1.0,
                }
            )
            frequencies[speaker] += 1

    _consolidate_canonical_names(infos, frequencies, annotations)

    # Keep all frequently speaking characters up to the configured safety cap.
    ordered_names = [
        name for name, _count in frequencies.most_common(max(1, max_characters))
    ]
    result_characters = []
    for name in ordered_names:
        info = next(
            (item for item in infos.values() if item.name == name),
            CharacterInfo(name=name),
        )
        profile = characters.generate_voice_profile(info.name, info.gender)
        result_characters.append(
            {
                "name": info.name,
                "gender": info.gender,
                "frequency": frequencies[info.name],
                **profile,
            }
        )

    retained = {item["name"] for item in result_characters}
    annotations = [
        item for item in annotations if item["speaker_name"] in retained
    ]
    return {
        "characters": result_characters,
        "annotations": annotations,
        "errors": errors,
    }
