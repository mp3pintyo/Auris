# Auris Windows x64

Az asztali kiadás Windows 10/11 x64 rendszeren használható. A telepítő saját
Python-környezetet, CPU-s AI-függőségeket és FFmpeg/ffprobe programokat tartalmaz.
A használathoz nem kell Git, Python-telepítés vagy parancssor.

## Telepítés és első indítás

1. A [GitHub Releases](https://github.com/mp3pintyo/Auris/releases/latest) oldalról
   töltsd le az `Auris-Setup-<verzió>-x64.exe` fájlt és indítsd el.
2. Kövesd a magyar telepítő lépéseit. Alapértelmezett programhely:
   `%LOCALAPPDATA%\Programs\Auris`. Rendszergazdai jogosultság nem szükséges.
3. Indítsd az Aurist az asztali vagy Start menüben létrehozott ikonnal.
4. Az első indításkor válaszd a **Gyors indulás** (Supertonic 3, CPU) vagy a
   **Saját hangok és hangklónozás** (OmniVoice) lehetőséget, majd kattints a
   **Letöltés és beállítás** gombra. Az állapot és az aktuális fájl letöltése
   az ablakban követhető.
5. Kész beállítás után nyisd meg a könyvtárat. NVIDIA-gyorsítás telepítése
   esetén az **Auris újraindítása** gombbal aktiváld az új környezetet.

A Supertonic modell körülbelül 0,4 GB, az OmniVoice több GB. NVIDIA-gyorsítás
esetén további több GB-os letöltés szükséges. A modellek első letöltéséhez és
a hiányzó Microsoft WebView2 beállításához internet kell. A már telepített
motorok helyi felolvasása internet nélkül is működik; webes cikkimport és
külső API-k használata továbbra is hálózati kapcsolatot igényel.

## NVIDIA és más hardver

A Supertonic videokártya nélkül is fut; DirectX 12-es videokártyán (AMD,
Intel, NVIDIA) DirectML-lel külön telepítés nélkül azt használja. Az OmniVoice
CPU-val is használható, lassabban.
A kezdeti beállítás felismeri az NVIDIA-kártyát. Ha az illesztőprogram CUDA
12.8-at vagy újabb verziót támogat, az OmniVoice mellett bekapcsolható a
**NVIDIA-gyorsítás telepítése**. Ez az Auris saját felhasználói környezetébe
telepíti a PyTorch CUDA-komponenseket; az NVIDIA-illesztőprogramot nem módosítja.
Más hardveren az első asztali kiadás CPU-val indul. A forrásból indított
webes Auris meglévő hardvertámogatása változatlan.

Más motort később a **Beállítások** oldalon választhatsz. Az OmniVoice-hoz
a Beállítások modellletöltése is használható. Az asztali kezdeti beállítás
újra megnyitható a Súgó asztali telepítésről szóló részéből.

## Könyvek, modellek és frissítés

Minden felhasználói adat a `%LOCALAPPDATA%\Auris` mappában van:

- `data`: könyvtáradatbázis, beállítások, hangprofilok és mentések;
- `uploads`: feltöltött forrásfájlok;
- `audio_cache`: elkészített hangok;
- `exports`: exportált hangoskönyvek;
- `models`: letöltött modellek;
- `runtime`: az opcionális GPU-környezet és az alkalmazásablak adatai;
- `logs`: indítási és telepítési naplók.

Frissítéshez zárd be az Aurist, majd futtasd az új telepítőt. A programfájlok
cserélődnek, a külön tárolt könyvek és modellek megmaradnak. Eltávolításkor
is megmarad a felhasználói adatmappa. A forrásból futó webes példány és az
asztali kiadás külön könyvtárat használ; az Auris ZIP-mentésével viheted át
a könyveket és beállításokat.

Az Auris ablakának bezárása leállítja a helyi szervert és a háttérfeladatokat.
A megszakadt tartós feladatokat a következő indítás után a Feladatok oldalon
folytathatod. Egy adatmappához egyszerre egy asztali példány indulhat.

## Hibaelhárítás

- A kiadás nincs digitálisan aláírva. A Windows SmartScreen jelezhet ismeretlen
  kiadót; a telepítőt a projekt GitHub Release oldaláról töltsd le. A kiadás
  `SHA256SUMS.txt` fájlja tartalmazza a telepítő ellenőrzőösszegét.
- Ha a modellletöltés megszakad, ellenőrizd az internetet és a szabad
  tárhelyet, majd indítsd újra a beállítást. A kész fájlokat újra felhasználjuk.
- Ha az ablak nem indul, futtasd újra a telepítőt internetkapcsolattal a
  hiányzó WebView2 beállításához. Ellenőrizd a `logs/desktop.log` és
  `logs/launcher.log` fájlokat.
- NVIDIA-telepítési hibánál a `logs/gpu-install.log` tartalmazza a részleteket.
  A Gyors indulás választásával CPU-n is használhatod az Aurist.
- OCR-hez a Tesseract és a magyar nyelvi adat, speciális könyvformátumokhoz
  a Calibre továbbra is opcionális, külön telepítendő eszköz. Az FFmpeg és
  ffprobe az asztali csomag része.

## Fejlesztői build és ellenőrzés

A build a projekt tesztelt Windows x64 Python 3.11 virtuális környezetéből
csak a szükséges csomagokat másolja át; könyveket, beállításokat, hangmintákat
és TTS-modellsúlyokat nem csomagol. A meglévő magyar és angol NLP-modell
belekerülhet a függőségekkel együtt. A csomagolt CPython 3.11.9 önálló, izolált
futtatókörnyezet. A CPU-s Torch/torchaudio 2.11.0, a WebView-alapú ablakhoz
pywebview 6.2.0 kerül bele. A build letölti a hivatalos Python-csomagot,
a Microsoft WebView2 bootstrappert és az FFmpeg Windows-buildjét. A
teljes függőséglista a release `runtime-manifest.json` mellékletében van.

```powershell
reader\.venv\Scripts\python.exe scripts\windows\build.py
# Forrásmódosítás után, a már elkészített runtime újrahasználatával:
reader\.venv\Scripts\python.exe scripts\windows\build.py --app-only
```

Az Inno Setup 7 buildeszköz szükség esetén a `build/windows/inno` mappába
települ. Kimenet: `dist/windows/Auris-Setup-<verzió>-x64.exe`.

A csomagolt háttérszerver külön tesztadatokkal is elindítható:

```powershell
build\windows\package\Auris.exe --headless --data-dir C:\Temp\auris-desktop-qa --port 17903
```

A normál webes indítás (`reader/run.bat`, illetve `reader/app.py`) továbbra
is használható. Egyedi telepítésben az `AURIS_DATA_DIR` környezeti változóval
adható meg a külön adattárolás helye. A kiadási ellenőrzés a csomagolt
futtatókörnyezetet rendszer-Python és külső FFmpeg nélküli PATH mellett,
első modellletöltéssel, valódi felolvasással, újraindítással, frissítési
adatmegőrzéssel és helyi Playwright-képernyőképekkel vizsgálja.
