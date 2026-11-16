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

### 2.0 Testo intero (diventa la PR numero 1)

Aggiunta del 16/11 pomeriggio, dopo il «Cambio di priorità» di Giuseppe. Passa davanti a tutto
il resto del disegno. Stato: **in attesa dell'OK di Giuseppe**, nessun codice scritto.

**In quattro righe**
1. Fino a 8.000 caratteri si fa come oggi, ma leggendo tutto. Oltre, il testo si divide in pezzi
   da circa 6.000 caratteri tagliati a fine frase: ogni pezzo dà le sue affermazioni (con citazione
   vera) e una riga di appunti; alla fine una chiamata sola scrive il riassunto dagli appunti.
   **Il testo lungo si legge una volta sola, non due come oggi.**
2. Se un pezzo fallisce, il contenuto è `failed` e non si salva niente a metà.
3. Serve un campo nuovo (una migrazione piccola) che dice «questo è stato letto per intero»: la
   nota del connettore sparisce solo per quelli.
4. Il passato lo rifà **il 7b locale, giorno e notte** (deciso da Giuseppe), dopo il giro quotidiano
   e mai al suo posto: **~243 ore di modello, circa 13 giorni a calendario** (calcolo); le 17 puntate
   ~4 ore, gli articoli di Medyca ~9.

#### A. Cosa taglia oggi (elenco verificato nel codice con `grep`)

| Dove | Taglio | Entra nella PR 1? |
|---|---|---|
| `knowledge_agent.py:124` riassunto articoli/puntate | 6.000 | sì |
| `knowledge_agent.py:169,181` affermazioni articoli | 8.000 | sì |
| `enrich_agent.py:235,329` trascrizione reel (analisi e affermazioni) | 3.000 | sì |
| `enrich_agent.py:234,328` didascalia reel | 1.500 (197 reel la superano) | sì: si legge intera (Instagram ne ammette 2.200) |
| `blog_workflow.py:136` bozza da intervista | 12.000, **in silenzio** | no: PR a parte; subito scritto nei limiti noti |
| `blog_workflow.py:180` articolo da espandere | 4.000, in silenzio | no: come sopra |
| `blog_workflow.py:51` ogni reel del tema nella bozza | 700 | no: è un estratto voluto, va solo dichiarato |
| `knowledge_agent.py:228`, `cluster_agent.py:72` testo dentro il vettore | 4.000 | no: il vettore contiene anche il riassunto (che ora copre tutto), e la ricerca ha già i vettori di ogni passaggio del testo intero |

#### B. Vincoli misurati

- **Groq** (`03-llm-and-embeddings.md`, limite pubblico, quello del nostro conto non è verificato):
  8.000 token al minuto, 200.000 al giorno su `gpt-oss-120b`. Misurato in `llm_calls`: 15/11
  155 mila letti + 63 mila scritti; 16/11 119 + 37 mila; fratelli 20-45 mila. La richiesta più
  grande mai servita: 3.278 token letti, 4.878 contando il tetto di risposta.
  Quindi **un testo da 30.000 caratteri (~8.700 token) non può partire in una richiesta sola**: supera
  il minuto. `client._patient` aspetta il minuto fino a 6 volte, ma una richiesta troppo grande
  spreca tutte e sei le attese (limite già scritto nella documentazione).
  Non verificato: se Groq conta nel minuto anche il tetto di risposta. Disegno come se sì.
- **7b locale**: finestra 8.192 token, limite 1.500 s a chiamata. Primi numeri veri del banco
  (letti da `banco/run.log` e `run2.log`; `risultati.md` non c'è ancora, quindi **provvisori**):
  legge 15-17,8 token/s, scrive 2,5-4,2; un'analisi vera 116-189 s. Un po' meglio dei 13 / 2,8
  della lavagna.
- **Chi risponde si decide dentro `client.chat()`, chiamata per chiamata**: lo stesso contenuto può
  avere il pezzo 1 su Groq e il pezzo 2 sul 7b. Perciò **la misura del pezzo è una sola**, quella
  che entra in tutti e due. Due soglie diverse vorrebbero dire due comportamenti e pezzi che
  cambiano a metà contenuto.
- Quanto c'è da rifare (mia query in sola lettura, `scratchpad/arch/q6.py`; 3,45 caratteri per token misurati):

| Gruppo | Contenuti | Caratteri | di cui ≤ 8.000 | di cui lunghi | Pezzi |
|---|---|---|---|---|---|
| 1. Puntate, video, interviste | 17 | 282 mila | 2 | 15 | 51 |
| 2. Blog di Medyca | 38 | 663 mila | 3 | 35 | 122 |
| 3. Articoli competitor in tema | 360 | 3,60 milioni | 140 | 220 | 548 |
| 4. Reel in tema > 3.000 | 225 | 7,14 milioni | 62 | 163 | 1.233 |
| 5a. Reel fuori tema > 3.000 | 40 | 1,08 milioni | 14 | 26 | 182 |
| 5b. Articoli competitor fuori tema | 439 | 4,69 milioni | 158 | 281 | 736 |

  Nota: il capo conta 358 reel (2 di Medyca), io 265 e nessuno di Medyca. La mia query tiene solo i
  reel attivi con trascrizione e account collegato; lo sviluppatore deve far tornare i due conti
  prima del rifacimento. I «reel» lunghi sono video veri: metà supera i 36.000 caratteri, il più
  lungo 85.699 (15 pezzi).

#### C. Come si legge tutto

**Testo fino a 8.000 caratteri — strada corta, come oggi.** Due chiamate (analisi, affermazioni),
stessi prompt di oggi, ma tutte e due leggono il testo intero: il taglio 6.000 sale a 8.000 e
quello dei reel da 3.000 a 8.000. Entra in Groq (al massimo ~3.400 token letti + tetto) e nel 7b.

**Testo oltre 8.000 — strada lunga, a pezzi.**
1. **Taglio.** Pezzi tutti simili, mai più di ~6.000 caratteri (`n = lunghezza / 6.000` arrotondato
   in su, poi pezzi di lunghezza uguale). Il taglio cade sull'ultima fine frase (`. ! ?` o a capo)
   prima del limite; se non c'è punteggiatura (capita con Whisper) sull'ultimo spazio. Mai a metà
   parola. **Nessuna sovrapposizione** fra pezzi: così niente affermazioni doppie nate dal taglio.
   6.000 caratteri sono ~1.750 token, la misura che il rapporto di ricerca consiglia per i modelli
   piccoli. È un'impostazione: il banco (punti 5 e 9, non ancora fatti) può cambiarla **[BANCO]**.
2. **Ogni pezzo — una chiamata.** È il prompt delle affermazioni di oggi, con due ritocchi: al
   massimo 3 affermazioni per pezzo, e in più una riga di appunti («di cosa parla questo pezzo»,
   massimo 25 parole). Risposta: `{"sintesi": "...", "argomenti": [{"testo","citazione"}]}`.
   Sono fatti brevi, non prosa. Il prompt dice «pezzo 3 di 7 di …» perché il modello non lo tratti
   come un testo completo.
3. **Citazioni vere.** Ogni citazione si controlla **contro il suo pezzo**, con lo stesso controllo
   di oggi (`_norm(citazione) in _norm(testo)`): se non c'è, l'affermazione si scarta. Il modello
   vede un pezzo solo, quindi non può cucire una citazione a cavallo di due.
4. **Unione delle affermazioni** (nel codice, nessuna chiamata): si tolgono le doppie (stessa
   citazione, o testi quasi uguali misurati con il modello dei vettori che la piattaforma usa già,
   soglia da tarare sui primi contenuti); poi si sceglie a giro, la prima di ogni pezzo, poi la
   seconda, così **le affermazioni coprono tutto il testo** e non solo l'inizio; ordine finale:
   quello del testo.
5. **Tetto.** Oggi 6 per qualunque testo. Per un testo di 15 pezzi 6 sono poche. Propongo: 6 fino a
   8.000 caratteri; per i lunghi fino a **12** (domanda 2). Il connettore oggi ne mostra al massimo
   10 (`server.py:449,543`): va portato a 12.
6. **Riassunto — una chiamata finale.** Riceve titolo, la riga di apertura di oggi (`_intro`), gli
   appunti di tutti i pezzi e i testi delle affermazioni tenute, e restituisce **lo stesso JSON
   dell'analisi di oggi** (riassunto, argomenti, tema, in tema / fuori tema). Per i reel riceve in
   più i primi ~1.500 caratteri veri della trascrizione e la didascalia, perché gancio e analisi
   del gancio parlano dell'inizio. Con 15 pezzi sono ~3.400 token: entra ovunque. Limite dichiarato:
   oltre ~40 pezzi (240.000 caratteri) gli appunti non entrano più; oggi il massimo è 15. Se
   succede, `failed` con un messaggio chiaro, non un taglio.
7. **Si salva tutto insieme, alla fine.** Analisi e affermazioni entrano nel database in un'unica
   scrittura.

Perché così: gli appunti dei pezzi **sono** le affermazioni, quindi il testo lungo si legge una
volta. Con due passate separate (come oggi) il rifacimento costerebbe quasi il doppio in lettura.

**Cosa riuso**: `ARGUMENTS_USER_TEMPLATE` e il controllo della citazione (`enrich_agent._norm`,
`write_doc_arguments`); `build_doc_enrich_prompt`, `_intro`, `write_doc_enrich`, `write_enrichment`
(il JSON finale è quello di oggi, quindi chi lo salva non cambia); `_embedder()` per le doppie;
`_parallel` / `_tracked` per barra e stati; `LLMTruncated` e `NOT_THE_ITEMS_FAULT` del client.
Codice nuovo: un modulo solo, piccolo (`pipeline/whole_text.py`: tagliare, unire, togliere le doppie),
usato da reel e articoli.

#### D. Fallimenti

- Un pezzo che fallisce (JSON rotto, risposta tagliata, errore) → **tutto il contenuto è `failed`**
  (`enrich_status` e `argument_status`), con scritto quale pezzo («pezzo 3 di 7: …»). Niente viene
  salvato. Mai un'analisi di 6 pezzi su 7 mostrata come intera.
- Un pezzo senza affermazioni non è un errore (lista vuota = risposta corretta, come oggi).
- Modello non disponibile a metà (non è colpa del contenuto) → resta `pending`; i pezzi già fatti
  si buttano e si rifanno al giro dopo. Scelta voluta: salvare i pezzi a metà chiederebbe una
  tabella nuova. Costo: al massimo il lavoro di un contenuto per ogni interruzione.
- Nessun secondo tentativo automatico, come oggi.

#### E. Come si segna «letto per intero»

Oggi `_nota_analisi` (`server.py:381`) decide solo dalla lunghezza. Dopo la PR direbbe il falso in
un senso o nell'altro. **Serve un campo, quindi una migrazione.**

- `full_text_status` su `reels` e su `knowledge_documents` (stessi valori degli altri stati):
  `done` = l'analisi in vigore ha letto tutto; `pending` = fatta sull'inizio, da rifare;
  `failed` = il rifacimento è fallito.
- La migrazione mette `done` a chi ha un testo che stava già dentro il vecchio taglio (lì l'analisi
  aveva letto tutto) e `pending` agli altri. Circa 3.900 righe, pochi secondi. Aggiungere la
  colonna non blocca la tabella.
- La nota compare **solo se lo stato non è `done`**, con i numeri di allora (3.000 e 6.000, tenuti
  come costanti «del vecchio taglio»). Sparisce contenuto per contenuto, man mano che si rifà.
- Ogni analisi nuova scrive `done`. Una trascrizione rifatta rimette il contenuto in coda come oggi.

#### F. Rifare quelli già dentro — sul 7b locale, giorno e notte

Deciso da Giuseppe (16/11 sera): **Groq a pagamento no; il rifacimento lo fa il modello locale**, e
che duri giorni non importa. Groq gratuito resta com'è, tutto per il giro quotidiano dei contenuti
nuovi: non vedo motivi contrari, anzi così il rifacimento non gli toglie un solo token.

**Comando nuovo** `manage.py reanalyze_whole`, costruito sul modello di `reprocess --stage enrich`
(che già rifà analisi + affermazioni un contenuto alla volta). Non uso `reprocess --stage
knowledge`: quello rimette in coda tutti i `failed`, cosa che qui non si vuole.

- **Solo locale.** Le sue chiamate non passano mai da Groq. Serve un parametro piccolo in
  `client.chat()`, gemello di `remote_only` che esiste già.
- **Cosa prende**: i contenuti attivi con `full_text_status="pending"`. È il dato a dire cosa
  manca: **non rifà mai due volte**, e ripartire vuol dire solo rilanciarlo.
- **Ordine** (`--gruppo`): 1 puntate/video/interviste → 2 articoli di Medyca → 3 articoli competitor
  in tema → 4 reel lunghi in tema → 5 fuori tema. Miglioria che propongo: **dentro ogni gruppo dal
  più corto al più lungo**, così ogni giorno si chiudono più contenuti e le note spariscono prima.
- **Non blocca il giro delle 03:30 e delle 14:15.** Oggi il lucchetto del modello locale
  (`client._ollama_slot`) ha due livelli: una persona che aspetta passa davanti al lavoro di fondo.
  Ne aggiungo un terzo, con lo stesso meccanismo: **persona → giro della pipeline → rifacimento**.
  Il giro, quando parte, alza una bandierina (un file accanto al lucchetto, come fa già la
  priorità); il rifacimento la guarda **prima di ogni chiamata** e, se è alzata, si mette da parte
  finché il giro finisce. Una chiamata del rifacimento dura 3-5 minuti: è l'attesa massima per il
  giro (che ne tollera 30, `OLLAMA_LOCK_WAIT`). Il rifacimento non tocca il lucchetto «un giro alla
  volta» (`PIPELINE_LOCK_PATH`), quindi non può far saltare un giro.
- **Come gira giorno e notte**: lanciato dal cron ogni ora, con un suo lucchetto «una copia sola».
  Se è già in corso, il nuovo lancio esce subito. Dopo un riavvio del server o un rilascio riparte
  da solo entro un'ora.
- **Come si ferma**: un interruttore in `ScraperConfig` (tabella che esiste già), letto fra una
  chiamata e l'altra: spento → finisce la chiamata in corso e si ferma; riacceso → riparte da dove
  era. Se viene ucciso a metà di un contenuto si perdono solo i pezzi di quel contenuto.
- **Come si vede a che punto è** (pagina «Avanzamento»):
  - gratis, già oggi: ogni chiamata locale fuori dal giro compare nella lista «altre chiamate» con
    il nome del contenuto; basta darle l'etichetta «Rifacimento sul testo intero»;
  - in più un riquadro piccolo: per ogni gruppo «fatti / da fare / falliti», il contenuto in
    lavorazione («pezzo 4 di 9»), in pausa o no, e la fine stimata. I conti vengono da
    `full_text_status` nel database (veri anche dopo un riavvio); la stima dai secondi medi delle
    ultime chiamate locali del rifacimento, come fa già `progress_report` per gli stadi.
- **I falliti**: `full_text_status="failed"` con il motivo in `last_error`. Restano tali: si
  ritentano solo con `--ritenta-falliti`, scritto a mano. Il riquadro li conta.
- **Il cliente non vede mai un contenuto vuoto**: tutto si calcola in memoria e solo a lavoro
  finito analisi e affermazioni si sostituiscono in una scrittura unica. Fino ad allora restano
  riassunto, affermazioni e nota vecchi (la nota è ancora vera). Se fallisce resta tutto com'era.
- **Vettori**: dopo il rifacimento `embed_status` torna `pending` e il giro notturno ricalcola il
  vettore (regola già scritta in `03-llm-and-embeddings.md`, «Re-embed after a re-analysis»). Per i
  reel lo stadio dei vettori calcola solo quelli mancanti (`embed_agent.py:32`): il vettore vecchio
  va tolto insieme alla scrittura nuova. I vettori dei passaggi non cambiano.
- **Temi**: lo stadio `cluster` della notte lavora sui vettori nuovi. Durante il rifacimento
  qualche contenuto cambia tema da una notte all'altra; un articolo che letto per intero risulta
  in tema (o fuori) entra o esce da ricerca e temi. È l'effetto voluto, ma va detto al cliente.

#### G. Tempi del rifacimento sul 7b

Come ho contato (calcolo, su caratteri misurati e sulle velocità **provvisorie** del banco: 16,5
token/s in lettura, 3,4 in scrittura; fra parentesi con le velocità più lente della lavagna, 13 e 2,8):
- un pezzo: ~2.040 token letti, ~300 scritti → **~212 s** (264);
- chiamata finale: articolo ~100 s (124), reel ~215 s (267);
- un contenuto corto (fino a 8.000, due chiamate): articolo ~455 s, reel ~430 s.

| Gruppo | Contenuti | Chiamate | Ore di modello (calcolo) |
|---|---|---|---|
| 1. Puntate, video, interviste | 17 | 51 pezzi + 15 finali + 4 | **~4 h** (fino a 5) |
| 2. Articoli di Medyca | 38 | 122 + 35 + 6 | **~9 h** (fino a 11) |
| 3. Articoli competitor in tema | 360 | 548 + 220 + 280 | **~56 h** (fino a 70) |
| 4. Reel lunghi in tema | 225 | 1.233 + 163 + 124 | **~90 h** (fino a 112) |
| 5. Fuori tema (40 reel + 439 articoli) | 479 | 918 + 307 + 344 | **~85 h** (fino a 106); **~73 h** con la PR «fuori tema» |
| **Totale** | 1.119 | ~4.370 | **~243 h, cioè ~10 giorni filati**; senza i fuori tema ~158 h, ~6,5 giorni |

A calendario conto un 20-30% in più: le pause per i due giri al giorno, i lavori chiesti dal
cliente, e la macchina che rallenta quando gira altro (misurato in passato: fino al 70% su una
chiamata). Quindi **circa 13 giorni per tutto, 8-9 senza i fuori tema**. Le prime due righe (i
contenuti del reclamo e quelli di Medyca) stanno in **una notte e un giorno**.

Avvertenze:
- le velocità sono di una decina di chiamate del banco, non ancora il suo rapporto finale; i token
  scritti per pezzo sono una stima. **Il gruppo 1 è la misura vera**: dopo le 17 puntate questa
  tabella si rifà con numeri cronometrati;
- la CPU resta occupata per quasi due settimane. Chi chiede una bozza ha la precedenza ma aspetta
  la chiamata in corso (3-5 minuti);
- **qualità**: tutto il rifatto sarà scritto dal 7b. Oggi 1.177 analisi dei reel sono di Claude
  (Opus 5 e Sonnet 5, misurato in `enrichments.llm_model`) e gli articoli recenti di `gpt-oss-120b`.
  La documentazione ha già scritto che la qualità del 7b «non è provata» e che storpia termini
  («brain fog» → «fuga del cervello»). Si guadagna la copertura di tutto il testo; lo stile può
  scendere. È il motivo per cui ci si ferma a guardare le 17 puntate (domanda 5).

#### H. Ordine nuovo: cosa serve PRIMA del rifacimento grosso

Regola per decidere: **obbliga a rifare due volte solo ciò che cambia il contenuto salvato**
(quante affermazioni, quanto lunghe le citazioni, misura dei pezzi, parole dei prompt). Ciò che
cambia solo il tempo si può aggiungere a rifacimento in corso, ma prima arriva più ore toglie.

| Passo | Contenuto | Perché a questo punto | Ore tolte al rifacimento (calcolo) |
|---|---|---|---|
| **PR 1** | Testo intero: pezzi e unione (**una lettura sola** per i testi lunghi), **affermazioni asciutte (ex 2b)**, campo + migrazione + nota del connettore, comando di rifacimento solo locale con la sua priorità, riquadro in Avanzamento | È il minimo che toglie il limite. Le asciutte stanno qui perché cambiano il contenuto: dopo vorrebbe dire rifare | lettura unica: circa metà della lettura dei lunghi, ~60 h già dentro la stima; asciutte: ~13% della scrittura, già dentro |
| **Giro 1** | Le 17 puntate (~4 h), poi **ci si ferma**: Giuseppe le legge | Primissima cosa, come chiesto. È anche il banco vero del 7b: tempi, token scritti, quante affermazioni scarta | — |
| **Ritocco** | Se la lettura dice di cambiare qualcosa (tetto di 12, lunghezza delle citazioni, misura dei pezzi) si cambia **adesso** e le 17 si rifanno: sono 4 ore | Dopo costerebbe giorni | — |
| **Giro 2** | Articoli di Medyca (~9 h) | Può partire appena le 17 sono approvate | — |
| **PR 2** | **Tetto locale** (`local_max_tokens`, valori presi dal giro 1) + **niente affermazioni sugli articoli corti fuori tema (ex 2a)** + **testa comune dei due prompt per i testi corti (ex PR 4)** | Da avere **prima del gruppo 3**. Il tetto protegge ~4.000 chiamate dal caso «12 minuti a vuoto». La testa comune fa leggere il testo corto una volta sola: il banco (provvisorio) dice che la cache funziona con il testo prima (9 s invece di 99) e non con i prompt di oggi (109 s) | testa comune ~12 h su 379 contenuti corti; fuori tema ~12 h sul gruppo 5 |
| **Giri 3, 4, 5** | Articoli in tema (~56 h), reel lunghi (~90 h), fuori tema (~73 h) | Di fila, senza altre soste | — |
| **Dopo** | Bozze di blog dal testo intero (`blog_workflow`, tagli 12.000 e 4.000) | Non riguarda riassunti e affermazioni | — |

Se la PR 2 tarda, i giri 3-5 possono partire lo stesso: niente andrà rifatto, si spendono solo
~24 ore in più. I ritocchi piccoli all'analisi (ex 2c) non li metto più: cambierebbero il prompt
dell'analisi a metà rifacimento per pochi secondi di guadagno.

#### I. File da toccare nella PR 1

- `BEC/pipeline/whole_text.py` (nuovo) — tagliare a fine frase, unire, togliere le doppie.
- `BEC/llm/prompts.py` — prompt del pezzo e della chiamata finale; limite di parole su testo e citazione.
- `BEC/pipeline/agents/knowledge_agent.py`, `enrich_agent.py` — strada corta sul testo intero, strada lunga, scrittura unica, stato nuovo.
- `BEC/core/models.py` + migrazione — `full_text_status` su `Reel` e `KnowledgeDocument`.
- `BEC/mcp_bridge/server.py` — `_nota_analisi` legge il campo; fino a 12 affermazioni; istruzioni del connettore (riga 96).
- `BEC/core/management/commands/reanalyze_whole.py` (nuovo), e `reprocess.py` da rileggere (una trascrizione rifatta deve rimettere lo stato a `pending`).
- `BEC/llm/client.py` — il parametro «solo locale» e il terzo livello del lucchetto (il rifacimento si mette da parte se un giro è in corso).
- `BEC/pipeline/dag.py` — il giro alza e abbassa la sua bandierina.
- `BEC/core/progress_report.py`, `FEC` pagina Avanzamento — etichetta della chiamata e riquadro del rifacimento (seguendo `.claude/skills/ui-design/`).
- `BEC/core/management/commands/eval_mcp.py` — oggi dà per certo che ogni citazione stia nella prima parte del testo (`04-mcp-connector.md:202`): non sarà più vero.
- `BEC/core/queue_eta.py` — la stima dei tempi conta una chiamata per contenuto: con i pezzi non vale più.
- `BEC/core/tests/test_mcp_tools.py:513-515` — afferma i tagli 6000 / 8000 / 3000.

**Documentazione nello stesso commit**: `01-data-model.md` (campo e diagramma); `02-pipeline.md`
(stadi `enrich` e `knowledge`, comando nuovo, i tre livelli del lucchetto locale, stima dei tempi); `06-frontend.md` (riquadro in Avanzamento); `03-llm-and-embeddings.md` («What
the document analysis reads» riscritta, limiti noti); `04-mcp-connector.md` (nota, affermazioni,
righe 202-219); `.claude/architecture-summary.md` (riga del limite 6.000 / 8.000 / 3.000); pagina
`Documentazione` in parole del cliente («leggiamo tutto il testo; i contenuti vecchi si stanno
rifacendo, la nota dice quali mancano»); pagina tecnica del drawio; docstring dei moduli.

**Test** (risposte finte, nessuna chiamata a Groq né a Ollama)
- taglio: mai a metà parola; a fine frase quando c'è; i pezzi rimessi insieme danno il testo identico; testo senza punteggiatura; 8.000 esatti = strada corta, 8.001 = pezzi;
- una citazione vera del pezzo 3 viene tenuta, una inventata scartata, una che sta in un altro pezzo scartata;
- due pezzi con la stessa affermazione → una sola; tetto rispettato; le affermazioni tenute vengono da pezzi diversi;
- pezzo 2 di 3 con JSON rotto o tagliato → contenuto `failed`, niente salvato, analisi vecchia intatta;
- modello non disponibile a metà → `pending`, non `failed`;
- `nota_analisi`: presente con `pending` e testo lungo, assente con `done`, presente con `failed`;
- migrazione: testo corto → `done`, lungo → `pending`;
- rifacimento: non riprende i `done`; non riprende i `failed` senza `--ritenta-falliti`; non chiama mai Groq; con un giro in corso non prende il modello e riparte quando finisce; interruttore spento → si ferma dopo la chiamata in corso; due copie insieme → la seconda esce; rilanciato continua; rispetta l'ordine dei gruppi; `owner_type` non cambia mai; dopo il rifacimento il vettore è da ricalcolare;
- il prompt dell'analisi di un articolo corto resta uguale a oggi alla lettera (test esistente).

**Rischi**
- **Qualità del riassunto fatto dagli appunti** invece che dal testo: non provata, né su Groq né
  sul 7b. È il rischio principale: per questo i primi 17 si guardano a mano.
- **Regola owned/competitor**: non la sfioro. Ogni chiamata lavora un contenuto solo; pezzi e
  appunti non escono dal loro contenuto; il comando non tocca `owner_type`.
- Il 7b può ignorare «massimo 3» o «massimo 25 parole»: più token, niente di rotto.
- Più chiamate per contenuto = più occasioni di un `failed` (un pezzo su 15 basta). I `failed`
  storici per JSON tagliato sono stati 143: va guardato il numero dopo il primo gruppo.
- Un giro notturno con un video nuovo da 85.000 caratteri fa 16 chiamate invece di 2: se Groq è
  finito, sul 7b è circa un'ora.
- Le affermazioni cambiano per tutti i contenuti rifatti: il cliente può non ritrovare una frase
  che ricordava.
- Il limite del minuto di Groq: se conta anche il tetto di risposta, un pezzo chiede ~3.300 token
  su 8.000. Regge, ma non è verificato sul nostro conto.

**Alternative scartate**
- *Una richiesta sola a Groq per i testi lunghi* (la finestra c'è): il limite di 8.000 token al
  minuto la rifiuta, e se cade sul 7b non entra in 8.192.
- *Soglie diverse per Groq e per il 7b*: chi risponde si sa solo a chiamata fatta.
- *Pezzi con sovrapposizione*: crea affermazioni doppie; il taglio a fine frase basta.
- *Due passate sui pezzi* (una per il riassunto, una per le affermazioni): quasi il doppio di lettura.
- *Strada lunga anche per i testi corti*: cambierebbe tutte le analisi nuove senza motivo.
- *Salvare i pezzi a metà in una tabella*: più codice e una tabella in più per risparmiare poco.
- *Alzare la finestra del 7b a 16.384*: leggere 9.000 token in un colpo sono 10-12 minuti e i
  modelli piccoli perdono il centro dei testi lunghi (rapporto di ricerca).

#### L. Domande per Giuseppe (testo intero)

Già decise da Giuseppe e messe nel disegno: Groq a pagamento no; il rifacimento gira sul 7b
locale giorno e notte; la durata in giorni non è un problema.

1. **Quante affermazioni per un testo lungo?** *Raccomando fino a 12*, scelte da tutti i pezzi. Con
   6 una puntata di un'ora resterebbe coperta a metà. Va deciso prima del giro 1.
2. **Ci fermiamo dopo le 17 puntate per leggerle**, prima di rifare il resto con il 7b? *Raccomando
   sì*: è l'unica prova di qualità del 7b su questo compito, e cambiare idea dopo costa giorni.
3. **Rifacciamo anche i fuori tema** (479 contenuti, ~73-85 ore, nascosti da ricerca e temi)?
   *Raccomando sì, per ultimi*: il giudizio «fuori tema» era stato dato leggendo solo l'inizio, e una
   puntata che apre con gli sponsor può essere stata giudicata male. La loro nota resta vera finché non tocca a loro.
4. **Va bene che riassunto e affermazioni rifatti cambino** (e siano scritti dal 7b al posto di
   Claude o di Groq), e che qualche contenuto cambi tema o entri/esca dalla ricerca? *Raccomando sì*,
   dicendolo al cliente nella pagina Documentazione.
5. **Il riquadro in Avanzamento sta nella PR 1 o subito dopo?** *Raccomando nella PR 1*: è il modo
   di vedere a che punto è un lavoro di due settimane. Senza, resta solo la riga della chiamata in corso.
6. **Le bozze di blog** (`blog_workflow`) tagliano a 12.000 e 4.000 caratteri senza dirlo. *Raccomando
   una PR a parte, dopo*, e di scriverlo subito nei limiti noti.

### 2.0b In tre righe (disegno del mattino: passi 2, 3, 4)

L'ordine delle PR qui sotto (§2.6) è superato da §2.0-H. Il resto vale.


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

## Decisione di Giuseppe (16/11/2026, dopo il reset dei limiti)

«In questa branch inizia il lavoro con Haiku, fai tutte le trascrizioni, quindi non andare
sul modello locale, e quindi poi restituiscimi l'outcome. Una volta fatto faccio una merge
request [...] uso il modello di Claude Haiku della mia subscription»

Vale come OK al disegno, con queste modifiche (capo):

- **Rifacimento del pregresso = eccezione una tantum con Claude Haiku** (abbonamento di
  Giuseppe), non con il 7b. Il giro di ogni giorno resta Groq + 7b, niente Anthropic.
  L'eccezione si scrive nella documentazione.
- Haiku fa da «modello»: legge i prompt veri della pipeline sul testo intero e scrive la
  risposta grezza in file (`/home/medyca-admin/medycabrain-rianalisi/`, fuori da git).
  **Nessuna scrittura sul database prima del merge e della conferma di Giuseppe.**
- Il caricamento lo fa un comando nuovo della PR (`import_reanalysis`), che passa ogni
  risposta dallo **stesso parser e dallo stesso salvataggio della pipeline**, controlla
  le citazioni, scrive in una transazione per contenuto e segna `full_text_status=done`.
- Esce dalla PR 1: il comando `reanalyze_whole` sul 7b, il lucchetto a tre livelli, il
  riquadro in Avanzamento. Restano: testo intero nella pipeline per i contenuti nuovi
  (a pezzi sul 7b), campo + migrazione, `nota_analisi`, affermazioni fino a 12 sui testi
  lunghi, sosta di lettura dopo le puntate (Giuseppe le legge dopo il caricamento).
