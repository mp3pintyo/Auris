# Auris: magyar olvasási és hallgatási élmény

Jóváhagyás: a felhasználó 2026-09-10-én az áttekintés fejlesztéseit engedélyezte, specifikáció utáni folyamatos megvalósítással. A külső integrációk közül kizárólag Trafilatura engedélyezett.

## Cél és határok

Az OmniVoice marad az elsődleges magyar beszédmotor. A meglévő Higgs támogatás megmarad. Nincs Piper, Docling, Audiobookshelf, faster-whisper vagy új OCR/alignment modell. Nincs felhős kötelezettség, új frontend keretrendszer vagy új beszédmodell-letöltés. A webcikk letöltése hálózatot igényel; a tárolt cikk helyi könyvként használható. Valós szóidőzítő modell helyett ebben a változatban a meglévő becsült kiemelés időszámítását javítjuk és becsültként dokumentáljuk.

## Munkacsomagok és elfogadás

### A. Magyar szöveg és import

- Egyedi belső feltöltési fájlnév, SHA-256 alapú duplikációjelzés; azonos nevű különböző könyvek nem írhatják felül egymást.
- Üres/szövegréteg nélküli dokumentum nem kerül a könyvtárba. A hiba magyarul elmagyarázza, hogy előzetes OCR szükséges; OCR-motor nem kerül be.
- Fájlos és URL-es import előnézettel: szerkeszthető cím/szerző/nyelv, fejezetlista, mintaszöveg; megerősítéskor ugyanaz a feldolgozott tartalom kerül tárolásra.
- Trafilatura adapter csak HTTP(S) publikus címeket tölthet le, méret/idő/átirányítás korláttal; belső hálózat, localhost és fájl URL tiltva. Nem futtat weboldali JavaScriptet. Címet, szerzőt, forrás-URL-t és bekezdéseket tárol.
- Magyar PDF elválasztásjavítás csak sortörésből eredő kötőjel esetén; normál kötőjeles szavak megőrzése. Eredeti dokumentum megtartása.
- Globális és könyvenkénti kiejtési szótár (szó/kifejezés → felolvasandó alak), előnézet, törlés/visszavonhatóság; az olvasószöveg nem változik. Könyvspecifikus szabály felülírja a globálist. Változáskor érintett TTS-cache érvénytelenítése.

### B. Tartós feladatok és újraelemzés

- SQLite tárolja a generálási/export/újraelemzési feladatot, bemenetet, állapotot, progresszt, hibát és eredményt. Új oldalról is követhető.
- Újraindításkor félbemaradt feladat „megszakadt”; explicit Folytatás cache-ből. Nincs váratlan automatikus LLM-költség vagy modellindítás.
- Megszakítás kooperatív: a már elkészült hangok megmaradnak; egy futó batch befejeződhet. Nem indít új munkát a megszakítás után.
- Könyv vagy kijelölt fejezet újraelemzése; hibás fejezetek újrapróbálása. Megmarad a könyvazonosító, fejezetazonosító, kézi beszélőjavítás és hangbeállítás. Pozíció/könyvjelző szöveghez visszaillesztése, ha a szegmentálás változik.
- Feladatok oldal listáz, frissít, megszakít, folytat és letölt; olvasó export eredménye ide is bekerül.

### C. Olvasó és hallgatás

- Alapból nyugodt szöveg, opcionális beszélőjelölések; a szerkesztő mód változatlanul elérhető.
- Mobilon csukott tartalomjegyzék, nagyobb vezérlők, billentyűzetes fókusz és Esc-kezelés. Jelölések és állapotok képernyőolvasóbarátak.
- 15 mp vissza/előre a rendelkezésre álló hangidők alapján, elalvásidőzítő (15/30/60 perc vagy fejezet vége), hátralévő idő (becsült jelzéssel, ha nem minden hang kész).
- Könyvbeli keresés találati részlettel és fejezet/mondat helyre ugrással.
- Media Session fejhallgató/médiagomb támogatás ahol böngésző engedi; nem állítunk garantált mobil háttérlejátszást.
- A szókiemelés nem szorozza másodszor a médiaidőt a playbackRate-tel.
- Export célpresetek, vizuális fejezetválasztó, opcionális felirat, MP3/WAV mellett fejezetes M4B ffmpeg segítségével. Letöltési linkek popup helyett.

### D. Könyvtár, hangok, indulás és tárolás

- Könyvtár keresés, rendezés, állapotszűrés, sorozat/gyűjtemény metaadatok, kiemelt Folytatás, szerkeszthető könyvadatok.
- Voice Studio keresés és összecsukható szereplők, központi mentett hangprofilok (narrátor/szereplő → profil → másik könyv/szereplő), magyar próbamondat; a profilhoz referenciafájl tartós másolata tartozik.
- Első indítási segéd gép/modell/ffmpeg ellenőrzéssel, három minőségprofillal, a meglévő letöltőhöz vezetéssel és magyar próbahanggal. Mentés+alkalmazás egyértelműen jelzi a modell újratöltését. A haladó paraméterek megmaradnak.
- Magyar kezelőfelület az elsődleges folyamatokon, a technikai motornevek változatlanok. A dokumentáció összhangban lesz a működéssel.
- Tárhelyáttekintés és hordozható könyvtármentés/visszaállítás. Visszaállítás összeolvasztás helyett ellenőrzött, explicit megerősített cserével, automatikus biztonsági másolattal; adatbázis, források, referenciahangok és beállítások, a nagy újragenerálható hangcache opcionális. API-kulcsok alapból nem részei a kimentett beállításoknak.
- Könyvtörlésnél külön választás a forrásfájl és a generált hang törlésére; csak Auris által kezelt fájlok törölhetők, közösen használt referenciák megmaradnak.

## Architektúra és ellenőrzés

Marad Flask + SQLite + vanilla JS. Új funkciók külön core modulokban és Flask Blueprintben; app.py csak a meglévő útvonalak szükséges integrációjánál változik. A modellek verzióit nem frissítjük. Fejlesztés a közös IDE-munkakönyvtárban külön feature ágon: a projekt környezete és modellútvonalai megmaradnak.

Minden jelentős backend viselkedésre célzott unittest; helyi Playwright teljes felhasználói folyamatokra és mobilméretre, képernyőképpel és konzolhibák vizsgálatával. A Python csak reader/.venv-ből fut. Teljes unittest csomag, Python szintaxis és JS szintaxisellenőrzés a végén. Import- és exportpróbák külön tesztadatokon; éles könyvtárat nem törlünk vagy írunk felül. A TTS minősége és sebessége csak tényleges mérés alapján értékelhető.
