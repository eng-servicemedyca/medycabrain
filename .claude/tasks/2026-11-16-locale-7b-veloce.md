---
id: 2026-11-16-locale-7b-veloce
titolo: Il 7b locale più veloce nel giro di ogni giorno
stato: revisione
ramo: feat/locale-7b-veloce
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Giuseppe, 16/11/2026: «Il mio obiettivo è ottimizzare e fare con un modello locale», poi
«Resta sui 7B», e dopo il rilascio della PR 28: «Vai con ottimizzazione».

Perimetro: il 7b (`qwen2.5:7b-instruct-q4_K_M` su Ollama) nel giro quotidiano. Fuori:
cambiare modello, cambiare motore, Groq a pagamento, Anthropic.

## Primi fatti (capo)

- Lavoro precedente, rilasciato: `.claude/tasks/2026-11-16-locale-piu-veloce.md`. Lì ci
  sono il primo disegno (§2.0b-2.7: risposte più corte, niente rilettura, compiti fuori dal
  modello), le domande ancora aperte (§2.7) e il testo intero ora in produzione
  (`BEC/pipeline/whole_text.py`), che ha cambiato i prompt e le chiamate.
- Banco di prova del 7b, misurato il 16/11: `/home/medyca-admin/ricerche/banco-7b-2026-11-16/risultati.md`
  (copia anche in scratchpad/banco). In breve:
  - 135 s a chiamata in media; legge 15-18 token/s, scrive 2,5-4,2;
  - la cache del prefisso di Ollama funziona solo se l'inizio del prompt è identico
    (lettura da 84 s a 0,2 s) e oggi non scatta mai;
  - `format=json` non rallenta;
  - 7 thread leggono il 15% più in fretta senza perdere in scrittura (un solo campione);
  - ogni cambio di `num_thread` ricarica il modello.
- Ricerca: `/home/medyca-admin/ricerche/reports/Ottimizzazione modelli locali su CPU.md`.
- Difetto visto in produzione: affermazioni quasi uguali sullo stesso contenuto quando il
  testo è letto in una chiamata sola (il filtro delle doppie vale solo a pezzi).
- Sulla stessa macchina un altro progetto (`medyca-crm-dev`, transcriber) ha usato il
  360-485% di CPU alle 15:09 del 16/11.

## 2. Disegno          (architetto, 16/11/2026 sera)

Stato: **in attesa dell'OK di Giuseppe**. Nessuna riga di codice scritta. Rifatto sul codice
di oggi (`BEC/pipeline/whole_text.py` e chi lo chiama), non sul disegno del mattino.

### 2.0 In cinque righe

1. **Una PR sola**, che tocca solo le affermazioni dei testi corti (fino a 8.000 caratteri):
   stesso inizio del prompt dell'analisi, istruzioni in fondo, e le due chiamate una dietro
   l'altra. Il modello locale legge il testo una volta invece di due. **Il prompt dell'analisi
   non cambia di una lettera**, quindi le analisi di Groq restano quelle di oggi.
2. Guadagno atteso sulla seconda chiamata (calcolo su velocità misurate dal banco): **circa
   −45 s su un articolo medio, fino a −115 s su uno vicino agli 8.000 caratteri, −55 s su un reel**.
3. **Per i pezzi dei testi lunghi il prefisso comune non dà niente**: ogni pezzo è già letto
   in una chiamata sola. Lo dico chiaro perché la richiesta lo dava per utile.
4. **Il filtro delle doppie a 0,90 da solo toglie anche affermazioni diverse** (misurato sui
   reel di produzione) e **non avrebbe tolto nulla sull'articolo 2214**. Propongo una regola
   un po' più stretta, uguale per testi corti e pezzi (domanda 3).
5. **I 7 thread restano fuori da questa PR**: non sono codice (è una riga di `.env`), la prova
   ha un campione solo, e con il punto 1 il loro guadagno scende a pochi secondi.

Prima di scrivere codice serve **una prova di 40 minuti sul 7b** (§2.2): non l'ho potuta fare
io perché alle 18:08 girava `run_pipeline --only knowledge` (carico 15-16 su 18 core, Ollama
senza modello in memoria): una misura adesso sarebbe sporca e toglierebbe CPU alla produzione.

### 2.1 Vincoli misurati (e cosa è solo calcolato)

Misurato da me oggi, in sola lettura (script in `scratchpad/arch7b/a1.py … a4.py`, transazione
`READ ONLY` sul database di produzione; nessuna chiamata a Groq né al 7b):

- **Il 7b non ha mai servito una chiamata in produzione**: in `llm_calls` (781 righe, dal 15/11)
  le chiamate locali sono tutte del vecchio 3b (`a1.py`). E il banco ha cronometrato solo
  **analisi** (6 chiamate, 161-219 token scritti): **quanto scrive il 7b per le affermazioni non
  lo sa nessuno**. I tetti locali delle affermazioni quindi non si possono «prendere dal banco»:
  vanno presi dalla prova del §2.2.
- **Com'è il codice oggi** (letto): testo corto = 2 chiamate (analisi, affermazioni); testo lungo
  = 1 chiamata per pezzo (affermazioni + appunti) + 1 finale sugli appunti. I due prompt del
  testo corto divergono dal primo carattere: sistema diverso (`KB_SYSTEM` / `ENRICH_SYSTEM`
  contro `ARGUMENTS_SYSTEM`) e prima riga diversa. L'analisi ha **già** il testo prima e le
  regole dopo; le affermazioni no.
- **Ordine dei lavori** (`enrich_agent.run`, `knowledge_agent.run`): prima tutte le analisi, poi
  tutte le affermazioni. Invece `core/upload_workflow.py:393-394` e `reprocess.py:143-144` le
  fanno già una dietro l'altra: lì il guadagno arriva senza cambiare l'ordine.
- **Coda delle istruzioni delle affermazioni**: 606 caratteri, circa 176 token (`python3` su
  `prompts.py`). È quello che resta da leggere alla seconda chiamata: ~11-14 s.
- **Lunghezza delle affermazioni salvate** (`a2.py`; quasi tutte scritte da Groq, Claude e
  Haiku, non dal 7b): articoli 13.476 affermazioni, testo 16,7 parole in media (22% oltre 20),
  citazione 21,4 (45% oltre 20, 28% oltre 25, massimo 138). Reel 6.657: testo 13,7 (7% oltre
  20), citazione 15,8 (21% oltre 20, 10% oltre 25).
- **Doppie nei testi corti** (`a2.py`, `a4.py`; solo reel, perché le affermazioni degli articoli
  non hanno vettori salvati): a soglia 0,90 si toglierebbero **31 affermazioni su 4.555 (0,68%)
  in 22 reel su 877 (2,5%)**; a 0,85 il 2,3%; a 0,95 lo 0,18%. Doppie esatte: 6 coppie con la
  stessa citazione e 2 con lo stesso testo nei reel; negli articoli 12 coppie con citazione
  identica, 13 con una citazione dentro l'altra, 3 con testo identico (18 articoli su 2.201).
  **È un difetto raro.**
- **La soglia 0,90 sbaglia** (`a3.py`, `a4.py`): fra 0,90 e 0,95 ci sono 32 coppie, e 23 hanno
  citazioni diverse. Lette a campione (6 + 3, è poco): «le donne hanno bisogno di 7 ore e mezza
  di sonno» / «gli uomini di 6 e mezza»; «il farro contiene glutine» / «l'orzo contiene glutine»;
  «alcuni biscotti sono buoni per dimagrire» / «alcuni sono cattivi». Sono affermazioni
  **diverse** che il filtro butterebbe. Le doppie vere stanno a 0,95 o più (10 coppie), oppure
  hanno la stessa citazione.
- **Articolo 2214** (il difetto visto in produzione): con il modello dei vettori della
  piattaforma la coppia più vicina fra le sue 12 affermazioni è a **0,771**, nessuna citazione in
  comune. **Né la soglia 0,90 né la mia regola l'avrebbero toccato.** Non so quali due frasi ha
  visto il capo: va detto, altrimenti si rilascia un filtro credendo che chiuda quel caso.
- **Thread**: `OLLAMA_NUM_THREAD` è una variabile di `.env` (`config/settings/base.py:154`), non
  codice.

Preso dal banco (misurato da altri, 16/11): legge 15-17,8 token/s, scrive 2,5-4,2 (media
3,35), la scrittura varia del 25% da sola; la cache riusa l'inizio identico (lettura da 84-90 s
a 0,2-1,7 s) anche se cambia `num_predict`; con i prompt di oggi non scatta mai (100 s).

**Supposto, non verificato**: che la cache scatti con i **template veri riscritti** (il banco
l'ha provata con istruzioni di prova); che il 7b rispetti «massimo 20 parole»; che le
affermazioni con l'istruzione in fondo siano buone quanto oggi, sul 7b e su Groq.

### 2.2 Passo 0 — la prova prima del codice (40 minuti di modello)

La fa chi ha fatto il banco, con lo stesso `harness.py` (stesso lucchetto, stesse opzioni della
produzione), a macchina quieta e lontano dalle 03:30 e dalle 14:15. Sei contenuti corti: 3
articoli e 3 reel, in gruppi separati Medyca / competitor (ogni prompt contiene un contenuto
solo). Per ognuno tre chiamate: analisi di oggi → affermazioni **nuove** (stesso inizio,
istruzioni in fondo, limiti di parole) → affermazioni **di oggi**.

| Cosa si guarda | Passa se | Se non passa |
|---|---|---|
| Lettura della seconda chiamata | sotto 20 s (oggi 45-125) | il punto 1 non entra: resta il resto |
| Affermazioni tenute dal controllo delle citazioni, nuove contro vecchie | in media non più di 1 in meno per contenuto, e non più citazioni scartate | si tolgono i limiti di parole e si riprova solo l'ordine |
| Token scritti con il prompt nuovo | dà il numero per i tetti locali (§2.4) | — |

Costo: 6 × (135 + ~80 + ~200 s) ≈ 42 minuti (calcolo).

### 2.3 Punto 1 — prefisso comune e chiamate una dietro l'altra

**Comportamento**
- Una funzione sola per tipo di contenuto costruisce «la testa»: messaggio di sistema
  dell'analisi + inizio del messaggio fino alla fine del testo. Per gli articoli:
  `KB_SYSTEM` e «riga di apertura, TITOLO, TESTO»; per i reel: `ENRICH_SYSTEM` e «Analizza
  questo reel, DIDASCALIA, TRASCRIZIONE AUDIO». L'analisi è testa + le sue regole (**le stesse
  parole di oggi**); le affermazioni sono la stessa testa + una coda nuova. L'uguaglianza byte
  per byte la garantisce il codice.
- La coda delle affermazioni dice chiaro che il compito cambia («Ora non fare l'analisi:
  estrai solo le affermazioni…»), riporta le regole di oggi, e riprende la frase che oggi sta
  nel messaggio di sistema («solo ciò che è stato realmente detto»). Per gli articoli aggiunge
  «cita solo dal TESTO, non dal titolo» (ora il titolo è nel prompt, e una citazione dal titolo
  verrebbe scartata dal controllo).
- **Ordine**: per ogni contenuto, analisi e subito dopo affermazioni, poi il successivo. Il
  secondo giro («Affermazioni») resta e prende solo gli arretrati (analisi fatte in un giro
  precedente). Analisi fallita → affermazioni non tentate. Affermazioni fallite → l'analisi
  resta `done`. Modello non disponibile fra le due → analisi salvata, affermazioni `pending`.
- **Pezzi dei testi lunghi: non li tocco.** Ogni pezzo è una chiamata sola e la chiamata finale
  legge gli appunti, non il testo: non c'è nessuna seconda lettura da risparmiare. Spostare il
  testo in testa cambierebbe le risposte di Groq per zero secondi.

**Guadagno** (calcolo su velocità misurate; diventa misura con il passo 0): la seconda
chiamata legge ~200 token invece di tutto. Articolo medio (800-1.000 token): **−45 s** su ~120.
Articolo vicino a 8.000 caratteri (~2.300 token): **−115 s**. Reel (1.100-1.300 token):
**−55 s**. Sulla coppia analisi + affermazioni è circa il 20-30%. **Zero** quando l'analisi l'ha
fatta Groq e le affermazioni cadono sul locale, e zero per i pezzi.

**Groq: come non si peggiora, e come si prova senza chiamarlo**
1. L'analisi (sistema e messaggio) resta identica: lo prova un test «alla lettera» (esiste per
   gli articoli, `test_a_blog_keeps_the_old_words_to_the_letter`; se ne aggiunge uno per i reel
   e uno per la chiamata finale dei testi lunghi, con il testo di `main` congelato nel test).
2. Cambia solo il prompt delle affermazioni corte. La garanzia più forte non dipende dal
   modello: **un'affermazione senza citazione vera nel testo viene scartata dal codice**, come
   oggi. Quindi il rischio non è «affermazioni inventate», è «meno affermazioni».
3. Si prova sul 7b (passo 0), che è il modello più debole: se regge lui, è ragionevole che
   regga Groq. **È una deduzione, non una prova.**
4. Dopo il rilascio si guarda il primo giro fatto da Groq, senza spendere nulla in più:
   affermazioni per contenuto (oggi 5,1 articoli, 5,2 reel) e righe «affermazioni scartate» nel
   log. Se scendono, si torna indietro con un revert: nessun dato va rifatto.
5. Un prompt solo per tutti e due i modelli (scelta già presa nel lavoro precedente, §2.2):
   non la riapro.

**File**
- `BEC/llm/prompts.py` — testa dei reel staccata dalle regole; coda nuova delle affermazioni.
- `BEC/pipeline/agents/knowledge_agent.py`, `enrich_agent.py` — funzione della testa; prompt
  delle affermazioni; giro per contenuto.
- `BEC/core/tests/` — vedi i test.

**Riuso**: `_intro`, `_doc_enrich_user`, `_enrich_user`, `build_*_prompt`, `_parallel`,
`_tracked`, gli stati separati. Nessuna migrazione.

**Test** (risposte finte): sistema identico e stesso inizio (`startswith`) per blog, video,
intervista, reel; analisi identica a `main` alla lettera; ordine delle chiamate
analisi-affermazioni-analisi-affermazioni; i tre casi di errore qui sopra; reel senza parlato
→ nessuna chiamata per le affermazioni (come oggi); un contenuto lungo dentro il giro non
viene letto due volte.

**Documentazione**: `03-llm-and-embeddings.md` («The local backstop» con i numeri del banco e
della prova, «What the analysis reads»); `02-pipeline.md` (stadi `enrich` e `knowledge`,
«Progress of a round»); `06-frontend.md` e pagina `Documentazione` per il nome della barra;
pagina tecnica del drawio (ordine dentro lo stadio); `architecture-summary.md` (una riga);
commenti in testa ai moduli.

**Rischi**
- Tutto il guadagno dipende dalla cache con i template veri: per questo il passo 0 viene prima.
- La barra «Analisi» diventa «Analisi e affermazioni» e la barra «Affermazioni» resta quasi
  sempre a zero: **il cliente lo vede** (domanda 2).
- Un lavoro chiesto dal cliente che si infila fra le due chiamate fa perdere il vantaggio di
  quella coppia; niente si rompe.
- Invarianti: `owner_type` non è toccato (ogni prompt resta su un contenuto solo; la riga «un
  CONCORRENTE di Medyca» c'era già nell'analisi); i falliti restano `failed`; nessuna
  credenziale nuova.

### 2.4 Punto 2 — affermazioni asciutte e tetti solo per il locale

**Comportamento**
- Nella coda nuova e nel prompt dei pezzi: «testo: una frase, massimo 20 parole»; «citazione:
  il pezzo più corto che basta, massimo 25 parole, copiato parola per parola». 25 e non 20 per
  la citazione: oggi il 45% delle citazioni degli articoli supera le 20 parole, e chiedere a un
  7b di accorciare troppo lo spinge a riformulare (e allora il controllo la scarta).
- `chat()` riceve un secondo tetto facoltativo, usato **solo** quando risponde Ollama. Groq
  resta com'è (lì il ragionamento conta nel tetto: «i tetti sono correttezza, non costo»).
- Una risposta tagliata al tetto locale resta `failed` (strada che esiste: `LLMTruncated`),
  senza secondo tentativo.

**Valori**

| Chiamata | Tetto oggi | Tetto locale proposto | Da dove viene |
|---|---|---|---|
| Analisi (reel e articoli, anche finale dei lunghi) | 2000 | **800** | banco: massimo scritto 219 su 6 chiamate; 800 è 3,6 volte |
| Affermazioni corte | 1200 reel, 2000 articoli | **1000, provvisorio** | calcolo: 6 × (20 + 25 parole) ≈ 570 token se il limite è rispettato. Il banco non l'ha misurato |
| Pezzo (3 affermazioni + appunti) | 1200 | **700, provvisorio** | calcolo: ≈ 330 token |

Regola per i due provvisori: dopo il passo 0, il doppio del massimo scritto dal 7b, mai sotto
il calcolo qui sopra. **Se il passo 0 non si fa, i tetti delle affermazioni non si toccano.**

**Guadagno**: asciutte, **−5/−16 s a chiamata** (calcolo: ~55 token in meno sugli articoli,
~15 sui reel; piccolo, lo dico chiaro). I tetti non tolgono niente alla media: tolgono il caso
peggiore, da ~10 minuti di scrittura a vuoto (2000 token) a ~4-5 (calcolo a 3,35 token/s).

**File**: `BEC/llm/prompts.py`; `BEC/llm/client.py` (parametro, passato a `_ollama_chat`, e il
tetto vero scritto in `llm_calls`); i due agenti (passano il valore).

**Test**: il tetto locale arriva a Ollama e non a Groq; risposta tagliata al tetto locale →
`failed`, `truncated`, nessun secondo tentativo; una citazione corta ed esatta passa, una
riformulata è scartata (già oggi).

**Documentazione**: `03-llm-and-embeddings.md` («Token ceilings»); commento in testa a
`client.py`; pagina `Documentazione`: una riga («le citazioni sono più brevi»).

**Rischi**: un tetto troppo basso crea `failed` che restano tali (storico: 143 per JSON
tagliato); il 7b può ignorare i limiti di parole (allora niente guadagno, niente di rotto);
le citazioni nuove sono più corte anche quando scrive Groq, e le vecchie non si rifanno:
convivono due stili (domanda 1).

### 2.5 Punto 3 — le doppie anche nei testi corti

**Comportamento**: sul testo corto, dopo il controllo delle citazioni, le affermazioni passano
dalla stessa funzione dei pezzi (`whole_text.merge_claims`, con un «pezzo» solo): via le doppie
esatte (oggi nei corti non si tolgono nemmeno quelle), via le quasi uguali, poi il tetto di 6.
Il tetto si applica **dopo** il filtro, non prima.

**La regola** (una sola, per corti e pezzi): due affermazioni sono la stessa se la somiglianza
è **almeno 0,95**, oppure **almeno 0,90 e le citazioni si sovrappongono** (uguali, una dentro
l'altra, o più di metà delle parole in comune). Sui reel di produzione toglie ~19 coppie invece
di 42 e lascia stare «donne 7 ore e mezza / uomini 6 e mezza». Se Giuseppe preferisce la
soglia 0,90 secca, come chiesto, è una riga in meno: ma butta anche affermazioni diverse
(§2.1, domanda 3).

**Guadagno**: nessuno in secondi; costa meno di 1 s a contenuto (più ~10 s una volta per
caricare il modello dei vettori nello stadio `enrich`). È qualità.

**File**: `BEC/pipeline/whole_text.py`; i due agenti (`write_doc_arguments`,
`_extract_arguments`). **Riuso**: `merge_claims`, `_embed_texts` dei due agenti.

**Test**: due affermazioni con la stessa citazione → una; simili con citazioni diverse sotto
0,95 → restano tutte e due; il modello dei vettori non si carica → restano le affermazioni,
tolte solo le esatte (già così nei pezzi); 8 valide con una doppia → 6 tenute.

**Documentazione**: `02-pipeline.md` («Reading the whole text»), commento in `whole_text.py`
(la soglia non è più «non tarata»: scrivere i numeri del §2.1), `04-mcp-connector.md` se cita
le doppie.

**Rischi**: campione letto a mano piccolo (9 coppie); gli articoli non sono misurati per
somiglianza (non hanno vettori salvati); **non chiude il caso 2214**.

### 2.6 Punto 4 — 7 thread: fuori da questa PR

- Non è una modifica al codice: è `OLLAMA_NUM_THREAD=7` in `.env`, più un commento.
- La prova è un campione solo, e la scrittura balla del 25% da sola.
- Con il punto 1 la lettura pesa meno: il guadagno diventa ~9 s sulla prima chiamata di ogni
  contenuto (calcolo dal campione: 65 → 57 s), circa il 4% della coppia.
- La macchina è condivisa: oggi alle 18:08 il carico era 15-16, alle 15:09 un altro progetto
  usava 4-5 core. A 8 thread la scrittura è già caduta a 2,3 token/s: il margine è stretto.

**Prova da fare prima** (a parte, ~25 minuti): 6 e 7 thread alternati, 5 coppie, prompt
sempre nuovo (riga «Rif. n» in testa), una volta a macchina quieta e una mentre gira un altro
lavoro pesante. Si adotta 7 solo se la lettura mediana sale di almeno il 10% **e** la scrittura
mediana non scende più del 5%, in tutte e due le condizioni. Poi è un passo di rilascio con
la sua riga in `03-llm-and-embeddings.md`.

### 2.7 Cosa resta fuori (dichiarato)

- I pezzi dei testi lunghi: stesso ordine di oggi (cambiano solo i limiti di parole e il tetto locale).
- Le affermazioni sugli articoli fuori tema (domanda 4): PR a parte.
- Le doppie già salvate (decine, non migliaia): non si ripuliscono.
- `import_reanalysis`: non riceve il filtro delle doppie (lavoro una tantum, già fatto).
- I 7 thread; cambiare modello o motore; i lavori di scrittura chiesti dal cliente.
- `queue_eta.py`: da rileggere, non da cambiare (stima dai tempi degli stadi passati; i primi
  giri dopo il rilascio sembreranno più lenti del vero).

### 2.8 Domande aperte per Giuseppe (solo quelle di questa PR)

1. **Citazioni più corte (massimo 25 parole) e testo dell'affermazione massimo 20, anche
   quando scrive Groq?** *Raccomando sì.* Il guadagno è piccolo (5-16 s), ma rende sicuro il
   tetto locale. Le vecchie restano come sono.
2. **Barra «Analisi e affermazioni» al posto di due?** *Raccomando sì*: è il prezzo del
   leggere il testo una volta sola.
3. **Doppie: soglia 0,90 secca, o la regola più stretta (0,95, oppure 0,90 con la stessa
   citazione)?** *Raccomando la più stretta*: la secca butta affermazioni diverse. E serve
   sapere dal capo quali due frasi del 2214 erano «quasi uguali»: nessuna delle due regole le
   trova.
4. **Niente affermazioni sugli articoli fuori tema** (erano il 52% degli articoli, misura del
   mattino; ~120-200 s risparmiati ognuno). *Raccomando sì, ma in una PR subito dopo*: cambia
   ciò che il cliente legge nel connettore e tocca lo stato in 33 punti di 12 file. Questa PR
   la prepara (analisi e affermazioni già in fila).
5. **Dieci chiamate vere a Groq per confrontare le affermazioni prima e dopo?** *Non serve
   prima del merge*: basta guardare il primo giro (§2.3). Se Giuseppe le vuole, sono il modo
   più diretto.
6. **Il passo 0 (40 minuti di 7b) si fa prima di scrivere il codice?** *Raccomando sì*: senza,
   il punto 1 è una scommessa e i tetti delle affermazioni non hanno numeri.

## Passo 0 — risultati (sviluppatore, 16-17/11/2026, 23:04-00:20)

**Esito: NON passa, per poco, su due righe. Nessun codice scritto.** Stato lasciato a `approvato`.

Come: sei contenuti corti (3 articoli, 3 reel; Medyca e competitor in chiamate separate, un
contenuto per prompt), 18 chiamate sul 7b con `harness` adattato (stesso lucchetto della
pipeline, 6 thread, `num_ctx` 8192, `keep_alive` 30m; database solo in lettura, nessuna
chiamata a Groq). Per ognuno: analisi di oggi, affermazioni **nuove** (testa uguale
all'analisi, coda nuova con limiti di parole), affermazioni **di oggi**. Tetto 2000 su tutte
le nuove per misurare quanto scrive davvero. Finita alle 00:20, ben prima delle 03:00. File
grezzi (anche le risposte): `/home/medyca-admin/ricerche/banco-7b-2026-11-16/passo0/` (`raw0.jsonl`,
`run0.log`, `sample0.json`, gli script `pick0.py`, `run0.py`, `newprompts.py`).

**La cache scatta, con i template veri.** Seconda chiamata, secondi di lettura:

| Contenuto | Token del prompt | Lettura nuova | Lettura di oggi |
|---|---|---|---|
| articolo Medyca medio (2.034 car.) | 893 | 22,7 | 56,8 |
| articolo Medyca lungo (7.387 car.) | 2.575 | 21,0 | 189,4 |
| articolo competitor (3.069 car.) | 1.310 | 20,7 | 75,5 |
| reel Medyca 1 | 1.426 | 18,5 | 81,6 |
| reel Medyca 2 | 1.046 | 24,5 | 61,3 |
| reel competitor | 1.198 | 20,0 | 80,0 |
| **media** | | **21,2** (mediana 20,9) | **90,8** |

Il guadagno sulla seconda chiamata è di **circa 70 s a contenuto in media** (articolo lungo:
−168 s). Ma la soglia del disegno era «sotto 20 s» e la media è 21,2: **solo 1 su 6 è sotto
(18,5), uno è a 20,0**. La lettura non dipende dalla lunghezza del testo (21,0 s a 2.575 token,
come a 893): è la coda nuova che pesa, circa 260 token (calcolo: 893 meno la testa; ~21 s a
~12 token/s sulla coda in cache lunga).

**Affermazioni tenute dal controllo delle citazioni** (nuove / di oggi): 4/6, 6/6, 1/0, 2/3,
4/3, 2/6. Totale **19 contro 24: −0,8 a contenuto in media** (soglia: non più di 1 in meno:
passa), ma **scartate 9 contro 8** (soglia: non di più: non passa per una). Il campione è di sei:
le differenze stanno dentro il rumore tra una chiamata e l'altra, e sul competitor le
vecchie hanno scartato tutte e 4 le righe. Nelle nuove, due reel hanno citazioni di 3 parole (sotto i 12 caratteri): il controllo le scarta.

**Il 7b non rispetta il limite di parole della citazione.** Nell'articolo lungo le nuove
citazioni sono di 38, 47, 54, 51, 26, 38 parole (limite chiesto: 25), contro 13-29 di oggi.
Il limite «testo massimo 20 parole» invece lo rispetta, anzi scrive più corto (6-12 parole
contro 9-19). Quindi la citazione non si accorcia con le parole; le citazioni più lunghe non
sono un guadagno ma un costo di scrittura (742 token scritti nell'articolo lungo, 2,9 token/s).

**Token scritti, per i tetti (§2.4)**

| | Massimo scritto | Doppio |
|---|---|---|
| affermazioni nuove (6 contenuti) | **742** (articolo lungo, 6 affermazioni) | **1.484** |
| affermazioni di oggi | 883 (reel, tetto 1.200 non toccato) | — |
| analisi (6 chiamate) | 202 | 404 (il banco già diceva 800 col triplo) |

Quindi il tetto provvisorio 1.000 delle affermazioni corte **era troppo basso**: la regola
«doppio del massimo» dà almeno 1.480 (per gli articoli; i reel hanno scritto al massimo 382,
cioè 764). Il tetto di 700 per i pezzi non è stato provato (il passo 0 non li tocca).

**Velocità di scrittura in questa prova: 2,0-3,5 token/s**, mediana 2,9 (il banco aveva 2,5-4,2).
Il modello è stato scaricato e ricaricato due volte da qualcuno fuori dalla prova (190 s e 173 s
di caricamento, prima dell'analisi di `art-comp-medio` e di `reel-comp-1`): non so da chi; la
cache fra analisi e affermazioni non ne ha sofferto, perché le due chiamate stanno sempre
dopo il ricaricamento.

**Cosa si può fare (scelta del capo / di Giuseppe, non mia).** Il disegno dice: se la lettura
non passa, il punto 1 non entra. Dai numeri, due strade che non ho provato:
1. *Accorciare la coda* (260 → ~120 token: tolgo il «Ora non fare l'analisi…» ripetuto, i limiti
   di parole che il 7b non rispetta, e riporto le regole in due righe). Calcolo: lettura ~10-12 s.
   Richiede una seconda prova (6 × ~200 s ≈ 20 minuti, solo le chiamate nuove) prima del codice.
2. *Accettare il 21,2 come «quasi 20»* e andare avanti con la coda di oggi. Non lo faccio io: la
   regola era scritta e il capo mi ha detto di fermarmi.
In tutti e due i casi: tetto delle affermazioni corte **non 1.000 ma almeno 1.500**, e il limite
«citazione massimo 25 parole» non regge sul 7b (si toglie, o si lascia come desiderio).

## Passo 0, seconda prova — coda corta (sviluppatore, 17/11/2026, 08:40-09:04)

Scelta di Giuseppe: strada 1 (coda di ~100 token; via «Ora non fare l'analisi…» e il limite di 25
parole sulla citazione; resta «testo massimo 20 parole»). Stessi 6 contenuti, 6 chiamate nuove
(`passo0/run1.py`, `raw1.jsonl`, `run1.log`; coda in `newprompts2.py`, **identica** a
`ARGUMENTS_TAIL_TEMPLATE` di `prompts.py`). Stessa regola di lucchetto, database in sola lettura,
niente Groq, `.env` intatto. Differenza di metodo: la testa di ogni contenuto è stata messa in cache
con la chiamata dell'analisi **ferma a 1 token** (non ho rifatto l'analisi intera: la cache vede lo
stesso prefisso). Le chiamate di oggi non sono state rifatte: confronto con le misure del 16/11.

| Contenuto | Token | Lettura | Scritti | Tenute (nuove / oggi) | Scartate (nuove / oggi) |
|---|---|---|---|---|---|
| articolo Medyca medio | 746 | 9,6 s | 225 | 4 / 6 | 0 / 0 |
| articolo Medyca lungo | 2.428 | 10,4 s | 528 | 5 / 6 | 1 / 0 |
| articolo competitor | 1.163 | 9,3 s | 306 | 2 / 0 | 1 / 4 |
| reel Medyca 1 | 1.279 | 10,3 s | 379 | 5 / 3 | 0 / 3 |
| reel Medyca 2 | 899 | 9,9 s | 216 | 3 / 3 | 1 / 1 |
| reel competitor | 1.051 | 10,2 s | 433 | 6 / 6 | 0 / 0 |
| **totale / media** | | **9,95 s** | max **528** | **25 / 24** | **3 / 8** |

**Passa su tutte le soglie**: lettura 9,95 s (soglia 20; era 21,2 con la coda lunga, 90,8 oggi);
tenute +0,2 a contenuto (soglia: non più di 1 in meno); scartate 3 contro 8 (soglia: non più di 1 in
più). Il massimo scritto è 528 token (doppio: 1.056): il tetto 1.500 delle affermazioni regge, con
margine. Il tetto 800 dell'analisi regge (massimo 202).

**Cosa non va bene, e non lo dice nessuna soglia.** In un reel su sei (`reel-owned-2`, trascrizione
corta) le affermazioni nuove sono di 1-3 parole («Informazione.», «Protezione.») con citazioni di 3
parole: passano il controllo (la citazione c'è, è lunga 12+ caratteri) ma valgono poco; il prompt di
oggi su quel reel ne dava 3 da 11-19 parole. Anche la prima prova (coda lunga) aveva citazioni da 3
parole sullo stesso reel: dipende dal contenuto, non solo dalla coda. Un campione di sei non lo
misura. Da guardare nelle prime notti sul 7b (affermazioni con testo sotto 3 parole).

## 3. Sviluppo          (sviluppatore, 17/11/2026)

Ramo `feat/locale-7b-veloce`. Passo 0 e seconda prova: sopra. Implementati i punti 1, 2 e 3 del
disegno; il punto 4 (7 thread) e le affermazioni sugli articoli fuori tema restano fuori, come deciso.

**Cosa cambia**
- **Punto 1, stesso inizio e chiamate una dietro l'altra.**
  `llm/prompts.py`: il messaggio dei reel è spaccato in `ENRICH_HEAD_TEMPLATE` (fino a fine
  trascrizione) e `ENRICH_RULES`; `ENRICH_USER_TEMPLATE` è la loro somma (uguale a `main`, provato).
  Nuova `ARGUMENTS_TAIL_TEMPLATE` (~100 token) al posto di `ARGUMENTS_USER_TEMPLATE`, tolto.
  `knowledge_agent.py`: `KB_ENRICH_HEAD` e `_doc_head`; `build_doc_arguments_prompt` dà sistema
  dell'analisi + testa + coda. `enrich_agent.py`: `_enrich_head`, e `_extract_arguments` usa
  `ENRICH_SYSTEM` + testa + coda. Il prompt dell'analisi non cambia di una lettera: test con sha256
  congelato da `main` per reel (anche «solo didascalia») e articolo.
  `run()` di tutti e due gli agenti: `_enrich_then_claims` per contenuto (analisi, subito le
  affermazioni). Analisi fallita: niente affermazioni. Affermazioni fallite: analisi resta `done`,
  `argument_status` `failed`, non si riprova. Modello non disponibile fra le due: analisi salvata,
  affermazioni `pending`, il giro si ferma (`deferred` le conta). I testi lunghi non fanno una
  seconda lettura. Il secondo giro «Affermazioni» resta, solo per gli arretrati, e non parte se il
  giro si è fermato. Barra: «Analisi e affermazioni».
- **Punto 2, tetti locali.** `client.chat(local_max_tokens=…)`, passato a `_ollama_chat` e scritto in
  `llm_calls`; Groq non cambia. `LOCAL_MAX_ANALYSIS=800`, `LOCAL_MAX_CLAIMS=1500`,
  `LOCAL_MAX_PIECE=1000` (**provvisorio**: non misurato; stima doppia di 3 affermazioni + appunti).
  Nel prompt dei pezzi: «testo: una frase, massimo 20 parole». **Il limite di 25 parole sulla
  citazione NON c'è**: il 7b non lo rispetta (26-54 parole), l'ho tolto dalla coda (§ passo 0).
- **Punto 3, doppie nei testi corti.** `whole_text`: `SAME_CLAIM=0,95`, `SAME_CLAIM_SAME_QUOTE=0,90`,
  `_quotes_overlap` (uguali, una dentro l'altra, o più di metà delle parole della più corta in
  comune), `_same_claim`; `merge_claims` li usa per pezzi e testi corti. `write_doc_arguments` e le
  affermazioni dei reel: `verified_claims` senza tetto, poi `merge_claims([claims], 6, embed)`: tetto
  dopo il filtro.

**File toccati**: `BEC/llm/prompts.py`, `BEC/llm/client.py`, `BEC/pipeline/whole_text.py`,
`BEC/pipeline/agents/enrich_agent.py`, `knowledge_agent.py`, test (`core/tests/test_7b_veloce.py`
nuovo, 33 test; `test_whole_text.py` una riga), documentazione: `03-llm-and-embeddings.md`,
`02-pipeline.md`, `06-frontend.md`, `architecture-summary.md`, pagina tecnica del drawio, pagina
`Documentazione` dell'app (`FEC/src/i18n/it.json`: nome della barra e un limite nuovo).

**Test**: `manage.py test core` 490 verdi, `makemigrations --check` pulito; nessuna chiamata vera a
Groq né a Ollama. Il database di prova è un PostgreSQL 16 usa-e-getta in scratchpad (l'utente di
produzione non può creare database).

**Scelte e perché**
- Coda corta e senza limite di parole sulla citazione: lo dice il passo 0.
- Tetti 800 / 1.500 / 1.000: doppio del massimo scritto dal 7b (202; 742 con la coda lunga, 528 con
  la corta), mai sotto il calcolo. Quello dei pezzi è l'unico non misurato.
- `ARGUMENTS_SYSTEM` resta solo per i pezzi; le affermazioni corte usano il sistema dell'analisi
  (serve per la cache).

**Cosa è rimasto fuori / da sapere**
- Punto 4 (7 thread) e affermazioni sugli articoli fuori tema (PR a parte, domanda 4).
- **Il risparmio è zero** se l'analisi la fa Groq e le affermazioni cadono sul 7b, e per i pezzi.
- **Qualità del 7b sui reel corti**: un caso su sei con affermazioni da 1-3 parole (sopra). Non
  corretto: da guardare nelle prime notti.
- Il filtro delle doppie non prende «frasi che si somigliano» (articolo 2214, 0,771): accettato da
  Giuseppe. Le citazioni molto corte si sovrappongono facilmente (scoperto scrivendo un test: «il
  farro contiene glutine» / «l'orzo contiene glutine» condividono 2 parole su 3): la regola è pensata
  per citazioni di una frase. Non misurato su articoli (niente vettori salvati).
- Provato solo sul 7b e con 6 contenuti; Groq non provato (nessuna chiamata, come deciso): si guarda
  il primo giro fatto da Groq (affermazioni per contenuto, oggi 5,1 articoli / 5,2 reel, e righe
  «affermazioni scartate»); se scendono, revert.
- `queue_eta.py` non toccato: i primi giri dopo il rilascio possono sembrare più lenti del vero.
- Durante la prova il modello è stato scaricato e ricaricato da qualcuno fuori dalla prova (visto 3
  volte, 145-190 s): non so da chi.
- Il drawio: modificato solo il testo della pagina tecnica (stadio `enrich`); non ho rigenerato altro.

## 4. Revisione          (revisore, 17/11/2026, giro 1)

**Verdetto: passa.** Nessun rilievo bloccante. Restano da `stato: revisione` finché non c'è il collaudo.
Non ho eseguito i test (servirebbe un database); ho letto il diff e verificato a parte i punti sotto.

**Controllato e a posto**
- **Prompt dell'analisi identico a `main`.** Ho confrontato a parte, con `ast`, le costanti
  `ENRICH_USER_TEMPLATE`, `ENRICH_SYSTEM`, `ARGUMENTS_SYSTEM` (prompts.py) e `KB_ENRICH_USER`,
  `KB_SYSTEM`, `KB_ENRICH_JSON` (knowledge_agent.py) tra `main` e `HEAD`: tutte uguali, carattere per
  carattere. `_enrich_user` ricompone testa + regole (+ nota «solo didascalia» dopo, come prima). Anche i
  test con sha256 congelato lo coprono. Groq non cambia per l'analisi.
- **`local_max_tokens` solo a Ollama.** `client.py`: `local_max = local_max_tokens or max_tokens` è usato
  solo nel ramo locale (`usage.begin` e `_ollama_chat`); i rami Groq usano ancora `max_tokens`. Senza il
  parametro, il comportamento è quello di prima. Troncamento locale: `LLMTruncated`, «not retrying», `failed`.
- **Stati.** Analisi fallita: eccezione, `enrich_status=failed`, nessuna affermazione chiesta. Affermazioni
  fallite: ritornate (non sollevate), analisi resta `done`, `argument_status=failed`, nessun reset.
  `_fail_whole` cambia i tre stati solo per `WholeTextError`, cioè solo per i testi lunghi, che qui non
  fanno la seconda chiamata. Modello sparito fra le due: analisi salvata prima del `break`, affermazioni
  `pending`, `deferred` contato giusto (`1 + restanti`), e la fase «Affermazioni» non parte (`not stopped`).
  Niente stato nuovo.
- **owned / competitor.** `owner_type` non è toccato; ogni prompt contiene un solo contenuto; nessun
  codice che confronti o unisca contenuti diversi (`merge_claims` lavora su un contenuto alla volta).
- **Doppie.** `_same_claim`: `sim >= 0,95` oppure `>= 0,90` con citazioni sovrapposte; tetto 6 applicato
  in `merge_claims` dopo il filtro (verified_claims senza `limit`). Embedder che non carica: restano le
  affermazioni, tolte solo le esatte (`except` con avviso, non inghiotte l'errore del contenuto).
- **Documentazione nello stesso commit**: 02, 03, 06, architecture-summary, drawio (XML valido),
  `it.json` (JSON valido). Nessun segreto nel diff (cercati `sk-ant-`, `gsk_`, `BEGIN PRIVATE KEY`).
  Nessun commit su `main` (5 commit sul ramo, tutti `feat/locale-7b-veloce`).

**Rilievi (tutti non bloccanti, in ordine di gravità)**
1. **Tetto locale delle affermazioni dei reel più alto di prima.** `enrich_agent.py:~265`:
   `max_tokens=1200, local_max_tokens=LOCAL_MAX_CLAIMS (1500)`. Per i reel il tetto sul 7b passa da
   1.200 a 1.500, cioè il caso peggiore di scrittura sale (~+100 s a 3 tok/s) invece di scendere. Il
   disegno diceva «1000» per le affermazioni corte; il passo 0 ha misurato al massimo 382 token sui reel
   (doppio: 764) e 528 sugli articoli. Non è un errore (il documento 03 scrive 1.500 e dice come è nato),
   ma la documentazione non dice che per i reel è un aumento. Scelta: tenere 1.500 e scriverlo, oppure
   usare 1.000-1.200 per i reel.
2. **Tetto dei pezzi (1.000) non misurato**, come ammesso. Se un pezzo viene tagliato sul 7b,
   `LLMTruncated` → `WholeTextError` → l'intero testo lungo diventa `failed` e non si riprova. Il calcolo
   (~330 token, 3 volte di margine) è ragionevole; da guardare al primo testo lungo letto dal 7b.
3. **Documentazione: frase doppia** in `documentation/low-level/02-pipeline.md` (~riga 904): «The caption
   of a reel goes in whole; the caption of a reel goes in whole (Instagram allows 2 200 characters…».
   Un taglia-e-incolla rimasto in mezzo; va tolta una metà.
4. **Rischio già dichiarato, qui solo ricordato:** le affermazioni di Groq cambiano prompt (sistema
   dell'analisi + testa + coda corta, citazione senza il limite di parole) e non sono state provate su
   Groq. La difesa vera (citazione verificata dal codice) regge; il primo giro con Groq va guardato come
   scritto in §3. Un reel su sei con affermazioni da 1-3 parole sul 7b: da guardare nelle prime notti.

Nessuno dei quattro cambia il verdetto. I numeri 1 e 3 sono due righe.

## 5. Collaudo          (collaudatore, 17/11/2026, giro 1)

**Verdetto: passa.** Nessun difetto del ramo. Due cose sulla qualità del 7b sono da guardare (ultimo punto).

**Comandi eseguiti** (worktree `wt-7b`, ramo `feat/locale-7b-veloce`, PostgreSQL 16 usa-e-getta in scratchpad,
chiavi di Groq e simili svuotate)

```
makemigrations --check --dry-run  ->  No changes detected
manage.py check                   ->  System check identified no issues (0 silenced).
manage.py test core               ->  Ran 490 tests in 53.268s   OK
npm run build (FEC, tsc -b)       ->  ✓ built in 24.17s   (solo il solito avviso: pezzi oltre 500 kB)
```

**Pagina Documentazione nella build** (`FEC/dist/assets/index-*.js`): contiene «Per ogni reel o articolo il
modello fa prima il riassunto e subito dopo le affermazioni, così legge il testo una prima volta sola: per
questo c'è una barra sola, «Analisi e affermazioni»» e «Quando a lavorare è il modello sul server, le
affermazioni sono scritte più corte…». Trovate con grep. Non l'ho guardata a schermo (vedi sotto).

**Prova vera sul 7b, su una copia del database.** `pg_dump` del database di produzione (sola lettura) in un
PostgreSQL a parte (`copy7b`, porta 55477). Scelti 4 contenuti, riportati a `pending` nella copia (analisi e
affermazioni vecchie cancellate nella copia) e tutti gli altri messi `is_active=false`, così il giro tocca solo
loro: reel owned 198, reel competitor 169, articolo owned 2175 (1.383 car.), articolo competitor 543 (1.502 car.).
Lanciato `run_pipeline --only enrich,knowledge` con `LLM_PROVIDER_ORDER=ollama`, `LLM_ENDPOINTS=` e tutte le
chiavi vuote (nessuna chiamata a Groq né ad Anthropic), lucchetto `_ollama_slot` di produzione
(`/tmp/medycabrain-ollama.lock`), lucchetto del giro su un file mio. Qwen 7b, 6 thread. Le chiamate sono
finite alle 09:32, ben prima delle 13:30. Output del giro:

```
✓ enrich done in 541.4s — {'enriched': 2, 'enrich_failed': 0, 'arg_reels': 2, 'arguments': 10, 'arg_failed': 0}
✓ knowledge done in 547.4s — {'enriched': 2, 'enrich_failed': 0, 'arg_docs': 2, 'arguments': 7, 'arg_failed': 0, ...}
```

`llm_calls` (letto/scritto in secondi, token; tutte `is_local`, `ollama`, `done`, `truncated` falso, attesa 0):

```
 item        chiamata   lettura  scrittura  token letti  token scritti  tetto
 reel 169    analisi     78,1 s    62 s      1439         250            800
 reel 169    affermaz.    9,1 s   161 s       928         439           1500
 reel 198    analisi     57,3 s    46 s      1022         170            800
 reel 198    affermaz.    9,3 s    70 s       511         255           1500
 art. 2175   analisi     46,3 s    52 s       753         164            800
 art. 2175   affermaz.   11,7 s   130 s       718         313           1500
 art. 543    analisi     56,7 s   108 s       829         149            800
 art. 543    affermaz.   18,1 s   114 s       794         196           1500
```

**Verificato**
- **Seconda chiamata con lettura breve:** 9,1 / 9,3 / 11,7 / 18,1 s (media 12,05 s), contro 46-78 s della
  prima sullo stesso contenuto. Tre su quattro come nella seconda prova (9,95 s); l'articolo competitor a 18,1 s è
  il più alto. Il tetto di scrittura locale arriva a Ollama (800 e 1500 in `llm_calls`); massimo scritto 439
  (tetto 1500: margine largo).
- **Analisi e affermazioni salvate:** `Enrichment` per i due reel (`llm_model=ollama:qwen2.5:7b-instruct-q4_K_M`),
  `summary_it` e `topics` per i due articoli; 6+4 affermazioni dei reel e 3+4 degli articoli. Stati: reel e
  articoli `enrich_status=done`, `argument_status=done`, `full_text_status=done`, `last_error` vuoto.
- **Una barra sola:** `stage_runs`, fase 1 «Analisi e affermazioni» (reel: 2 su 2, 541 s; articoli: 2 su 2,
  547 s, 0 falliti), poi la fase «Affermazioni» con 0 elementi (nessun arretrato). Il secondo giro parte e non
  trova niente, come progettato.
- **Owned / competitor:** un contenuto per chiamata; `owner_type` invariato (198 e 2175 owned, 169 e 543
  competitor); nessun altro reel o articolo toccato (`updated_at` recente: 0 e 0). I testi dei prompt non li
  ho letti dal vivo (il database non li salva): la riga «concorrente» e la separazione le coprono i test.
- I vettori delle affermazioni sono vuoti sulle 10 dei reel e sulle 7 degli articoli: è normale, li calcola lo stadio
  `cluster` (le affermazioni degli articoli non hanno vettori per scelta, già così in `main`).

**Non provato**
- **Le tre strade di errore dal vivo** (analisi fallita, affermazioni fallite, modello sparito fra le due):
  in questa prova sono andate tutte bene. Le coprono solo i test con risposte finte (490 verdi).
- **Groq:** nessuna chiamata, come deciso. Resta il controllo del primo giro fatto da Groq (§3).
- **UI a schermo, telefono (~380 px) e computer:** non l'ho fatto. `:9093` è produzione e gira `main`, quindi la
  barra nuova lì non c'è. Per vederla serve avviare il ramo. **Giuseppe, dopo il merge e il deploy:** apri
  `:9093` → «Avanzamento» durante il primo giro e controlla che la barra si chiami «Analisi e affermazioni»; apri
  «Documentazione» e leggi i due testi sopra; guarda tutto anche a 380 px di larghezza. Gli stati vuoto/errore della
  pagina non sono toccati dal ramo.
- Il giro con più di un lavoro in parallelo e un lavoro del cliente fra le due chiamate.
- Il caso in cui il modello dei vettori non si carica: non provato dal vivo (qui si è caricato).

**Qualità del 7b su questi 4 (da leggere, non è un difetto del ramo; 4 contenuti non sono una misura)**
- Nel database copiato le affermazioni «vecchie» erano di Groq; non è un confronto 7b-contro-7b. Il numero:
  affermazioni salvate, vecchie contro nuove: reel 12 contro 10 (6+6 contro 6+4), articoli 12 contro 7 (6+6 contro 3+4).
- **Reel 198:** una affermazione ha un testo che non corrisponde alla citazione. Testo «Gli ormoni bioidentici non
  hanno problemi di brevetti», citazione «gli ormoni bioidentici non hanno questo problema». La citazione c'è nel
  testo (il controllo la lascia passare), ma il testo dice un'altra cosa.
- **Articolo 2175 (owned):** le affermazioni arrivano da un elenco di link in fondo alla pagina («Gli articoli di
  questo passo», citazione «- 4 articoli», voci dell'indice), non dai contenuti. Sono tenute perché le citazioni
  esistono. Stessa famiglia del caso «affermazioni da 1-3 parole» del passo 0.
- **Articolo 543:** la prima affermazione è «La primavera è il periodo dell'anno che amo di più» (poco valore).
- Ho anche visto, nella copia, testi con caratteri rotti (`Â«normaliÂ»`) già nel testo salvato dell'articolo:
  non c'entra con il ramo.

Nessuna di queste cose ha un controllo che la fermi oggi (il filtro guarda solo la citazione). Dico solo che il
verde dei test e della prova non dice che le affermazioni del 7b siano buone.

## Registro

- 16/11 — capo: aperto il lavoro, lanciato l'architetto.
- 16/11 — architetto: scritta la sezione 2. Fermo in attesa dell'OK di Giuseppe. Passo 0 (prova sul 7b) non fatto: la macchina era occupata dal giro `knowledge`.
- 16/11 23:00 — capo: Giuseppe dà l'OK («Ok») a passo 0 e PR. Risposte alle domande di §2.8:
  1 sì (limiti di parole anche per Groq); 2 sì (una barra); 3 regola più stretta; 4 sì ma in
  una PR dopo, non in questa; 5 no; 6 sì, il passo 0 si fa prima del codice. Sul 2214: le due
  frasi quasi uguali hanno somiglianza 0,771, nessuna regola le prende, ed è accettato così.
  Giro `knowledge` finito (2.299 documenti con vettore), la macchina è libera.
- 17/11 00:20 — sviluppatore: passo 0 fatto (18 chiamate sul 7b, 23:04-00:20). Non passa: lettura della seconda chiamata 21,2 s in media (soglia 20; oggi 90,8), scartate 9 contro 8. Fermato, nessun codice. Numeri e strade nella sezione «Passo 0 — risultati».
- 17/11 09:10 — sviluppatore: Giuseppe sceglie la strada 1 (coda corta). Seconda prova: lettura 9,95 s, tenute 25 contro 24, scartate 3 contro 8: passa. Implementati i punti 1-3, 490 test verdi, documentazione nello stesso commit. Stato: revisione.
- 17/11 — revisore: giro 1, passa. 4 rilievi non bloccanti (tetto 1.500 dei reel più alto di prima, tetto dei pezzi non misurato, frase doppia in 02-pipeline.md, rischio Groq già dichiarato). Prompt dell'analisi identico a `main` verificato costante per costante. `stato` resta `revisione` fino al collaudo.
- 17/11 09:40 — collaudatore: giro 1, passa. 490 test verdi, nessuna migrazione, build ok. Prova vera sul 7b su una copia del database (4 contenuti, 9 minuti per stadio): seconda chiamata letta in 9-18 s, stati e una sola barra corretti, owned/competitor separati. Qualità del 7b da guardare nelle prime notti.
