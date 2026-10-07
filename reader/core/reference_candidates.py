"""Cut a long voice recording into reference-clip candidates with exact text.

A good cloning reference is one clean speaker for about 8-16 seconds, cut at
a pause, with its exact transcript. Which stretch of a longer recording clones
best cannot be predicted from length, pitch or pace, so the candidates are
meant to be auditioned (rendered and measured) rather than guessed.

The known transcript is split into sentences with the Hungarian-aware
splitter, aligned to the recognizer's word timestamps, and every run of
consecutive sentences lasting ``min_seconds``-``max_seconds`` becomes a
candidate. Two neighbouring candidates share
one cut per sentence boundary: the quietest ~100 ms near it, so no word is
clipped. At the start and end of the recording the cut follows the sound, not
the recognizer (whose word times end early): a stretch whose speech runs into
the end of the file, with no quiet after it, is not offered, because a cut-off
last word that the transcript still spells out in full makes the clone swallow
word endings.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass

import numpy as np

FRAME_SECONDS = 0.02
SEARCH_SECONDS = 0.35
SMOOTH_FRAMES = 5
# Recording edges: speech ends where 150 ms stay 30 dB under the speech level.
QUIET_BELOW_SPEECH_DB = 30.0
QUIET_SECONDS = 0.15
EDGE_SEARCH_SECONDS = 1.5
EDGE_MARGIN_SECONDS = 0.1


@dataclass
class Candidate:
    start: float
    end: float
    text: str
    first_sentence: int
    last_sentence: int

    @property
    def duration(self) -> float:
        return self.end - self.start


def split_sentences(text: str) -> list[str]:
    from core.enrichment import _split_paragraph_sentences

    paragraph = " ".join(str(text or "").split())
    return [s.strip() for s in _split_paragraph_sentences(paragraph) if s.strip()]


def _tokens(text: str) -> list[str]:
    from core.qa import comparable_text

    return comparable_text(text, "hu").split()


def sentence_times(sentences: list[str], words: list[dict]) -> list[tuple[float, float] | None]:
    """Start/end time of every sentence from recognizer word timestamps.

    Recognized words are matched to the transcript's words; a sentence without
    any timed match gets ``None``.
    """
    ref, owner = [], []
    for index, sentence in enumerate(sentences):
        for token in _tokens(sentence):
            ref.append(token)
            owner.append(index)
    hyp, times = [], []
    for word in words:
        start, end = word.get("start"), word.get("end")
        for token in _tokens(word.get("word", "")):
            hyp.append(token)
            times.append((start, end))
    spans: list[list[float] | None] = [None] * len(sentences)
    matcher = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            start, end = times[block.b + k]
            if start is None or end is None:
                continue
            index = owner[block.a + k]
            span = spans[index]
            if span is None:
                spans[index] = [float(start), float(end)]
            else:
                span[0], span[1] = min(span[0], float(start)), max(span[1], float(end))
    return [tuple(s) if s else None for s in spans]


def _quietest(audio: np.ndarray, sr: int, lo: float, hi: float) -> float:
    """Centre of the quietest ~100 ms between ``lo`` and ``hi`` seconds."""
    size = max(1, int(FRAME_SECONDS * sr))
    a, b = max(0, int(lo * sr)), min(len(audio), int(hi * sr))
    if b - a <= size:
        return (lo + hi) / 2
    frames = audio[a:a + (b - a) // size * size].reshape(-1, size)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    width = min(len(rms), SMOOTH_FRAMES)
    smooth = np.convolve(rms, np.ones(width) / width, mode="same")
    # The middle of the quietest stretch, so both neighbours keep some pause.
    quiet = np.flatnonzero(smooth <= smooth.min() * 1.05 + 1e-6)
    longest, run = [quiet[0]], [quiet[0]]
    for index in quiet[1:]:
        run = run + [index] if index == run[-1] + 1 else [index]
        if len(run) > len(longest):
            longest = run
    return (a + longest[len(longest) // 2] * size + size / 2) / sr


def _boundary(audio, sr, times, k) -> float:
    """Cut between sentences k and k+1, shared by both neighbours.

    Recognizer word times often touch (a word's end is the next word's start),
    so the pause hides inside them; search a little around the boundary.
    """
    end, start = times[k][1], times[k + 1][0]
    return _quietest(audio, sr, min(end, start) - SEARCH_SECONDS, max(end, start) + SEARCH_SECONDS)


def _frame_db(audio: np.ndarray, sr: int) -> np.ndarray:
    size = max(1, int(FRAME_SECONDS * sr))
    frames = audio[:len(audio) // size * size].reshape(-1, size)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    width = min(len(rms), SMOOTH_FRAMES) or 1
    return 20 * np.log10(np.convolve(rms, np.ones(width) / width, mode="same") + 1e-9)


def speech_edge(audio: np.ndarray, sr: int, t: float, direction: int) -> float | None:
    """Walk from the recognizer's word edge ``t`` (forward for +1, backward for
    -1) to the first 150 ms of quiet; the cut lands 100 ms into it. ``None``
    when the sound runs into the file edge or keeps going for 1.5 s."""
    db = _frame_db(audio, sr)
    if not len(db):
        return None
    quiet = db < np.percentile(db, 90) - QUIET_BELOW_SPEECH_DB
    run = max(1, int(round(QUIET_SECONDS / FRAME_SECONDS)))
    step = int(round(EDGE_SEARCH_SECONDS / FRAME_SECONDS))
    start = min(len(db) - 1, max(0, int(t / FRAME_SECONDS)))
    margin = EDGE_MARGIN_SECONDS / FRAME_SECONDS
    if direction > 0:
        for k in range(start, min(len(db) - run + 1, start + step)):
            if quiet[k:k + run].all():
                return (k + margin) * FRAME_SECONDS
    else:
        for k in range(start, max(run - 1, start - step) - 1, -1):
            if quiet[k - run + 1:k + 1].all():
                return max(0.0, (k + 1 - margin) * FRAME_SECONDS)
    return None


def _cut_before(audio, sr, times, i) -> float | None:
    if i > 0 and times[i - 1] is not None:
        return _boundary(audio, sr, times, i - 1)
    return speech_edge(audio, sr, times[i][0], -1)


def _cut_after(audio, sr, times, j) -> float | None:
    if j + 1 < len(times) and times[j + 1] is not None:
        return _boundary(audio, sr, times, j)
    return speech_edge(audio, sr, times[j][1], +1)


def candidates(audio: np.ndarray, sr: int, text: str, words: list[dict], *,
               min_seconds: float = 8.0, max_seconds: float = 16.0,
               target_seconds: float = 12.0) -> list[Candidate]:
    """Every run of consecutive timed sentences within the length range,
    nearest to ``target_seconds`` first."""
    sentences = split_sentences(text)
    times = sentence_times(sentences, words)
    out: list[Candidate] = []
    for i in range(len(sentences)):
        for j in range(i, len(sentences)):
            run = times[i:j + 1]
            if any(t is None for t in run):
                break
            start, end = _cut_before(audio, sr, times, i), _cut_after(audio, sr, times, j)
            if start is None:
                break
            if end is None:
                continue
            duration = end - start
            if duration > max_seconds:
                break
            if duration >= min_seconds:
                out.append(Candidate(start, end, " ".join(sentences[i:j + 1]), i, j))
    out.sort(key=lambda c: (abs(c.duration - target_seconds), c.first_sentence))
    return out


def cut(audio: np.ndarray, sr: int, candidate: Candidate, fade_seconds: float = 0.01) -> np.ndarray:
    piece = np.array(audio[int(candidate.start * sr):int(candidate.end * sr)], dtype=np.float32)
    fade = min(len(piece) // 2, int(fade_seconds * sr))
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        piece[:fade] *= ramp
        piece[-fade:] *= ramp[::-1]
    return piece


_CLAUSE_RE = re.compile(r"(?<=[,;:])\s+|\s+(?=[–—-]\s)")


def _split_long(sentences, times, words, max_seconds):
    """Break sentences longer than ``max_seconds`` at clause punctuation, then words."""
    out_s, out_t = [], []
    for sentence, span in zip(sentences, times):
        if span is None or span[1] - span[0] <= max_seconds:
            out_s.append(sentence)
            out_t.append(span)
            continue
        parts = [part for part in _CLAUSE_RE.split(sentence) if part.strip()]
        if len(parts) < 2:
            tokens = sentence.split()
            pieces = max(2, math.ceil((span[1] - span[0]) / (max_seconds * 0.75)))
            size = math.ceil(len(tokens) / pieces)
            parts = [" ".join(tokens[k:k + size]) for k in range(0, len(tokens), size)]
        part_times = sentence_times(parts, [w for w in words if w.get("start") is not None
                                            and span[0] - 0.01 <= w["start"] <= span[1] + 0.01])
        deeper_s, deeper_t = _split_long(parts, part_times, words, max_seconds) if len(parts) > 1 else (parts, part_times)
        out_s.extend(deeper_s)
        out_t.extend(deeper_t)
    return out_s, out_t


def partition(audio: np.ndarray, sr: int, text: str, words: list[dict], *,
              max_seconds: float = 16.0, min_seconds: float = 2.0) -> list[Candidate]:
    """Split a recording into consecutive, non-overlapping clips of whole sentences.

    Used to build a training dataset: sentences are packed greedily while the
    clip stays within ``max_seconds``; a single sentence longer than that, an
    untimed sentence, or speech cut off by the file edge ends the run.
    """
    sentences = split_sentences(text)
    times = sentence_times(sentences, words)
    sentences, times = _split_long(sentences, times, words, max_seconds)
    out: list[Candidate] = []
    i = 0
    while i < len(sentences):
        if times[i] is None:
            i += 1
            continue
        start = _cut_before(audio, sr, times, i)
        if start is None:
            i += 1
            continue
        best_j, best_end = None, None
        j = i
        while j < len(sentences) and times[j] is not None:
            end = _cut_after(audio, sr, times, j)
            if end is None or end - start > max_seconds:
                break
            best_j, best_end = j, end
            j += 1
        if best_j is None:
            i += 1
            continue
        if best_end - start >= min_seconds:
            out.append(Candidate(start, best_end, " ".join(sentences[i:best_j + 1]), i, best_j))
        i = best_j + 1
    return out
