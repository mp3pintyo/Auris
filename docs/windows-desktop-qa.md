# Windows x64 kiadási ellenőrzés – Auris 4.4.0

Dátum: 2026-10-01. A kiadás első Windows x64 telepítője:
`Auris-Setup-4.4.0-x64.exe`. A pontos méret és SHA256 a kiadás mellékleteiben
ellenőrizhető.

## Automatizált ellenőrzések

- Teljes Python-tesztkészlet: 567 teszt, sikeres; 1 kihagyott teszt.
- Reader és Voice Studio JavaScript-tesztek: 22 sikeres teszt.
- Projektkörnyezet és telepített csomag: `pip check`, nincs hibás függőség.
- Verzió, kétnyelvű changelog és tag: `scripts/release.py check --tag v4.4.0`.
- Helyi Playwright: első indítás, motorválasztás, érvénytelen bemenet
  elutasítása, súgóhivatkozások, asztali és 390 px széles mobilnézet.
  Képernyőképek készültek; a konzolhibalisták üresek.

## Csomag és telepítő

A csomagolt és a valóban telepített `Auris.exe` Windows-rendszerkönyvtárakra
korlátozott PATH mellett indult, külső Python és FFmpeg nélkül. Az izolált
CPython 3.11.9 importálta az AI- és ablakfüggőségeket. A `sys.path` csak a
csomagolt interpreter, annak csomagjai és az alkalmazás könyvtárait tartalmazta;
rendszer- és felhasználói Python-csomag nem került bele.

A NumPy-csomag Microsoft által aláírt C++ DLL-je eredeti nevén is a csomagba
került. A Torch importja után a Windows ténylegesen az Auris mellékelt
`runtime/msvcp140.dll` fájlját töltötte be, nem egy rendszertelepítés példányát.

A telepítő sikeresen működött szóközt és magyar ékezetet tartalmazó
programkönyvtárban. A telepített natív WebView2-ablak saját helyi szerveréről
megjelenítette a kezdeti beállítást. Helyi Playwright CDP-ellenőrzés és
képernyőkép készült; a böngészőkonzolban nem volt hiba.

Az ismételt indítás ugyanahhoz az adatmappához nem indított második szervert.
A GPU-beállítás utáni alkalmazás-újraindítás ténylegesen betöltötte az új
felhasználói CUDA-környezetet.

## Valódi modellek és magyar beszéd

A kezdeti beállítás valódi Supertonic 3 és OmniVoice modellfájlokat töltött
le külön próba-adatmappákba. Az opcionális NVIDIA-telepítés saját könyvtárba
telepítette és tényleges CUDA-próbával ellenőrizte a Torch/torchaudio
2.11.0+cu128 környezetet.

A telepített alkalmazás API-jával mindkét motor magyar WAV-ot és MP3-at
generált; ezek nem teszthelyettesítők eredményei:

| Motor | Hardver | WAV hossza | Mintavétel | RMS | MP3 mérete |
| --- | --- | ---: | ---: | ---: | ---: |
| Supertonic 3 | CPU / ONNX Runtime | 7,29 s | 24 kHz | 0,0622 | 117 548 bájt |
| OmniVoice | NVIDIA RTX 3090, CUDA Graph, BF16 | 5,12 s | 24 kHz | 0,0715 | 82 988 bájt |

A próba a hangok időtartamát és jelszintjét ellenőrizte. Ez technikai
működésellenőrzés; nem teljes beszédminőségi vagy minden hardverre kiterjedő
értékelés.

## Újraindítás és adatmegőrzés

Mindkét próbakönyvtárba TXT-könyv került, a téma papírnézetre váltott.
Újraindítás után a könyvek és a téma az API-n keresztül is elérhetők maradtak.
A végleges telepítő helyben történő újrafuttatása sikeres volt; a könyvtárak,
beállítások, a Supertonic modell és a külön GPU-környezet ellenőrzött fájljainak
SHA256-értékei változatlanok maradtak. Az újratelepített alkalmazás ismét
elindult és az API megőrizte a két próbakönyvet és a mentett témát.

Az eltávolító sikeresen eltávolította a próbatelepítés programfájljait.
Mindkét adatmappában megmaradtak a könyvek, a beállítások és a letöltött
modell, illetve GPU-környezet. A könyvtáradatbázisok tartalmát SQL-lekérdezés,
a többi ellenőrzött adatfájlt SHA256-összehasonlítás igazolta.

## Ellenőrzési környezet és korlátok

Az ellenőrzés helyi Windows x64 gépen, NVIDIA RTX 3090 kártyával történt,
izolált csomagolt futtatókörnyezettel. Teljesen friss Windows virtuális gépen
végzett próba nem történt. A Calibre és a Tesseract külön opcionális eszköz;
az első modellletöltéshez és a hiányzó WebView2 telepítéséhez internet kell.
A telepítő digitális aláírás nélkül kerül kiadásra.

A képernyőképek, API-eredmények és telepítési naplók a helyi, Git által
figyelmen kívül hagyott `build/windows` könyvtárban találhatók. A kiadás
ellenőrzőösszegei a GitHub Release `SHA256SUMS.txt` mellékletében szerepelnek.

## Kiegészítés: 4.5.0 és 4.5.1 (2026-10-07)

A 4.5.0 runtime-ja a 4.4.0-hoz képest egyetlen csomagban tér el: a sima
`onnxruntime` 1.30.0 helyett `onnxruntime-directml` 1.24.4 került bele, a
Microsoft `DirectML.dll` fájljával. A 4.5.1 runtime-manifesztje bájtra
azonos a 4.5.0-éval.

- Teljes Python-tesztkészlet: 588 teszt, sikeres (1 kihagyva), sima és
  DirectML-es onnxruntime mellett is; JavaScript-tesztek: 22 sikeres.
- A telepítés szóközt és ékezetet tartalmazó mappába, Windows-rendszerkönyvtárakra
  korlátozott PATH mellett: a csomagolt CPython 3.11.9 izolált, a `pip check`
  tiszta, az elérhető végrehajtók `DmlExecutionProvider` és `CPUExecutionProvider`.
- Helyi Playwright: első indítás valódi Supertonic-letöltéssel, súgó, 1280 és
  390 px széles nézet, a Beállítások DirectML-címkéje; a konzolhibalisták üresek.
- A telepített alkalmazás API-ján a Supertonic 3 állapota `GPU · DirectML`
  (NVIDIA RTX 3090). Magyar TXT-könyvből valódi hang készült (10,86 s,
  24 kHz, RMS 0,059, 1,34 s alatt); a Parakeet-átirat a forrásszöveget két apró eltéréssel adta vissza.
- Újratelepítés és újraindítás után a könyvek, a modell és a beállítás megmaradt.
  Az eltávolítás után a könyvtáradatbázis, a modell és a többi adatfájl megmaradt.
- A 4.5.0 eltávolítója a futás közben keletkezett `__pycache__` fájlokat
  (kb. 3700 db) a programmappában hagyta; a 4.5.1 eltávolítója a programmappát
  teljesen kiüríti, az adatmappát nem érinti.
- Ékezetes telepítési útvonalon az angol szöveg felolvasása a 4.5.0-ban hibával
  leállt (a `wetext`/kaldifst nem nyitja meg a nem ASCII útvonalat). A 4.5.1
  ilyenkor a num2words-alapú számnormalizálást használja; a magyar szöveget
  ez nem érintette.
