"""Isolated UI fixture. Produces silent test WAVs, never real model audio."""

import sys, os, hashlib, time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import tempfile

qa = Path(
    os.environ.get(
        "AURIS_QA_DATA", str(Path(tempfile.gettempdir()) / "auris-implementation-qa")
    )
)
qa.mkdir(parents=True, exist_ok=True)
from core import database, settings, tts_engine, exporter
import numpy as np
import soundfile as sf

database.DB_PATH = str(qa / "reader.db")
settings.SETTINGS_FILE = qa / "settings.json"
tts_engine.AUDIO_CACHE_DIR = str(qa / "audio")
exporter.EXPORTS_DIR = str(qa / "exports")
for name in ["audio", "exports", "uploads"]:
    (qa / name).mkdir(exist_ok=True)
settings.save(
    {"tts_engine": "omnivoice", "onboarding_complete": False, "theme": "night"}
)
import app
from core.experience_api import bp

if "experience" not in app.app.blueprints:
    app.app.register_blueprint(bp)
app.UPLOAD_DIR = str(qa / "uploads")


class TestToneEngine:
    engine_name = "higgs"

    def status(self):
        return {
            "state": "ready",
            "engine": "omnivoice",
            "model_exists": True,
            "accel": {},
        }

    def generate_preview(self, sample_text="", **kw):
        return self.generate(text=sample_text, **kw)

    def invalidate_voice_prompt(self, *args):
        pass

    def load_async(self):
        pass

    def unload(self):
        pass

    def reload(self):
        pass

    def wait_until_unloaded(self, timeout=600):
        return True

    def cancel(self):
        return True

    def set_dedicated_cuda_stream(self, *args):
        pass

    def generate(self, text="", **kw):
        key = hashlib.sha256((text + str(kw)).encode()).hexdigest()
        path = qa / "audio" / (key + ".wav")
        duration = float(os.environ.get("AURIS_QA_AUDIO_SECONDS", "1"))
        sf.write(path, np.zeros(round(24000 * duration), dtype=np.float32), 24000)
        return {
            "audio_path": str(path),
            "cache_key": key,
            "duration_sec": duration,
            "cache_hit": False,
        }

    def generate_many(self, items, on_item=None, on_status=None, **kw):
        results = []
        for i, item in enumerate(items):
            time.sleep(0.04)
            result = self.generate(**item)
            results.append(result)
            if on_item:
                on_item(i, result)
        return results


app.tts = TestToneEngine()


@app.app.route("/api/qa-fixture")
def fixture_marker():
    return {"fixture": True}


app.app.run(host="127.0.0.1", port=int(os.environ.get("AURIS_QA_PORT", "17861")), threaded=True, use_reloader=False)
