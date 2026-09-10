import io
import json
import os
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app as application
from core import database, settings, voice_preset_file
from core.experience_api import bp


def make_wav(seconds=0.1, sample_rate=24000):
    frames = int(seconds * sample_rate)
    data = b'\0\0' * frames
    header = b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE'
    header += b'fmt ' + struct.pack(
        '<IHHIIHH', 16, 1, 1, sample_rate, sample_rate * 2, 2, 16
    )
    return header + b'data' + struct.pack('<I', len(data)) + data


class VoiceProfilePortabilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(database, 'DB_PATH', str(self.root / 'reader.db')),
            patch.object(settings, 'SETTINGS_FILE', self.root / 'settings.json'),
            patch.object(application, '_startup_complete', True),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])
        database.init_db()
        if 'experience' not in application.app.blueprints:
            application.app.register_blueprint(bp)
        application.app.config['TESTING'] = True
        self.client = application.app.test_client()

    def test_archive_round_trip_preserves_voice_fields(self):
        wav = make_wav()
        blob = voice_preset_file.build_archive(
            'Magyar narrátor', wav, ref_text='Pontos átirat.',
            source_filename='hang.wav', instruct='male, elderly, low pitch',
        )
        payload = voice_preset_file.read_archive(blob)
        self.assertEqual(payload.audio_bytes, wav)
        self.assertEqual(payload.ref_text, 'Pontos átirat.')
        self.assertEqual(payload.instruct, 'male, elderly, low pitch')

    def test_path_traversal_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('meta.json', json.dumps({'format': 1, 'name': 'X'}))
            archive.writestr('../../evil.exe', b'bad')
        with self.assertRaises(voice_preset_file.VoicePresetFileError):
            voice_preset_file.read_archive(buffer.getvalue())

    def test_export_then_import_creates_portable_profile(self):
        audio = self.root / 'voice.wav'
        audio.write_bytes(make_wav())
        with database.get_conn() as conn:
            profile_id = conn.execute(
                'INSERT INTO voice_profiles(name,instruct,ref_audio_path,ref_audio_name,ref_text) '
                'VALUES(?,?,?,?,?)',
                ('Anna', 'female, young adult', str(audio), 'anna.wav', 'Szia.'),
            ).lastrowid
        exported = self.client.get(f'/api/voice-profiles/{profile_id}/export')
        self.assertEqual(exported.status_code, 200)
        with database.get_conn() as conn:
            conn.execute('DELETE FROM voice_profiles')
        imported = self.client.post(
            '/api/voice-profiles/import',
            data={'file': (io.BytesIO(exported.data), 'Anna.aurisvoice')},
            content_type='multipart/form-data',
        )
        self.assertEqual(imported.status_code, 200, imported.get_json())
        with database.get_conn() as conn:
            profile = conn.execute('SELECT * FROM voice_profiles').fetchone()
        self.assertEqual(profile['name'], 'Anna')
        self.assertEqual(profile['instruct'], 'female, young adult')
        self.assertEqual(profile['ref_text'], 'Szia.')
        self.assertTrue(os.path.isfile(profile['ref_audio_path']))

    def test_import_rejects_wrong_extension(self):
        response = self.client.post(
            '/api/voice-profiles/import',
            data={'file': (io.BytesIO(b'PK'), 'voice.zip')},
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
