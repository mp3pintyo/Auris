import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "auris_release", ROOT / "scripts" / "release.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseVersionTest(unittest.TestCase):
    def test_parse_and_bump_each_supported_level(self):
        self.assertEqual(release.parse_version("3.1.7"), (3, 1, 7))
        self.assertEqual(release.next_version("3.1.7", "patch"), "3.1.8")
        self.assertEqual(release.next_version("3.1.7", "minor"), "3.2.0")
        self.assertEqual(release.next_version("3.1.7", "major"), "4.0.0")

    def test_invalid_version_and_level_are_rejected(self):
        for value in ("v3.1.0", "3.1", "03.1.0", "3.1.0-beta"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.parse_version(value)
        with self.assertRaisesRegex(ValueError, "patch, minor vagy major"):
            release.next_version("3.1.0", "large")


class ReleaseFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.version = self.root / "VERSION"
        self.changelog = self.root / "CHANGELOG.md"

    def write(
        self,
        version="3.1.0",
        unreleased=(
            "### Magyar\n\n#### Hozzáadva\n\n- Új funkció.\n\n"
            "### English\n\n#### Added\n\n- New feature.\n"
        ),
    ):
        self.version.write_text(version + "\n", encoding="utf-8")
        self.changelog.write_text(
            "# Változásnapló\n\n"
            "## [Unreleased]\n\n"
            + unreleased
            + "\n## [3.1.0] - 2026-09-10\n\n"
            "### Magyar\n\n#### Hozzáadva\n\n- Előző kiadás.\n\n"
            "### English\n\n#### Added\n\n- Previous release.\n",
            encoding="utf-8",
        )

    def test_prepare_moves_unreleased_content_and_updates_version(self):
        self.write()
        result = release.prepare_release(
            self.version, self.changelog, "patch", "2026-09-11"
        )
        self.assertEqual(result, "3.1.1")
        self.assertEqual(self.version.read_text(encoding="utf-8"), "3.1.1\n")
        text = self.changelog.read_text(encoding="utf-8")
        self.assertIn("## [Unreleased]\n\n## [3.1.1] - 2026-09-11", text)
        self.assertIn("### Magyar\n\n#### Hozzáadva\n\n- Új funkció.", text)
        self.assertIn("### English\n\n#### Added\n\n- New feature.", text)

    def test_prepare_rejects_empty_unreleased_section(self):
        self.write(unreleased="")
        with self.assertRaisesRegex(ValueError, "Unreleased"):
            release.prepare_release(
                self.version, self.changelog, "patch", "2026-09-11"
            )
        self.assertEqual(self.version.read_text(encoding="utf-8"), "3.1.0\n")

    def test_validation_accepts_matching_version_and_tag(self):
        self.write(version="3.1.1", unreleased="")
        text = self.changelog.read_text(encoding="utf-8").replace(
            "## [3.1.0]", "## [3.1.1]"
        )
        self.changelog.write_text(text, encoding="utf-8")
        self.assertEqual(
            release.validate_release(self.version, self.changelog, "v3.1.1"),
            "3.1.1",
        )

    def test_validation_rejects_tag_mismatch_and_unreleased_changes(self):
        self.write(version="3.1.1", unreleased="")
        text = self.changelog.read_text(encoding="utf-8").replace(
            "## [3.1.0]", "## [3.1.1]"
        )
        self.changelog.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "tag"):
            release.validate_release(self.version, self.changelog, "v3.2.0")
        self.changelog.write_text(
            text.replace("## [Unreleased]\n", "## [Unreleased]\n\n- Függő változás.\n"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Unreleased"):
            release.validate_release(self.version, self.changelog, "v3.1.1")

    def test_release_notes_extract_exact_section(self):
        self.write()
        notes = release.release_notes(self.changelog, "3.1.0")
        self.assertIn("### Magyar", notes)
        self.assertIn("### English", notes)
        with self.assertRaisesRegex(ValueError, "2.0.0"):
            release.release_notes(self.changelog, "2.0.0")

    def test_release_notes_rejects_a_single_language_section(self):
        self.write(
            unreleased="### Magyar\n\n#### Hozzáadva\n\n- Csak magyarul.\n"
        )
        with self.assertRaisesRegex(ValueError, "Magyar.*English"):
            release.prepare_release(
                self.version, self.changelog, "patch", "2026-09-11"
            )


if __name__ == "__main__":
    unittest.main()
