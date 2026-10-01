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

### Magyar

#### Hozzáadva

- Windowson a Supertonic 3 és a Parakeet beszédfelismerő DirectML-lel bármilyen DirectX 12-es videokártyán fut (`onnxruntime-directml`). RX 6600-on a Supertonic kb. ötször, a Parakeet kb. 3,7-szer gyorsabb, mint processzoron (i7-13700K). Ha a DirectML nem indul el, a motor processzoron fut; Python 3.10-zel a processzoros onnxruntime marad. A Beállítások → Beszédmotor alatt visszaállítható a processzor. A MOSS-TTS-Nano processzoron marad, mert ott gyorsabb.

### English

#### Added

- On Windows, Supertonic 3 and the Parakeet speech recognizer run on any DirectX 12 GPU through DirectML (`onnxruntime-directml`). On an RX 6600 Supertonic is about five times and Parakeet about 3.7 times faster than on the CPU (i7-13700K). If DirectML cannot start, the engine runs on the CPU; Python 3.10 keeps the CPU onnxruntime. Settings → Speech engine can switch them back to the CPU. MOSS-TTS-Nano stays on the CPU, where it is faster.

## [4.3.5] - 2026-09-29

### Magyar

#### Javítva

- A Produkció oldal szereposztása és a Hangstúdió szereplőlistája nyelvi modell nélkül minden szereplőnél „0 megszólalást” mutatott, mert csak a nyelvi modelles jelöléseket számolta. Most a szabályok alapján hozzárendelt mondatokat is számolja, és a Hangstúdió e szerint rendez.

### English

#### Fixed

- The Production cast and the Voice Studio character list showed "0 lines" for every character without a language model, because they counted model annotations only. Rule-based attributions are counted too, and Voice Studio sorts by that count.

## [4.3.4] - 2026-09-29

### Magyar

#### Javítva

- **Nyelvi modell nélküli beszélő-hozzárendelés**: a „suttogta Anna”, „sóhajtott Imre” típusú párbeszédsorok eddig gazdátlanok maradtak, ha a szereplő teljes néven (Kovács Anna, Nagy Imre) szerepelt. Most a rövid név és a megszólítás („Imre bácsi”) az egyértelmű teljes névhez kapcsolódik, és egy bekezdésen belül a név nélküli folytatás is a már azonosított beszélőé. A próbakönyvben a beszélőhöz rendelt sorok száma kettőről kilencre nőtt.

### English

#### Fixed

- **Speaker attribution without a language model**: lines like "suttogta Anna" or "sóhajtott Imre" stayed unassigned when the character was detected by full name (Kovács Anna, Nagy Imre). A short name or an honorific ("Imre bácsi") now resolves to the unambiguous full name, and an unattributed sentence continues the speaker already found in the same paragraph. In the demo book, attributed lines went from two to nine.

## [4.3.3] - 2026-09-29

### Magyar

#### Javítva

- Új böngészőben minden oldal a mentett témával indul. Eddig világos operációsrendszer-beállításnál a Könyvtár, a Produkció, az Ellenőrzés és a Feladatok világosan nyílt, az olvasó és a Beállítások viszont a mentett sötét témával, és a téma az olvasó megnyitása után váltott át.

### English

#### Fixed

- In a new browser every page starts in the saved theme. With a light OS colour scheme the Library, Production, Quality and Jobs pages used to open light while the reader and Settings used the saved dark theme, and the theme flipped after the reader was opened.

## [4.3.2] - 2026-09-29

### Magyar

#### Javítva

- Magyarra fordított, eddig angolul maradt üzenetek: a leállított export, generálás és szereplőelemzés állapota a Feladatok oldalon („Az export leállítva az aktuális csomag után”), a Beállítások GPU-gyorsítási állapota („Hibrid gyorsítás: Triton-kernelek + CUDA Graph”), a fejezet készültsége, valamint a Higgs- és az MP4-metaadat-hibák.

### English

#### Fixed

- Messages that were still English are now Hungarian: cancelled export, generation and character-analysis states on the Jobs page, the GPU acceleration status in Settings, chapter readiness, and Higgs and MP4-metadata errors.

## [4.3.1] - 2026-09-29

### Magyar

#### Javítva

- **A teljes könyv generálása vagy exportja 20 GB-nál nagyobb videokártyán összeomolhatott** (legalább a 3.5.0 óta, CUDA Graph és hibrid módban): a két párhuzamos modellsáv egyszerre rögzített CUDA-gráfot, és a közös véletlenszám-generátor miatt a folyamat leállt. A kétsávos export alatt a CUDA Graph most szünetel (a Triton-kernelek maradnak), a gráfrögzítés pedig folyamatszinten egyszerre csak egy helyen fut. Saját mérés, 48 klónozott mondat: két sáv Tritonnal 13,2 s, egy sáv hibrid módban 15,6 s.

### English

#### Fixed

- **Whole-book generation or export could crash on GPUs with more than 20 GB** (since at least 3.5.0, in CUDA Graph and hybrid modes): both parallel model lanes captured CUDA graphs at once and the shared CUDA RNG brought the process down. During a two-lane export CUDA Graphs now pause (Triton kernels stay on), and graph capture runs one at a time per process. Own measurement, 48 cloned sentences: two lanes with Triton 13.2 s, one hybrid lane 15.6 s.

## [4.3.0] - 2026-09-29

### Magyar

#### Hozzáadva

- A **Szereplőhangok** import nyelvi modell nélkül is működik: ilyenkor a gépen futó HuSpaCy ismeri fel a szereplőket, és a párbeszédeket szabályok rendelik hozzájuk. Nyelvi modell beállításakor a modelles elemzés fut, mint eddig; félkész beállításnál továbbra is hibaüzenet jelzi a hiányzó adatot.

#### Javítva

- A magyar névfelismerés nem ragasztja a mondat eleji szót a névhez („Délre Péter” → „Péter”, „Reggel Anna” → „Anna”); a vezetéknevek („Kovács Anna”) megmaradnak.
- A szereplőelemzés állapotüzenetei és néhány importhibaüzenet angolul maradt („Connecting to…”, „Analyzing chapter…”, „Partial: …”, „Unsupported format”); most magyarok.

### English

#### Added

- **Character voices** import also works without a language model: the local HuSpaCy detection finds the characters and rules assign dialogue to them. With a model configured the model-based analysis runs as before; a half-finished model setup still reports the missing value.

#### Fixed

- Hungarian name detection no longer glues a sentence-initial word onto a name ("Délre Péter" → "Péter", "Reggel Anna" → "Anna"); surnames ("Kovács Anna") are kept.
- Character-analysis status messages and some import errors were still English ("Connecting to…", "Analyzing chapter…", "Partial: …", "Unsupported format"); they are Hungarian now.

## [4.2.1] - 2026-09-29

### Magyar

#### Javítva

- **Higgs hangklónozás referenciahanggal**: a 3.5.0 óta a referencia kódjainak gyorsítótárazása hiányzó import miatt hibával leállt, így a Higgs referenciahangos generálása nem működött. Javítva, és valódi modellel ellenőrizve.

#### Változott

- Az `app.py` tovább bomlott: a szereplő- és narrátorhangok (`core/voices_api.py`), valamint az olvasás, szerkesztés, haladás és könyvjelzők (`core/reading_api.py`) külön modulba kerültek. A felesleges importok és a megszűnt összevonási beállítás naplózása kikerült.

### English

#### Fixed

- **Higgs voice cloning with a reference**: since 3.5.0 the reference-code cache failed on a missing import, so Higgs generation with reference audio did not work. Fixed and verified with the real model.

#### Changed

- `app.py` was split further: character and narrator voices (`core/voices_api.py`) and reading, editing, progress and bookmarks (`core/reading_api.py`) are separate modules. Unused imports and logging of the removed coalescing setting were dropped.

## [4.2.0] - 2026-09-29

### Magyar

#### Hozzáadva

- **Parakeet beszédfelismerés processzoron**: választható ASR-háttér a minőségellenőrzéshez (Automatikus, Whisper, Parakeet, Parakeet + Whisper-megerősítés). Automatikus módban videokártyán a magyar Whisper, processzoron az NVIDIA Parakeet v3 fut (ONNX), és csak a gyanús mondatokat hallgatja vissza a Whisper is. A Parakeet egy menetben adja a szöveget és a szóidőket.

#### Változott

- A súgó leírja, miért nem kvantálja az Auris a Higgs-modellt (FP8, int8, vLLM).

### English

#### Added

- **Parakeet speech recognition on CPU**: a selectable ASR backend for quality control (Automatic, Whisper, Parakeet, Parakeet + Whisper confirmation). Automatic uses the Hungarian Whisper on a GPU and NVIDIA Parakeet v3 (ONNX) on CPU, where only suspicious sentences are re-checked by Whisper. Parakeet returns text and word timings in one pass.

#### Changed

- The documentation explains why Auris does not quantise the Higgs model (FP8, int8, vLLM).

## [4.1.0] - 2026-09-29

### Magyar

#### Hozzáadva

- **Triton-gyorsítás Windowson is**: a Beállításokban egy gombbal (vagy telepítéskor `AURIS_TRITON=1`) települ a PyTorch-verzióhoz illő Triton. A kerneleket az Auris tartalmazza, Python 3.11-en is működnek. RTX 3090-en a hibrid mód kb. 25%-kal gyorsabb a CUDA Graphnál, azonos kiejtési pontossággal.
- **Referenciahang-tisztítás** feltöltéskor és mikrofonos felvételnél: zúgás- és zajszűrés, csendvágás, hangerő-kiegyenlítés (kikapcsolható).
- **Változat másik hanggal** az Ellenőrzés oldalon: egy mondat új változata bármelyik mentett hangprofillal elkészíthető és kiválasztható.
- **Hangeffektek** mondatonként (a mondattal együtt vagy az előtte lévő szünetben, választható hangerővel); az exportba keverve, az időzítések megtartásával.

#### Változott

- Az oldalak a feladatok és a beszédmotor állapotát a szerveresemény-csatornáról kapják; a gyakori ismételt lekérdezés csak tartalékként maradt meg.
- Egységes betűk és színek: a kis feliratok táblázatos számokkal a felület betűjét használják, a kód olvashatóbb monospace betűt; az állapotszínek világos témában is kellő kontrasztúak.
- A Produkció oldal fejezetlistája telefonon kártyás elrendezésű; az olvasó oldalsávjának gombjai nem vágódnak le.
- A teljes könyv generálása és a fejezet ellenőrzése akkor is elindítható, ha a beszédmotor még töltődik: a feladat megvárja a betöltést, és ezt ki is írja. Korábban 503-as hibát adott.
- A maradék angol hibaüzenetek (fejezetkijelölés, modellletöltés, export) magyarok.
- A `requirements.txt` már nem sorolja fel a gradio, tensorboardX és webdataset csomagot; ezeket csak az omnivoice hozza magával.

### English

#### Added

- **Triton acceleration on Windows too**: one button in Settings (or `AURIS_TRITON=1` during setup) installs the Triton build that matches PyTorch. The kernels ship with Auris and run on Python 3.11. On an RTX 3090 the hybrid mode is about 25% faster than CUDA Graph with the same pronunciation accuracy.
- **Reference clean-up** on upload and microphone recording: hum and noise reduction, silence trimming and level matching (optional).
- **Takes in another voice** on the Quality page: an alternative of any sentence can be rendered with any saved voice profile and selected.
- Per-sentence **sound effects** (with the sentence or in the pause before it, adjustable level), mixed into exports without changing any timing.

#### Changed

- Pages receive job and engine state from the server-event stream; frequent polling remains only as a fallback.
- Consistent type and colour: small labels use the UI font with tabular figures, code uses a readable monospace font, and status colours keep their contrast in light themes.
- The Production page chapter list uses cards on phones; the reader sidebar buttons no longer clip.
- Whole-book generation and chapter checks can start while the speech engine is still loading; the job waits and says so instead of returning HTTP 503.
- Remaining English error messages (chapter selection, model download, export) are Hungarian.
- `requirements.txt` no longer lists gradio, tensorboardX and webdataset; they only arrive as omnivoice dependencies.

## [4.0.0] - 2026-09-29

### Magyar

#### Hozzáadva

- **Produkció oldal** minden könyvhöz: lépéssor az importtól az exportig, fejezetenkénti hang- és ellenőrzési állapot, szereposztás, a teljes könyv generálása egy gombbal és gyors exportgombok.
- **Parancssor** (`auris_cli.py`): könyvek listázása, importálás, generálás, ellenőrzés, export és egyszeri felolvasás.
- **OpenAI-kompatibilis felület** (`POST /v1/audio/speech`, `/v1/models`, `/v1/audio/voices`) az aktív beszédmotorral és a mentett magyar hangprofilokkal, opcionális tokenes védelemmel.
- **Docker** futtatás (`docker compose up -d`) NVIDIA GPU-val vagy CPU-val.
- **Telepíthető alkalmazás**: a böngészőből telepíthető, a már elkészült hangrészek szerver nélkül is lejátszhatók.
- Élő frissítés egyetlen szerveresemény-csatornán; a menüben jelvény mutatja a futó feladatokat.
- Lejátszó: fejezet-idősáv, megjegyzett lejátszási sebesség, <kbd>J</kbd>/<kbd>L</kbd> és <kbd>[</kbd>/<kbd>]</kbd> billentyűk, mondatonkénti billentyűzetes bejárás, borító és szerző a telefon zárolt képernyőjén.
- Hangstúdió: mikrofonos referenciafelvétel csendlevágással, hangprofilok összehasonlítása ugyanazon a mondaton, hangforrás-jelvények, rendezés, több szereplőre egyszerre alkalmazható profil, visszajátszható referenciák, magyar hangleírások.
- Könyvtár: betűborító a borító nélküli könyveknek, készültségi sávok, közvetlen linkek; a Szereplőhangok import-mód nyelvi modell nélkül magyarázattal le van tiltva; a már meglévő könyvet a figyelmeztetés megnevezi.
- Feladatok: magyar feladatnevek, időpontok és időtartam, szűrők, letöltési linkek.

#### Változott

- Egységes megjelenés: közös színek és térközök, SVG-ikonok, világos és sötét téma villanás nélkül, látható fókusz, kevesebb animáció a mozgáscsökkentést kérőknek, értesítések felugró ablak helyett.
- Telefonon is használható menü, eszköztár, Könyvtár és Feladatok oldal.
- A felület szövegei magyarul, egy helyen (`static/i18n/hu.json`) tárolódnak; a szerver hibaüzenetei is magyarok.
- A Könyvtár egyetlen kéréssel tölti be a könyvek készültségét.
- Az olvasó, a beállítások és az export kódja kisebb, önálló modulokra bomlott; a nem használt hangösszevonási kód kikerült.

### English

#### Added

- **Production page** per book: pipeline from import to export, per-chapter audio and quality status, cast overview, one-click whole-book generation and quick exports.
- **Command line** (`auris_cli.py`): list books, import, generate, quality-check, export and one-off speech.
- **OpenAI-compatible API** (`POST /v1/audio/speech`, `/v1/models`, `/v1/audio/voices`) using the active engine and saved Hungarian voice profiles, with optional token protection.
- **Docker** deployment (`docker compose up -d`) with an NVIDIA GPU or on CPU.
- **Installable app**: install from the browser; audio that has already been generated plays without the server.
- Live updates over one server-event stream; the menu shows a badge for running jobs.
- Player: chapter timeline, remembered playback speed, <kbd>J</kbd>/<kbd>L</kbd> and <kbd>[</kbd>/<kbd>]</kbd> shortcuts, keyboard navigation between sentences, cover and author on the phone lock screen.
- Voice Studio: microphone reference recording with silence trimming, side-by-side profile comparison on the same sentence, voice-source badges, sorting, applying one profile to several characters, playable references, Hungarian voice descriptions.
- Library: typographic covers for books without artwork, progress bars, direct links; the Character voices import mode is disabled with an explanation when no language model is configured; the duplicate warning names the existing book.
- Jobs: Hungarian job names, timestamps and durations, filters, download links.

#### Changed

- Consistent design: shared colour and spacing tokens, SVG icons, light and dark themes without a flash, visible focus, reduced motion when requested, toasts instead of pop-up alerts.
- Phone-friendly navigation, toolbar, Library and Jobs pages.
- Interface strings are Hungarian and kept in one place (`static/i18n/hu.json`); server error messages are Hungarian too.
- The Library loads every book's progress in a single request.
- Reader, settings and export code is split into smaller modules; unused audio-coalescing code was removed.

## [3.8.0] - 2026-09-29

### Magyar

#### Hozzáadva

- **Kiadási csomagok** az export panelen:
  - EPUB3 felolvasós könyv Media Overlays szövegkiemeléssel (az EPUBCheck szerint hibátlan);
  - Audiobookshelf-mappa `metadata.json`-nal, leírással és felolvasóval, igény szerint közvetlen feltöltéssel;
  - kiadói csomag: 192 kbit/s, 44,1 kHz mono MP3 és ötperces minta;
  - hangszerkesztő-csomag: szereplőnkénti WAV-sávok, Audacity-címkék és `.lof`.
- Opus és FLAC exportformátum.
- A narrátor hangján felolvasott **nyitó és záró szöveg** szerkeszthető sablonnal és könyvenként megadható felolvasónévvel.
- Könyvenkénti **háttérzene**, amely beszéd közben automatikusan lehalkul.
- **Pontos szókiemelés**: a minőségellenőrzés beszédfelismeréssel méri a szavak idejét, az olvasó ezt használja; mérés nélkül szótagszám és írásjelszünet alapján becsül.
- **Kiejtés javítása az olvasóban**: szó kijelölése → IPA-átírás, meghallgatás a narrátor hangján, mentés a könyvhöz vagy minden könyvhöz; ellenőrzésre javasolt nevek és idegen szavak listája a kiejtési szótárban.
- **Nyelvi modelles segéd** a Hangstúdióban: hangjavaslat a szereplők mondatai és leírása alapján, valamint második körös beszélő-ellenőrzés, amely a kézi beállításokat nem írja felül.
- Audiobookshelf-szerver beállításai (cím, API-kulcs, könyvtár) a Beállítások oldalon.

#### Változott

- Minden exportcél külön almappába kerül, így a különböző formátumok nem keverednek a letöltött csomagban.

### English

#### Added

- **Publishing packages** in the export panel:
  - EPUB3 read-along book with Media Overlays highlighting (EPUBCheck: no errors);
  - Audiobookshelf folder with `metadata.json`, description and narrator, with optional direct upload;
  - distribution package: 192 kbit/s, 44.1 kHz mono MP3 plus a five-minute sample;
  - DAW package: per-speaker WAV tracks, Audacity labels and a `.lof` list.
- Opus and FLAC export formats.
- **Opening and closing credits** read in the narrator's voice, with an editable template and a per-book narrator name.
- Per-book **background music** that ducks automatically under speech.
- **Accurate word highlighting**: quality control measures word timings with speech recognition and the reader uses them; without measurements it estimates from syllables and punctuation pauses.
- **Pronunciation fixes in the reader**: select a word to see its IPA, hear the sentence in the narrator's voice, and save a book or global rule; the dictionary suggests names and foreign words to check.
- **Language-model assistant** in Voice Studio: voice suggestions from each character's lines and descriptions, and a second-pass speaker review that never overrides manual choices.
- Audiobookshelf server settings (URL, API key, library) in Settings.

#### Changed

- Every export target is written to its own subfolder, so different formats are not mixed in a downloaded package.

## [3.7.0] - 2026-09-29

### Magyar

#### Hozzáadva

- **Minőségellenőrzés** oldal (olvasó → Ellenőrzés): magyar Whisper-beszédfelismeréssel visszahallgatott mondatok, karakterhiba-arány (ékezetérzékenyen, a számok kimondott alakjával), valamint túlvezérlés, néma hang, hosszú szünet, túl gyors vagy túl lassú felolvasás és szokatlan hossz jelzése; hullámforma-előnézet, szűrők és összesítés.
- Hibás mondatok automatikus újragenerálása legfeljebb három új változattal, a legkisebb hibájú kiválasztásával; kézi **Új változat**, változatok meghallgatása és kiválasztása, mondatonkénti **Jóváhagyás**.
- Fejezetenkénti hangerő-jelentés mastering előtt és után: RMS, csúcs, zajszint, EBU R128 hangosság és ACX-megfelelés.
- Opcionális szobazaj a szünetekben (ACX), a fájl elején és végén.
- A Beállítások oldalon a minőségellenőrzés küszöbei, a változatok száma és a beszédfelismerő modell állíthatók.

#### Változott

- Exportkor a beszédmotorok mondatszéli csendje levágódik, így a szünetek hossza egyenletes; a felirat a levágott hangot követi.

### English

#### Added

- **Quality control** page (reader → Ellenőrzés): sentences are re-heard with Hungarian Whisper speech recognition, with a character error rate (accent-sensitive, numbers in spoken form) and flags for clipping, silence, long pauses, too fast or too slow reading and unusual duration; waveform preview, filters and a summary.
- Automatic regeneration of failing sentences with up to three alternative takes, keeping the one with the lowest error; manual **new take**, listening to and selecting takes, and per-sentence **approval**.
- Per-chapter loudness report before and after mastering: RMS, peak, noise floor, EBU R128 loudness and ACX compliance.
- Optional room tone in pauses (ACX), at the start and end of files.
- Settings for quality-control thresholds, the number of takes and the speech-recognition model.

#### Changed

- Export trims the speech engines' silence at sentence edges so pauses have consistent lengths; subtitles follow the trimmed audio.

## [3.6.0] - 2026-09-29

### Magyar

#### Hozzáadva

- Négy új, magyarul hivatalosan beszélő helyi beszédmotor:
  - **MOSS-TTS 1.5 (4B)**: Apache-2.0, GPU, hangklónozás, külön folyamatban, rögzített modellverzióval;
  - **MOSS-TTS-Nano**: videokártya nélküli hangklónozás;
  - **Supertonic 3**: CPU, tíz beépített hang, hangklónozás nélkül;
  - **Piper**: Anna, Berta és Imre magyar hangja, hangklónozás nélkül; a GPL-es csomag a Beállítások oldalon külön telepíthető.
- A motorválasztó alatt látszik, hogy a motor támogat-e hangklónozást, hangleírást és tempóállítást; motoronként külön beállítási blokk.
- Hangstúdió: klónozás nélküli motornál figyelmeztetés jelenik meg, a referenciafeltöltés elrejtődik, és szereplőnként, illetve a narrátornál választható beépített hang.
- A MOSS-motorok referenciahang nélkül a leírás neméhez illő, automatikusan készített magyar mintahangot klónoznak.

### English

#### Added

- Four new local speech engines with official Hungarian support:
  - **MOSS-TTS 1.5 (4B)**: Apache-2.0, GPU, voice cloning, in an isolated process with a pinned model revision;
  - **MOSS-TTS-Nano**: voice cloning without a graphics card;
  - **Supertonic 3**: CPU, ten preset voices, no voice cloning;
  - **Piper**: the Hungarian voices Anna, Berta and Imre, no voice cloning; the GPL package can be installed separately from Settings.
- The engine selector shows whether an engine supports voice cloning, voice description and speed control, with a separate settings block per engine.
- Voice Studio: for engines without cloning it shows a notice, hides reference upload, and offers a preset voice per character and for the narrator.
- Without a reference recording the MOSS engines clone an automatically created Hungarian sample voice matching the described gender.

## [3.5.0] - 2026-09-29

### Magyar

#### Hozzáadva

- Magyar szövegfeldolgozás a felolvasás előtt: dátumok (`március 15-e`, `2024. 10. 05.`), egybetűs római számok (`I. István`), időpontok (`7.30-kor`), telefonszámok, tartományok (`2-3 napos`), törtek, előjeles számok, pénznemek és mértékegységek ragozással (`500 Ft-ért`, `5 kg-os`), rövidítések (`pl.`, `kb.`, `stb.`, `Kft.`) és betűszók (`BKV`, `EU-ban`).
- Magyar mondatbontás: ékezetes nagybetű és `„`, `»` előtti határ; rövidítés, sorszám (`IV. Béla`, `1848. március`) és névkezdőbetű (`Szabó J. Éva`, `Gy.`) után nincs téves határ; magyar fejezetcímek (`ELSŐ FEJEZET`, `Előszó`) felismerése.
- Magyar párbeszéd és hangulat: `»…«`, `„…“` idézőjel, a gondolatjeles párbeszéd egységes kezelése, magyar beszélő-hozzárendelő igék (`mondta Anna`), valamint a `suttogta`, `nevetett`, `sóhajtott`, `lassan` szavak hatása.
- Nyelvi modell nélküli magyar szereplőfelismerés HuSpaCy-val (egy gombbal telepíthető), a ragozott névalakok és a teljes nevek összevonásával, magyar utónév alapú nembecsléssel.
- A kiejtési szótár egyszavas szabályai a ragozott alakokra is érvényesek (`Anna` → `Annának`).
- A leírással megadott (voice design) hangok egyszer egy magyar mintamondatból referenciaklipet kapnak, és a szakaszok ezt klónozzák, így a hangszín a könyv egészében állandó. Kikapcsolható a Beállítások oldalon.
- Importáláskor a lágy kötőjel és láthatatlan jelek eltávolítása, a régi `õ`/`û` → `ő`/`ű` javítása, a PDF-sorvégi elválasztás és az összetételi kötőjel (`Kossuth-díj`) megkülönböztetése; címke nélküli EPUB-nál a nyelv felismerése a szövegből.

#### Változott

- Az új szereplők és az alapértelmezett narrátor hangleírása nem tartalmaz idegen akcentust.
- A könyvexport a kijelölt fejezetek hangját egy menetben, fejezethatárokon átívelő GPU-csomagokban készíti; a mastering fejezetenként, párhuzamosan fut (saját mérés, M4B: 92,6 s → 57,4 s); a fejezet-WAV és az MP3 blokkonként, közvetlenül FFmpeg-gel készül.
- Gyorsabb első lejátszás: a modell betöltés után bemelegszik, a lejátszandó mondat azonnal indul, a következő mondatok egy csomagban készülnek.
- A Higgs referenciahangot hangonként egyszer kódolja; a Higgs alapértelmezett tokenkorlátja 2048, így a hosszú szakasz sem vágódik le.
- A normalizáló verziója a hangcache-kulcs része, ezért a javítások a korábban generált magyar hangrészekre is érvényesülnek; a mentett beszélőjelölések a szövegük alapján automatikusan az új mondathatárokhoz igazodnak.

#### Javítva

- A tárhelyösszesítő nem hibázik, ha egy SQLite-segédfájl a listázás közben eltűnik.

### English

#### Added

- Hungarian text processing before speech: dates (`március 15-e`, `2024. 10. 05.`), single-letter Roman numerals (`I. István`), times (`7.30-kor`), phone numbers, ranges (`2-3 napos`), fractions, signed numbers, currencies and units with inflection (`500 Ft-ért`, `5 kg-os`), abbreviations (`pl.`, `kb.`, `stb.`, `Kft.`) and acronyms (`BKV`, `EU-ban`).
- Hungarian sentence splitting: boundaries before accented capitals and `„`, `»`; no false boundary after abbreviations, ordinals (`IV. Béla`, `1848. március`) and initials (`Szabó J. Éva`, `Gy.`); Hungarian chapter headings (`ELSŐ FEJEZET`, `Előszó`) are recognized.
- Hungarian dialogue and mood: `»…«` and `„…“` quotes, consistent dash-dialogue handling, Hungarian attribution verbs (`mondta Anna`), and the effect of `suttogta`, `nevetett`, `sóhajtott`, `lassan`.
- Hungarian character detection without a language model using HuSpaCy (one-click install), merging inflected name forms and full names, with gender estimation from Hungarian given names.
- Single-word pronunciation rules also apply to inflected forms (`Anna` → `Annának`).
- Voices described by text (voice design) are rendered once into a Hungarian reference clip that every segment clones, keeping the timbre constant across a book. It can be disabled in Settings.
- Import removes soft hyphens and invisible characters, repairs legacy `õ`/`û` → `ő`/`ű`, distinguishes PDF line-break hyphenation from compound hyphens (`Kossuth-díj`), and detects the language of untagged EPUBs from their text.

#### Changed

- New characters and the default narrator no longer carry a foreign accent in their voice description.
- Book export synthesizes all selected chapters in one pass with GPU packs spanning chapter boundaries; mastering runs per chapter in parallel (own measurement, M4B: 92.6 s → 57.4 s); chapter WAV and MP3 are written in blocks directly with FFmpeg.
- Faster first playback: the model warms up after loading, the sentence to play starts immediately, and the following sentences are generated in one pack.
- Higgs encodes each reference voice once; the default Higgs token limit is 2048 so long segments are not cut off.
- The normalizer version is part of the audio cache key, so fixes reach previously generated Hungarian audio; saved speaker annotations are re-aligned to the new sentence boundaries by their text.

#### Fixed

- The storage summary no longer fails when an SQLite side file disappears while it is being listed.

## [3.4.2] - 2026-09-29

### Magyar

#### Javítva

- Egy szereplő vagy a narrátor referenciahangjának cseréje után a régi hang már nem kerülhet elő a cache-ből: minden feltöltés tartalom alapú, egyedi fájlnevet kap.
- Más weboldalról érkező módosító kéréseket (CSRF) és idegen Host fejlécet az Auris elutasít; a mentett API-kulcsokat a Beállítások oldal nem küldi vissza, és a Hugging Face repóazonosítókat ellenőrzi.
- A leállítás valóban megállítja a generálást az aktuális GPU-csomag után, két exportsáv esetén mindkét sávban.
- Egy váratlanul kilépő feladat nem marad „Fut” állapotban, így nem blokkolja az importot, a beállításokat és a generálást az újraindításig.
- Érvénytelen, hatástalan aluláteresztő szűrő eltávolítva a masteringből; az M4B fejezetei között 2 másodperc csend van; a sortörést tartalmazó fejezetcím nem akasztja meg az M4B ellenőrzését.
- A fejezetenkénti ZIP-ben az azonos című fejezetek nem írják felül egymást, a hangfájlok tömörítés nélkül, gyorsabban kerülnek a csomagba.
- A modell nem töltődhet be kétszer párhuzamosan; a Higgs worker leállítása nem keveredik egy futó generálás válaszával.
- A beállítások beolvasási hibája nem vált át csendben az alapértékekre (és ezzel másik beszédmotorra); a beállítások gyorsítótárból olvasódnak.
- SQLite WAL mód, 30 másodperces várakozás zárolásnál, index a hangcache-kulcson; a régi adatbázisok táblaátalakítása megőrzi az összes szegmensoszlopot.
- A régi lezárt feladatok és a kézi mentések ideiglenes másolatai automatikusan törlődnek.
- Letöltéskor a más meghajtón lévő útvonal 403-as választ ad 500-as hiba helyett.
- A `run.bat` és a `run.sh` nem indul a rendszer Pythonjával, ha hiányzik a `.venv`; a telepítő tesztelt PyTorch-verziótartományt telepít.

### English

#### Fixed

- Replacing a character or narrator reference voice can no longer return the old voice from the audio cache: every upload gets a content-addressed file name.
- Cross-site write requests (CSRF) and foreign Host headers are rejected; saved API keys are no longer returned by the Settings API, and Hugging Face repository IDs are validated.
- Stopping a job now halts generation after the current GPU pack, in both lanes of a two-worker export.
- A job whose worker exits unexpectedly no longer stays "running" and blocks import, settings and generation until restart.
- Removed an invalid, ineffective low-pass filter from mastering; M4B chapters are separated by 2 seconds of silence; a chapter title containing a line break no longer fails M4B verification.
- Chapters with identical titles no longer overwrite each other in the per-chapter ZIP, and audio is stored without recompression.
- The model can no longer be loaded twice concurrently; stopping the Higgs worker no longer interleaves with a running generation's reply.
- A settings read error no longer silently falls back to defaults (and another TTS engine); settings are cached.
- SQLite WAL mode, a 30-second lock wait, and an index on audio cache keys; the legacy table rebuild keeps every segment column.
- Old finished jobs and temporary copies of manual backups are cleaned up automatically.
- Downloads of paths on another drive return 403 instead of a 500 error.
- `run.bat` and `run.sh` no longer fall back to the system Python when `.venv` is missing; setup installs a tested PyTorch version range.

## [3.4.1] - 2026-09-29

### Magyar

#### Javítva

- A README telepítési parancsa a magyar forkot klónozza, és a projektleírás egyértelműen megjelöli az eredeti repóhoz fűződő kapcsolatot.

### English

#### Fixed

- The README installation command clones the Hungarian fork, and the project description identifies its relationship to the upstream repository.

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
