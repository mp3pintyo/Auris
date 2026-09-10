# Ellenőrzési jegyzőkönyv

A specifikáció: [magyar olvasási élmény](../specs/2026-09-10-magyar-olvasasi-elmeny-design.md).

## Környezet

- Python: `reader/.venv/Scripts/python.exe`, meglévő OmniVoice/Higgs verziókkal.
- Trafilatura: 2.2.0; `pip check` szerint nincs függőségi ütközés.
- Böngésző: helyi Playwright + telepített Chrome. A tesztadatbázis a rendszer ideiglenes könyvtárában van, a felhasználó könyvtára nem módosult.
- A böngészős tesztszerver néma WAV-okat készít: ezek a kezelőfelületet, a cache-t, a feladatokat és a fájlexportot ellenőrzik. Nem hangminőség- vagy sebességbenchmarkok.

## Újrafuttatás

A repository gyökeréből:

```powershell
reader/.venv/Scripts/python.exe reader/tests/ui_fixture_server.py
```

Egy másik terminálban állítsd a `NODE_PATH` változót a helyileg telepített Playwright `node_modules` könyvtárára, majd:

```powershell
node reader/tests/browser_experience.cjs
node reader/tests/job_terminal_states.playwright.cjs
node reader/tests/backup_experience.playwright.cjs
node reader/tests/reanalysis_selection.playwright.cjs
node --test reader/tests/reader_experience.node.test.js reader/tests/voice_studio.node.test.js
```

A backup-próba kifejezetten lecseréli az elkülönített tesztkönyvtárat, és a fixture marker nélkül nem indul el.

A teljes Python-csomag a `reader` mappából:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
```

## Ellenőrzött folyamatok

- Fájlimport előnézet, metadata, azonos tartalom jelzése, egyszer használható token, Esc és fókusz.
- Trafilatura HTML/szövegkinyerés és publikus URL-szabályok; szövegréteg nélküli és sérült PDF hibakezelése, magyar elválasztások.
- Könyvtári keresés, gyűjtemény, állapot; globális/könyvsaját kiejtés és eredeti olvasószöveg megőrzése.
- Narrátor/karakter referencia és átirat, hangprofil mentés/alkalmazás, egyedi prompt megőrzése; karakterkeresés és összecsukás.
- Asztali, 390 pixeles mobil és 768 pixeles táblagépnézet; kiemelés, keresés, billentyűzet és exportválasztó.
- Megszakított feladat után az olvasó vezérlőinek feloldása; újraindítás és explicit folytatás.
- M4B teljes böngészős indítás és letöltés; valódi FFmpeg/ffprobe két magyar fejezetjelölővel.
- Mentés és visszaállítás böngészőből; forrás/reference/cache hordozhatóság, titkok és gépi modellútvonalak kizárása, visszaállított cache kiszolgálása.
- Súgó tartalomjegyzék-hivatkozások, képernyőképek és konzolhibák ellenőrzése.

## Review

Az implementáló agentek egymás külön rétegeit ellenőrizték. A feltárt hibák javítása célzott regressziós tesztekkel történt: megszakítási polling, 760/768 px eltérés, belső exportútvonal kijelzése, párhuzamos resume/cancel, régi törlési útvonal és befejezett exportok megőrzése.

A végső eredmények a `progress.md` fájlban szerepelnek. Fizikai telefonos háttérlejátszás, valódi fejhallgatógomb és hosszú, valós beszédminőség/sebességmérés nem része ennek az automatizált ellenőrzésnek.
