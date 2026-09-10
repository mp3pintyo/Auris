# Auris Versioning and GitHub Releases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a complete historical Auris release timeline and a repeatable, validated process for future version bumps and GitHub Releases.

**Architecture:** `VERSION` and `CHANGELOG.md` are the repository sources of truth. A dependency-free Python CLI prepares and validates versions, while a tag-triggered GitHub Actions workflow publishes the matching changelog section as the release body. Historical tags and releases are created only after the implementation is merged and verified.

**Tech Stack:** Git, GitHub Releases, GitHub Actions, Python standard library, `unittest`, Markdown, YAML

**Spec:** `docs/superpowers/specs/2026-09-10-verziozas-es-github-releases-design.md`

## Global Constraints

- Version numbers use `MAJOR.MINOR.PATCH`; Git tags add the `v` prefix.
- Current implemented product version is `3.1.0`; release infrastructure closes as patch release `3.1.1`.
- Existing historical tags must never be moved after publication.
- User-facing release notes and process documentation are Hungarian.
- GitHub CI must not install the GPU/TTS dependency stack.
- Full validation uses `reader\.venv\Scripts\python.exe` from the repository root or `.venv\Scripts\python.exe` from `reader`.

---

### Task 1: Dependency-free release CLI

**Files:**
- Create: `scripts/release.py`
- Create: `reader/tests/test_release_tool.py`

**Interfaces:**
- Consumes: root `VERSION` and `CHANGELOG.md` paths.
- Produces: `parse_version(str) -> tuple[int, int, int]`, `next_version(str, str) -> str`, `prepare_release(Path, Path, str, str) -> str`, `validate_release(Path, Path, str | None) -> str`, and `release_notes(Path, str) -> str`.

- [ ] **Step 1: Write failing unit tests**

```python
def test_minor_bump_resets_patch(self):
    self.assertEqual(release.next_version("3.1.7", "minor"), "3.2.0")

def test_prepare_moves_unreleased_content(self):
    version, changelog = self.files("3.1.0", "## [Unreleased]\n\n### Added\n- Új funkció.\n\n## [3.1.0] - 2026-09-10\n")
    self.assertEqual(release.prepare_release(version, changelog, "patch", "2026-09-10"), "3.1.1")
    self.assertIn("## [3.1.1] - 2026-09-10\n\n### Added\n- Új funkció.", changelog.read_text(encoding="utf-8"))

def test_check_rejects_tag_mismatch(self):
    with self.assertRaisesRegex(ValueError, "tag"):
        release.validate_release(version, changelog, "v3.2.0")
```

- [ ] **Step 2: Run tests and confirm the missing module failure**

Run: `reader\.venv\Scripts\python.exe -m unittest reader.tests.test_release_tool`

Expected: failure because `scripts/release.py` does not exist.

- [ ] **Step 3: Implement the CLI and file transformations**

Implement strict numeric SemVer parsing, `patch`/`minor`/`major` arithmetic,
non-empty `Unreleased` validation, dated changelog promotion, exact tag matching,
release-section extraction, argparse subcommands, and nonzero exits with concise
errors. File writes must use UTF-8 and preserve a trailing newline.

- [ ] **Step 4: Run the focused tests**

Run: `reader\.venv\Scripts\python.exe -m unittest reader.tests.test_release_tool`

Expected: all release-tool tests pass.

- [ ] **Step 5: Commit the tested CLI**

```powershell
git add scripts/release.py reader/tests/test_release_tool.py
git commit -m "feat: add validated release version tool"
```

### Task 2: Version sources and historical changelog

**Files:**
- Create: `VERSION`
- Create: `CHANGELOG.md`
- Create: `RELEASING.md`
- Modify: `README.md`
- Modify: `reader/templates/docs.html`

**Interfaces:**
- Consumes: the seventeen-version map in the specification and `scripts/release.py`.
- Produces: current version `3.1.1`, one extractable changelog section per version, and the documented future release procedure.

- [ ] **Step 1: Write the full historical changelog**

Create a Hungarian changelog with `## [Unreleased]`, then sections from
`3.1.1` through `1.0.0`. Group changes under `Added`, `Changed`, `Fixed`, or
`Release process`; include original development dates and credit `@snokris` and
`@lvalics` in `3.1.0`.

- [ ] **Step 2: Add the current version and release guide**

Write `3.1.1` to `VERSION`. Document these exact commands in `RELEASING.md`:

```powershell
reader\.venv\Scripts\python.exe scripts\release.py next patch
reader\.venv\Scripts\python.exe scripts\release.py prepare patch
reader\.venv\Scripts\python.exe -m unittest discover -s reader\tests -p "test_*.py"
git tag -a vX.Y.Z -m "Auris vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

- [ ] **Step 3: Link release information from product documentation**

Add the current version, changelog link, Releases link, and release guide link
to `README.md`. Add a concise Hungarian “Verzió és frissítés” passage to the
built-in documentation without changing its information architecture.

- [ ] **Step 4: Validate every changelog section**

Run `release.py notes --version` for all seventeen versions and fail if any
section is missing or empty. Run `release.py check --tag v3.1.1`.

- [ ] **Step 5: Commit versioned documentation**

```powershell
git add VERSION CHANGELOG.md RELEASING.md README.md reader/templates/docs.html
git commit -m "docs: add complete Auris release history"
```

### Task 3: GitHub release automation and PR policy

**Files:**
- Create: `.github/workflows/release.yml`
- Create: `.github/release.yml`
- Create: `.github/pull_request_template.md`

**Interfaces:**
- Consumes: `VERSION`, `CHANGELOG.md`, `scripts/release.py`, tag name, and GitHub-provided `GITHUB_TOKEN`.
- Produces: a published GitHub Release whose title is `Auris X.Y.Z` and whose body is the matching changelog section.

- [ ] **Step 1: Add categorized generated-notes configuration**

Configure Hungarian categories for `breaking`, `feature`/`enhancement`,
`bug`/`fix`, and `documentation`, plus an “Egyéb változások” fallback. Exclude
`skip-changelog` pull requests and Dependabot from generated notes.

- [ ] **Step 2: Add the PR checklist**

Require a selected patch/minor/major impact, an `Unreleased` changelog entry or
an explicit no-user-impact reason, relevant tests, and documentation impact.

- [ ] **Step 3: Add the tag-triggered workflow**

On `v[0-9]+.[0-9]+.[0-9]+` tag push, checkout full history, run the focused
release-tool tests, run `release.py check --tag "$GITHUB_REF_NAME"`, fetch
`origin/main`, require the tagged commit to be its ancestor, extract release
notes, and call:

```bash
gh release view "$GITHUB_REF_NAME" >/dev/null 2>&1 || \
  gh release create "$GITHUB_REF_NAME" --verify-tag --latest \
    --title "Auris ${GITHUB_REF_NAME#v}" --notes-file release-notes.md
```

- [ ] **Step 4: Parse and inspect the YAML**

Use Python with the installed YAML module when available; otherwise inspect the
workflow with GitHub CLI after push. Confirm the workflow has only
`contents: write` and contains no model installation or untrusted script input.

- [ ] **Step 5: Commit automation**

```powershell
git add .github
git commit -m "ci: publish validated GitHub releases from tags"
```

### Task 4: Verification, main integration, tags, and GitHub Releases

**Files:**
- Modify: `docs/superpowers/plans/2026-09-10-verziozas-es-github-releases.md` only to mark completed checkboxes if useful.

**Interfaces:**
- Consumes: all repository release artifacts and the approved historical tag map.
- Produces: merged `main`, seventeen immutable annotated tags, and seventeen published GitHub Releases.

- [ ] **Step 1: Run repository validation**

From `reader`, run:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
node --test tests\reader_experience.node.test.js tests\voice_studio.node.test.js
.venv\Scripts\python.exe -m pip check
```

Render `/docs` with local Playwright, save a screenshot, inspect it, and require
zero browser console errors. Confirm every documentation table-of-contents link
targets a unique existing ID.

- [ ] **Step 2: Merge and push the implementation**

Merge `feat/versioned-releases` into the latest `main` with a merge commit,
repeat the release-tool and full Python tests on `main`, then push `main`.

- [ ] **Step 3: Create and verify annotated historical tags**

Create the sixteen approved historical tags at their exact commit IDs and
`v3.1.1` at the final release commit. Before pushing, verify every tag with
`git rev-list -n 1 TAG` and refuse to overwrite any existing remote tag.

- [ ] **Step 4: Publish historical releases**

For every tag without a release, extract its changelog section into a temporary
UTF-8 file and run `gh release create TAG --verify-tag --title "Auris X.Y.Z"
--notes-file FILE`. Mark only `v3.1.1` as latest. Do not modify an existing
release.

- [ ] **Step 5: Verify the public result**

Require `gh release list` to contain all seventeen versions, `gh release view
v3.1.1` to report latest, `git ls-remote --tags origin` to match local peeled
tag commits, no open release workflow failure, a clean working tree, and equal
local/remote `main` hashes.
