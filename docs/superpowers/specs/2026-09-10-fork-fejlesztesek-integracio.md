# Külső Auris-forkok integrációs felülvizsgálata

Dátum: 2026-09-10

Vizsgált források:

- `flc/Auris` (`main`, közös alap: `fd345e1`)
- `snokris/Auris-Studio` (`dev`, közös alap: `ae5ad6c`)

## Integrációs elv

A forkok teljes ágának összeolvasztása nem biztonságos, mert mindkettő az Auris jelenlegi `main` ága előtti állapotból indult. Az integráció funkciónként történt, a jelenlegi tartós feladatkezelés, M4B-export, Trafilatura-import, több-beszélős narráció, hangprofilok és magyar kezelőfelület megtartásával. A magyar beszédminőség és az offline működés elsőbbséget kapott.

## Átvett és átdolgozott fejlesztések

| Forrás | Eredeti fejlesztés | Auris-integráció |
|---|---|---|
| `flc/Auris` | Egyedi próbaszöveg és WAV-letöltés | Közös magyar próbaszövegmező, narrátor- és szereplő-WAV mentés a jelenlegi Hangstúdióban. |
| `flc/Auris` | PRC/MOBI import | Közvetlen, függőségmentes PalmDOC/Mobipocket olvasó; DRM elutasítása; metaadat, borító, TOC és jelenetek kezelése; az előnézetes importfolyamatba kötve. |
| `snokris/Auris-Studio` | Magyar számfelolvasás | OmniVoice és Higgs szövegnormalizálásába kötve, vezérlőtagek megőrzésével. |
| `snokris/Auris-Studio` | Magyar fejezetfelismerés | Betűvel írt sorszámok, magyar névvel jelölt szakaszok és rövid bevezető próza megőrzése. |
| `snokris/Auris-Studio` | Hordozható hangpreset | A jelenlegi általános hangprofilokra átültetett `.aurisvoice` export/import, méret-, ZIP-, útvonal- és WAV-ellenőrzéssel. |
| `snokris/Auris-Studio` | Hangcache-kezelés | Tárhelystatisztika és legalább egyórás, adatbázisban nem hivatkozott WAV-ok kézi törlése. |
| `snokris/Auris-Studio` | Gyorsbillentyű-módosítók | Ctrl/Cmd/Alt kombinációk figyelmen kívül hagyása az olvasóban. |

## Nem átvett vagy már kiváltott fejlesztések

| Fejlesztés | Döntés |
|---|---|
| Piper, F5-TTS és ElevenLabs motorok | Nem került be. Jelentősen növelné a telepítési és karbantartási terhet; a projekt magyar fókuszához az OmniVoice és a Higgs jelenlegi támogatása illeszkedik. |
| Régi narrátor-zárolás, narrátorpreset és egynarrátoros mód | A jelenlegi Auris már korszerűbb hangprofil-, referenciahang- és egy narrátoros megoldást tartalmaz. |
| Régi export-életciklus, mappázás és összefűzött MP3 | A tartós Feladatok oldal, folytatható export, fejezetes M4B, ZIP és biztonságos letöltés ezeket nagyrészt kiváltja. |
| Több-beszélős mód kikapcsolása | Nem illeszkedik az Auris jelenlegi céljához és a felhasználói igényhez. |
| Automatikus Whisper szóillesztés a hangdaraboláshoz | Nem került alapértelmezésként be: külön ASR-modellt, letöltést, memóriát és késleltetést igényelne. A jelenlegi Auris alapból nem egyesíti a szegmenseket, ezért a forkban javított vágási hiba nem áll fenn az alapbeállításban. |
| Fejezetszerkesztő és alternatív felvételek | Értékes, de a jelenlegi beszélőannotációkhoz, könyvjelzőkhöz és tartós feladatokhoz külön tranzakciós terv szükséges; közvetlen átemelés adatvesztési és elavult-cache kockázatú. |
| Forknév, régi képernyőképek és dokumentáció | Nem került be, mert az Auris jelenlegi arculatát és működését írná felül. |

## Elfogadási feltételek

- A teljes Python tesztcsomag hibamentes.
- A kapcsolódó Node felületi tesztek hibamentesek.
- A Hangstúdió, a Könyvtár és a Beállítások módosított nézete Playwright alatt hiba nélküli konzollal jelenik meg.
- A beépített magyar dokumentáció, a README és a kétnyelvű változásnapló leírja az új működést.
