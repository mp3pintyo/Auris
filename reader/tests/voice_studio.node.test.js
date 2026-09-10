const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildInstruct,
  parseInstruct,
  filterCharacters,
  targetPayload,
  saveVoiceProfile,
  previewPayload,
  optionLabel,
} = require('../static/js/voice_studio.js');

test('neutral accent is omitted while saved prompt values remain parseable', () => {
  assert.deepEqual(
    parseInstruct('female, middle-aged, high pitch, british accent'),
    {
      gender: 'female',
      age: 'middle-aged',
      pitch: 'high pitch',
      accent: 'british accent',
    },
  );
  assert.equal(
    buildInstruct('female', 'middle-aged', 'high pitch', ''),
    'female, middle-aged, high pitch',
  );
  assert.equal(optionLabel(''), 'Semleges / nincs akcentus');
  assert.equal(optionLabel('young adult'), 'Fiatal felnőtt');
});

test('unchanged controls keep a legacy free-form prompt byte for byte', () => {
  const original = '  warm Hungarian voice, calm narration  ';
  const parsed = parseInstruct(original);

  assert.equal(
    buildInstruct(parsed.gender, parsed.age, parsed.pitch, parsed.accent, original),
    original,
  );
});

test('changing a structured control retains unknown prompt instructions', () => {
  const original = 'female, young adult, moderate pitch, warm Hungarian voice, calm narration';

  assert.equal(
    buildInstruct('female', 'elderly', 'moderate pitch', '', original),
    'female, elderly, moderate pitch, warm Hungarian voice, calm narration',
  );
});

test('character search is case-insensitive and keeps the original objects', () => {
  const characters = [
    { id: 1, name: 'Árvíztűrő Aladár' },
    { id: 2, name: 'Bori' },
  ];

  assert.deepEqual(filterCharacters(characters, 'ÁRVÍZ'), [characters[0]]);
  assert.deepEqual(filterCharacters(characters, '  '), characters);
});

test('profile target payload distinguishes narrator from character', () => {
  assert.deepEqual(targetPayload(7, null), { book_id: 7 });
  assert.deepEqual(targetPayload(7, 12), { book_id: 7, char_id: 12 });
});

test('profile creation saves current edits before capturing the profile', async () => {
  const events = [];
  const request = async (url, options) => {
    events.push(['request', url, JSON.parse(options.body)]);
    return { id: 4, name: 'Esti narrátor' };
  };

  const result = await saveVoiceProfile({
    bookId: 7,
    charId: null,
    name: ' Esti narrátor ',
    saveCurrent: async () => {
      events.push(['save']);
      return true;
    },
    request,
  });

  assert.deepEqual(events, [
    ['save'],
    ['request', '/api/voice-profiles', { name: 'Esti narrátor', book_id: 7 }],
  ]);
  assert.deepEqual(result, { id: 4, name: 'Esti narrátor' });
});

test('Hungarian preview text is included in preview requests', () => {
  const payload = previewPayload('female, young adult', 'Pontos átirat.');

  assert.equal(payload.instruct, 'female, young adult');
  assert.equal(payload.ref_text, 'Pontos átirat.');
  assert.match(payload.text, /árvíztűrő tükörfúrógép/i);
});

test('A custom Hungarian preview text is preserved', () => {
  const payload = previewPayload('female, young adult', '', 'Tűz és vér.');
  assert.equal(payload.text, 'Tűz és vér.');
});
