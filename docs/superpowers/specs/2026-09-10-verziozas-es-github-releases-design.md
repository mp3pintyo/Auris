# Auris verziózás és GitHub Releases – specifikáció

## Cél

Az Auris teljes fejlesztési története kapjon visszakereshető, felhasználóknak is
érthető verziókat. A Git tagek rögzítsék a pontos forrásállapotot, a GitHub
Releases oldal legyen a kiadások nyilvános idővonala, a repositoryban tárolt
`CHANGELOG.md` pedig maradjon a változások szerkeszthető és verziókövetett
forrása.

## Verziózási szabály

Az Auris hatásalapú, SemVer alakú verziókat használ: `MAJOR.MINOR.PATCH`.

- `PATCH`: hibajavítás, kisebb felületi vagy dokumentációs javítás, belső
  folyamatfejlesztés, kompatibilitást nem érintő optimalizálás.
- `MINOR`: új, visszafelé kompatibilis felhasználói képesség vagy érdemi
  munkafolyamat-fejlesztés.
- `MAJOR`: új Auris-termékgeneráció, alapvetően átalakított használati mód,
  illetve visszafelé nem kompatibilis változás.

Ez tudatosan tágabb a könyvtárak szigorú Semantic Versioning szabályánál:
önálló alkalmazásként egy nagy termékgeneráció akkor is kaphat főverziót, ha
nem tör meg programozói API-t.

## Történeti kiadások

Minden commit pontosan egy kiadási tartományba kerül. Merge commitok és egy
azonos funkcióhoz tartozó apró köztes commitok nem kapnak külön verziót.

| Verzió | Célcommit | Eredeti dátum | Kiadási téma |
|---|---|---|---|
| `v1.0.0` | `d175c1f` | 2026-07-13 | A forkolt projekt első Auris-állapota |
| `v1.1.0` | `7b7ecc4` | 2026-07-17 | GPU-kezelés, két worker és szegmensexport |
| `v1.2.0` | `4603c75` | 2026-07-18 | Egyedi export és Higgs TTS 3 |
| `v1.2.1` | `340b8ff` | 2026-07-18 | Lejátszási pozíció javítása Stop után |
| `v1.3.0` | `d34ef6f` | 2026-07-19 | Reszponzív felület |
| `v1.3.1` | `977906d` | 2026-07-19 | Kisebb felület-, minőség- és importjavítások |
| `v1.4.0` | `7dc3997` | 2026-07-19 | Voice clone és voice design szétválasztása |
| `v1.4.1` | `e5c8f10` | 2026-07-19 | Mondatkezdési hanghiba és generálási folyamat javítása |
| `v2.0.0` | `f336cdd` | 2026-07-19 | Helyi LLM-alapú szereplőfelismerés |
| `v2.1.0` | `ae5ad6c` | 2026-07-19 | Fejezet-előgenerálás és gyorsabb narráció |
| `v2.2.0` | `1996e41` | 2026-07-26 | Szereplőkezelés és szerkesztés |
| `v2.3.0` | `9d8de2a` | 2026-07-26 | Természetes szünetek, tisztább import és jobb export |
| `v2.4.0` | `2847b25` | 2026-07-26 | OpenAI-alapú szereplőfelismerés |
| `v2.4.1` | `fd345e1` | 2026-07-27 | Import- és beszélő-hozzárendelési javítások |
| `v3.0.0` | `7db9952` | 2026-09-10 | Magyar olvasási élmény, Trafilatura, feladatok, M4B és mentés |
| `v3.1.0` | `58c41f7` | 2026-09-10 | DOCX, Apple MPS, cache- és könyvtárfejlesztések |
| `v3.1.1` | a release-rendszer végső commitja | 2026-09-10 | Verziózási és kiadási folyamat |

Az első tizenhat tag történeti commitra mutat. A `v3.1.1` a jelen specifikáció
teljes megvalósítását tartalmazó végső commitot jelöli.

## Repositoryban tárolt elemek

- `VERSION`: egyetlen sorban az aktuális verzió `v` előtag nélkül.
- `CHANGELOG.md`: magyar, Keep a Changelog jellegű idővonal, legfelül
  `Unreleased` szakasszal és alatta a fenti kiadásokkal.
- `RELEASING.md`: a verzióválasztás, helyi ellenőrzés, kiadás-előkészítés,
  tagelés és hibajavítás pontos menete.
- `scripts/release.py`: függőségmentes parancssori eszköz a következő verzió
  kiszámítására, az `Unreleased` szakasz kiadássá alakítására, az egyezések
  ellenőrzésére és egy verzió release notes szövegének kiírására.
- `reader/tests/test_release_tool.py`: a verziószámítás, changelog-átalakítás,
  ellenőrzés és release notes kinyerés regressziós tesztjei.
- `.github/workflows/release.yml`: `vX.Y.Z` tag push esetén ellenőrzi a
  verziót és a changelogot, futtatja a release-eszköz tesztjét, ellenőrzi, hogy
  a tag commitja a `main` része, majd GitHub Release-t hoz létre.
- `.github/release.yml`: GitHub által generált release notes kategóriák kézi
  vagy kiegészítő használathoz.
- `.github/pull_request_template.md`: minden új PR-ben kötelezővé teszi a
  változástípus és a changelog-hatás megjelölését.

## `scripts/release.py` felülete

```text
python scripts/release.py current
python scripts/release.py next patch|minor|major
python scripts/release.py prepare patch|minor|major [--date YYYY-MM-DD]
python scripts/release.py check [--tag vX.Y.Z]
python scripts/release.py notes [--version X.Y.Z]
```

Az eszköz a repository gyökeréhez képest kezeli a `VERSION` és
`CHANGELOG.md` fájlt. A `prepare` csak nem üres `Unreleased` tartalommal fut,
frissíti a `VERSION` fájlt, és dátummal ellátott verziószakasszá alakítja a
változásokat. A `check` hibával áll le érvénytelen verzió, hiányzó changelog
szakasz, eltérő tag vagy nem üres `Unreleased` szakasz esetén. A `notes` a
kért verzió törzsét adja vissza GitHub Release leírásként.

## Jövőbeli kiadási folyamat

1. Minden felhasználót érintő változás bekerül a `CHANGELOG.md` `Unreleased`
   részének `Added`, `Changed`, `Fixed` vagy `Removed` kategóriájába.
2. A PR szerzője megjelöli a javasolt `patch`, `minor` vagy `major` hatást.
3. Kiadáskor a karbantartó lefuttatja a teljes Auris tesztcsomagot és a
   Playwright-ellenőrzést.
4. A `release.py prepare <szint>` frissíti a verziót és lezárja a changelogot.
5. A változások commitolása után annotált `vX.Y.Z` tag készül és felkerül.
6. A GitHub workflow csak ellenőrzött, `main`-be tartozó tagből publikál
   Release-t; egy már létező Release esetén sikeresen, módosítás nélkül leáll.

## Történeti GitHub Release-ek

A visszamenőleges kiadások magyar, kézzel kurált jegyzetet kapnak a
`CHANGELOG.md` megfelelő szakaszából. Minden leírás feltünteti az eredeti
fejlesztési dátumot, mert a GitHub publikálási időpontja szükségképpen a
mostani migráció időpontja lesz. A `v3.1.0` megemlíti a külső közreműködőket
és a merge-elt pull requesteket.

## Hibakezelés és biztonság

- Meglévő tag eltérő commitra nem mozgatható.
- Publikált kiadás tartalma nem írható át ugyanazzal a verzióval; javítás új
  patch kiadásban történik.
- A workflow minimális `contents: write` jogosultságot kap.
- A release-eszköz nem commitol, nem tagel és nem pushol automatikusan.
- A teljes TTS-függőségkészlet nem települ GitHub runnerre; a workflow a
  függőségmentes release-tesztet futtatja, míg a teljes alkalmazásteszt a
  dokumentált helyi kiadási kapu.

## Elfogadási feltételek

- A `VERSION` értéke `3.1.1`, és egyezik a legújabb taggel.
- A changelog minden történeti commitot lefed a meghatározott tartományokban.
- A release-eszköz tesztjei és a teljes Auris tesztcsomag sikeresek.
- A changelogból minden kiadás release notes szövege kinyerhető.
- A 17 annotált tag a meghatározott commitokra mutat.
- A GitHubon 17 publikált Release látható, és `v3.1.1` a Latest.
- A `main` tiszta, és megegyezik az `origin/main` állapotával.
