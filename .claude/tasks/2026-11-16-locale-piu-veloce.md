---
id: 2026-11-16-locale-piu-veloce
titolo: Modello locale 7b più veloce sulla CPU
stato: disegno
ramo: feat/locale-piu-veloce
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Parole di Giuseppe, 16/11/2026:

> «adesso quello che dobbiamo fare [...] è portare una ottimizzazione per quanto riguarda i
> modelli locali su CPU. Questo è molto importante perché ovviamente i crediti di Grok
> finiscono in fretta e tutto quello che non viene fatto da Grok viene fatto dalla CPU,
> quindi dobbiamo trovare un'ottimizzazione. [...] andare a cercare [...] tra paper
> accademici, utilizza deep research»

Dopo aver letto il rapporto della ricerca:

> «Puoi anche implementare jev se necessario, procedi con la lista dei task per ottimizzare
> il modello locale 7b»

Nota del capo: «jev» non l'ho capito (dettatura?). Non l'ho interpretato: l'ho chiesto a
Giuseppe. Finché non risponde non entra nel disegno.

**Perimetro deciso dalle sue parole:** si ottimizza **il 7b**
(`qwen2.5:7b-instruct-q4_K_M`). Cambiare modello (riga 5 del rapporto) è fuori da questo
lavoro. Cambiare motore al posto di Ollama (riga 7) è fuori: prova debole, fatica alta.

## Primi fatti (capo)

Rapporto completo, con le fonti:
`/home/medyca-admin/ricerche/reports/Ottimizzazione modelli locali su CPU.md`
Note grezze dei quattro filoni: `/home/medyca-admin/ricerche/research_notes/Ottimizzazione modelli locali su CPU/`

Misurato sul nostro server (commenti in `BEC/config/settings/base.py` e tabella `llm_calls`):

- Macchina: VM KVM, 18 vCPU EPYC Zen 1, AVX2 senza AVX-512, cache L3 8 MiB, 94 GB RAM. Ollama 0.40.16.
- Ogni chiamata manda già `num_thread=6`, `num_ctx=8192`, `keep_alive=30m`, `format=json` quando serve.
- Prova dei thread già fatta sul 7b (scrittura): 4 thread 2,9-3,2 token/s; 6 → 3,8-4,0; 12 → 1,4-1,9; 18 → 0,2-0,8.
- 7b: legge ~13 token/s, scrive ~2,8. Analisi media ~250 s, la più lunga ~530 s: **calcolati**, non cronometrati su prompt veri.
- Il 7b non ha mai servito una chiamata in produzione. Storico locale solo del 3b (46 chiamate):
  `knowledge` 34 chiamate, 1.923 token letti e 386 scritti in media, 118 s, tempo 47% lettura / 52% scrittura;
  `enrich` 5 chiamate, 1.110 letti e 521 scritti, 116 s, 27% / 65%, 8% caricamento.
- Quindi qui **scrivere costa 4-5 volte più che leggere**, e pesa almeno metà della chiamata.

Lista dei task (dal rapporto, tolte le righe fuori perimetro):

1. **Banco di prova** (solo misura, nessun codice in produzione): 7b cronometrato sui prompt
   veri di `enrich` e `knowledge`; salute della VM (steal, processi concorrenti); punti fini
   dei thread (5, 6, 7, 8) con lettura e scrittura separate; `format=json` acceso/spento;
   la cache del prefisso funziona in Ollama 0.40.16?
2. **Risposte più corte**: JSON compatto, chiavi brevi, etichette a elenco chiuso, tetti alle
   liste, niente campi che il codice sa calcolare. Stima −17/19% se l'output medio scende da
   386 a 250 token. Un JSON tagliato resta `failed`.
3. **Compiti semplici fuori dal modello generativo** (etichette a elenco chiuso, riordino dei
   risultati). Tocca la regola owned/competitor: **serve la decisione di Giuseppe** prima di
   allenare qualcosa su etichette miste.
4. **Testo prima, istruzione dopo; compiti dello stesso testo uno dietro l'altro**, così il
   modello non rilegge il testo. Vale solo se il passo 1 conferma la cache del prefisso.
5. **Testi interi a pezzi**: appartiene al lavoro separato «riassunti su tutto il testo», ma
   va disegnato tenendo conto di questo (30.000 caratteri non entrano in 8.192 token).

Vincoli: licenze commerciali; owned mai mescolato con i competitor; i fallimenti restano
`failed`; niente chiamate vere a Groq nei test (finisce il tetto del giorno); le prove sul
modello locale prendono lo stesso lucchetto su file (`OLLAMA_LOCK_PATH`) e non girano a
cavallo delle 03:30 e delle 14:15, quando parte la pipeline.

## 2. Disegno          (architetto)

Stato: **in attesa dell'OK di Giuseppe**. Nessuna riga di codice è stata scritta.
Il banco di prova (passo 1) non aveva ancora numeri quando ho chiuso (16/11, `banco/risultati.md`
assente, `raw.jsonl` vuoto): dove una scelta dipende dal banco è scritto **[BANCO]**.

### 2.0 In tre righe

1. La chiamata che costa di più sul modello locale non è l'analisi, è **l'estrazione delle
   affermazioni**: scrive circa 590 token contro 158. E **più di metà di quelle chiamate lavora
   su articoli che l'analisi ha appena giudicato fuori tema** e che la piattaforma poi nasconde.
   Saltarle è il guadagno più grande e non richiede nessun modello nuovo.
2. Le risposte dell'analisi sono già corte: lì accorciare rende poco. Il resto del guadagno
   viene dal non far rileggere il testo (passo 4), se il banco conferma la cache.
3. Il passo 3 (classificatore, riordinatore) oggi **non toglierebbe nessuna chiamata**: lo
   sconsiglio in questo lavoro.

### 2.1 Vincoli misurati

Velocità del 7b usate per tutti i calcoli (dalla lavagna, misurate): leggere 77 ms a token
(13 token/s), scrivere 360 ms a token (2,8 token/s). **Ogni tempo «7b» qui sotto è un calcolo**
fatto con queste due velocità: il banco li sostituirà con tempi veri.

Misurato da me, in sola lettura sul database di produzione (transazione `READ ONLY`,
script in `scratchpad/arch/q1.py … q5.py`):

- `llm_calls` ha solo **674 righe, dal 15/11 02:35 al 16/11 13:27** (due giorni). È poco: i
  massimi veri possono essere più alti.
- `llm_calls` **non distingue analisi e affermazioni** dentro lo stesso stadio. Le ho separate
  così: reel per `max_tokens` (2000 = analisi, 1200 = affermazioni); articoli perché lo stesso
  articolo compare due volte e i token scritti sono in due gruppi netti (126-243 e 288-995).
  È una mia deduzione, non un'etichetta del registro.
- I token scritti da Groq (`gpt-oss`) **comprendono il ragionamento**: non sono confrontabili
  con quelli del modello locale. Per questo, dove posso, uso i caratteri salvati nel database.
- Rapporto misurato sul modello locale: **3,45 caratteri per token** (6.641 caratteri / 1.923 token).

| Chiamata | File | Tetto oggi | Letti (token) | Scritti (token) | Fonte | Tempo 7b (calcolo) |
|---|---|---|---|---|---|---|
| Analisi reel | `enrich_agent._enrich_one` | 2000 | ~1.400 (max 1.884) | ~260 | letti: 30 chiamate Groq; scritti: 895 caratteri medi di JSON salvato su 1.623 reel | 108 + 94 = **~200 s** |
| Affermazioni reel | `enrich_agent._extract_arguments` | 1200 | 1.110 | 522 (max **1.180**) | 5 chiamate locali 3b | 85 + 188 = **~275 s** |
| Analisi articolo | `knowledge_agent._enrich_one` | 2000 | 1.797 | 158 (max 243) | 16 chiamate locali 3b | 138 + 57 = **~195 s** |
| Affermazioni articolo | `knowledge_agent._extract_arguments` | 2000 | 2.036 | 590 (max 995) | 18 chiamate locali 3b | 157 + 212 = **~370 s** |
| Nome di un tema | `cluster_agent._name_cluster` | 300 | 511 | ~125 con ragionamento | 27 chiamate Groq | ~75 s |
| Forme degli indirizzi di un blog | `blog_discovery._classify_llm` | 700 | — | — | 0 chiamate in due giorni | — |

Quindi un articolo intero (analisi + affermazioni) costa ~565 s, un reel ~475 s (calcolo).
Nell'analisi dell'articolo **il 71% del tempo è lettura**; nelle affermazioni il 57% è scrittura.

Altri fatti misurati:

- **Affermazioni sugli articoli fuori tema**: 1.197 articoli attivi su 2.299 sono `is_on_topic=false`
  e non sono «ispirazione»; portano **5.563 affermazioni su 10.719** (52%). Quegli articoli sono
  esclusi da ricerca (`core/knowledge.py:113`), temi (`cluster_agent.py:227`), temi del cliente
  (`custom_topics.py:86`) e conteggi MCP (`server.py:169`). Le loro affermazioni si vedono solo
  aprendo l'articolo per numero. La coda delle affermazioni (`knowledge_agent.py:270`) non guarda
  `is_on_topic`.
- Per i **reel non vale**: i reel fuori tema (368 su 1.647) non sono esclusi da ricerca e temi
  (nessun filtro `is_on_topic` sui reel in `cluster_agent.py` e `knowledge.py`).
- Dentro un'affermazione, **la citazione copiata parola per parola è il pezzo più lungo**:
  articoli 126 caratteri di testo + 167 di citazione, 5,1 affermazioni a testo; reel 100 + 122, 5,2.
- Campi dell'analisi reel, caratteri medi: riassunto 222, analisi del gancio 152, pubblico 113,
  argomenti 92, gancio 69, tema 23. Articoli: riassunto 344, argomenti 144, motivo del fuori tema 167.
- **I JSON tagliati sono già stati il guasto principale delle affermazioni**: 99 articoli e 44 reel
  sono `failed` con `Unterminated string` (JSON tagliato, storico). Abbassare un tetto alla cieca
  ne crea altri.
- Oggi analisi e affermazioni dello stesso articolo girano **a 11 minuti di distanza, con altri
  articoli in mezzo** (righe 75-173 poi 201-314 di `llm_calls`): prima tutte le analisi, poi tutte
  le affermazioni.
- Tagli di oggi: reel 3.000 caratteri di trascrizione + 1.500 di didascalia per tutti e due i
  compiti; articoli **6.000** per l'analisi e **8.000** per le affermazioni. 854 articoli attivi
  superano i 6.000, 551 gli 8.000.
- Riordino della ricerca MCP: `core/knowledge.py:406-414` chiama con `remote_only=True`, e c'è un
  test (`test_llm_chain.py:267`). **Non tocca mai la CPU.** 9 chiamate in due giorni, 1,8 s l'una.
- Tutti i campi dell'analisi sono visti dal cliente: `hook_analysis_it`, `target_audience_it`,
  `off_topic_reason` stanno in `FEC/src/components/reels/ReelDetailDrawer.tsx` e in
  `mcp_bridge/server.py` (righe 436-438, 524). **Nessun campo si può togliere in silenzio.**

Supposto, non verificato:

- che Ollama 0.40.16 riusi l'inizio del prompt fra due chiamate **[BANCO, punto C]**;
- che il 7b scriva più o meno quanto il 3b (i token scritti qui sopra sono del 3b e di Groq);
- che il 7b rispetti un limite scritto in parole («massimo 20 parole»).

### 2.2 Passo 2 — risposte più corte

**Cosa propongo, dalla voce che rende di più.**

**2a. Non estrarre le affermazioni dagli articoli fuori tema** (serve il sì di Giuseppe, domanda 1).
Dopo l'analisi, se l'articolo è fuori tema e non è «ispirazione», `argument_status` diventa
`skipped` (valore che esiste già in `core/models.py:20`) e la chiamata non parte. Non è un
terzo valore di `owner_type` e non è un `failed` azzerato: è un lavoro non richiesto, con il suo nome.
- Guadagno (calcolo su quota misurata): ~370 s risparmiati per ogni articolo fuori tema, cioè
  **in media −196 s ad articolo su 565 (−35%)**. Vale anche per Groq: meno token spesi dal tetto
  del giorno, quindi meno lavoro che cade sulla CPU.
- Cosa vede il cliente: aprendo un articolo fuori tema non trova più le affermazioni. Lo
  strumento MCP `leggi_articolo` deve dirlo con una frase («fuori tema: affermazioni non estratte»).
  Le 5.563 già salvate restano dove sono.
- Solo articoli. Per i reel no: i reel fuori tema restano in ricerca e temi.

**2b. Affermazioni più asciutte** (un solo prompt, vale per Groq e per il locale).
In `ARGUMENTS_USER_TEMPLATE`: «testo: una frase sola, massimo 20 parole»; «citazione: il pezzo più
corto che basta a reggere l'affermazione, massimo 20 parole, copiato parola per parola». Il
controllo che la citazione esista nel testo resta identico (una citazione più corta è ancora una
porzione esatta).
- Guadagno (calcolo): articoli da ~293 a ~200 caratteri per affermazione → ~140 token in meno →
  **−50 s su 370 (−13%)**. Reel: già corte, ~−12 s su 275 (−4%).
- Cosa vede il cliente: citazioni più brevi nelle schede e nel connettore.

**2c. Ritocchi piccoli all'analisi** (stesso prompt per tutti): esempio di JSON scritto su una
riga invece che su dieci (il modello copia la forma); «motivo del fuori tema: massimo 12 parole»;
«analisi del gancio: una frase»; «pubblico: massimo 12 parole».
- Guadagno (calcolo): 20-30 token → **−7/−11 s** a chiamata. Poco: lo dico chiaro.

**2d. Tetti (`max_tokens` → `num_predict`) — giudizio.**
- Per **Groq restano come sono**: lì il ragionamento conta nel tetto, e la documentazione dice
  già «i tetti sono correttezza, non costo» (`03-llm-and-embeddings.md`, «Token ceilings»). Non
  riapro quella scelta.
- Sul **locale** però il tetto è anche tempo: 2.000 token sono 12 minuti se il modello parte a
  scrivere a vuoto. Propongo un secondo numero facoltativo, `local_max_tokens`, usato solo
  quando la chiamata cade su Ollama. Valori **[BANCO]**: il doppio del massimo che il 7b scrive
  sui 30 testi del banco, dopo i prompt nuovi. Senza numeri del banco non si tocca niente.
- Il tetto delle affermazioni reel (1200) è **stretto**: il 3b è arrivato a 1.180. Con 2b
  dovrebbe allargarsi il margine; non va abbassato.
- **Un JSON tagliato resta `failed`**: la strada esiste già (`LLMTruncated` → `LLMError` →
  l'agente scrive `failed`; test `test_llm_chain.py:119, 186, 203`). Va aggiunto un test che lo
  provi anche con `local_max_tokens`.

**Un prompt o due?** Uno solo. Due prompt (uno per Groq, uno per il locale) vogliono dire due
comportamenti da collaudare a ogni modifica, e analisi dello stesso tipo scritte in due stili
secondo chi ha risposto quella notte. E accorciare aiuta anche Groq: il suo tetto del giorno è la
ragione per cui il lavoro arriva sulla CPU.

**File da toccare**
- `BEC/llm/prompts.py` — testi di 2b e 2c (reel).
- `BEC/pipeline/agents/knowledge_agent.py` — 2a (coda delle affermazioni e stato `skipped`), 2c (articoli).
- `BEC/pipeline/agents/enrich_agent.py` — solo se si applica `local_max_tokens`.
- `BEC/llm/client.py` — solo per `local_max_tokens` (un parametro in `chat()`, passato a `_ollama_chat`).
- `BEC/mcp_bridge/server.py` — la frase per l'articolo fuori tema senza affermazioni.
- `BEC/core/queue_eta.py`, `core/management/commands/reprocess.py`, `progress.py` — da rileggere:
  `argument_status` compare in 33 punti di 12 file (`grep`), e `skipped` non deve sembrare «in coda».

**Cosa riuso**: `SKIPPED` (`core/models.py:20`); `LLMTruncated` e la sua strada in `llm/client.py`;
il controllo della citazione in `write_doc_arguments` / `_extract_arguments`; `_nota_analisi` in
`mcp_bridge/server.py` come modello per la frase nuova.

**Documentazione nello stesso commit**: `02-pipeline.md` (stadio `knowledge`: quando le
affermazioni si saltano); `03-llm-and-embeddings.md` («Token ceilings» e il prompt delle
affermazioni); `04-mcp-connector.md` (`leggi_articolo`); pagina `Documentazione`
(`FEC/src/pages/Documentation.tsx`) una riga in parole del cliente; docstring in cima ai moduli.
Il diagramma drawio non cambia (nessuno stadio nuovo).

**Test da scrivere** (nessuna chiamata vera a Groq né a Ollama: risposte finte)
- articolo fuori tema e non ispirazione → nessuna chiamata, `argument_status="skipped"`;
- articolo fuori tema ma ispirazione → la chiamata parte;
- articolo in tema → come oggi; reel fuori tema → come oggi;
- `leggi_articolo` su un articolo `skipped` dice la frase e non una lista vuota muta;
- risposta tagliata a `local_max_tokens` → `failed`, `truncated=True`, nessun secondo tentativo;
- una citazione corta ma esatta passa il controllo; una non esatta viene scartata (già oggi).

**Rischi**
- Il giudizio «fuori tema» dato dal 7b può sbagliare più di Groq: un falso fuori tema perde anche
  le affermazioni. Ma quell'articolo è già nascosto da ricerca e temi per lo stesso giudizio:
  il danno in più è piccolo, e `reprocess` lo rimette in coda.
- Un limite in parole può essere ignorato dal 7b: allora il guadagno di 2b è più basso, niente si rompe.
- Analisi nuove leggermente diverse dalle 3.900 già salvate (frasi più corte). Le vecchie non si rifanno.

**Alternative scartate**
- *Chiavi JSON corte* (`s` al posto di `summary_it`): ~20 token, 7 s. In cambio una tabella di
  traduzione nel codice e `raw_response` illeggibile. Non vale.
- *Calcolare il gancio nel codice* (prime parole della trascrizione): 7 s. Le trascrizioni di
  Whisper spesso non hanno punteggiatura, e il gancio lo vede il cliente. Non vale il rischio.
- *Togliere `hook_analysis_it` o `target_audience_it`*: li vede il cliente.
- *Meno argomenti negli articoli* (oggi 4-8): entrano nel vettore e nel confronto con i temi del cliente. Fermi.
- *Prompt diverso per il locale*: vedi sopra.
- *Citazione indicata con il numero della frase invece che copiata* (toglierebbe ~250 token, ~90 s):
  promettente, ma cambia il patto «citazione copiata» e nessuno l'ha provata su un 7b. Non in
  questo giro; se interessa, prima una prova al banco.

### 2.3 Passo 4 — il modello non rilegge lo stesso testo

**Com'è oggi (letto nel codice)**
- Ordine dentro il prompt: l'**analisi** mette già il testo prima e le regole dopo, per reel e
  articoli. Le **affermazioni** hanno una riga, poi il testo, poi le regole.
- Ma i due prompt dello stesso contenuto **divergono subito**: messaggio di sistema diverso
  (`KB_SYSTEM` / `ENRICH_SYSTEM` contro `ARGUMENTS_SYSTEM`), prima riga diversa, nei reel didascalia
  e trascrizione in ordine scambiato, negli articoli taglio diverso (6.000 / 8.000) e titolo
  presente solo nell'analisi. Il pezzo in comune è di pochi token.
- Ordine dei lavori: stesso stadio (`enrich` per i reel, `knowledge` per gli articoli), ma due giri
  separati: prima tutte le analisi, poi tutte le affermazioni.

**Strada A — due chiamate, stesso inizio (la mia proposta, solo se il punto C del banco dice sì)**
1. Le affermazioni adottano **l'inizio del prompt dell'analisi**, costruito da una sola funzione
   usata da tutti e due: stesso messaggio di sistema, stessa prima riga, stesso titolo, stesso
   testo con lo stesso taglio. In fondo cambia solo l'istruzione del compito. L'identità byte per
   byte la garantisce il codice, non l'attenzione di chi scrive.
2. **Il prompt dell'analisi non cambia parole**: resta valido il test
   `test_a_blog_keeps_the_old_words_to_the_letter` e la scelta già presa («2.281 analisi non si
   muovono»). Cambia solo il prompt delle affermazioni; la frase «riporta solo ciò che è stato
   detto» scende dal sistema all'istruzione finale.
3. **Un taglio solo per gli articoli** (domanda 3): propongo 8.000 per tutti e due.
4. **Un contenuto alla volta**: per ogni articolo (o reel) analisi e subito dopo affermazioni,
   poi il successivo. Con 2a viene naturale: analisi → fuori tema → si passa oltre.
- Guadagno (calcolo, **vale zero se il punto C dice no**): la seconda chiamata legge solo
  l'istruzione (~60 token) invece del testo. Articolo in tema: −150 s di lettura, +18 s perché
  l'analisi legge fino a 8.000 → **~−130 s su 565 (−23%)**. Reel: **~−80 s su 475 (−17%)**.
- Condizioni perché funzioni: nessun'altra chiamata locale in mezzo (un lavoro chiesto dal cliente
  con priorità può infilarsi: si perde il vantaggio di quella coppia, niente si rompe); modello
  caricato (già `keep_alive=30m`); stessa finestra (già fissa).

**Strada B — una sola chiamata che fa analisi e affermazioni**
- Pro: il testo si legge una volta **senza dipendere dalla cache**, e anche Groq spende quasi metà
  dei token in ingresso.
- Contro: un errore fa perdere tutto insieme, e le affermazioni sono proprio la parte che si taglia
  (143 `failed` storici per JSON tagliato): trascinerebbero giù anche analisi buone. La risposta
  diventa ~750-850 token in un colpo. Nessuna prova che un 7b in italiano tenga due compiti senza
  peggiorare. I due stati (`enrich_status`, `argument_status`) andrebbero legati. Riscrive il prompt
  dell'analisi, cioè riapre la scelta «le analisi non si muovono».
- Giudizio: **no in questo lavoro**. La riprendo solo se il punto C dice che la cache non funziona,
  e comunque dopo una prova di qualità al banco su 20 testi.

**Strada C — regole fisse in testa, uguali per tutti i contenuti** (variante): la cache
risparmierebbe le regole (reel ~650 token = 50 s; articoli ~250 = 19 s) a ogni chiamata, anche fra
contenuti diversi. Ma sposta le istruzioni lontano dalla risposta (qualità non provata su un 7b) e
riscrive il prompt dell'analisi. Il banco oggi non la misura: se interessa, va aggiunta una prova
«stessa testa, testo diverso». Non la propongo ora.

**File da toccare (strada A)**
- `BEC/llm/prompts.py` — istruzione finale delle affermazioni, staccata dalla testa.
- `BEC/pipeline/agents/knowledge_agent.py` — funzione unica per la testa; un taglio solo; giro per contenuto.
- `BEC/pipeline/agents/enrich_agent.py` — lo stesso per i reel (stesso ordine didascalia/trascrizione).
- `BEC/mcp_bridge/server.py` — legge le costanti del taglio per `nota_analisi`.
- `BEC/core/tests/test_mcp_tools.py:513-515` — oggi afferma 6000 / 8000 / 3000.
- `BEC/core/progress.py` e la pagina «Avanzamento» — oggi due barre («Analisi», «Affermazioni»):
  con il giro per contenuto diventa una sola barra. **Il cliente lo vede.**
- `BEC/core/queue_eta.py` — stima i tempi dai giri passati: va riletto.

**Cosa riuso**: `build_doc_enrich_prompt`, `_intro`, `build_enrich_prompt` (la testa c'è già);
`_parallel` e `_tracked` di `enrich_agent.py`; gli stati separati, che restano due.

**Documentazione**: `02-pipeline.md` (stadi `enrich` e `knowledge`, sezione «Progress of a round»);
`03-llm-and-embeddings.md` («What the document analysis reads», la sezione del modello locale con
il numero misurato dal banco); `04-mcp-connector.md` (righe 202-219, i tagli); pagina
`Documentazione` e `06-frontend.md` se cambia la barra di Avanzamento; pagina tecnica del drawio
(ordine dentro lo stadio).

**Test**: i due prompt dello stesso contenuto hanno sistema identico e la stessa testa
(`startswith`), per blog, video, intervista, reel con e senza parlato; il prompt dell'analisi è
uguale a oggi alla lettera; l'ordine delle chiamate finte è analisi-affermazioni-analisi-affermazioni;
analisi fallita → affermazioni non tentate; modello locale non disponibile a metà → resta `pending`,
non `failed`; affermazioni fallite → l'analisi resta `done`.

**Rischi**
- Tutto il guadagno dipende dal punto C. Va provato **come chiama il nostro codice**: `/api/chat`,
  messaggio di sistema, `format=json`, `num_ctx=8192`.
- Le affermazioni con l'istruzione dopo il testo potrebbero cambiare qualità, anche su Groq.
  Serve un confronto su ~10 contenuti prima del rilascio (domanda 5).
- Taglio a 8.000: per gli articoli già analizzati a 6.000 la nota del connettore direbbe «primi
  8.000» mentre il riassunto ne ha letti 6.000 (riguarda gli 854 sopra i 6.000). Da scrivere nei limiti noti.
- **Passo 5 (testi interi) — vincolo rispettato**: la testa comune è costruita su «un pezzo di
  testo», non su «il documento». Quando arriverà la lettura a pezzi, ogni pezzo avrà la sua
  coppia di chiamate consecutive. Non alzo né il taglio oltre 8.000 né la finestra.

### 2.4 Passo 3 — compiti semplici fuori dal modello generativo (solo candidati)

| Candidato | Chiamate oggi | Tempo locale | Giudizio |
|---|---|---|---|
| Riordino della ricerca MCP | 9 in due giorni | **zero**: è `remote_only`, verificato | Un riordinatore sulla CPU non farebbe risparmiare nulla; anzi aggiungerebbe lavoro alla CPU. Servirebbe solo per avere un ordine migliore quando Groq rifiuta: è qualità, non velocità |
| `content_format` (elenco chiuso di 7) | nessuna sua: è un campo dell'analisi reel | ~3 s dentro l'analisi | Un classificatore non toglie la chiamata |
| `is_on_topic` (sì/no) | nessuna sua: è un campo dell'analisi | ~2 s | Idem. Diventa interessante solo come **filtro prima dell'analisi** (salterebbe ~195 s per ogni articolo fuori tema, il 52%), ma allora l'articolo fuori tema resta senza riassunto, e il cliente lo vede |
| Forme degli indirizzi di un blog | 0 in due giorni | — | Ha già una regola di riserva senza modello |
| Nome dei temi | 27 in due giorni, ~75 s l'una sul locale | — | È scrittura, non etichetta: resta al modello |

In breve: oggi **non esiste una chiamata che sia solo un'etichetta**. Il guadagno «fuori tema» lo
prende già la voce 2a, senza allenare nulla.

Domande che spettano a Giuseppe se si volesse comunque il filtro prima dell'analisi:
- un classificatore allenato sulle etichette di Medyca e dei competitor insieme rispetta la regola
  di separazione? (Impara da tutti e due, ma non mostra a nessuno il contenuto dell'altro.)
- va bene che un articolo fuori tema resti senza riassunto?
- chi verifica a mano i 100 casi di controllo?
- i termini d'uso del modello Groq che ha prodotto le etichette permettono di allenarci sopra?

### 2.5 Cosa resta fuori

- Cambiare modello o motore (deciso da Giuseppe).
- I testi lunghi letti a pezzi (lavoro separato; qui solo il vincolo).
- I lavori chiesti dal cliente che scrivono testo libero e possono cadere sul locale: brief e bozza
  di strategia (1800 / 2400 token), bozze di blog (2400 / 2800 / 3200), idee (1200). Sul 7b una
  bozza da 3.200 token sono ~19 minuti di sola scrittura più ~4,5 di lettura: **vicino al limite di
  30** (calcolo). Non li tocco, ma lo segnalo (domanda 6).
- Rifare le analisi e le affermazioni già salvate.
- Classificatore e riordinatore (passo 3).
- «jev»: non capito, non entra finché Giuseppe non chiarisce.

### 2.6 In quante PR, in che ordine

| PR | Contenuto | Dipende da | Guadagno locale (calcolo) | Rischio |
|---|---|---|---|---|
| **1** | 2a: niente affermazioni sugli articoli fuori tema | sì di Giuseppe (domanda 1) | −35% per articolo, in media | basso |
| **2** | 2b + 2c: affermazioni e campi più asciutti, JSON su una riga | niente | articoli −50 s (−13% della chiamata), reel −12 s, analisi −7/11 s | basso |
| **3** | 2d: `local_max_tokens` | **[BANCO]** token scritti dal 7b | nessuno sulla media: toglie il caso da 12 minuti | medio (un tetto sbagliato crea `failed`) |
| **4** | Passo 4, strada A | **[BANCO] punto C** | articoli in tema −23%, reel −17% | medio (cambia l'ordine dei lavori e la barra di Avanzamento) |

La 1 e la 2 possono partire subito. La 3 e la 4 aspettano il banco. Se il punto C dice no, la 4
non si fa.

Somma per un articolo, se tutto va come calcolato: oggi ~565 s; fuori tema ~195 s; in tema
~565 − 50 − 130 = ~385 s. Media sui due casi: **~285 s, circa la metà di oggi**. È un calcolo su
velocità misurate e quote misurate, non un tempo cronometrato.

### 2.7 Domande aperte per Giuseppe

1. **Smettiamo di estrarre le affermazioni dagli articoli che l'analisi giudica fuori tema?**
   (Oggi sono il 52% e non compaiono né in ricerca né nei temi.) *Raccomando sì*, tenendo fuori
   dalla regola gli articoli segnati come ispirazione.
2. **Va bene che le citazioni diventino più corte** (massimo ~20 parole) in tutte le affermazioni
   nuove, anche quelle fatte da Groq? *Raccomando sì.* E il numero massimo resta 6? *Raccomando di
   lasciarlo a 6*: scendere a 4 farebbe risparmiare altri ~60 s ad articolo, ma il cliente vedrebbe meno.
3. **Taglio unico per gli articoli: 8.000 o 6.000 caratteri?** *Raccomando 8.000* (il riassunto
   legge un po' di più; nessuna affermazione si perde). Il prezzo: la nota del connettore sarà
   imprecisa per gli articoli già analizzati a 6.000.
4. **Una barra sola «Analisi e affermazioni» nella pagina Avanzamento al posto di due** va bene?
   *Raccomando sì*: è il prezzo del lavorare un contenuto alla volta.
5. **Posso far spendere ~10 chiamate vere a Groq**, una volta, per confrontare le affermazioni
   prima e dopo il nuovo prompt? *Raccomando sì*: è l'unico modo di sapere se la qualità tiene
   anche lì. Senza il tuo sì il confronto si fa solo sul modello locale.
6. **I lavori di scrittura chiesti dal cliente (bozze, brief) devono poter cadere sul modello
   locale?** Una bozza lunga ci mette oltre 20 minuti. *Raccomando di deciderlo in un lavoro a
   parte*; l'alternativa è «solo Groq, e se rifiuta: riprova più tardi», come già fa il piano editoriale.
7. **Passo 3**: *raccomando di non farlo in questo lavoro*. Non toglie chiamate dalla CPU. Sei d'accordo?
8. **Soglia per tenere una modifica**: il rapporto propone «almeno il 20% di tempo in meno e
   qualità non peggiore». La PR 2 da sola sta sotto. *Raccomando di tenerla comunque*: costa poco e
   alleggerisce anche Groq.

## Registro

- 16/11 15:10 — capo: aperto il lavoro. Lanciati insieme il banco di prova (passo 1, sola
  misura) e l'architetto (passi 2-4). Il disegno aspetta l'OK di Giuseppe.

## Cambio di priorità (Giuseppe, 16/11/2026 pomeriggio)

Il cliente ha letto nel connettore: «Un limite che resta: il riassunto e le affermazioni
vengono ancora ricavati solo dai primi 6.000 caratteri. Il database lo dichiara in
nota_analisi, quindi per quelle puntate vale il testo e non le affermazioni.»

Parole di Giuseppe: «Aggiusta tutto, non possiamo lasciare questo limite. Fai un assesment
e vedi quanto ci metto prima, poi rilasciamo dobbiamo provvedere a questo errore»

Quindi: **riassunto e affermazioni devono leggere tutto il testo, per tutti i contenuti**,
e quelli già analizzati sull'inizio vanno rifatti. Questo passa davanti al resto del
disegno; il resto (fuori tema, risposte asciutte, niente rilettura) resta e serve a pagare
il conto.

### Numeri (capo, sola lettura sulla produzione, 16/11)

Contenuti attivi analizzati solo sull'inizio:

| Cosa | Quanti | Caratteri totali |
|---|---|---|
| Puntate/video di riferimento > 6.000 | 17 | 282 mila |
| Articoli in tema > 6.000 (358 competitor + 38 owned circa; 396 blog) | 396 | 4,24 milioni |
| Articoli fuori tema > 6.000 | 441 | 4,71 milioni |
| Reel > 3.000 (356 competitor, 2 owned) | 358 | 8,41 milioni (il più lungo 85.699) |

Articoli > 30.000 caratteri: 13. Reel > 8.000: 189.

Groq oggi: circa 200-250 mila token al giorno sul modello principale prima di «daily token
budget exhausted» (15/11: 155 mila letti + 63 mila scritti su gpt-oss-120b), più i modelli
fratelli (20-45 mila al giorno visti). 7b locale: legge ~13 token/s, scrive ~2,8.

Stima grezza (3,5 caratteri per token, due letture per contenuto come oggi): puntate ~0,16
milioni di token; articoli in tema ~3,3 milioni; reel lunghi ~4,8 milioni; articoli fuori
tema ~1,4 milioni se solo riassunto. Totale ~10 milioni di token. È un calcolo.
