"""Read Hungarian numbers out loud the way a narrator would.

Both TTS engines mangle bare digits in Hungarian: they either spell them in
English or guess a wrong Hungarian form, and ``num2words``' Hungarian tables
are wrong for ordinals above a hundred (``102.`` comes back as *"százkétik"*).
Hungarian audiobooks are full of years, dates and chapter numbers, so the whole
mapping lives here instead: digits in, spoken words out.

The hard parts this module gets right:

* ``932.`` is an ordinal — *"kilencszázharminckettedik"*, not *"kilencszázharminckettő"*
* a date reads differently from an ordinal: ``1932. március 5-én`` →
  *"ezerkilencszázharminckettő március ötödikén"*
* a number in front of a noun uses the short form: ``12 alma`` →
  *"tizenkét alma"*, while a bare ``12`` stays *"tizenkettő"*
* suffixes glued on with a hyphen keep their own vowels: ``3-at`` → *"hármat"*
"""

from __future__ import annotations

import re

__all__ = [
    'cardinal',
    'ordinal',
    'day_of_month',
    'looks_hungarian',
    'normalize_hungarian',
]

_UNITS = ('nulla', 'egy', 'kettő', 'három', 'négy', 'öt', 'hat', 'hét',
          'nyolc', 'kilenc')
_TENS = {2: 'húsz', 3: 'harminc', 4: 'negyven', 5: 'ötven', 6: 'hatvan',
         7: 'hetven', 8: 'nyolcvan', 9: 'kilencven'}
# 11-19 and 21-29 use a bound form of the tens ("tizenhárom", "huszonhárom").
_BOUND_TENS = {1: 'tizen', 2: 'huszon'}
_SCALES = ((10 ** 9, 'milliárd'), (10 ** 6, 'millió'), (1000, 'ezer'))

# Above 2000 Hungarian spelling puts a hyphen on the thousand boundary
# ("kétezer-huszonnégy"), below it the number is one word.
_HYPHEN_ABOVE = 2000

_MONTHS = (
    'január', 'február', 'március', 'április', 'május', 'június',
    'július', 'augusztus', 'szeptember', 'október', 'november', 'december',
)

# Words that can follow a number without being counted by it, so "2 és 3"
# stays "kettő és három" instead of turning into the attributive "két".
_NOT_COUNTED = {
    'és', 'vagy', 'meg', 'de', 'is', 'sem', 'se', 'pedig', 'hogy', 'mint',
    'majd', 'azaz', 'avagy', 'valamint', 'illetve', 'plusz', 'mínusz',
}

# Nouns that make a trailing period an ordinal even when the word is
# capitalised, as in the chapter heading "5. Fejezet".
_ORDINAL_NOUNS = {
    'fejezet', 'rész', 'kötet', 'könyv', 'század', 'évszázad', 'esztendő',
    'esztendejében', 'év', 'évben', 'oldal', 'kiadás', 'világháború',
    'emelet', 'sor', 'pont', 'bekezdés', 'versszak', 'felvonás', 'jelenet',
    'szám', 'osztály', 'kerület', 'alkalom', 'helyezett', 'hadsereg',
    'törvény', 'paragrafus', 'cikkely', 'melléklet', 'függelék', 'táblázat',
    'ábra', 'levél', 'napon', 'nap', 'hét', 'hónap', 'ízben',
}

# Parts of the year: after these a year stays a cardinal, because "1932. nyarán"
# is read as "ezerkilencszázharminckettő nyarán", not as an ordinal.
_YEAR_PARTS = {
    'nyarán', 'nyara', 'nyarától', 'nyaráig', 'tavaszán', 'tavasza',
    'őszén', 'ősze', 'őszétől', 'telén', 'tele', 'karácsonyán', 'húsvétján',
    'elején', 'eleje', 'végén', 'vége', 'közepén', 'közepe', 'folyamán',
    'táján', 'őszén', 'januárjában', 'decemberében',
}

_LOWER = 'a-záéíóöőúüű'
_VOWEL_SUFFIX_START = set('aeioóöőuúüű')
_BACK_VOWELS = set('aáoóuú')


def _multiplier(n: int) -> str:
    """The form used in front of száz/ezer/millió: 2 is "két", never "kettő"."""
    return cardinal(n, before_noun=True)


def _below_hundred(n: int) -> str:
    if n < 10:
        return _UNITS[n]
    tens, unit = divmod(n, 10)
    if unit == 0:
        return 'tíz' if tens == 1 else _TENS[tens]
    if tens in _BOUND_TENS:
        return _BOUND_TENS[tens] + _UNITS[unit]
    return _TENS[tens] + _UNITS[unit]


def _below_thousand(n: int) -> str:
    if n < 100:
        return _below_hundred(n)
    hundreds, rest = divmod(n, 100)
    head = 'száz' if hundreds == 1 else _multiplier(hundreds) + 'száz'
    return head + (_below_thousand(rest) if rest else '')


def cardinal(n: int, before_noun: bool = False) -> str:
    """``932`` → "kilencszázharminckettő"; before a noun 2 becomes "két"."""
    n = int(n)
    if n < 0:
        return 'mínusz ' + cardinal(-n, before_noun)

    if n < 1000:
        word = _below_thousand(n)
    else:
        word = ''
        for value, name in _SCALES:
            if n < value:
                continue
            count, rest = divmod(n, value)
            if value == 1000 and count == 1:
                head = name  # 1000 is "ezer", never "egyezer"
            else:
                head = _multiplier(count) + name
            if rest:
                separator = '-' if n > _HYPHEN_ABOVE else ''
                word = head + separator + cardinal(rest)
            else:
                word = head
            break

    if before_noun and word.endswith('kettő'):
        word = word[:-len('kettő')] + 'két'
    return word


# The last element of a compound carries the ordinal ending; everything in
# front of it stays a cardinal ("ezerkilencszáz" + "harminc" + "kettedik").
_ORDINAL_ENDINGS = sorted(
    (
        ('kettő', 'kettedik'), ('három', 'harmadik'), ('négy', 'negyedik'),
        ('öt', 'ötödik'), ('hat', 'hatodik'), ('hét', 'hetedik'),
        ('nyolc', 'nyolcadik'), ('kilenc', 'kilencedik'), ('egy', 'egyedik'),
        ('tíz', 'tizedik'), ('húsz', 'huszadik'), ('harminc', 'harmincadik'),
        ('negyven', 'negyvenedik'), ('ötven', 'ötvenedik'),
        ('hatvan', 'hatvanadik'), ('hetven', 'hetvenedik'),
        ('nyolcvan', 'nyolcvanadik'), ('kilencven', 'kilencvenedik'),
        ('száz', 'századik'), ('ezer', 'ezredik'), ('millió', 'milliomodik'),
        ('milliárd', 'milliárdodik'), ('nulla', 'nulladik'),
    ),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


def ordinal(n: int) -> str:
    """``932`` → "kilencszázharminckettedik"."""
    n = int(n)
    if n == 1:
        return 'első'
    if n == 2:
        return 'második'
    word = cardinal(n)
    for ending, replacement in _ORDINAL_ENDINGS:
        if word.endswith(ending):
            return word[:-len(ending)] + replacement
    return word + 'dik'


def _day_stem(n: int) -> str:
    """The stem a date suffix attaches to: "elsej-én", "ötödik-én"."""
    return 'elsej' if int(n) == 1 else ordinal(n)


def _harmony_vowel(word: str) -> str:
    """Back or front linking vowel, ignoring the neutral i of "-dik"."""
    for char in reversed(word):
        if char in _BACK_VOWELS:
            return 'a'
        if char in 'eéöőüű':
            return 'e'
    return 'e'


def day_of_month(n: int) -> str:
    """``5`` → "ötödike" — how a date is read when nothing follows it."""
    if int(n) == 1:
        return 'elseje'
    word = ordinal(n)
    return word + _harmony_vowel(word)


def _attach(stem: str, suffix: str) -> str:
    """Glue a written suffix onto a stem without doubling the linking letter."""
    if stem.endswith('j') and suffix.startswith('j'):
        suffix = suffix[1:]
    return stem + suffix


# Stems that change shape in front of a suffix that starts with a vowel:
# "három" + "-at" is "hármat", "ezer" + "-et" is "ezret".
_SUFFIX_STEMS = (('három', 'hárm'), ('kettő', 'kett'), ('ezer', 'ezr'),
                 ('hét', 'het'))


def _cardinal_with_suffix(n: int, suffix: str) -> str:
    word = cardinal(n)
    if suffix[:1] in _VOWEL_SUFFIX_START:
        for ending, stem in _SUFFIX_STEMS:
            if word.endswith(ending):
                word = word[:-len(ending)] + stem
                break
    return word + suffix


_ROMAN_PARTS = (
    (1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'),
    (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I'),
)


def _roman_value(text: str) -> int | None:
    """Value of a canonically written Roman numeral, else ``None``.

    The round-trip check keeps letter salad out: ``DVD`` parses to a number
    with a naive reader, but it is not how anyone writes 995.
    """
    values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    total = 0
    previous = 0
    for char in reversed(text):
        value = values.get(char)
        if value is None:
            return None
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    if total <= 0 or _to_roman(total) != text:
        return None
    return total


def _to_roman(value: int) -> str:
    out = []
    for amount, letters in _ROMAN_PARTS:
        while value >= amount:
            out.append(letters)
            value -= amount
    return ''.join(out)


_MONTH_RE = '|'.join(_MONTHS)
_SUFFIX_RE = f'[{_LOWER}]+'

_THOUSAND_GROUPED = re.compile(r'(?<![\d.,])(\d{1,3})(?:[.  ](\d{3}))+(?![\d.,])')
_DATE_FULL = re.compile(
    rf'\b(\d{{1,4}})\.\s+({_MONTH_RE})\s+(\d{{1,2}})\.(?:-({_SUFFIX_RE}))?'
)
_DATE_MONTH_DAY = re.compile(rf'\b({_MONTH_RE})\s+(\d{{1,2}})\.(?:-({_SUFFIX_RE}))?')
_DATE_YEAR_MONTH = re.compile(rf'\b(\d{{3,4}})\.\s+({_MONTH_RE})\b')
_ROMAN = re.compile(r'\b([IVXLCDM]{2,})\.(?=\s+(\w+))')
_TIME = re.compile(rf'\b(\d{{1,2}}):(\d{{2}})(?:-({_SUFFIX_RE}))?')
_PERCENT = re.compile(rf'(\d+)(?:,(\d+))?\s*%(?:-?({_SUFFIX_RE}))?')
_DEGREE = re.compile(rf'(-?\d+)\s*°\s*C(?:-?({_SUFFIX_RE}))?\b')
_SUFFIXED = re.compile(rf'\b(\d+)-({_SUFFIX_RE})')
_ORDINAL = re.compile(rf'\b(\d+)\.(?=\s+(\w+))')
_DECIMAL = re.compile(r'\b(\d+),(\d+)\b')
_INTEGER = re.compile(r'\b\d+\b')


def _is_ordinal_context(word: str) -> bool:
    """``század``, ``fejezet``, ``esztendejében`` — nouns you count with."""
    plain = word.lower()
    return plain in _ORDINAL_NOUNS or any(
        plain.startswith(noun) for noun in _ORDINAL_NOUNS
    )


def _expand_roman(match: re.Match) -> str:
    """``XX. század`` and ``II. Erzsébet`` are ordinals; other letters are not."""
    value = _roman_value(match.group(1))
    following = match.group(2)
    if value is None:
        return match.group()
    if following[:1].isupper():
        # A ruler's name: "II. Erzsébet" reads as "Második Erzsébet".
        return ordinal(value).capitalize()
    if _is_ordinal_context(following):
        return ordinal(value)
    return match.group()


def _date_suffix(day: int, suffix: str | None) -> str:
    if not suffix:
        return day_of_month(day)
    return _attach(_day_stem(day), suffix)


def _number_suffix(n: int, suffix: str) -> str:
    """A hyphenated suffix decides whether this is a date or a plain number.

    ``-án``/``-én``/``-jén`` only ever appear on a day of the month, so
    ``5-én`` is "ötödikén" while ``1932-ben`` stays "ezerkilencszázharminckettőben".
    """
    if suffix.startswith('ér'):  # "5-ért" is a plain number, not a date
        return _cardinal_with_suffix(n, suffix)
    if suffix[:1] in ('á', 'é', 'j'):
        return _attach(_day_stem(n), suffix)
    return _cardinal_with_suffix(n, suffix)


def _expand_time(match: re.Match) -> str:
    hour, minute = int(match.group(1)), int(match.group(2))
    suffix = match.group(3) or ''
    if minute:
        spoken = f'{cardinal(hour, before_noun=True)} óra {cardinal(minute)} perc'
    else:
        spoken = f'{cardinal(hour, before_noun=True)} óra'
    return _cardinal_tail(spoken, suffix) if suffix else spoken


def _cardinal_tail(spoken: str, suffix: str) -> str:
    """Attach a suffix to the last word of an already spoken phrase."""
    head, _, last = spoken.rpartition(' ')
    glued = _attach(last, suffix)
    return f'{head} {glued}' if head else glued


def _expand_degree(match: re.Match) -> str:
    """``21 °C`` is "huszonegy Celsius-fok"; ``21 °C-ban`` keeps its suffix."""
    spoken = f'{cardinal(int(match.group(1)))} Celsius-fok'
    suffix = match.group(2)
    return _attach(spoken, suffix) if suffix else spoken


def _expand_percent(match: re.Match) -> str:
    whole, fraction, suffix = match.group(1), match.group(2), match.group(3)
    spoken = cardinal(int(whole), before_noun=True)
    if fraction:
        spoken = f'{cardinal(int(whole))} egész {cardinal(int(fraction))}'
    spoken = f'{spoken} százalék'
    return _cardinal_tail(spoken, suffix) if suffix else spoken


def _counts_the_next_word(text: str, end: int) -> bool:
    """True when the number modifies a following noun ("12 alma")."""
    rest = text[end:]
    match = re.match(rf'\s+([{_LOWER}]+)', rest)
    if not match:
        return False
    return match.group(1) not in _NOT_COUNTED


def _expand_ordinal_or_sentence_end(text: str):
    """``932. esztendejében`` is an ordinal; ``Volt 932. Aztán…`` is not."""
    def repl(match: re.Match) -> str:
        following = match.group(2)
        value = int(match.group(1))
        if 1000 <= value <= 2999 and following.lower() in _YEAR_PARTS:
            # A year in front of a season or a part of the year keeps its
            # cardinal form: "1932. nyarán" is "ezerkilencszázharminckettő nyarán".
            return cardinal(value)
        if following[:1].islower() or following.lower() in _ORDINAL_NOUNS:
            return ordinal(value)
        # A capitalised word after the period reads as a new sentence, so the
        # number itself is a plain cardinal and the period stays a full stop.
        return f'{cardinal(value)}.'
    return _ORDINAL.sub(repl, text)


def normalize_hungarian(text: str) -> str:
    """Replace every digit group in ``text`` with its spoken Hungarian form."""
    if not text:
        return text
    if not any(char.isdigit() for char in text) and not _ROMAN.search(text):
        return text

    def join_groups(match: re.Match) -> str:
        return re.sub(r'[.  ]', '', match.group())

    out = _THOUSAND_GROUPED.sub(join_groups, text)

    out = _DATE_FULL.sub(
        lambda m: f'{cardinal(int(m.group(1)))} {m.group(2)} '
                  f'{_date_suffix(int(m.group(3)), m.group(4))}',
        out,
    )
    out = _DATE_MONTH_DAY.sub(
        lambda m: f'{m.group(1)} {_date_suffix(int(m.group(2)), m.group(3))}',
        out,
    )
    out = _DATE_YEAR_MONTH.sub(
        lambda m: f'{cardinal(int(m.group(1)))} {m.group(2)}', out
    )

    out = _ROMAN.sub(_expand_roman, out)

    out = _TIME.sub(_expand_time, out)
    out = _PERCENT.sub(_expand_percent, out)
    out = _DEGREE.sub(_expand_degree, out)
    out = _SUFFIXED.sub(lambda m: _number_suffix(int(m.group(1)), m.group(2)), out)
    out = _expand_ordinal_or_sentence_end(out)
    out = _DECIMAL.sub(
        lambda m: f'{cardinal(int(m.group(1)))} egész {cardinal(int(m.group(2)))}',
        out,
    )
    out = _INTEGER.sub(
        lambda m: cardinal(int(m.group()), _counts_the_next_word(out, m.end())),
        out,
    )
    return out


_HUNGARIAN_CODES = {'hu', 'hun', 'hu-hu', 'hungarian', 'magyar'}


def looks_hungarian(language: str | None, text: str = '') -> bool:
    """Hungarian by declared language, or by letters only Hungarian uses."""
    code = str(language or '').strip().lower()
    if code in _HUNGARIAN_CODES:
        return True
    if code and code not in {'none', 'auto', ''}:
        return False
    return bool(re.search(r'[őűŐŰ]', text))
