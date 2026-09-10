# SDD ledger — plan: 2026-09-10-magyar-olvasasi-elmeny.md

Ruling: Az előzetes jóváhagyás és folyamatos végrehajtási kérés teljesíti a tervezési jóváhagyást; nem kérünk ismételt engedélyt.
Ruling: Közös IDE checkout külön feature ágon, külön worktree helyett; rögzített venv/modellútvonalak és azonnali felhasználói hozzáférés megőrzése.

| Feladatok | Közös felület | Egyeztetés |
|---|---|---|
| 1,5 | parser séma és preview token | root építi Blueprintbe |
| 2,3,7 | job API, export audio_fmt=m4b/sub_fmt=none | agent 2 backend, agent 3 olvasó, root jobs oldal |
| 2,4 | app.py TTS és startup | app.py agent 2 kizárólag, root utólag integrál |
| 3,4 | kereső API | chapter_id/chapter_title/segment_index/excerpt |
| 4,6 | profiles/pronunciation/setup | root mindkettő |
| 1..8 | saját teszt vs követelmény | célzott tesztek, végén teljes suite; nincs OCR/új motor |

Spec és terv átnézve: a kizárt integrációk nem szerepelnek megvalósítandó feladatként. Valós alignment helyett a meglévő időzítés javítása.

## Integráció és ellenőrzés

- 1,3,5,6,7 implementálva és célzottan ellenőrizve; 2,4 integrálva, a review által talált konkurenciahiba javítása folyamatban.
- Teljes Python suite a review-javítások előtt: 167/167. Trafilatura 2.2.0 telepítve, pip check tiszta.
- Helyi Playwright: import/duplikáció/dialog Esc, könyvtár/metaadat/szótár, olvasó/mobil, M4B letöltés, hangprofil, karakterkeresés, mentés-visszaállítás. A fixture néma WAV-ot ad, beszédminőségi vagy sebességmérésnek nem tekinthető.
- Valódi FFmpeg/ffprobe: M4B két magyar fejezetjelölővel.
- Független review: agent thread limit miatt új reviewer nem indítható; az agentek az általuk nem implementált réteget nézték át. Backend review: reader_experience; frontend review: import_service.
- Javítva: cancelled/interrupted polling, 768 px TOC, export belső útvonal kijelzése, mobil rejtett fájlmező overflow, profilmentés egyedi promptjainak megőrzése.
- Root integrációs javítások: __main__ modulazonosság, pontos magyar preview nyelv/szöveg, kiejtés csak enriched_text-ben, hordozható cache-kiszolgálás, restore korábbi jobok törlése, forrás/reference backup próba.

## Végső állapot

Mind a 8 feladat elkészült. A független review négy backend megállapítását a reviewer javítottnak ellenőrizte: atomi resume, atomi cancel, befejezett export megtartása, régi DELETE útvonal koordinálása.

- Teljes Python suite: **176/176**, 17,436 s; napló: `%TEMP%/auris-implementation-qa/unittest-final.log`.
- Node viselkedési tesztek: **12/12**. Python compileall, JS szintaxis és git diff whitespace ellenőrzés sikeres.
- Helyi Playwright: import–könyvtár–olvasó–export, megszakított/félbeszakadt feladatok, backup–restore, hangprofil és mobil nézet sikeres; konzolhiba: 0.
- Kijelölt fejezetek újraelemzése a könyv adatlapján is elkészült. Külön böngészős teszt ellenőrizte a fejezetazonosítós kérés tartalmát, az üres kijelölést és az újranyitáskor alaphelyzetbe állást. A kérés ebben a próbában szimulált választ kapott, nem indított külső elemzést.
- Végső könyvtár-, súgó- és fejezetkijelölés-képernyőképek szemrevételezve: `%TEMP%/auris-implementation-qa/screens/11-library-final.png`, `12-docs-final.png`, `13-selected-reanalysis.png`.
- Új integráció kizárólag Trafilatura. OmniVoice/modellverziók változatlanok. Valós magyar beszédminőség- vagy sebességbenchmark nem készült; a böngészős fixture néma teszthangot generál.
- README és beépített magyar súgó frissítve. A változások a `feat/magyar-olvasasi-elmeny` ág munkafájljai között vannak, commit nélkül.
