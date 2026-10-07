# IndexTTS2 Premium (SECourses): átvételi javaslat és terv

Dátum: 2026-10-07

Vizsgált forrás: `FurkanGozukara/Premium_IndexTTS2_SECourses`, "Version 1.3" (`832d854`, 2026-10-07). A helyi másolat a `tmp/` mappában van, amelyet a `.git/info/exclude` zár ki a gitből.

## Összefoglaló

A projekt három beszédmodellt fog össze egy Gradio alkalmazásban: az IndexTTS 2.5-öt, az **OmniVoice**-t és a Tencent AuK-ot. A legnagyobb értéke nem a kódja, hanem a **mérésekkel alátámasztott minőségi döntései**. Ezek közül sok közvetlenül az OmniVoice-ra vonatkozik, ami az Auris fő motorja.

A három legfontosabb tanulság:

1. **Több take, és a legjobb megtartása** (take-minőség): szakaszonként N változat egy batch-ben, sorba rendezés hanghasonlóság szerint, majd Whisper-ellenőrzés. Az OmniVoice szóhibaaránya 0,65 %-ról **0,20 %-ra** csökkent, a hibátlan sorok száma 60-ból 50-ről 56-ra nőtt.
2. **Az OmniVoice mintavétele rosszul van beállítva az Aurisban.** A forrás mérései szerint 32 lépés és 2,0 guidance a legjobb, a `position_temperature` 5 helyett 0,5 pedig körülbelül harmadával csökkenti a take-ek közti szórást. Az Auris alapból 16 lépéssel dolgozik, és a többi paramétert nem adja át.
3. **A referenciaklip választása döntő.** Ugyanannak a beszélőnek négy klipje 0,725 és 0,817 közötti hanghasonlóságot adott, és ezt sem a hossz, sem a hangmagasság nem jelezte előre. A „referencia-meghallgatás” tesztmondatokkal próbálja ki a jelölt klipeket, és mérés alapján választ.

A **hangtanítás** (OmniVoice full fine-tune / DoRA) technikailag átvehető. Az OmniVoice saját, Apache-2.0 licencű tanítókódja már a venv-ben van (`omnivoice/training/`). A forrás tanítóképessége azonban angol nyelvre van kötve, magyar mérés nincs, a modellsúlyok pedig CC-BY-NC licencűek. Ezért a tanításra **előbb egy mérő kísérletet** (spike) javaslok, és csak akkor érdemes felületet építeni rá, ha az eredmény egyértelműen jobb a jól beállított zero-shot klónozásnál.

## Licenc: ötleteket veszünk át, kódot nem

| Elem | Licenc | Következmény |
|---|---|---|
| Premium_IndexTTS2_SECourses | Nincs LICENSE, Patreonon terjesztik, egyetlen szerző | **Minden jog fenntartva.** Kódot nem másolunk. Algoritmusokat, küszöböket és mérési eredményeket újra megvalósítunk. |
| `indextts/utils/nemo_tn.py` a repóban | Apache-2.0 (Xiaomi) | Átvehető volna, de nincs rá szükség (lásd lent). |
| OmniVoice kód (venv: `omnivoice` 0.2.1) | Apache-2.0 | A tanításhoz és a feldolgozáshoz szabadon használható. |
| OmniVoice modellsúlyok | **CC-BY-NC** | Minden finomhangolt hang is nem kereskedelmi célú. Ezt a felületen jelezni kell. |
| AuK / Qwen Thinker | MIT / Qwen Research License | Nem vesszük át: csak angolul és kínaiul beszél, a licenc korlátozó. |

Hangtanításnál kötelező figyelmeztetés: csak saját vagy engedélyezett hangot szabad tanítani.

## Az Auris jelenlegi állapota (a tervhez releváns részek)

- **OmniVoice-paraméterek:** csak a `num_step` állítható, alapértéke 16 (`reader/core/tts_engine.py:223`). A `guidance_scale`, `t_shift`, `position_temperature` és `class_temperature` az upstream alapértéken marad: 2,0, 0,1, **5,0** és 0. A gyorsító útvonal csak a tokenpontozást cseréli le (`reader/core/tts_accel.py:279`), ezért ezek a paraméterek gond nélkül továbbadhatók.
- **Referencia átirata (`ref_text`):** csak kézzel adható meg. Ha üres, az upstream OmniVoice menet közben betölti az általános `openai/whisper-large-v3-turbo` modellt. Ez külön letöltés és külön VRAM, a magyarra finomhangolt Whispert nem használja, és a felhasználó nem látja az átiratot (`omnivoice/models/omnivoice.py:770`).
- **Referencia-előkészítés:** ffmpeg-tisztítás, -20 LUFS (`reader/core/reference_audio.py`). Nincs hosszellenőrzés, nincs vágás csendnél, nincs minőségpontszám, és csak WAV fogadható el.
- **QA:**
  - Kézzel indítható, fejezetenként.
  - A CER-t a megjelenített szöveghez méri, nem a ténylegesen kimondott (`enriched_text`) szöveghez (`reader/core/qa_api.py:240`).
  - Automatikus újragenerálás csak `fail` esetén történik, a take-eket kizárólag CER alapján választja.
  - **Hanghasonlóság-mérés egyáltalán nincs.**
- **Hangdizájn-horgony:** négy próbálkozásból a nullátmenet-arány alapján választ (`reader/core/tts_engine.py:1225`), ASR- vagy hasonlóság-ellenőrzés nélkül.
- **Tanítás, LoRA:** nincs.
- **Már ma is erős (nem kell átvenni):**
  - magyar számnormalizálás és lexikon
  - magyar mondatbontás és rövid mondatok összevonása
  - szegmensszélek vágása és szabályalapú szünetek
  - CUDA Graph/Triton gyorsítás és kétsávos export
  - magyar Whisper és Parakeet ASR

## Javaslatok: hanggenerálás és klónozás

A forrás minden mérése **angol** szövegen készült. Ezért minden változtatást egy magyar mérőkeret (F0) kapuz: csak az kerül alapértelmezésbe, ami magyarul is mérhetően javít.

| # | Javaslat | Forrás mérése | Auris-oldali megvalósítás | Ráfordítás | Várt hatás |
|---|---|---|---|---|---|
| G1 | **OmniVoice-minőségprofil.** „Legjobb” profil: 32 lépés, guidance 2,0, `position_temperature` 0,5. „Gyors” profil: 16 lépés. | 32/2,0 volt a legjobb; az 1,5, a 3,0, a 64 lépés, a `t_shift` 0,3 és a `class_temperature` 0,5 rosszabb. A 0,5-ös pozícióhőmérséklet harmadával csökkentette a take-ek szórását. | `OmniVoiceGenerationConfig` mezők a beállításokban, a cache-kulcsban és a hangprofilban. Exporthoz „Legjobb”, interaktív olvasáshoz „Gyors” javasolt. | S | közepes–magas |
| G2 | **Automatikus referencia-átirat** a magyar Whisperrel, szerkeszthető mezőben. Az átirat a WAV mellé mentett `.txt` fájlba kerül, és egyszer készül el. | Az üres átirat egyszeri, gyorsítótárazott Whisper-átírással a vágott referenciából. | A `qa.py` ASR-backendjének újrahasznosítása a feltöltéskor. A meglévő átiratot nem írja felül. | S | magas (a hibás vagy üres `ref_text` rontja a klónt) |
| G3 | **Referencia-ellenőrzés és -vágás.** Szélső csend vágása, majd vágás a legcsendesebb ponton legfeljebb körülbelül 15 s-ra. Figyelmeztetés 5 s alatt, valamint zajszint- és klippelés-jelzés. Bármilyen hangformátum ffmpeg-gel. Az `afftdn` zajszűrő kikapcsolható legyen. | 15 s jobb, mint 12 s; 6 s jelentősen rosszabb (AuK-mérés). Az OmniVoice 20 s felett figyelmeztet. | A `reference_audio.py` bővítése és visszajelzés a Hangstúdióban. | S | közepes |
| G4 | **Hanghasonlóság-mérő** (speaker embedding) mint új alapkomponens. | CAMPPlus 192 dimenziós vektor, 20 s ablakok átlaga, koszinusz-hasonlóság. | Javaslat: **CAMPPlus vagy WeSpeaker ONNX** az `onnx_device.py`-on keresztül, így CPU-n, DirectML-en és AMD-n is fut. A modell igény szerint töltődik le. Hangprofilonként tárolt „hangközéppont” (centroid). | M | előfeltétel: G5, G7, G8, T-ág |
| G5 | **Take-minőség az exportban.** Fokozatai: „Kevesebb szóhiba N-ből” (megáll az első hibátlan take-nél), vagy „Leghasonlóbb, hibátlan N-ből” (N take egy batch-ben, sorba rendezés G4 szerint, Whisper-ellenőrzés a legjobb K-n). | OmniVoice: 1 take helyett a 10-ből leghasonlóbb, 5 ellenőrzéssel: a szóhiba 0,65 %-ról 0,20 %-ra csökkent. Ára körülbelül 0,24×-ről 2,9× valós idejűre lassulás (A6000). | A `generate_many` már tud batch-elni, a cache-kulcsban már szerepel a `take`, a `segment_takes` tábla már létezik. Új: választási logika, GPU-szintenkénti alapértékek, előrehaladás-kijelzés. | M | **nagyon magas** |
| G6 | **QA-bíró javítása.** A mérés a ténylegesen kimondott, normalizált szöveghez történjen. Kiejtési szabályok visszafordítása, névtoleranciával. Csonkolás- és ismétlésjelzés. Rögzített `hu` nyelv. | Kiejtési jelölések nélkül a szótári szavak 400 %-os WER-t kaptak. Csonkolás: a hipotézis rövidebb a referencia 60 %-ánál, és a vége eltér. Ismétlés: egy n-gram legalább háromszor. | `qa.py` és `qa_api.py` módosítása. Ez a G5 bírája is. | S–M | magas (megbízható döntés nélkül G5 sem működik jól) |
| G7 | **Referencia-meghallgatás.** Egy hosszabb felvételből vagy több feltöltött klipből jelölt ablakok készülnek, mindegyikkel 3–4 rögzített magyar tesztmondat renderelődik fix seedekkel. Az nyer, amelyik a hangközépponthoz a leghasonlóbb, legfeljebb +5 pont WER-többlettel. Váltás csak +0,005 előny felett történik. | Finomhangolt hangon a nyertes 0,855-öt ért el, a 15 s-os alapreferencia 0,827-et. | „Legjobb referencia keresése” gomb a Hangstúdióban, tartós feladatként. | M | közepes–magas |
| G8 | **Hangdizájn-horgony választása** a nullátmenet-arány helyett ASR-rel és stabilitással (a take-ek közti hasonlóság). | – | `tts_engine.py:1225` lecserélése G4 és G6 felhasználásával. | S | közepes |
| G9 | **Szakaszhossz-őr becsült időtartam alapján.** Cél körülbelül 7–12 s, egy menetben legfeljebb körülbelül 20–30 s. | 7–12 s egyformán jó, 17–20 s kissé rosszabb, 36 s egy menetben 8,7 % WER (12 s-on 1,3 %). | A mai 500 karakteres plafon magyarul körülbelül 35 s is lehet, az egynarrátoros 60 szavas blokk körülbelül 25 s. Kell egy időtartam-alapú plafon az OmniVoice `duration_estimator`-ával. | S | közepes |
| G10 | **Belső szünetplafon.** A modell által túlnyújtott belső szünetek rövidítése: −40 dBFS, legalább 120 ms, mindkét oldalon a plafon fele marad, 8 ms-os áttűnéssel. Explicit szünetekhez nem nyúl. | Klónozott hangok hajlamosak elnyújtani a vessző- és mondatszüneteket. | Opcionális exportlépés. A QA ma csak jelzi az 1,5 s-nál hosszabb szünetet, de nem javítja. | S | közepes |
| G11 | **Felolvasási tempó.** 1,05–1,10-es klónozott narráció tesztelése magyarul. A referencia saját tempójának kiszűrése, ha célsebesség van megadva. | Klónozott narráción az 1,10 rangsorolt legjobban, és a szóhibát is csökkentette. | Csak mérés után, profilonkénti alapértékként. | S | bizonytalan, mérni kell |

### Nem javasolt átvenni

- **IndexTTS2-specifikus funkciók:** érzelemvektorok, Qwen érzelemszöveg, s2mel dekóder-adapter, typical sampling, block swap. Az OmniVoice-on nem értelmezhetők.
- **ConvRot INT8 OmniVoice-ra:** kevesebb memóriát használt, de lassabb volt a BF16-nál, és a modell kicsi. Ráadásul csak CUDA-n fut.
- **AuK:** csak angolul és kínaiul beszél, a Qwen-licenc korlátozó, és nagy a VRAM-igénye.
- **NeMo/WeText normalizálás, CMU/ARPAbet kiejtés:** az Auris magyar normalizálója és kiejtési szabályai ennél célzottabbak.
- **Szegmensenkénti hangerő-illesztés a referenciához:** az Auris szándékosan programszintű masteringet használ. Csak akkor érdemes elővenni, ha a mérés hangerő-ugrást mutat.
- **Gradio-felület, Patreon-specifikus telepítő és modellmappák.**

## Javaslatok: hangtanítás

### Mit tudna

Az Auris-ban ez egy **OmniVoice-hang finomhangolása** volna egy beszélő felvételeiből. Az eredmény egy „tanított hang”, amely a hangprofilhoz kötődik.

- **Módszer GPU-szintenként** (a forrás mérései RTX 5090-en, 4096 tokenes mikro-batch-csel, 16 s-ig terjedő klipekkel):
  - **≥ 16 GB:** full fine-tune, LR 2e-5. 19,5 GB, illetve gradient checkpointinggal 11,5 GB. A DoRA-nál jobbnak mérték, és frissítésenként körülbelül háromszor gyorsabb.
  - **6–12 GB:** DoRA r32/α64, LR 1e-4, checkpointinggal. Körülbelül 2,7 GB.
- **Recept:**
  - 8192 token frissítésenként (körülbelül 4 perc beszéd)
  - epochok: 25 × √(14 óra ÷ tanítóanyag órái), 10 és 100 közé szorítva
  - fix maszkos validáció, a legjobb checkpoint megtartása, korai leállítás
  - `prompt_ratio` 0 (a hang referencia nélkül is beszél) vagy 0,3 (a klónozhatóság megmarad); mindkettőt mérni kell
  - EMA és checkpoint-átlagolás **nem kell**, a forrás mérései szerint nem javítottak
- **Az Auris egyedi előnye:** a könyv szövege ismert. Egy meglévő hangoskönyv és a hozzá tartozó EPUB összeillesztésével (a `core/alignment.py` és a magyar Whisper segítségével) pontos átiratú tanítóanyag készülhet. Ez kiváltja a forrás felirat- és Whisper-gépezetének nagy részét.
- **Adatkapuk:**
  - 4–16 s-os klipek, átlagosan 14 s, ebből negyede körülbelül 6 s-os, negyede körülbelül 10 s-os
  - -20 LUFS, 24 kHz
  - másodpercenként 1,0–5,5 szó, csúcsszint legalább -35 dBFS, klippelés legfeljebb 0,1 %
  - az ASR-átirat első és utolsó szava egyezzen
  - opcionális beszélő-ellenőrzés: G4 legalább 0,70 a teljes klipre és legalább 0,60 6 s-os ablakonként
  - validációra egész forrásfelvételek kerülnek félre
- **Kiértékelés:**
  - Base, legjobb és utolsó checkpoint összevetése körülbelül 12 félretett mondaton, 2 seeddel.
  - Mért értékek: magyar WER és hanghasonlóság a valódi felvételhez.
  - Döntési pontszám: Δhasonlóság − 4 × ΔWER. **A Base is nyerhet.**
  - A tanítás végén referencia-meghallgatás (G7), majd kész hangprofil a G1, G5 és G11 beállításaival.

### Kockázatok

- **A magyar minőség nem bizonyított.** A forrás minden mérése egyetlen angol narrátoron készült.
- **Erőforrásigény:**
  - Egy full checkpoint 1,2 GB, a folytatható tanítási állapot körülbelül 5–7 GB.
  - Több tanított hang egy könyvben modellcserét jelent. Itt a LoRA/DoRA előnyösebb, mert gyorsan cserélhető.
  - A tanítás és az olvasó ugyanazért a GPU-ért versenyez.
- **Platform:** csak NVIDIA CUDA-n reális. ROCm-en Linux alatt kísérleti, **DirectML-en nem működik**.
- **Verziók:** a forrás transformers 5.16-ot vagy újabbat használ, az Auris OmniVoice-a 5.3-at. Az upstream tanítókód ellenőrzése szükséges.
- **Licenc:** CC-BY-NC. A felületen jelezni kell, és beleegyezési nyilatkozat kell hozzá.

## Ütemterv

Minden blokk változásnaplóval és GitHub release-zel zárul.

| Fázis | Tartalom | Ráfordítás | Kapu / elfogadás |
|---|---|---|---|
| **F0 – Magyar mérőkeret** | A `scripts/benchmark_tts.py` bővítése: 40–60 magyar mondat (a `test_docs` alapján is), 2–3 referenciahang, 2 seed. Mért értékek: CER/WER a magyar Whisperrel, hanghasonlóság (G4), időtartam és RTF. JSON- és Markdown-riport. | M | Ismételhető alapmérés a mai beállításokkal. |
| **F1 – Gyors nyerések** | G1 (minőségprofil), G2 (automatikus átirat), G3 (referencia-ellenőrzés), G6 (QA-bíró), G9 (szakaszhossz-őr). | S–M | F0 szerint nem romlik a CER, és a G1 profil mérhetően javít. A teljes unittest-csomag és a Playwright-ellenőrzés hibátlan. |
| **F2 – Take-minőség** | G4 (hanghasonlóság-mérő), G5 (best-of-N az exportban és a QA-ban), G8 (horgony). | M | F0-n a szóhiba és a hibás szegmensek aránya csökken. Az exportidő-szorzó dokumentált. GPU-szintenkénti alapértékek beállítva. |
| **F3 – Referencia és ritmus** | G7 (referencia-meghallgatás), G10 (szünetplafon), G11 (tempómérés). | M | A hasonlóság javul a kézi referenciához képest. Hallgatási próba. |
| **T0 – Tanítási kísérlet** | Parancssori szkript az upstream `omnivoice.training` kódra: 1 magyar hang, 1–2 óra anyag, full és DoRA, `prompt_ratio` 0 és 0,3. | M | **Döntési pont:** a tanított hang az F0 mérőkereten jobb-e, mint az F1–F3 szerint beállított zero-shot klón. Ha nem, a T-ág leáll. |
| **T1 – Adatkészlet-építő** | Hangoskönyv + EPUB, illetve saját felvételek; illesztés, adatkapuk, `manifest.jsonl`, tokencache. | M | – |
| **T2 – Tanítófeladat** | Külön folyamatban fut, tartós feladatként: előrehaladás, leállítás, folytatás, VRAM-szintenkénti beállítások. | M | – |
| **T3 – Betöltés** | A tanított hang a hangprofilban: adapter vagy full checkpoint, referencia, tempó, ajánlott beállítások. | S | – |
| **T4 – Kiértékelés és felület** | Base és checkpointok összevetése, meghallgatható minták, elfogadás. Varázsló a Hangstúdióban. | M–L | – |

## F0 mérési eredmények (2026-10-08, RTX 3090)

Eszközök:
- `scripts/benchmark_quality.py`: 40 magyar mondat (`scripts/data/benchmark_hu.txt`) generálása. Mért értékek: magyar Whisper WER/CER, CAM++ hanghasonlóság (`core/speaker_similarity.py`), RTF. A take-választási módokat ugyanazokból a take-ekből szimulálja.
- `scripts/reference_candidates.py`: egy hosszú felvételből mondathatárokon vágott, 8–16 s-os referenciajelöltek, mindegyik a pontos szövegével.

Nyers eredmények: `reader/data/performance/` (nincs a gitben).

### 1. Bíróhiba a QA-ban (javítva)

A magyar egybe- és különírás (kétezer huszonhatos / kétezerhuszonhatos, át vezet / átvezet) szóhibának számított. Emiatt a WER egy take-nél körülbelül 5 %, a legjobb take-választás után pedig 1,5 % volt, holott a hang hibátlan volt. A `qa.score_transcript` most legfeljebb háromszavas egybeírást egyezésnek vesz. Ez az Auris QA-oldalának WER-értékét is pontosítja.

### 2. Paraméterprofilok (7,6 s-os referencia, 10 seed)

| Profil | 1 take WER | Hibátlan sor | Hasonlóság | Legjobb 10-ből: hasonlóság / legrosszabb | RTF |
|---|---:|---:|---:|---|---:|
| 16 lépés (jelenlegi) | 2,66 % | 31/40 | 0,855 | 0,877 / 0,827 | 0,093 |
| 16 lépés, pos.temp 0,5 | 2,24 % | 34/40 | 0,858 | 0,881 / 0,834 | 0,098 |
| 32 lépés | 1,99 % | 34/40 | 0,859 | 0,880 / 0,826 | 0,186 |
| 32 lépés, pos.temp 0,5 | 2,75 % | 31/40 | 0,860 | 0,881 / 0,829 | 0,197 |
| 32 lépés, pos.temp 0,5, tempó 1,10 | 2,69 % | 33/40 | 0,857 | 0,876 / 0,824 | 0,206 |

**Következtetés:** a forrás OmniVoice-beállításai magyarul nem javítottak a zajon túl, a 32 lépés viszont kétszer lassabb. **A G1 elmarad:** az alapbeállítás 16 lépés marad. A mintavételi paraméterek a motorban továbbadhatók, de a felületen nem jelennek meg.

### 3. Take-választás (ugyanez a mérés)

- **Legkevesebb hiba 3-ból:** a WER 2,7 %-ról 0,16 %-ra csökken, 39/40 hibátlan sorral. Átlagosan csak 1,2–1,4 render és ugyanennyi Whisper-ellenőrzés kell soronként.
- **Leghasonlóbb 10-ből, 5 ellenőrzéssel:** a hasonlóság +0,02-vel nő, a leggyengébb sor 0,766-ról 0,827-re javul, a szóhiba ugyanolyan alacsony.

**A G5 a legértékesebb lépés.**

### 4. Saját hang: 55,9 s-os felvétel és jelölt klipek (16 lépés, 5 seed, hasonlóság a teljes felvételhez)

| Referencia | 1 take WER | Hibátlan (3-ból) | Leghasonlóbb 5-ből: hasonlóság / legrosszabb | RTF |
|---|---:|---:|---|---:|
| Teljes 55,9 s | 22,2 % | 14/40 | 0,880 / 0,808 | **0,902** |
| 35,5–45,4 s (9,9 s) | 2,34 % | 37/40 | **0,897 / 0,852** | 0,114 |
| 35,5–50,1 s (14,6 s) | 2,34 % | 38/40 | 0,894 / 0,847 | 0,150 |
| 40,6–55,1 s (14,5 s, helyes vég) | 1,94 % | **40/40** | 0,893 / 0,834 | 0,151 |
| 40,6–50,1 s (9,5 s) | 2,08 % | **40/40** | 0,888 / 0,841 | 0,110 |
| 10,5–22,9 s (12,4 s) | 3,17 % | 38/40 | 0,885 / 0,834 | 0,125 |
| 22,9–35,5 s (12,6 s) | 2,57 % | 39/40 | 0,883 / 0,842 | 0,134 |
| 0,0–10,5 s (10,5 s) | 0,97 % | 40/40 | 0,871 / 0,825 | 0,127 |
| 40,6–54,4 s (**levágott utolsó szó**) | 22,99 % | 11/40 | 0,863 / 0,790 | 0,154 |
| 45,4–54,4 s (**levágott utolsó szó**) | 25,03 % | 11/40 | 0,850 / 0,779 | 0,119 |

**Következtetések:**

- **Az 55 s-os referencia rossz és lassú:** a szóhiba tízszeres, a generálás nyolcszor lassabb. Ha van átirat, az upstream OmniVoice nem vágja meg a referenciát, csak a belső szüneteket rövidíti. Az Auris ma bármilyen hosszú feltöltést elfogad.
- **Az utolsó szó levágása katasztrofális.** Ha a referencia vége csonka, az átirat viszont kiírja a teljes szót, a modell a szó maradékát a kimenet elejére teszi („Szólította Eszter…”), és elnyeli a szóvégeket. Ugyanazok a szakaszok helyes véggel 23–25 % helyett 2–4 % szóhibát adtak. A felvételed vége maga is hirtelen szakad meg: 54,9 s-nál digitális csend jön.
- **A klip megválasztása számít.** Ugyanabból a felvételből a jó jelöltek hasonlósága 0,871 és 0,897 között szórt, egy-egy take esetén 0,850 és 0,879 között. Ez megfelel a forrás megfigyelésének, ezért a G7 referencia-meghallgatás indokolt.

### Átrendezett prioritások

1. **G3 (megemelve): referencia-ellenőrzés.**
   - Hosszkorlát: 15 s felett figyelmeztetés és felajánlott vágás.
   - Csend az elején és a végén. Ha a beszéd a fájl széléig tart, hibaüzenet „a felvétel vége le van vágva” szöveggel.
   - Az átirat első és utolsó szava egyezzen azzal, amit a Whisper hall.
   - Automatikus átirat (G2).
2. **G5 + G6: take-választás az exportban.**
   - „Normál” export: 1 take, opcionálisan „legkevesebb hiba 3-ból”.
   - „Leghasonlóbb” export: 10-ből 5 ellenőrzéssel.
3. **G7: referencia-meghallgatás** a jelöltvágóra (`core/reference_candidates.py`) építve: hosszú felvétel feltöltésekor a Hangstúdió felajánlja a legjobb klipet.
4. **G1 elmarad.** A G9, G10 és G11 később, mérés után.

## Döntések (2026-10-07)

1. **Kétféle export.**
   - **Normál:** a mai viselkedés, egy take szegmensenként.
   - **Leghasonlóbb:** N take közül a leghasonlóbb hibátlan take. Alapértéke 24 GB-on 10 take és 5 Whisper-ellenőrzés; N és K állítható.
   - Az exportindításkor kell választani; a választás feladatonként mentődik.
2. **Hanghasonlóság-modell:** igény szerint letölthető ONNX speaker-embedding modell. Licence Apache-2.0 legyen.
3. **Cél-GPU a tanításhoz:** NVIDIA RTX 3090, 24 GB, Ampere, BF16.
   - Alapértelmezés a full fine-tune: LR 2e-5, mikro-batch 4096 token, 2-es akkumuláció, gradient checkpointing nélkül. A forrás 19,5 GB-os csúcsot mért ezzel a beállítással.
   - Szűkös memóriánál a DoRA r32 a tartalék.
   - A 3090 a forrás 5090-es méréseinél nagyjából 2–3-szor lassabb.
4. **A tanítás célja a felhasználó saját hangjának minél pontosabb klónozása.** Ennek következményei:
   - **Tanítóanyag:** saját felvétel. A fő út a **vezetett felolvasás** a Hangstúdióban: az Auris mondatokat ad, a felhasználó felolvassa őket, így az átirat pontos és nincs szükség ASR-re. Másodlagos út a hosszabb saját felvétel feltöltése, amelyet a magyar Whisper ír át és vág fel. A hangoskönyv és EPUB alapú út nem cél.
   - **Mennyiség:** 30–60 perc tiszta beszéd a minimum a kísérlethez, 1–2 óra az ajánlott. A forrás legkisebb mért futása 2 óra volt.
   - **Viszonyítási alap** a T0 döntésnél: a saját hang zero-shot klónja **legjobb referenciával (G7), minőségprofillal (G1) és a Leghasonlóbb exporttal (G5)**. A tanítás csak akkor marad a tervben, ha ezt mérhetően felülmúlja.
   - Egyetlen beszélőről van szó, ezért a `prompt_ratio` 0 (referencia nélküli beszéd) és a 0,3 (klónozás a tanított modellel) változatot is mérni kell. A forrásban a tanított modell és a meghallgatással választott referencia együtt adta a legjobb eredményt.
   - A G7 referencia-meghallgatás a saját hosszabb felvételből már tanítás nélkül is javíthat. Ezért az F3 előbb jön, mint a T0.

Licenc: a tanított hang CC-BY-NC. Saját hangról van szó, személyes használatra, ezért ez nem akadály, de a felületen jelezni kell.
