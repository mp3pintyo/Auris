# Változásnapló

Az Auris fontos változásai ebben a fájlban követhetők. A projekt
`MAJOR.MINOR.PATCH` alakú, hatásalapú verziózást használ: a patch kisebb
javítás, a minor új kompatibilis képesség, a major pedig új termékgeneráció
vagy inkompatibilis változás.

## [Unreleased]

## [3.1.2] - 2026-09-10

### Fixed

- A GitHub Actions tag-szűrője már ténylegesen elindítja a kiadási workflow-t
  a `vX.Y.Z` tagekre; a kiadási eszköz továbbra is szigorúan ellenőrzi a tag
  és a `VERSION` egyezését.

## [3.1.1] - 2026-09-10

### Release process

- Elkészült a teljes történeti változásnapló és a repositoryban tárolt
  `VERSION` fájl.
- Függőségmentes kiadás-előkészítő és ellenőrző parancssori eszköz készült.
- A `vX.Y.Z` tagekből ellenőrzött GitHub Release-t publikáló workflow és
  egységes pull request ellenőrzőlista került a projektbe.

## [3.1.0] - 2026-09-10

**Történeti kiadás.** A fejlesztések eredeti dátuma 2026-07-21 és 2026-07-28;
a pull requestek 2026-09-10-én kerültek a `main` ágba.

### Added

- Apple Silicon MPS gyorsítás az OmniVoice és a Higgs TTS motorhoz.
- DOCX-import Word címsorstílusokból képzett fejezetekkel és használható
  hibaüzenetekkel.
- Könyvcím, szerző és nyelv szerkesztése; nyelvváltáskor a régi hangok
  megerősítés után érvénytelenné válnak.
- A teljes könyvkártya megnyitja az olvasót, miközben a műveletgombok külön
  használhatók maradnak.

### Fixed

- A TTS cache-kulcs már megkülönbözteti az OmniVoice tényleges eszközét és
  adattípusát.
- A fájltípus-jelvény világos borítókon is olvasható.

### Contributors

- MPS támogatás: @snokris.
- DOCX, cache és könyvtári fejlesztések: @lvalics.

## [3.0.0] - 2026-09-10

### Added

- Trafilatura-alapú nyilvános webcikk-import biztonságos URL-kezeléssel és
  szerkeszthető előnézettel.
- Kereshető, szűrhető és rendezhető könyvtár, folytatási kártya és
  szerkeszthető könyvadatok.
- Mobilbarát olvasó, időugrás, hátralévőidő-becslés és elalvásidőzítő.
- Magyar kiejtési szótár és újrafelhasználható hangprofilok.
- Tartós, megszakítható és explicit folytatható háttérfeladatok.
- Teljes, hibás vagy kijelölt fejezetek szereplőelemzésének újrafuttatása.
- Fejezetjelölős M4B-export, könyvtármentés és visszaállítás.

### Changed

- A felület és a beépített súgó átfogó magyar olvasási élményt kapott.
- A fejezet megnyitása már nem indít automatikus hanggenerálást; az előtöltés
  a Lejátszás művelettel kezdődik.

### Fixed

- A kézzel narrációra állított szöveg egyértelmű „Narráció” jelölést kap.
- Hangváltáskor a korábbi interaktív generálás befejezése nem akadályozza a
  mentést, az olvasó elhagyása pedig megszakítja a függő kéréseket.

## [2.4.1] - 2026-07-27

### Fixed

- Javult a könyvimport megbízhatósága.
- A kézzel hozzárendelt szereplők bekerülnek a fejezetszűrt listába.
- A narrációra visszaállított mondatok nem számítanak szereplő-előfordulásnak.
- A normál nézet helyesen különbözteti meg az új szereplőt, a kézi narrációt
  és az automatikus narrátorváltást.

## [2.4.0] - 2026-07-26

### Added

- OpenAI szolgáltató használható a szereplők és dialógusok felismeréséhez.

## [2.3.0] - 2026-07-26

### Added

- Az exportok saját kimeneti mappába menthetők.
- Az MP3-fájlok fejezetcímet, könyvcímet, szerzőt és fejezetsorszámot kapnak.

### Changed

- A valódi bekezdések végén természetes szünet hallható lejátszáskor és
  exportban.
- Az 500 karakternél hosszabb szövegegységek biztonságos határon darabolódnak.
- Az import eltávolítja a problémás BOM, zero-width, vezérlő- és hibás Unicode
  karaktereket.

## [2.2.0] - 2026-07-26

### Added

- A felismert szereplők kezelhetők és szerkeszthetők.
- A beszélő-hozzárendelések kézzel javíthatók.

### Changed

- Frissült a szereplőkezelés dokumentációja és a fejlesztői útmutatás.

## [2.1.0] - 2026-07-19

### Added

- Fejezet-előgenerálás a folyamatosabb hallgatáshoz.
- Gyorsított narrátoros generálás és hatékonyabb TTS-kötegelés.

## [2.0.0] - 2026-07-19

### Added

- Helyi LM Studio, Ollama és más OpenAI-kompatibilis szerver használható
  fejezetenkénti szereplő- és dialógusfelismeréshez.
- A hozzárendelések tartósan tárolódnak, a szereplők külön hangot kaphatnak.
- Kapcsolatellenőrző és modellbeállítások kerültek a Beállítások oldalra.
- Részleges elemzési hiba esetén a sikeres fejezetek eredménye megmarad.

### Changed

- Elemzés előtt a TTS modell felszabadítja a VRAM-ot.
- A korábbi spaCy/regex felismerés tartalék módként maradt elérhető.

## [1.4.1] - 2026-07-19

### Fixed

- Megszűnt a mondatok elején esetenként hallható idegen „ó” hang.
- A mondatok külön hangklipként készülnek, miközben a GPU-kötegelés megmarad.
- Folyamatosabb lett a hanggenerálás és verziózott cache váltotta fel az érintett
  régi klipeket.

## [1.4.0] - 2026-07-19

### Changed

- Referenciahang esetén kizárólag voice clone, referenciahang nélkül kizárólag
  voice design fut.
- A kötegelt generálás és a cache-kulcsok ugyanazt a módválasztást követik.
- Hangot befolyásoló beállításváltáskor nem játszható vissza régi cache-elt hang.

## [1.3.1] - 2026-07-19

### Added

- Új Auris favicon.
- Jelzés figyelmeztet a még el nem mentett beállításokra.

### Changed

- Az OmniVoice minimális minőségi beállítása 12 lépés lett.

### Fixed

- Az import kiszűri a felolvasásba kerülő oldalszámokat.

## [1.3.0] - 2026-07-19

### Added

- Reszponzív elrendezés készült kisebb képernyőkhöz és mobil használathoz.

## [1.2.1] - 2026-07-18

### Fixed

- A Stop megnyomása után a lejátszás nem ugrik vissza a fejezet elejére.

## [1.2.0] - 2026-07-18

### Added

- Higgs TTS 3 — 4B beszédmotor.
- Egyedi fejezet- és könyvexport.

## [1.1.0] - 2026-07-17

### Added

- GPU-erőforrás-kezelés és optimalizált TTS-futtatás.
- Két workerrel végzett export.
- Szegmensenkénti export és mondaton belüli szüneteltetés.

## [1.0.0] - 2026-07-13

### Added

- A forkolt projekt első Auris-állapota EPUB, PDF és TXT könyvimporttal,
  OmniVoice felolvasással, könyvtárral, olvasóval és exporttal.
