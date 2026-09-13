import unittest
import json
import os
import tempfile
from unittest.mock import patch

from core import text_editor
from core import exporter


class StructuredTextTests(unittest.TestCase):
    def test_headings_and_unpunctuated_paragraphs_are_separate(self):
        blocks = text_editor.validate_blocks([
            {'text': 'A kezdet', 'kind': 'heading'},
            {'text': 'Első bekezdés', 'kind': 'paragraph'},
            {'text': 'Második bekezdés.', 'kind': 'paragraph'},
        ])
        segs = text_editor.enrich_blocks(blocks, {}, 'narrator', True, None)
        self.assertEqual([s['text'] for s in segs], [b['text'] for b in blocks])
        self.assertEqual(segs[0]['enriched_text'], 'A kezdet.')
        self.assertEqual(exporter.pause_after_segment(segs[0], segs[1]), 1.2)
        self.assertTrue(all(s['ends_paragraph'] for s in segs))

    def test_explicit_zero_pause_and_speed(self):
        blocks = text_editor.validate_blocks([
            {'text': 'Várj…', 'kind': 'paragraph', 'pause_ms': 0, 'speed': 0.8},
            {'text': 'Folytatás.', 'kind': 'paragraph'},
        ])
        segs = text_editor.enrich_blocks(blocks, {}, 'narrator', False, None)
        self.assertEqual(exporter.pause_after_segment(segs[0], segs[1]), 0)
        self.assertEqual(segs[0]['speed'], .8)

    def test_invalid_controls_and_empty_text_rejected(self):
        for block in ({'text': ''}, {'text': 'x', 'speed': float('nan')},
                      {'text': 'x', 'pause_ms': -1}, {'text': 'x', 'kind': 'script'},
                      {'text': 'x', 'speed': True}):
            with self.subTest(block=block), self.assertRaises(ValueError):
                text_editor.validate_blocks([block])

    def test_duplicate_units_remap_in_order(self):
        self.assertEqual(text_editor.unit_mapping('Igen.\n\nIgen.', 'Cím\n\nIgen.\n\nIgen.'), {0: 1, 1: 2})

    def test_position_mapping_keeps_edited_and_duplicate_passages_near_their_context(self):
        old = [{'text': t} for t in ['Cím', 'Igen.', 'Hibás szó.', 'Igen.', 'Vége.']]
        new = [{'text': t} for t in ['Cím', 'Új rész.', 'Igen.', 'Javított szó.', 'Igen.', 'Vége.']]
        self.assertEqual(text_editor.position_mapping(old, new), {0: 0, 1: 2, 2: 3, 3: 4, 4: 5})

    def test_export_includes_final_explicit_pause(self):
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'sample.wav')
            sf.write(path, np.ones(exporter.SAMPLE_RATE), exporter.SAMPLE_RATE)
            result = exporter._merge_wavs([{'audio_path': path, 'pause_ms': 700}])
            self.assertEqual(len(result), int(exporter.SAMPLE_RATE * 1.7))
            self.assertTrue(np.all(result[-int(exporter.SAMPLE_RATE * .7):] == 0))


class EditorApiTests(unittest.TestCase):
    def setUp(self):
        import app
        from core import database
        self.app = app
        self.database = database
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db, self.old_startup = database.DB_PATH, app._startup_complete
        database.DB_PATH = os.path.join(self.tmp.name, 'test.db')
        app._startup_complete = True
        database.init_db()
        self.blocks = text_editor.validate_blocks([
            {'text': 'Első mondat.', 'kind': 'paragraph'},
            {'text': '- Szia!', 'kind': 'paragraph'},
        ])
        with database.get_conn() as conn:
            conn.execute("INSERT INTO books(id,title,file_path,file_type,character_analysis_status,character_analysis_provider) VALUES(1,'Könyv','test.txt','txt','complete','llm')")
            conn.execute('INSERT INTO chapters(id,book_id,title,order_num,content,blocks_json) VALUES(2,1,?,0,?,?)',
                         ('Fejezet', text_editor.content_of(self.blocks), json.dumps(self.blocks)))
            conn.execute("INSERT INTO characters(book_id,name,instruct) VALUES(1,'Anna','female')")
            conn.execute("INSERT INTO speaker_annotations(book_id,chapter_id,unit_index,unit_text,speaker_name,source) VALUES(1,2,1,'- Szia!','Anna','manual')")
        self.client = app.app.test_client()
        self.url = '/api/books/1/chapters/2/editor'
        self.client.get('/api/tts/segments/1/2')

    def tearDown(self):
        self.database.DB_PATH, self.app._startup_complete = self.old_db, self.old_startup
        self.tmp.cleanup()

    def save(self, blocks, revision=0):
        return self.client.put(self.url, json={'title': 'Fejezet', 'blocks': blocks, 'revision': revision})

    def test_edit_reanchors_speakers_bookmarks_and_progress_and_restores(self):
        with self.database.get_conn() as conn:
            conn.execute("INSERT INTO reading_progress(book_id,chapter_id,position,offset_sec,cache_key) VALUES(1,2,1,2,'old')")
            conn.execute("INSERT INTO bookmarks(book_id,chapter_id,segment_index,text_excerpt) VALUES(1,2,1,'- Szia!')")
        response = self.save([{'text': 'Új cím', 'kind': 'heading'}] + self.blocks)
        self.assertEqual(response.status_code, 200, response.get_json())
        segs = self.client.get('/api/tts/segments/1/2').get_json()
        self.assertEqual(segs[2]['character_name'], 'Anna')
        self.assertEqual(segs[0]['block_kind'], 'heading')
        with self.database.get_conn() as conn:
            self.assertEqual(conn.execute('SELECT position FROM reading_progress').fetchone()[0], 2)
            self.assertEqual(conn.execute('SELECT segment_index FROM bookmarks').fetchone()[0], 2)
            self.assertEqual(conn.execute('SELECT offset_sec FROM reading_progress').fetchone()[0], 0)
        restored = self.client.post(self.url + '/restore', json={'revision': 1})
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertEqual(restored.get_json()['blocks'], self.blocks)
        self.assertEqual(self.client.get('/api/tts/segments/1/2').get_json()[1]['character_name'], 'Anna')

    def test_pause_edit_reuses_matching_audio_but_speed_edit_invalidates(self):
        path = os.path.join(self.tmp.name, 'cached.wav')
        with open(path, 'wb') as f:
            f.write(b'audio')
        with self.database.get_conn() as conn:
            conn.execute("UPDATE tts_segments SET audio_path=?,cache_key='cached',duration_sec=1 WHERE segment_index=0", (path,))
        self.blocks[0]['pause_ms'] = 0
        self.assertEqual(self.save(self.blocks).status_code, 200)
        with self.database.get_conn() as conn:
            row = conn.execute('SELECT * FROM tts_segments WHERE segment_index=0').fetchone()
            self.assertEqual(row['audio_path'], path)
            self.assertEqual(row['pause_ms'], 0)
        self.blocks[0]['speed'] = .8
        self.assertEqual(self.save(self.blocks, 1).status_code, 200)
        with self.database.get_conn() as conn:
            self.assertIsNone(conn.execute('SELECT audio_path FROM tts_segments WHERE segment_index=0').fetchone()[0])

    def test_stale_invalid_and_cross_book_requests_do_not_mutate(self):
        self.assertEqual(self.save(self.blocks, 12).status_code, 409)
        self.assertEqual(self.save([{'text': 'x', 'speed': 8}]).status_code, 400)
        self.assertEqual(self.client.get('/api/books/99/chapters/2/editor').status_code, 404)
        self.assertEqual(self.client.put('/api/books/99/chapters/2/editor', json={'revision': 0}).status_code, 404)
        self.assertEqual(self.client.get(self.url).get_json()['revision'], 0)

    def test_active_work_blocks_edit(self):
        with patch.object(self.app, '_active_durable_jobs', return_value=[{'state': 'running'}]):
            self.assertEqual(self.save(self.blocks).status_code, 409)

    def test_failed_rebuild_leaves_content_and_revision_untouched(self):
        with patch.object(self.app, '_compute_segments_for_chapter', side_effect=RuntimeError('failed')):
            with self.app.app.test_client() as client:
                with patch.dict(self.app.app.config, {'TESTING': False}):
                    self.assertEqual(client.put(self.url, json={'title': 'Changed', 'blocks': self.blocks, 'revision': 0}).status_code, 500)
        self.assertEqual(self.client.get(self.url).get_json()['revision'], 0)

    def test_preview_uses_narrator_speed_and_includes_pause(self):
        import numpy as np
        import soundfile as sf
        from core import tts_engine
        path = os.path.join(self.tmp.name, 'source.wav')
        sf.write(path, np.zeros(exporter.SAMPLE_RATE), exporter.SAMPLE_RATE)
        with patch.object(self.app.tts, 'status', return_value={'state': 'ready'}), \
             patch.object(self.app.tts, 'generate', return_value={'audio_path': path}) as generate, \
             patch.object(tts_engine, 'AUDIO_CACHE_DIR', self.tmp.name):
            response = self.client.post(self.url + '/preview', json={'block': {'text': 'Próba', 'kind': 'heading', 'speed': .8, 'pause_ms': 700}})
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(generate.call_args.kwargs['speed'], .8)
            self.assertEqual(generate.call_args.kwargs['text'], 'Próba.')
            output = response.get_json()['audio_url'].rsplit('/', 1)[-1] + '.wav'
            self.assertAlmostEqual(sf.info(os.path.join(self.tmp.name, output)).duration, 1.7, places=3)


if __name__ == '__main__':
    unittest.main()
