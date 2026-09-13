# Változásnapló / Changelog

Az Auris fontos változásai ebben a fájlban követhetők magyarul és angolul. A
projekt `MAJOR.MINOR.PATCH` alakú, hatásalapú verziózást használ: a patch
kisebb javítás, a minor új kompatibilis képesség, a major pedig új
termékgeneráció vagy inkompatibilis változás.

All notable Auris changes are documented here in Hungarian and English. The
project uses impact-based `MAJOR.MINOR.PATCH` versioning: patch releases contain
small fixes, minor releases add compatible capabilities, and major releases
represent a new product generation or an incompatible change.

## [Unreleased]

## [3.4.0] - 2026-09-13

### Magyar

#### Hozzáadva

- Opcionális fejezetszerkesztő OCR-javításhoz: cím/alcím/bekezdés, keresés–csere, blokkbontás, mentés, elvetés, előző változat visszaállítása és párhuzamos szerkesztések ütközésvédelme.
- Blokkonkénti tempó és 0–5000 ms szünet, összecsukott finomhangoló eszközökkel és narrátorhangos előnézettel. A szünetek lejátszáskor és exportkor is érvényesek; a Higgs nyers módja nem alkalmaz tempóvezérlést.

#### Javítva

- Az importált fejezetcímek a törzsszövegben és a felolvasásban is megmaradnak. Az EPUB/DOCX címsorszintek, bekezdések és a felismerhető PDF/OCR-tördelés megőrzése; a címek nem folynak össze a következő bekezdéssel.
- Szerkesztéskor a megmaradt szöveg beszélőjelölései és olvasási hivatkozásai követik a változást, az azonos hangrészek újrahasználhatók. A beépített magyar súgó részletesen leírja az új munkafolyamatot és korlátait.

### English

#### Added

- Optional chapter editor for OCR corrections: heading/subheading/paragraph blocks, find and replace, block splitting, save/discard, previous-version restore and concurrent-edit protection.
- Per-block speed and 0–5000 ms pauses in collapsed narration controls, with narrator-voice preview. Pauses apply to both playback and export; Higgs raw mode does not apply speed controls.

#### Fixed

- Imported chapter headings remain in the body text and narration. EPUB/DOCX heading levels, paragraphs and recognizable PDF/OCR structure are preserved; headings no longer run into the next paragraph.
- Editing reanchors unchanged speaker units and reading references, while matching audio remains reusable. Built-in Hungarian documentation explains the workflow and its limitations.

## [3.3.1] - 2026-09-11

### Magyar

#### Javítva

- Részletes Windows-telepítési útmutató a súgóban: Tesseract és magyar nyelvi adat, Calibre, FFmpeg/ffprobe, PATH, ellenőrző parancsok, újraindítás és hibaelhárítás.

### English

#### Fixed

- Step-by-step Windows setup in the built-in help: Tesseract and Hungarian language data, Calibre, FFmpeg/ffprobe, PATH, verification commands, restarting and troubleshooting.

## [3.3.0] - 2026-09-11

### Magyar

#### Hozzáadva

- Opcionális helyi Tesseract OCR magyar és többnyelvű felismeréssel, valamint Calibre-alapú AZW/AZW3, FB2, RTF, ODT, HTML, DOC és LRF import; eszközellenőrzés és import előtti szövegelőnézet.
- Napi/heti könyvtármentés megőrzési szabállyal, letöltéssel, utolsó siker/hiba kijelzésével és kimaradt mentések pótlásával az Auris futása közben.
- Bővebb könyvadatok: sorozatszám, leírás, kiadó és kiadási dátum; borító és könyvmetaadatok az M4B-fájlban.

#### Változott

- Az M4B-export kis hangblokkokkal, RF64 ideiglenes fájllal dolgozik, az egész könyv memóriába töltése helyett. Megszakítható feldolgozási fázisok, opcionális hangerő-kiegyenlítés és véglegesítés előtti ffprobe-ellenőrzés védi a kész exportot.
- A lejátszás a mondaton belüli időpontot is menti; más hangváltozat esetén biztonságosan a mondat elejéről folytatódik.
- A magyar súgó és a README az új funkciókat, az opcionális eszközök telepítését és a korlátokat is leírja.

### English

#### Added

- Optional local Tesseract OCR with Hungarian/multilingual recognition and Calibre-backed AZW/AZW3, FB2, RTF, ODT, HTML, DOC and LRF import; tool detection and text preview before importing.
- Daily/weekly library backups with retention, downloads, last-success/error status and catch-up while Auris is running.
- Extended book metadata: series index, description, publisher and publication date; embedded cover art and book metadata in M4B files.

#### Changed

- M4B export writes bounded audio blocks to an RF64 temporary file instead of loading the whole book into memory. Cancellable processing stages, optional loudness mastering and ffprobe verification precede publication of the finished audio file.
- Playback persists the time within a sentence and safely resets that offset when the audio variant changes.
- Hungarian help and README describe the new workflows, optional tool installation and limits.

## [3.2.4] - 2026-09-10

### Magyar

#### Kiadási folyamat

- Az Auris dokumentációs és kiadási skillje mostantól a projekt `.agents/skills` könyvtárában, a forráskóddal együtt verziózva biztosítja, hogy minden feltöltött változás teljes, ellenőrzött GitHub Release kiadással záruljon.
- A kiadási útmutató kötelező tesztparancsai mostantól a helyes `reader` munkakönyvtárból futnak, így az alkalmazásmodulok importálhatók.

### English

#### Release process

- The Auris documentation and release skill now lives in the project `.agents/skills` directory and is versioned with the source, ensuring every pushed change concludes with a complete, verified GitHub Release.
- The required test commands in the release guide now run from the correct `reader` working directory so application modules can be imported.

## [3.2.3] - 2026-09-10

### Magyar

#### Változott

- Az OmniVoice GPU-gyorsítás automatikus módja NVIDIA CUDA alatt CUDA Graphot, AMD ROCm, Apple MPS és CPU alatt optimalizált PyTorch útvonalat választ, és a beállításokban a tényleges gyorsítóeszköz jelenik meg.
- A CUDA Graph gyorsítótár biztonságosabban kezeli a változó tensoralakokat és sikertelen capture esetén automatikusan visszaáll az optimalizált PyTorch útvonalra.

#### Javítva

- A változó hosszúságú hangoknál megszűnt a költséges cuDNN-algoritmuskeresés: a mért RTX 3090-es konfiguráción az első négyes OmniVoice-köteg 27,62 másodperc helyett 2,53 másodperc alatt készült el, változatlan 16 dekódolási lépéssel.
- A telepítő felismeri az új NVIDIA `CUDA UMD Version` kimenetet, megőrzi a működő AMD ROCm PyTorch-környezetet, és Apple Silicon gépen helyesen jelzi az MPS gyorsítást.

#### Hozzáadva

- Megismételhető, gyorsítótár nélküli OmniVoice teljesítménymérő készült hangtervezéshez és hangklónozáshoz, JSON eredményekkel és WAV mintákkal.

### English

#### Changed

- OmniVoice automatic GPU acceleration now selects CUDA Graph on NVIDIA CUDA and optimized PyTorch on AMD ROCm, Apple MPS, and CPU, while Settings reports the actual acceleration device.
- The CUDA Graph cache now handles varying tensor shapes safely and automatically falls back to optimized PyTorch when graph capture fails.

#### Fixed

- Costly cuDNN algorithm searches are disabled for variable-length audio: on the measured RTX 3090 configuration, the first four-item OmniVoice batch dropped from 27.62 seconds to 2.53 seconds with the same 16 decoding steps.
- The installer recognizes the newer NVIDIA `CUDA UMD Version` output, preserves a working AMD ROCm PyTorch environment, and correctly reports MPS acceleration on Apple Silicon.

#### Added

- Added a reproducible cache-free OmniVoice benchmark for voice design and voice cloning, with JSON results and WAV samples.

## [3.2.2] - 2026-09-10

### Magyar

#### Javítva

- Lejátszás közben a következő két TTS-szegmens prioritással, egyenként készül, így a hosszú háttér-előtöltés nem okoz 30–40 másodperces hangszünetet.

### English

#### Fixed

- During playback, the next two TTS segments now use a priority, one-at-a-time path, preventing long background prewarming from causing 30–40 second audio gaps.

## [3.2.1] - 2026-09-10

### Magyar

#### Javítva

- A lejátszás közben szükséges következő TTS-szegmens nem várja meg a teljes előtöltési batch befejezését, így a hosszú GPU-generálás nem állítja meg a hangot.

### English

#### Fixed

- The next TTS segment needed during playback no longer waits for the entire look-ahead batch, so long GPU generation does not stop the audio.

## [3.2.0] - 2026-09-10

### Magyar

#### Hozzáadva

- DRM-mentes PRC/MOBI könyvek közvetlen importja metaadat-, borító-, tartalomjegyzék- és számozottjelenet-felismeréssel.
- Magyar számok, sorszámok, dátumok, időpontok, százalékok, hőmérsékletek és ragos számok nyelvhelyes felolvasási normalizálása OmniVoice és Higgs alatt.
- Magyar, betűvel írt fejezet- és részcímek, valamint névvel jelölt bevezető és záró szakaszok felismerése.
- Szabadon megadható hangpróbaszöveg és a narrátor- vagy szereplőpróba letöltése WAV-ként.
- Referenciahangot, átiratot és hangutasítást együtt hordozó `.aurisvoice` hangprofil-export és -import.
- A tárhelylapon megjelenő hangcache-statisztika és biztonságos árva-cache takarítás.

#### Javítva

- A fejezet előtti valódi bevezető próza nem vész el rövid címoldalként.
- Az olvasó gyorsbillentyűi nem fogják el a Ctrl, Cmd vagy Alt billentyűkombinációkat.

#### Közreműködők

- Az átvett és a jelenlegi Aurishoz átdolgozott fejlesztések eredeti szerzői: [@flc](https://github.com/flc/Auris) és [@snokris](https://github.com/snokris/Auris-Studio).

### English

#### Added

- Direct import for DRM-free PRC/MOBI books with metadata, cover, table-of-contents, and numbered-scene detection.
- Grammatically correct Hungarian speech normalization for cardinals, ordinals, dates, times, percentages, temperatures, and suffixed numbers in OmniVoice and Higgs.
- Detection of spelled-out Hungarian chapter and part headings, plus named opening and closing sections.
- Custom voice-preview text and WAV downloads for narrator and character previews.
- `.aurisvoice` profile export and import that keeps reference audio, transcript, and voice instruction together.
- Audio-cache statistics and safe orphan-cache cleanup on the Storage page.

#### Fixed

- Real introductory prose before the first chapter is no longer discarded as a short title page.
- Reader shortcuts no longer intercept Ctrl, Cmd, or Alt key combinations.

#### Contributors

- Original authors of the imported and Auris-adapted work: [@flc](https://github.com/flc/Auris) and [@snokris](https://github.com/snokris/Auris-Studio).

## [3.1.3] - 2026-09-10

### Magyar

#### Változott

- A teljes változásnapló, a kiadási útmutató és a GitHub Release leírások
  magyar és angol nyelven is elérhetők.
- A kiadási ellenőrző megköveteli mindkét nyelvi szakaszt az új kiadásokban.

### English

#### Changed

- The complete changelog, release guide, and GitHub Release descriptions are
  available in both Hungarian and English.
- Release validation now requires both language sections in every new release.

## [3.1.2] - 2026-09-10

### Magyar

#### Javítva

- A GitHub Actions tag-szűrője már ténylegesen elindítja a kiadási workflow-t
  a `vX.Y.Z` tagekre; a kiadási eszköz továbbra is szigorúan ellenőrzi a tag
  és a `VERSION` egyezését.

### English

#### Fixed

- The GitHub Actions tag filter now starts the release workflow for `vX.Y.Z`
  tags; the release tool continues to strictly verify that the tag matches
  `VERSION`.

## [3.1.1] - 2026-09-10

### Magyar

#### Kiadási folyamat

- Elkészült a teljes történeti változásnapló és a repositoryban tárolt
  `VERSION` fájl.
- Függőségmentes kiadás-előkészítő és ellenőrző parancssori eszköz készült.
- A `vX.Y.Z` tagekből ellenőrzött GitHub Release-t publikáló workflow és
  egységes pull request ellenőrzőlista került a projektbe.

### English

#### Release process

- Added a complete historical changelog and a repository-level `VERSION` file.
- Added a dependency-free command-line tool for preparing and validating
  releases.
- Added a workflow that publishes validated GitHub Releases from `vX.Y.Z` tags
  and a consistent pull request checklist.

## [3.1.0] - 2026-09-10

### Magyar

**Történeti kiadás.** A fejlesztések eredeti dátuma 2026-07-21 és 2026-07-28;
a pull requestek 2026-09-10-én kerültek a `main` ágba.

#### Hozzáadva

- Apple Silicon MPS gyorsítás az OmniVoice és a Higgs TTS motorhoz.
- DOCX-import Word címsorstílusokból képzett fejezetekkel és használható
  hibaüzenetekkel.
- Könyvcím, szerző és nyelv szerkesztése; nyelvváltáskor a régi hangok
  megerősítés után érvénytelenné válnak.
- A teljes könyvkártya megnyitja az olvasót, miközben a műveletgombok külön
  használhatók maradnak.

#### Javítva

- A TTS cache-kulcs már megkülönbözteti az OmniVoice tényleges eszközét és
  adattípusát.
- A fájltípus-jelvény világos borítókon is olvasható.

#### Közreműködők

- MPS támogatás: @snokris.
- DOCX, cache és könyvtári fejlesztések: @lvalics.

### English

**Historical release.** The changes were originally developed on 2026-07-21
and 2026-07-28; their pull requests were merged into `main` on 2026-09-10.

#### Added

- Apple Silicon MPS acceleration for the OmniVoice and Higgs TTS engines.
- DOCX import with chapters derived from Word heading styles and actionable
  error messages.
- Editing for book title, author, and language; changing the language
  invalidates old voices after confirmation.
- The entire book card opens the reader while action buttons remain separately
  usable.

#### Fixed

- TTS cache keys now distinguish the actual OmniVoice device and data type.
- File-type badges remain readable on light covers.

#### Contributors

- MPS support: @snokris.
- DOCX, cache, and library improvements: @lvalics.

## [3.0.0] - 2026-09-10

### Magyar

#### Hozzáadva

- Trafilatura-alapú nyilvános webcikk-import biztonságos URL-kezeléssel és
  szerkeszthető előnézettel.
- Kereshető, szűrhető és rendezhető könyvtár, folytatási kártya és
  szerkeszthető könyvadatok.
- Mobilbarát olvasó, időugrás, hátralévőidő-becslés és elalvásidőzítő.
- Magyar kiejtési szótár és újrafelhasználható hangprofilok.
- Tartós, megszakítható és explicit folytatható háttérfeladatok.
- Teljes, hibás vagy kijelölt fejezetek szereplőelemzésének újrafuttatása.
- Fejezetjelölős M4B-export, könyvtármentés és visszaállítás.

#### Változott

- A felület és a beépített súgó átfogó magyar olvasási élményt kapott.
- A fejezet megnyitása már nem indít automatikus hanggenerálást; az előtöltés
  a Lejátszás művelettel kezdődik.

#### Javítva

- A kézzel narrációra állított szöveg egyértelmű „Narráció” jelölést kap.
- Hangváltáskor a korábbi interaktív generálás befejezése nem akadályozza a
  mentést, az olvasó elhagyása pedig megszakítja a függő kéréseket.

### English

#### Added

- Trafilatura-based public web article import with safe URL handling and an
  editable preview.
- A searchable, filterable, sortable library with a continue-reading card and
  editable book metadata.
- A mobile-friendly reader with time seeking, remaining-time estimates, and a
  sleep timer.
- A Hungarian pronunciation dictionary and reusable voice profiles.
- Persistent background jobs that can be cancelled and explicitly resumed.
- Rerunning character analysis for all, failed, or selected chapters.
- Chapter-aware M4B export plus library backup and restore.

#### Changed

- The interface and built-in help received a comprehensive Hungarian reading
  experience.
- Opening a chapter no longer starts audio generation automatically; preloading
  begins when Play is pressed.

#### Fixed

- Text manually assigned to narration now shows a clear “Narráció” label.
- Finishing an earlier interactive generation no longer blocks voice changes,
  and leaving the reader cancels pending audio requests.

## [2.4.1] - 2026-07-27

### Magyar

#### Javítva

- Javult a könyvimport megbízhatósága.
- A kézzel hozzárendelt szereplők bekerülnek a fejezetszűrt listába.
- A narrációra visszaállított mondatok nem számítanak szereplő-előfordulásnak.
- A normál nézet helyesen különbözteti meg az új szereplőt, a kézi narrációt
  és az automatikus narrátorváltást.

### English

#### Fixed

- Improved book import reliability.
- Manually assigned characters now appear in the chapter-filtered list.
- Sentences reset to narration no longer count as character occurrences.
- The normal view now correctly distinguishes a new character, manual
  narration, and an automatic switch back to the narrator.

## [2.4.0] - 2026-07-26

### Magyar

#### Hozzáadva

- OpenAI szolgáltató használható a szereplők és dialógusok felismeréséhez.

### English

#### Added

- OpenAI can be used as a provider for character and dialogue detection.

## [2.3.0] - 2026-07-26

### Magyar

#### Hozzáadva

- Az exportok saját kimeneti mappába menthetők.
- Az MP3-fájlok fejezetcímet, könyvcímet, szerzőt és fejezetsorszámot kapnak.

#### Változott

- A valódi bekezdések végén természetes szünet hallható lejátszáskor és
  exportban.
- Az 500 karakternél hosszabb szövegegységek biztonságos határon darabolódnak.
- Az import eltávolítja a problémás BOM, zero-width, vezérlő- és hibás Unicode
  karaktereket.

### English

#### Added

- Exports can be saved to a dedicated output folder.
- MP3 files receive chapter title, book title, author, and chapter number
  metadata.

#### Changed

- Natural pauses are inserted at real paragraph endings during playback and
  export.
- Text units longer than 500 characters are split at safe boundaries.
- Import removes problematic BOM, zero-width, control, and malformed Unicode
  characters.

## [2.2.0] - 2026-07-26

### Magyar

#### Hozzáadva

- A felismert szereplők kezelhetők és szerkeszthetők.
- A beszélő-hozzárendelések kézzel javíthatók.

#### Változott

- Frissült a szereplőkezelés dokumentációja és a fejlesztői útmutatás.

### English

#### Added

- Detected characters can be managed and edited.
- Speaker assignments can be corrected manually.

#### Changed

- Updated character-management documentation and developer guidance.

## [2.1.0] - 2026-07-19

### Magyar

#### Hozzáadva

- Fejezet-előgenerálás a folyamatosabb hallgatáshoz.
- Gyorsított narrátoros generálás és hatékonyabb TTS-kötegelés.

### English

#### Added

- Chapter pregeneration for more continuous listening.
- Faster narrator generation and more efficient TTS batching.

## [2.0.0] - 2026-07-19

### Magyar

#### Hozzáadva

- Helyi LM Studio, Ollama és más OpenAI-kompatibilis szerver használható
  fejezetenkénti szereplő- és dialógusfelismeréshez.
- A hozzárendelések tartósan tárolódnak, a szereplők külön hangot kaphatnak.
- Kapcsolatellenőrző és modellbeállítások kerültek a Beállítások oldalra.
- Részleges elemzési hiba esetén a sikeres fejezetek eredménye megmarad.

#### Változott

- Elemzés előtt a TTS modell felszabadítja a VRAM-ot.
- A korábbi spaCy/regex felismerés tartalék módként maradt elérhető.

### English

#### Added

- Local LM Studio, Ollama, and other OpenAI-compatible servers can perform
  chapter-level character and dialogue detection.
- Assignments are stored persistently, and characters can receive individual
  voices.
- Connection testing and model configuration were added to Settings.
- Successful chapter results are preserved when analysis partially fails.

#### Changed

- The TTS model releases VRAM before analysis.
- The previous spaCy/regex detector remains available as a fallback.

## [1.4.1] - 2026-07-19

### Magyar

#### Javítva

- Megszűnt a mondatok elején esetenként hallható idegen „ó” hang.
- A mondatok külön hangklipként készülnek, miközben a GPU-kötegelés megmarad.
- Folyamatosabb lett a hanggenerálás és verziózott cache váltotta fel az érintett
  régi klipeket.

### English

#### Fixed

- Removed the occasional stray “ó” sound at the start of sentences.
- Sentences are generated as separate audio clips while GPU batching remains
  enabled.
- Audio generation is smoother, and a versioned cache replaces affected old
  clips.

## [1.4.0] - 2026-07-19

### Magyar

#### Változott

- Referenciahang esetén kizárólag voice clone, referenciahang nélkül kizárólag
  voice design fut.
- A kötegelt generálás és a cache-kulcsok ugyanazt a módválasztást követik.
- Hangot befolyásoló beállításváltáskor nem játszható vissza régi cache-elt hang.

### English

#### Changed

- A reference recording exclusively selects voice cloning; without one, voice
  design is used exclusively.
- Batched generation and cache keys follow the same mode selection.
- Changing a voice-affecting setting prevents playback of stale cached audio.

## [1.3.1] - 2026-07-19

### Magyar

#### Hozzáadva

- Új Auris favicon.
- Jelzés figyelmeztet a még el nem mentett beállításokra.

#### Változott

- Az OmniVoice minimális minőségi beállítása 12 lépés lett.

#### Javítva

- Az import kiszűri a felolvasásba kerülő oldalszámokat.

### English

#### Added

- Added a new Auris favicon.
- Added a warning for settings that have not yet been saved.

#### Changed

- The minimum OmniVoice quality setting is now 12 steps.

#### Fixed

- Import filters page numbers that would otherwise be read aloud.

## [1.3.0] - 2026-07-19

### Magyar

#### Hozzáadva

- Reszponzív elrendezés készült kisebb képernyőkhöz és mobil használathoz.

### English

#### Added

- Added a responsive layout for smaller screens and mobile use.

## [1.2.1] - 2026-07-18

### Magyar

#### Javítva

- A Stop megnyomása után a lejátszás nem ugrik vissza a fejezet elejére.

### English

#### Fixed

- Playback no longer jumps to the beginning of the chapter after pressing Stop.

## [1.2.0] - 2026-07-18

### Magyar

#### Hozzáadva

- Higgs TTS 3 — 4B beszédmotor.
- Egyedi fejezet- és könyvexport.

### English

#### Added

- Added the Higgs TTS 3 — 4B speech engine.
- Added custom chapter and book export.

## [1.1.0] - 2026-07-17

### Magyar

#### Hozzáadva

- GPU-erőforrás-kezelés és optimalizált TTS-futtatás.
- Két workerrel végzett export.
- Szegmensenkénti export és mondaton belüli szüneteltetés.

### English

#### Added

- Added GPU resource management and optimized TTS execution.
- Added export using two workers.
- Added segment-based export and pausing within a sentence.

## [1.0.0] - 2026-07-13

### Magyar

#### Hozzáadva

- A forkolt projekt első Auris-állapota EPUB, PDF és TXT könyvimporttal,
  OmniVoice felolvasással, könyvtárral, olvasóval és exporttal.

### English

#### Added

- The first Auris state of the fork, with EPUB, PDF, and TXT book import,
  OmniVoice narration, a library, reader, and export.
