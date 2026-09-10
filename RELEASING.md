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
[CHANGELOG.md](CHANGELOG.md) `Unreleased` szakaszába, az alábbi kategóriák
egyikébe:

- `Added` – új képesség;
- `Changed` – megváltozott működés;
- `Fixed` – hibajavítás;
- `Removed` – eltávolított vagy megszüntetett képesség;
- `Release process` – kiadási és karbantartási változás.

A pull requestben jelölni kell a javasolt verzióhatást és azt, hogy frissült-e
a változásnapló.

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
- a release-eszköz tesztjei sikeresek;
- a tag commitja a távoli `main` történetéhez tartozik.

Siker esetén a megfelelő changelog-szakaszból létrejön a GitHub Release. Már
létező Release változatlan marad.

## Hibás kiadás javítása

Publikált taget nem mozgatunk és kiadott forrásállapotot nem írunk át. Ha a
kiadásban hiba maradt, javító commit és új patch verzió készül. Hibás vagy
félbeszakadt workflow esetén előbb az Actions naplóját kell kijavítani, majd
ugyanaz a tag újrafuttatható; a release workflow idempotens.
