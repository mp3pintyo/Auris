import re
import hashlib
import random
import logging
from collections import Counter

log = logging.getLogger(__name__)

# ── spaCy (required) ──────────────────────────────────────────────────────────
# spaCy + en_core_web_sm are required for full character detection.
# If not yet installed the app degrades to regex-based detection and
# shows a warning in the Settings page.

_nlp = None
_spacy_error: str = ''


def _get_nlp():
    global _nlp, _spacy_error
    if _nlp is not None:
        return _nlp
    try:
        import spacy
        _nlp = spacy.load('en_core_web_sm')
        _spacy_error = ''
        return _nlp
    except ImportError:
        _spacy_error = 'spaCy is not installed. Run: pip install spacy'
        log.warning(_spacy_error)
        return None
    except OSError:
        _spacy_error = (
            'spaCy model en_core_web_sm not found. '
            'Go to Settings → spaCy and click Install Model.'
        )
        log.warning(_spacy_error)
        return None


def spacy_ready() -> bool:
    return _get_nlp() is not None


def spacy_error() -> str:
    _get_nlp()  # trigger detection
    return _spacy_error


# ── Name → gender lookup (common English names) ──────────────────────────────

MALE_NAMES = {
    'james','john','robert','michael','william','david','richard','joseph','thomas','charles',
    'christopher','daniel','matthew','anthony','mark','donald','steven','paul','andrew','kenneth',
    'joshua','kevin','brian','george','edward','ronald','timothy','jason','jeffrey','ryan',
    'jacob','gary','nicholas','eric','jonathan','stephen','larry','justin','scott','brandon',
    'benjamin','samuel','raymond','gregory','frank','alexander','patrick','jack','dennis','jerry',
    'tyler','aaron','henry','jose','adam','douglas','nathan','peter','zachary','kyle','henry',
    'walter','arthur','carl','albert','clarence','ralph','roy','eugene','wayne','louis',
    'harry','liam','noah','oliver','elijah','lucas','mason','ethan','aiden','logan','caleb',
    'sebastian','julian','ezra','miles','finn','leo','theo','max','felix','hugo','oscar',
    'edgar','ernest','victor','harold','claude','leon','otto','fred','alfred','edgar',
    'gilbert','roland','benedict','gabriel','raphael','dominic','marcus','julius',
    'sherlock','watson','holmes','darcy','heathcliff','rochester','pip','oliver','fagin',
    'tom','huck','atticus','gatsby','dorian','basil','doyle','dickens','austen',
}

FEMALE_NAMES = {
    'mary','patricia','jennifer','linda','barbara','elizabeth','susan','jessica','sarah','karen',
    'lisa','nancy','betty','margaret','sandra','ashley','dorothy','kimberly','emily','donna',
    'michelle','carol','amanda','melissa','deborah','stephanie','rebecca','sharon','laura','cynthia',
    'kathleen','amy','angela','shirley','anna','brenda','pamela','emma','nicole','helen','samantha',
    'katherine','christine','debra','rachel','carolyn','janet','catherine','maria','heather',
    'diane','julie','joyce','victoria','kelly','christina','joan','evelyn','lauren','judith',
    'olivia','sophia','isabella','ava','mia','charlotte','amelia','harper','abigail','ella',
    'scarlett','grace','lily','aria','chloe','penelope','layla','riley','zoey','nora','luna',
    'eleanor','violet','aurora','stella','hazel','alice','claire','audrey','ruby','alice',
    'jane','anne','margaret','dorothy','edith','mabel','ethel','florence','beatrice','cecily',
    'esme','clarice','eliza','lydia','catherine','marianne','elinor','emma','harriet','fanny',
    'hester','hattie','nell','daisy','molly','flora','rose','iris','vera','grace','pearl',
    'hermione','ginny','luna','lavender','parvati','tonks','narcissa','bellatrix',
    'katniss','primrose','effie','johanna','clove','glimmer','rue',
}


def detect_gender_by_name(name: str) -> str:
    first = name.strip().split()[0].lower()
    if first in MALE_NAMES:
        return 'male'
    if first in FEMALE_NAMES:
        return 'female'
    return 'unknown'


def detect_gender_by_pronouns(name: str, text: str) -> str:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    male_score = 0
    female_score = 0
    name_first = name.split()[0]

    for sent in sentences:
        if name_first not in sent:
            continue
        male_score += len(re.findall(r'\b(he|him|his)\b', sent, re.IGNORECASE))
        female_score += len(re.findall(r'\b(she|her|hers)\b', sent, re.IGNORECASE))

    if male_score > female_score:
        return 'male'
    if female_score > male_score:
        return 'female'
    return 'unknown'


def detect_gender(name: str, text: str) -> str:
    gender = detect_gender_by_name(name)
    if gender != 'unknown':
        return gender
    return detect_gender_by_pronouns(name, text)


# ── Voice profile generation ──────────────────────────────────────────────────

CHAR_COLORS = [
    '#FFD700', '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4',
    '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE',
    '#85C1E9', '#82E0AA', '#F0B27A', '#AED6F1', '#A9DFBF',
]


def _hash_seed(name: str) -> int:
    return int(hashlib.md5(name.lower().encode()).hexdigest(), 16)


def generate_voice_profile(name: str, gender: str) -> dict:
    rng = random.Random(_hash_seed(name))

    ages_m = ['young adult', 'middle-aged', 'elderly']
    ages_f = ['young adult', 'middle-aged']
    ages_n = ['child', 'teenager', 'young adult', 'middle-aged', 'elderly']

    pitches_m = ['very low pitch', 'low pitch', 'moderate pitch']
    pitches_f = ['moderate pitch', 'high pitch', 'very high pitch']
    pitches_n = ['low pitch', 'moderate pitch', 'high pitch']

    accents = [
        'american accent', 'british accent', 'australian accent',
        'canadian accent', 'indian accent',
    ]

    if gender == 'male':
        age = rng.choice(ages_m)
        pitch = rng.choice(pitches_m)
        g = 'male'
    elif gender == 'female':
        age = rng.choice(ages_f)
        pitch = rng.choice(pitches_f)
        g = 'female'
    else:
        age = rng.choice(ages_n)
        pitch = rng.choice(pitches_n)
        g = rng.choice(['male', 'female'])

    accent = rng.choice(accents)
    instruct = f'{g}, {age}, {pitch}, {accent}'

    color_idx = _hash_seed(name) % len(CHAR_COLORS)
    color = CHAR_COLORS[color_idx]

    return {
        'instruct': instruct,
        'gender': gender,
        'age': age,
        'pitch': pitch,
        'accent': accent,
        'color_hex': color,
    }


# ── Character extraction ──────────────────────────────────────────────────────

_SAID_RE = re.compile(
    r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+'
    r'(?:said|replied|asked|answered|whispered|shouted|cried|muttered|'
    r'exclaimed|called|added|continued|laughed|sighed|groaned|snapped|'
    r'retorted|insisted|demanded|pleaded|began|noted|observed|remarked)\b'
)
_QUOTE_SAID_RE = re.compile(
    r'["""][^"""]{3,}["""]\s*[,.]?\s*'
    r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+'
    r'(?:said|replied|asked|whispered|shouted|cried|muttered|exclaimed|called)\b'
)


def extract_characters_regex(text: str, top_n: int = 20) -> list[dict]:
    counter = Counter()
    for m in _SAID_RE.finditer(text):
        counter[m.group(1)] += 1
    for m in _QUOTE_SAID_RE.finditer(text):
        counter[m.group(1)] += 1

    # Filter out common false positives
    stop_words = {
        'The', 'A', 'An', 'He', 'She', 'It', 'They', 'We', 'You', 'I',
        'But', 'And', 'Or', 'So', 'As', 'In', 'On', 'At', 'By', 'For',
        'His', 'Her', 'Their', 'Its', 'Our', 'Your',
    }
    characters = []
    for name, freq in counter.most_common(top_n * 2):
        if name in stop_words or len(name) < 2:
            continue
        characters.append({'name': name, 'frequency': freq})
        if len(characters) >= top_n:
            break
    return characters


def extract_characters_spacy(text: str, top_n: int = 20) -> list[dict]:
    nlp = _get_nlp()
    if nlp is None:
        log.warning('spaCy unavailable — falling back to regex character detection.')
        return extract_characters_regex(text, top_n)

    chunk_size = 100_000
    counter = Counter()
    for i in range(0, len(text), chunk_size):
        doc = nlp(text[i:i + chunk_size])
        for ent in doc.ents:
            if ent.label_ == 'PERSON' and len(ent.text.split()) <= 3:
                name = ent.text.strip().title()
                if len(name) > 1:
                    counter[name] += 1

    # Merge with regex results for better recall
    for m in _SAID_RE.finditer(text):
        counter[m.group(1)] += 1

    stop_words = {'He', 'She', 'It', 'They', 'The', 'A', 'His', 'Her'}
    characters = []
    for name, freq in counter.most_common(top_n * 2):
        if name in stop_words:
            continue
        characters.append({'name': name, 'frequency': freq})
        if len(characters) >= top_n:
            break
    return characters


def extract_characters(text: str, top_n: int = 20) -> list[dict]:
    # Always attempt spaCy (preferred); regex is only the degraded fallback
    chars = extract_characters_spacy(text, top_n)

    # Enrich with gender + voice profile
    for ch in chars:
        gender = detect_gender(ch['name'], text)
        profile = generate_voice_profile(ch['name'], gender)
        ch.update(profile)

    return chars
