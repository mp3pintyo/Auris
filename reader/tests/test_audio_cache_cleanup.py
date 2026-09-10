import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app as application
from core import database, settings, tts_engine
from core.experience_api import bp


class AudioCacheCleanupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.patches = [
            patch.object(database, 'DB_PATH', str(self.root / 'reader.db')),
            patch.object(settings, 'SETTINGS_FILE', self.root / 'settings.json'),
            patch.object(tts_engine, 'AUDIO_CACHE_DIR', str(self.cache)),
            patch.object(application, '_startup_complete', True),
            patch.object(application, '_export_exclusive_active', return_value=False),
            patch.object(application, '_character_analysis_is_active', return_value=False),
            patch.object(application, '_chapter_generation_jobs', {}),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])
        database.init_db()
        if 'experience' not in application.app.blueprints:
            application.app.register_blueprint(bp)
        application.app.config['TESTING'] = True
        self.client = application.app.test_client()

    def test_old_orphans_are_removed_but_referenced_audio_is_kept(self):
        used = self.cache / 'used.wav'
        orphan = self.cache / 'orphan.wav'
        recent = self.cache / 'recent.wav'
        for path in (used, orphan, recent):
            path.write_bytes(b'RIFF-audio')
        old = time.time() - 7200
        os.utime(used, (old, old))
        os.utime(orphan, (old, old))
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO books(id,title,file_path,file_type) VALUES(1,'B','b.txt','txt')"
            )
            conn.execute(
                "INSERT INTO chapters(id,book_id,title,order_num,content) VALUES(1,1,'C',0,'x')"
            )
            conn.execute(
                "INSERT INTO tts_segments(book_id,chapter_id,segment_index,text,enriched_text,audio_path) "
                "VALUES(1,1,0,'x','x',?)",
                (str(used),),
            )
        status = self.client.get('/api/storage').get_json()['audio_cache']
        self.assertEqual(status['orphan_files'], 2)
        result = self.client.post('/api/storage/audio-cache/cleanup', json={})
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertTrue(used.exists())
        self.assertFalse(orphan.exists())
        self.assertTrue(recent.exists())


if __name__ == '__main__':
    unittest.main()
