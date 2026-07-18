import re
import unittest
from pathlib import Path


READER_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "reader.js"


class ReaderPlaybackTests(unittest.TestCase):
    def test_stop_keeps_current_chapter_position(self):
        source = READER_JS.read_text(encoding="utf-8")
        handler = re.search(
            r"document\.getElementById\('btn-stop'\)\.onclick\s*=\s*\(\)\s*=>\s*\{(.*?)\n\};",
            source,
            re.DOTALL,
        )

        self.assertIsNotNone(handler)
        self.assertIn("stopPlayback();", handler.group(1))
        self.assertNotIn("setCurrentSegment(0", handler.group(1))


if __name__ == "__main__":
    unittest.main()
