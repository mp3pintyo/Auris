# Auris kiadási folyamat

Az Auris a felhasználói hatás alapján választ `MAJOR.MINOR.PATCH` verziót. A
Git tag alakja `vX.Y.Z`, míg a [VERSION](VERSION) fájlban nincs `v` előtag.

## Mikor melyik szám változik?

- **patch**: hibajavítás, kis felületi vagy dokumentációs módosítás, belső
  optimalizálás és release-folyamat javítása;
- **minor**: új, visszafelé kompatibilis képesség vagy jelentős
  munkafolyamat-fejlesztés;
- **major**: új Auris-termékgeneráció, alapvetően átalakított használati mód
  vagy visszafelé nem kompatibilis változás.

Ha egy kiadás többféle változást tartalmaz, mindig a legnagyobb hatás dönt.

## Fejlesztés közben

Minden felhasználót érintő módosítás kerüljön a
[CHANGELOG.md](CHANGELOG.md) `Unreleased` szakaszába. Minden kiadásban kötelező
a `### Magyar` és a `### English` alfejezet, azonos tartalommal, az alábbi
kategóriák egyikében:

- `Added` – új képesség;
- `Changed` – megváltozott működés;
- `Fixed` – hibajavítás;
- `Removed` – eltávolított vagy megszüntetett képesség;
- `Release process` – kiadási és karbantartási változás.

A pull requestben jelölni kell a javasolt verzióhatást és azt, hogy mindkét
nyelven frissült-e a változásnapló.

## Kiadás előkészítése

Az aktuális és a következő verzió ellenőrzése:

```powershell
reader\.venv\Scripts\python.exe scripts\release.py current
reader\.venv\Scripts\python.exe scripts\release.py next patch
```

Az `Unreleased` szakasz lezárása és a `VERSION` frissítése:

```powershell
reader\.venv\Scripts\python.exe scripts\release.py prepare patch
reader\.venv\Scripts\python.exe scripts\release.py check --tag vX.Y.Z
```

A `patch` helyére `minor` vagy `major` írható. A kész release notes előnézete:

```powershell
reader\.venv\Scripts\python.exe scripts\release.py notes --version X.Y.Z
```

## Kötelező ellenőrzések

A repository gyökeréből:

```powershell
reader\.venv\Scripts\python.exe -m unittest discover -s reader\tests -p "test_*.py"
node --test reader\tests\reader_experience.node.test.js reader\tests\voice_studio.node.test.js
reader\.venv\Scripts\python.exe -m pip check
```

Felületet érintő változásnál a helyi Playwright-ellenőrzésnek is sikeresnek
kell lennie, képernyőképpel és üres böngészőkonzol-hibalistával.

## Commit, tag és publikálás

Az előkészített fájlokat a változással együtt vagy külön release commitban kell
elmenteni. Ezután:

```powershell
git add VERSION CHANGELOG.md
git commit -m "release: prepare Auris vX.Y.Z"
git tag -a vX.Y.Z -m "Auris vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

A tag push elindítja a `.github/workflows/release.yml` workflow-t. A workflow
ellenőrzi, hogy:

- a tag megegyezik a `VERSION` értékével;
- a changelog tartalmazza a verziót és az `Unreleased` rész üres;
- a kiadási jegyzet magyar és angol szakaszt is tartalmaz;
- a release-eszköz tesztjei sikeresek;
- a tag commitja a távoli `main` történetéhez tartozik.

Siker esetén a megfelelő changelog-szakaszból létrejön a GitHub Release. Már
létező Release változatlan marad.

## Hibás kiadás javítása

Publikált taget nem mozgatunk és kiadott forrásállapotot nem írunk át. Ha a
kiadásban hiba maradt, javító commit és új patch verzió készül. Hibás vagy
félbeszakadt workflow esetén előbb az Actions naplóját kell kijavítani, majd
ugyanaz a tag újrafuttatható; a release workflow idempotens.

---

# Auris release process

Auris selects a `MAJOR.MINOR.PATCH` version based on user impact. Git tags use
the `vX.Y.Z` form, while the [VERSION](VERSION) file omits the `v` prefix.

## Choosing the version number

- **patch**: a bug fix, small UI or documentation change, internal
  optimization, or release-process correction;
- **minor**: a new backward-compatible capability or a substantial workflow
  improvement;
- **major**: a new Auris product generation, a fundamental workflow change, or
  a backward-incompatible change.

When a release contains multiple types of change, the highest impact determines
the version.

## During development

Every user-facing change must be added to the `Unreleased` section of
[CHANGELOG.md](CHANGELOG.md). Each release section must contain both a
`### Magyar` and a `### English` subsection, with matching information under
the relevant categories:

- `Added` / `Hozzáadva` — new capabilities;
- `Changed` / `Változott` — changed behavior;
- `Fixed` / `Javítva` — bug fixes;
- `Removed` / `Eltávolítva` — removed capabilities;
- `Release process` / `Kiadási folyamat` — release and maintenance changes.

The pull request must identify the proposed version impact and confirm whether
the changelog was updated in both languages.

## Preparing a release

Check the current and next version:

```powershell
reader\.venv\Scripts\python.exe scripts\release.py current
reader\.venv\Scripts\python.exe scripts\release.py next patch
```

Promote the bilingual `Unreleased` section and update `VERSION`:

```powershell
reader\.venv\Scripts\python.exe scripts\release.py prepare patch
reader\.venv\Scripts\python.exe scripts\release.py check --tag vX.Y.Z
```

Replace `patch` with `minor` or `major` when required. Preview the finished
release notes with:

```powershell
reader\.venv\Scripts\python.exe scripts\release.py notes --version X.Y.Z
```

## Required checks

Run from the repository root:

```powershell
reader\.venv\Scripts\python.exe -m unittest discover -s reader\tests -p "test_*.py"
node --test reader\tests\reader_experience.node.test.js reader\tests\voice_studio.node.test.js
reader\.venv\Scripts\python.exe -m pip check
```

For UI changes, local Playwright verification must also pass with a screenshot
and an empty browser-console error list.

## Commit, tag, and publish

Commit the prepared files with the change or in a dedicated release commit:

```powershell
git add VERSION CHANGELOG.md
git commit -m "release: prepare Auris vX.Y.Z"
git tag -a vX.Y.Z -m "Auris vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

Pushing the tag starts `.github/workflows/release.yml`. The workflow verifies
that:

- the tag matches `VERSION`;
- the changelog contains the version and `Unreleased` is empty;
- the release notes contain both Hungarian and English sections;
- the release-tool tests pass;
- the tagged commit belongs to the remote `main` history.

On success, GitHub publishes the matching bilingual changelog section as the
Release description. An existing Release remains unchanged.

## Correcting a bad release

Do not move a published tag or rewrite a released source state. If a release
contains an error, create a fix commit and a new patch version. For a failed or
interrupted workflow, correct the Actions failure first and rerun the same tag;
the release workflow is idempotent.
