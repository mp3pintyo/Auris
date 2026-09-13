const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/reader.js'), 'utf8');
function extract(name, nextName) { return source.slice(source.indexOf(`function ${name}(`), source.indexOf(`function ${nextName}(`)); }
const code = extract('pauseAfterSegmentMs', '_swapAudio') + extract('_onAudioEnded', '_onAudioError');
function fixture(pause) {
  const calls = [];
  const context = {segments: [{text: 'Vége.', pause_ms: pause}], currentSegIdx: 0, currentChapterId: 1,
    isPlaying: true, _playGen: 1, _sleepMode: 'off', _interSegmentTimer: null, _pendingSegmentIdx: -1,
    DEFAULT_SEGMENT_PAUSE_MS: 350, PARAGRAPH_PAUSE_MS: 850, ELLIPSIS_PAUSE_MS: 1500, DIALOGUE_TURN_PAUSE_MS: 550,
    stopWordHighlight() {}, queueProgressSave() {}, stopPlayback() { calls.push('stop'); context.isPlaying = false; context._playGen++; },
    setTimeout(callback, delay) { calls.push({callback, delay}); return 1; }};
  vm.createContext(context); vm.runInContext(code, context); context._onAudioEnded();
  return {context, calls};
}
for (const pause of [null, undefined, 0]) assert.deepEqual(fixture(pause).calls, ['stop']);
{
  const {context, calls} = fixture(1250);
  assert.equal(calls.length, 1); assert.equal(calls[0].delay, 1250);
  assert.equal(context.isPlaying, true); assert.equal(context._pendingSegmentIdx, 1);
  calls[0].callback(); assert.equal(calls[1], 'stop');
}
{
  const {context, calls} = fixture(900);
  context.isPlaying = false; calls[0].callback();
  assert.equal(calls.length, 1, 'Pause cancels finishing callback.');
  context.isPlaying = true; context._playGen++;
  calls[0].callback(); assert.equal(calls.length, 1, 'Old timer cannot stop newer playback.');
}
console.log('Final explicit pause, immediate zero/default, and stale cancellation checks passed.');
