"""Hungarian numbers as a narrator would say them."""

import unittest
from unittest.mock import patch

from core.hungarian_numbers import (
    cardinal,
    day_of_month,
    looks_hungarian,
    normalize_hungarian,
    ordinal,
)
from core.tts_engine import apply_text_normalization


class CardinalTests(unittest.TestCase):
    def test_the_building_blocks(self):
        cases = {
            0: 'nulla', 1: 'egy', 2: 'kettő', 7: 'hét', 10: 'tíz',
            11: 'tizenegy', 12: 'tizenkettő', 19: 'tizenkilenc', 20: 'húsz',
            22: 'huszonkettő', 30: 'harminc', 32: 'harminckettő',
            99: 'kilencvenkilenc',
        }
        for value, expected in cases.items():
            self.assertEqual(cardinal(value), expected, value)

    def test_hundreds_use_the_short_two(self):
        self.assertEqual(cardinal(100), 'száz')
        self.assertEqual(cardinal(102), 'százkettő')
        self.assertEqual(cardinal(200), 'kétszáz')
        self.assertEqual(cardinal(932), 'kilencszázharminckettő')

    def test_thousands_and_the_hyphen_above_two_thousand(self):
        self.assertEqual(cardinal(1000), 'ezer')
        self.assertEqual(cardinal(1932), 'ezerkilencszázharminckettő')
        self.assertEqual(cardinal(2000), 'kétezer')
        self.assertEqual(cardinal(2024), 'kétezer-huszonnégy')
        self.assertEqual(cardinal(16000), 'tizenhatezer')

    def test_millions(self):
        self.assertEqual(cardinal(1_000_000), 'egymillió')
        self.assertEqual(cardinal(2_000_000), 'kétmillió')
        self.assertEqual(cardinal(3_200_000), 'hárommillió-kétszázezer')

    def test_two_becomes_short_in_front_of_a_noun(self):
        self.assertEqual(cardinal(2, before_noun=True), 'két')
        self.assertEqual(cardinal(12, before_noun=True), 'tizenkét')
        self.assertEqual(cardinal(22, before_noun=True), 'huszonkét')
        self.assertEqual(cardinal(3, before_noun=True), 'három')


class OrdinalTests(unittest.TestCase):
    def test_the_irregular_first_two(self):
        self.assertEqual(ordinal(1), 'első')
        self.assertEqual(ordinal(2), 'második')

    def test_only_the_last_element_takes_the_ending(self):
        self.assertEqual(ordinal(932), 'kilencszázharminckettedik')
        self.assertEqual(ordinal(1932), 'ezerkilencszázharminckettedik')
        self.assertEqual(ordinal(102), 'százkettedik')
        self.assertEqual(ordinal(2024), 'kétezer-huszonnegyedik')

    def test_round_numbers(self):
        self.assertEqual(ordinal(10), 'tizedik')
        self.assertEqual(ordinal(20), 'huszadik')
        self.assertEqual(ordinal(100), 'századik')
        self.assertEqual(ordinal(1000), 'ezredik')
        self.assertEqual(ordinal(1_000_000), 'egymilliomodik')

    def test_days_of_the_month(self):
        self.assertEqual(day_of_month(1), 'elseje')
        self.assertEqual(day_of_month(2), 'másodika')
        self.assertEqual(day_of_month(5), 'ötödike')
        self.assertEqual(day_of_month(10), 'tizedike')
        self.assertEqual(day_of_month(21), 'huszonegyedike')
        self.assertEqual(day_of_month(31), 'harmincegyedike')


class ReportedBugTests(unittest.TestCase):
    """The Monty Python line that started this: "az Úr 932. esztendejében"."""

    def test_a_number_with_a_period_before_a_noun_is_an_ordinal(self):
        self.assertEqual(
            normalize_hungarian('Anglia, az Úr 932. esztendejében'),
            'Anglia, az Úr kilencszázharminckettedik esztendejében',
        )

    def test_a_period_that_ends_a_sentence_is_not_an_ordinal(self):
        self.assertEqual(
            normalize_hungarian('Összesen 932. Ennyi volt.'),
            'Összesen kilencszázharminckettő. Ennyi volt.',
        )

    def test_a_capitalised_counted_noun_still_reads_as_an_ordinal(self):
        self.assertEqual(normalize_hungarian('5. Fejezet'), 'ötödik Fejezet')


class DateTests(unittest.TestCase):
    def test_a_full_date_reads_year_month_day(self):
        self.assertEqual(
            normalize_hungarian('1932. március 5-én történt.'),
            'ezerkilencszázharminckettő március ötödikén történt.',
        )

    def test_a_bare_day_gets_its_dated_form(self):
        self.assertEqual(
            normalize_hungarian('március 5. volt'),
            'március ötödike volt',
        )

    def test_the_first_of_the_month_is_irregular(self):
        self.assertEqual(
            normalize_hungarian('1-jén indultak'), 'elsején indultak'
        )

    def test_a_year_in_front_of_a_month_stays_cardinal(self):
        self.assertEqual(
            normalize_hungarian('1932. március folyamán'),
            'ezerkilencszázharminckettő március folyamán',
        )

    def test_a_year_in_front_of_a_season_stays_cardinal(self):
        self.assertEqual(
            normalize_hungarian('1932. nyarán'),
            'ezerkilencszázharminckettő nyarán',
        )


class SuffixTests(unittest.TestCase):
    def test_a_hyphenated_suffix_keeps_its_own_vowels(self):
        cases = {
            '1932-ben': 'ezerkilencszázharminckettőben',
            '3-at': 'hármat',
            '3-an': 'hárman',
            '3-as': 'hármas',
            '6-os': 'hatos',
            '5-öt': 'ötöt',
            '22-en': 'huszonketten',
            '1000-et': 'ezret',
            '7-et': 'hetet',
        }
        for written, spoken in cases.items():
            self.assertEqual(normalize_hungarian(written), spoken, written)

    def test_an_accented_suffix_marks_a_day_of_the_month(self):
        self.assertEqual(normalize_hungarian('5-ét'), 'ötödikét')
        self.assertEqual(normalize_hungarian('3-án'), 'harmadikán')
        self.assertEqual(normalize_hungarian('10-éig'), 'tizedikéig')

    def test_the_for_suffix_is_not_a_date(self):
        self.assertEqual(normalize_hungarian('5-ért'), 'ötért')


class EverydayNumberTests(unittest.TestCase):
    def test_a_number_in_front_of_a_noun_uses_the_short_two(self):
        self.assertEqual(
            normalize_hungarian('Mindössze 12 alma volt.'),
            'Mindössze tizenkét alma volt.',
        )

    def test_a_number_in_front_of_a_conjunction_stays_long(self):
        self.assertEqual(
            normalize_hungarian('2 és 3 meg 12 ember.'),
            'kettő és három meg tizenkét ember.',
        )

    def test_grouped_thousands_are_one_number(self):
        self.assertEqual(
            normalize_hungarian('10 000 forint'), 'tízezer forint'
        )
        self.assertEqual(
            normalize_hungarian('10.000 forint'), 'tízezer forint'
        )

    def test_decimals(self):
        self.assertEqual(
            normalize_hungarian('Ez 3,5 méter.'), 'Ez három egész öt méter.'
        )

    def test_percentages(self):
        self.assertEqual(normalize_hungarian('50%'), 'ötven százalék')
        self.assertEqual(
            normalize_hungarian('50%-os esély'), 'ötven százalékos esély'
        )

    def test_degrees(self):
        self.assertEqual(
            normalize_hungarian('21 °C volt'), 'huszonegy Celsius-fok volt'
        )
        self.assertEqual(
            normalize_hungarian('21 °C-ban'), 'huszonegy Celsius-fokban'
        )
        self.assertEqual(
            normalize_hungarian('-5 °C-ra hűlt'),
            'mínusz öt Celsius-fokra hűlt',
        )

    def test_clock_times(self):
        self.assertEqual(
            normalize_hungarian('10:30-kor'), 'tíz óra harminc perckor'
        )
        self.assertEqual(normalize_hungarian('8:00-kor'), 'nyolc órakor')


class RomanNumeralTests(unittest.TestCase):
    def test_a_century_is_an_ordinal(self):
        self.assertEqual(
            normalize_hungarian('A XX. században élt.'),
            'A huszadik században élt.',
        )

    def test_a_rulers_name_keeps_its_capital(self):
        self.assertEqual(
            normalize_hungarian('II. Erzsébet királynő'),
            'Második Erzsébet királynő',
        )

    def test_letters_that_only_look_roman_are_left_alone(self):
        for text in ('Megvettem a DVD. Aztán hazamentem.',
                     'Az MTA. tagja lett.'):
            self.assertEqual(normalize_hungarian(text), text, text)


class RoutingTests(unittest.TestCase):
    def test_hungarian_text_never_reaches_the_english_normalizer(self):
        with patch('core.tts_engine._num2words_fallback') as fallback:
            out = apply_text_normalization('Az Úr 932. esztendejében', 'hu')
        fallback.assert_not_called()
        self.assertIn('kilencszázharminckettedik', out)

    def test_hungarian_is_recognised_without_a_language_tag(self):
        self.assertTrue(looks_hungarian(None, 'Az idő későre jár, 12 óra.'))
        self.assertTrue(looks_hungarian('hu', 'anything'))
        self.assertFalse(looks_hungarian('en', 'I have 12 apples.'))

    def test_control_tags_survive_normalization(self):
        out = apply_text_normalization('[laughter] 3 alma és 2 körte', 'hu')
        self.assertIn('[laughter]', out)
        self.assertIn('három alma', out)

    def test_text_without_numbers_is_returned_unchanged(self):
        text = 'Nincs ebben a mondatban egyetlen szám sem.'
        self.assertEqual(normalize_hungarian(text), text)


if __name__ == '__main__':
    unittest.main()
