---
id: 2026-11-14-analisi-in-casa
titolo: Tutti i modelli sul VDS, nessun fornitore esterno (PR 2 di "pipeline in casa")
stato: disegno
ramo: feat/analisi-in-casa
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Parole di Giuseppe (13/11/2026, appena passati al nuovo VDS):

> now we have IProyal and a new VDS which is superpowerful despite it's only CPU,
> who cares we can find optimization to run our LLM there even though the token
> per second are slow. [...] I don't want to use the Anthropic API call and the
> Apify stuff because I have a powerful machine that I can run my process on.

Il 14/11/2026, letto il primo disegno
(`.claude/tasks/2026-11-14-pipeline-in-casa.md`) e le domande aperte, Giuseppe
ha risposto:

> Shifta tutto locale

Lettura del capo (registro del primo file, non parole di Giuseppe): nessun
fornitore esterno di modelli. Sul VDS vanno analisi (`enrich`, `knowledge`),
nomi dei temi (`cluster`), `blogscrape`, chat, ricerca MCP, strategia, piano
editoriale, ideazione, bozze blog e trascrizione. Gli embedding sono già
locali. La PR 1 (raccolta senza Apify) è approvata e resta com'è, sul ramo
`feat/pipeline-in-casa`.

Scelte già chiuse nel registro del primo file, che valgono anche qui: niente
strada "profonda" di Instagram; due letture al giorno; il codice di Apify resta
spento; il recupero del buco di 12 giorni si fa **dopo** questo lavoro.

## 2. Disegno            (architetto)

I fatti del primo disegno sono citati come «fatto N (primo file)» e non
ricopiati. Le misure nuove sono del 14/11/2026 tra le 20:00 e le 20:50, su
questo VDS, con Ollama libero (controllato con `/api/ps` prima di ogni prova).

### In sei righe

1. **Si può fare, ma la macchina è lenta per questo lavoro**, e va detto prima:
   la chat locale non è più una chat. Oggi, senza modifiche, una risposta
   chiede 6-8 minuti e la pagina la uccide a 5: **sarebbe rotta**.
2. **Con le modifiche proposte**: le fonti in 3 secondi, la prima parola in
   circa 1-2 minuti, la risposta finita in 2-4 minuti. Sopportabile per
   "chiedo e aspetto", non per conversare.
3. **La trascrizione in casa è la parte più pesante che non avevamo misurato.**
   Il Whisper piccolo già installato va a tempo reale (10 minuti di audio in
   10 minuti). Quello buono (stima) ci mette da 1,5 a 7 volte la durata.
4. **Il modello 3b non si può usare**: la sua licenza è «solo ricerca, non
   commerciale». È quello scritto oggi nel `.env`.
5. **Un interruttore solo nel `.env`** (`LOCAL_ONLY`). Acceso: nessuna chiamata
   esce. Spento: tutto torna come oggi, in un minuto.
6. **Tre PR**: fondamenta e prova di qualità; poi la parte per le persone
   (chat a flusso, precedenza, messaggi); poi la pulizia. L'interruttore si
   gira solo dopo le prime due e dopo che Giuseppe ha letto la prova.

### Fatti misurati oggi

**Trascrizione** (faster-whisper 1.0.3, modello `small` int8, l'unico in
cache: `ls ~/.cache/huggingface/hub`; script di prova in sola lettura su due
mp3 veri di `media/audio/`)

1. Reel da 61 secondi: **38 s con 4 thread, 35 s con 6 thread**. Con 12
   thread non aveva finito dopo 5 minuti e l'ho fermato: stesso difetto di
   Ollama (fatto 16 e nota in `~/brain`), il tetto è la memoria.
2. Video da 576 secondi (9 min 36 s): **589 secondi con 6 thread**. Cioè tempo
   reale. Il reel corto va a 0,58 volte la durata, quello lungo a 1,02: non so
   spiegare la differenza (la macchina non era del tutto ferma: carico 2,5
   prima della prova).
3. Memoria del processo: 0,9 GB sul corto, 1,4 GB sul lungo. Primo caricamento
   11 secondi.
4. Il `small` sbaglia le parole: nel campione ha scritto «molecole che vengono
   protettate le muscoli». È il difetto già noto (`transcriber_agent.py`:
   «umonibirentici»).
5. Durata dell'audio nel database (`transcripts.audio_duration_s`, 1473
   righe): metà dei reel dura meno di 67 secondi; negli ultimi 75 giorni
   mediana 63 s, 90° percentile 192 s, **media 289 s** per colpa di pochi
   video lunghi (157 righe oltre i 30 minuti fanno 157 ore su 193 totali).
6. Upload del cliente (`uploaded_media`): 14 video riusciti, **media 22
   minuti**, massimo 33; tutti tra il 13 e il 15/9 (5,1 ore di audio in tre
   giorni). Altri 3 falliti il 13/11.
7. `large-v3` e `large-v3-turbo` **non sono in cache**: non li ho scaricati,
   quindi i loro tempi qui sotto sono stime.

**Chat** (prompt veri costruiti con `knowledge._prepare` su una domanda vera,
senza chiamare nessun modello; poi mandati a Ollama a mano: 6 thread, finestra
8192; niente scritto nel database)

8. Il prompt della chat con 8 fonti pesa 8597 caratteri, **2581 token**. Con 4
   fonti 1642. Il riordino della ricerca (`_rerank`) 1174. Il piano editoriale
   circa 1300 in lettura e fino a 3600 in scrittura.
9. Tempi:

   | Modello | Prova | Prima parola | Risposta finita | Note |
   |---|---|---|---|---|
   | 7b | 8 fonti, modello freddo | **4 min 49 s** | **7 min 52 s** | 96 s di caricamento, 192 s a leggere, 183 s a scrivere 452 token |
   | 7b | 8 fonti, modello caldo | circa 3 min 13 s | circa 6 min 15 s | calcolato togliendo il caricamento |
   | 7b | 4 fonti, regole già in memoria | **52 s** | 3 min 47 s | tagliata al tetto di 500 token |
   | 3b | 8 fonti, freddo | 1 min 59 s | 4 min 41 s | **nessuna citazione [n]** nella risposta |
   | 3b | 4 fonti | 31 s | 2 min 8 s | tagliata al tetto di 350 token |
   | 3b | riordino della ricerca | - | 52 s | ha restituito 14 indici su 15 |
   | 3b | stessa domanda ripetuta | 1 s | 2 min 50 s | il prompt identico non viene riletto |

   Velocità in chat: il 7b legge 13,4 token/s e scrive 2,5-2,9 (più lento del
   fatto 17, perché il contesto è più lungo); il 3b legge 29 e scrive 3,1-3,6.
10. **La pagina aspetta al massimo 300 secondi** (`FEC/src/api/knowledge.ts`
    riga 110; Gunicorn `--timeout 300`). La risposta del 7b ne chiede 376-472:
    la persona vedrebbe un errore, sempre.
11. **Il pezzo di prompt uguale non viene riletto** (riga «ripetuta»): le
    regole fisse della chat (1737 caratteri) costano una volta sola, *se* la
    chiamata prima sullo stesso modello era anch'essa una chat.
12. **Lasciare il modello in memoria conta**: Ollama lo scarica dopo 5 minuti
    di silenzio e ricaricare il 7b costa 96-123 secondi. Con il 7b caricato a
    finestra 8192 la memoria occupata è 5,5 GB; la macchina ne ha 82 liberi.
13. **nginx è già pronto per la chat a flusso**: esiste il blocco
    `location = /api/v1/knowledge/ask/stream/` con `proxy_buffering off` e 600
    secondi. Manca il codice: `urls.py` ha solo `knowledge/ask/` e
    `answer_stream` è citato in un commento ma non esiste.
14. **Solo 3 chiamate su 16 chiedono la precedenza** (`priority=True`: chat,
    brief, bozza di strategia). Ideazione, piano editoriale e bozze blog no.
15. **Quanto si usano le funzioni interattive**: strategia ultimo lavoro il
    27/7, piano editoriale il 4/8, ideazione il 24/7, bozza blog il 27/7
    (tabella `jobs`). Chat: 38 domande in 20 giorni tra luglio e agosto, mai
    più di 9 in un giorno (`logs/access.log`, che si ferma ad agosto). Dal
    13/11 `llm_calls` ha 0 righe. Il log di nginx non lo posso leggere.
16. **Licenze** (`/api/show` di Ollama): il 7b è Apache 2.0. Il **3b è «Qwen
    Research License»: «for non-commercial purposes only»**. Non sono un
    avvocato, ma il testo è chiaro: per un cliente non va usato.
17. **`chat()` riprova tre volte anche gli errori locali**: un «modello
    occupato» dopo 900 secondi di attesa viene ritentato, quindi fino a 45
    minuti prima di fallire (`client.py`, ultimo `except`).
18. La pagina Stato mostra i nomi dei modelli leggendo le impostazioni remote
    (`core/ops.py`, `models()`): con tutto in casa direbbe ancora
    `whisper-large-v3` remoto.
19. I nomi dei temi nuovi sono pochi: 0-4 a notte negli ultimi quattro giri
    (i temi vecchi riusano il nome). Lo stadio `cluster` oggi dura 74 secondi.

### 1. Trascrizione in casa

**Proposta: faster-whisper** (già installato e già usato come riserva), non
whisper.cpp: andrebbe compilato, e su questa macchina il limite è la memoria,
non il programma (stima, non misurata).

| Modello | Reel da 1 minuto | Video da 10 minuti | Upload da 22 minuti | Memoria | Stato |
|---|---|---|---|---|---|
| `small` | 35 s (misurato) | 9 min 49 s (misurato) | circa 22 min | 0,9-1,4 GB (misurato) | installato; sbaglia i termini medici |
| `large-v3-turbo` | 1,5-3,5 min (stima) | 15-35 min (stima) | **35-75 min** (stima) | circa 2,5 GB (stima) | da scaricare, 1,6 GB |
| `large-v3` | 4-7 min (stima) | 45-75 min (stima) | **1,5-2,5 ore** (stima) | 3,5-4,5 GB (stima) | da scaricare, 3,1 GB |

Come ho fatto la stima: il `large` ha 7,4 volte i calcoli del `small`; il
`turbo` ha lo stesso "orecchio" del large ma una "bocca" piccola, quindi 2,5-3,5
volte il small. Moltiplicato per i tempi misurati (fatti 1 e 2). **Serve l'OK
di Giuseppe per scaricare i due modelli**; poi 20 minuti di prova sostituiscono
la stima.

- **Quale**: propongo `large-v3-turbo`, **se** passa la prova (sotto). Il
  `large-v3` è quello di oggi su Groq, quindi la qualità più sicura, ma un
  upload da mezz'ora chiederebbe fino a 4 ore.
- **Thread**: 6 (`WHISPER_CPU_THREADS`, oggi 4).
- **Convivenza con Ollama**: la memoria non è un problema (Whisper 2,5-4,5 GB
  + 7b 5,5 GB + il resto: meno di 20 GB su 94). Il problema è che due lavori
  pesanti insieme vanno tutti e due a metà velocità. Quindi **Whisper prende lo
  stesso lucchetto di Ollama** (`_ollama_slot`), un pezzo di audio alla volta
  (circa 30 secondi, come li produce già faster-whisper): tra un pezzo e
  l'altro lascia passare una persona che aspetta. Attesa massima dietro una
  trascrizione: 1-2 minuti con il turbo, fino a 4 con il large (stima).
- **Upload del cliente**: la barra può finalmente muoversi davvero (secondi
  trascritti su secondi totali). Il testo «può richiedere diversi minuti»
  diventa «circa N minuti», calcolato sulla durata.
- I 1460 testi già trascritti da Groq **non si rifanno**.

### 2. Chat e funzioni interattive

**Cosa succede senza fare niente**: la chat fallisce sempre (fatto 10). Se in
quel momento gira la pipeline, prima aspetta la fine della chiamata in corso
(fino a 6 min 40 s, fatto 17 del primo file), poi il riordino (circa 1 min 45 s
sul 7b, stima), poi la risposta: **fino a 14-15 minuti**.

**Cosa propongo**, in ordine di quanto aiuta:

1. **Le fonti subito, le parole dopo.** La ricerca è locale e dura 3 secondi.
   La pagina mostra subito le fonti trovate; la risposta scritta arriva sotto,
   parola per parola (flusso). Mentre aspetta, la pagina dice la verità: «in
   coda dietro la pipeline», «sto leggendo le fonti», poi il testo.
2. **Niente riordino con il modello** quando è tutto in casa: la ricerca usa
   l'ordine "per significato + parole" che è già la riserva di oggi. Toglie
   1-2 minuti alla chat e rende **la ricerca MCP immediata** e indipendente dal
   modello. Costo: precisione un po' più bassa, non misurata (si misura con
   `eval_mcp`, che esiste già, una volta, prima di spegnere).
3. **Prompt più corto e risposta più corta**: 4 fonti invece di 8, e la
   lunghezza chiesta nel prompt («al massimo 150 parole»). Il solo tetto di
   token non basta: taglia la frase a metà (fatto 9, due risposte tagliate).
4. **Le persone passano davanti, subito.** Oggi la precedenza vale solo tra
   una chiamata e l'altra. Proposta: quando arriva una persona, la chiamata
   della pipeline in corso si interrompe, cede il posto e si rifà dopo (non è
   un fallimento: è un rinvio, al massimo 3 volte, poi `failed` con il suo
   nome). Si butta fino a 6 minuti di lavoro per ogni domanda: con poche
   domande al giorno è niente. **Da provare in sviluppo**: quanto ci mette
   Ollama a liberarsi quando si chiude la connessione. Se non si libera in
   fretta, si resta alla precedenza di oggi.
5. **Il modello resta in memoria** (`keep_alive`), così non si paga il
   caricamento.
6. **La pipeline lavora di notte.** Giro completo alle 22:00 (oggi 03:30). Il
   giro delle 14:15 fa solo raccolta e download (minuti, nessun modello). Le
   letture restano due al giorno; i reel del pomeriggio si vedono analizzati
   la mattina dopo.
7. **Modello piccolo per la chat**: il 3b è escluso (licenza, e nella prova
   non ha citato le fonti). Un modello piccolo con licenza libera va scaricato
   e provato (domanda 2). Senza, la chat usa il 7b.

**Quanto aspetta una persona, dopo le modifiche** (7b, 4 fonti; in parte
misurato, in parte calcolato dalle velocità misurate):

| | Fonti | Prima parola | Risposta finita |
|---|---|---|---|
| Seconda domanda di fila | 3 s | circa 50 s (misurato 52) | circa 2 min |
| Prima domanda della giornata | 3 s | circa 2 min | circa 3-3,5 min |
| Mentre gira la pipeline, con l'interruzione | 3 s | circa 2 min + 10 s | circa 3,5 min |
| Mentre gira la pipeline, **senza** interruzione | 3 s | fino a 8-9 min | fino a 10 min |

**Le altre funzioni** (tutte lavori in sottofondo con barra, non richieste
dirette; tempi stimati sul 7b a 2,5-2,9 token/s):

| Funzione | Scrive fino a | Tempo stimato | Giudizio |
|---|---|---|---|
| Brief di strategia | 900 token | 6-8 min | lento ma usabile |
| Bozza da brief | 1200 token | 8-10 min | lento ma usabile |
| Ideazione | 1200 token, JSON | 7-9 min | usabile; **la pagina chiama con attesa massima di 300 s: da verificare in sviluppo se è una richiesta diretta, nel qual caso fallisce** |
| Bozze blog (3 passi) | 1200-1600 token | 8-10 min a passo | lento; qualità di scrittura non provata |
| Piano editoriale | 3600 token, JSON | circa 20-25 min | **a rischio**: un JSON così lungo da un 7b è facile che esca rotto |
| Trascrizione di un upload | - | 35-75 min per 22 min di video (turbo, stima) | usabile solo come "carico e torno" |

I testi «di solito 30-60 secondi» in `strategy.py` ed `editorial.py`
diventano falsi e vanno cambiati. Il modello locale manda i token uno alla
volta, quindi la barra può avanzare davvero.

**Detto chiaro: cosa diventa inutilizzabile se le modifiche non bastano.**
- La **chat come conversazione**: anche nel caso migliore è «chiedo, aspetto 2
  minuti». Se la prova di qualità boccia le risposte (fonti di Medyca e dei
  competitor confuse), la chat resta in modalità «solo fonti», senza testo.
- Il **riordino della ricerca MCP**: spento comunque.
- Il **piano editoriale**: probabile che fallisca spesso. Si vede nella prova.
- Tutto ciò che è **scrittura lunga in buon italiano** (bozze, brief): il 7b
  scrive, ma non è Claude. Non misurato.

Una cosa da sapere: il connettore MCP serve proprio a far leggere la banca
dati al Claude del cliente. Quella resta la chat migliore che ha, e non passa
da noi: è il suo abbonamento. «Tutto locale» riguarda la piattaforma, non
quello.

### 3. Quale modello per quale compito

| Compito | Proposta | Perché |
|---|---|---|
| Analisi di reel e articoli, affermazioni | 7b (o uno più grande se la prova lo chiede) | è dove un modello debole costa significato |
| Nomi dei temi | lo stesso dell'analisi | pochi a notte; li legge il cliente |
| Riconoscere gli articoli (`blogscrape`) | 7b | raro |
| Riordino ricerca | nessun modello | vedi sopra |
| Chat | 7b, o un modello piccolo libero se passa la prova | conta la prima parola |
| Strategia, piano, ideazione, bozze | 7b | rari, in sottofondo |
| Trascrizione | `large-v3-turbo` (o `large-v3`) | vedi sopra |

Oggi il codice conosce **un solo** modello locale (`OLLAMA_MODEL`). Servono
tre impostazioni in più, una per tipo di lavoro, più una per la chat; vuote
usano `OLLAMA_MODEL`.

**Modelli da scaricare, solo con l'OK**: uno più grande per l'analisi (12-14
miliardi di parametri, circa 8-9 GB) e uno piccolo libero per la chat (circa
4 miliardi, 3 GB). Stima per quello grande: metà della velocità del 7b, cioè
circa 14 minuti a reel e il doppio delle ore. I nomi esatti si scelgono al
momento dello scaricamento, guardando la licenza prima (fatto 16).

**La prova di qualità: `manage.py eval_local`** (comando nuovo, non scrive
nelle tabelle dei contenuti; rapporto in `logs/evals/`, come `eval_mcp`).
Riferimento: le analisi già salvate fatte da Claude.

| Cosa | Come si misura | Soglia per dire «si accende» |
|---|---|---|
| Analisi: 30 reel + 20 articoli, metà Medyca metà competitor, corti e lunghi | JSON valido e completo | almeno 49 su 50 |
| | tema uguale o vicino al riferimento (vicinanza dei vettori, più tabella affiancata che Giuseppe legge) | almeno 40 su 50 |
| | tema "ombrello" («menopausa», «salute femminile») | al massimo 2 su 50 |
| | citazioni vere su citazioni proposte | almeno 70% |
| | affermazioni salvate rispetto al riferimento | almeno 60% |
| Nomi dei temi: 20 temi | nome valido, non generico; Giuseppe li legge | nessuna soglia numerica: decide lui |
| Chat: 10 domande fisse | fonti di Medyca e competitor **mai scambiate** (lettura a mano) | 0 scambi su 10, altrimenti «solo fonti» |
| | risposta con citazioni [n], in italiano | almeno 9 su 10 |
| Piano editoriale: 3 prove | JSON valido | 3 su 3, altrimenti la funzione mostra un avviso |
| Trascrizione: 10 reel + 1 upload | parole diverse dal testo di Groq già salvato | al massimo 10% |
| | termini del glossario scritti giusti | almeno 95% |
| Tempo | secondi per contenuto | giorno tipico sotto 6 ore |

Le soglie sono una mia proposta: non c'è una misura precedente su cui
tararle. Macchina per la prova: circa 5 ore per modello sull'analisi, 1 ora
la chat, 2-3 ore la trascrizione (stime). Una o due notti.

### 4. Come si spegne l'esterno

**Un interruttore: `LOCAL_ONLY=1` nel `.env`.** Letto in pochi punti:

- `client._providers()` restituisce solo il modello locale, qualunque cosa
  dicano `LLM_PROVIDER_ORDER` e `LLM_ENDPOINTS`. Escono dalla catena
  `anthropic`, `groq`, `flow` (e `hf`, già dormiente).
- `model_for()` restituisce il modello locale di quel tipo di lavoro.
- `transcriber_agent._transcribe` salta Groq Whisper.
- `batch.available()` dice no: lo stadio `batch` risulta «non configurato»,
  come già previsto.
- **Cintura**: con l'interruttore acceso, le funzioni che parlano con
  l'esterno (`_fast_chat`, `_anthropic_chat`, `_hf_chat`, `transcribe_audio`)
  rifiutano di partire. Un test controlla che nessuna richiesta esca verso un
  indirizzo diverso da Ollama.

**Quando il locale fallisce, senza riserva:**

| Dove | Cosa succede | Cosa vede la persona |
|---|---|---|
| Pipeline, una chiamata | il contenuto resta `failed` con la causa vera («risposta locale tagliata dopo N secondi», «attesa scaduta») | pagina Avanzamento e Stato |
| Pipeline, Ollama spento | lo stadio si ferma dicendolo; i contenuti restano `pending` perché non sono stati provati | nota dello stadio: «modello locale non raggiungibile» |
| Chat | le fonti arrivano comunque | «Il modello non risponde. Qui sotto le fonti trovate.» Oggi vedrebbe `(Errore nella generazione: LLMError(...))` |
| Ricerca MCP | non usa più il modello | niente |
| Strategia, piano, bozze | il lavoro è `failed` | messaggio in chiaro e «Riprova» (c'è già) |
| Upload | `failed` | messaggio e «Riprova» (c'è già) |

Nessuno viene avvisato di notte: si vede la mattina su Stato, dove propongo
una riga fissa «Modelli: tutto sul VDS · ultimo errore». Avvisi via email:
fuori.

**Tornare indietro in un minuto**: `LOCAL_ONLY=0` e riavvio dei due servizi.
Funziona **solo finché la chiave di Groq resta nel `.env`**. Proposta: resta
per due settimane dopo l'accensione, poi si toglie (PR di pulizia). La chiave
morta di Anthropic e il rivenditore `flow` escono subito da `LLM_ENDPOINTS`.

### 5. Correzioni, recupero, ore-macchina

**Correzioni** (le cinque del primo disegno, confermate, più quattro nuove):

1. Finestra: `OLLAMA_NUM_CTX=8192` (la chat da 2581 token più risposta ci sta).
2. Tempi di attesa: silenzio ammesso da 120 a 600 s; tetto della risposta per
   la pipeline 1500 s; risposta tagliata = errore con il suo nome.
3. Un filo solo in `enrich` e `knowledge` quando è tutto locale.
4. Lucchetto «un giro alla volta» in `run_pipeline` e nel giro a mano.
5. Tetto per giro: `PIPELINE_LOCAL_MAX_ITEMS=40`; il resto resta `pending`.
6. **Nuova**: `keep_alive`, il modello resta in memoria.
7. **Nuova**: niente secondo tentativo su «occupato» e su «tagliata» (fatto 17).
8. **Nuova**: Whisper sotto lo stesso lucchetto, a pezzi.
9. **Nuova**: l'attesa del lucchetto per la pipeline sale da 900 a 3600 s
   (dietro un upload lungo non deve fallire).

**Recupero** (dopo l'accensione, mai in automatico; con il tetto di 40 a notte):

| Lavoro | Ore-macchina (7b + turbo) | Note |
|---|---|---|
| In attesa oggi (35 affermazioni, 1 reel, 6 trascrizioni) | circa 2 h | |
| Buco di 12 giorni, circa 61 reel | 10-19 h | 7 h di analisi; la trascrizione va da 3 a 12 h a seconda di quanti video lunghi ci sono |
| I 310 falliti, **solo con l'ordine di Giuseppe** | circa 18 h | cause scritte: risposta tagliata (142) e attesa scaduta (81). Sono difetti della macchina, non dei contenuti |
| **Totale** | **30-39 h**, circa 6-8 notti | |

**Un giorno tipico, tutto in casa** (stime costruite sulle misure):

| Lavoro | 7b + turbo | 7b + large-v3 |
|---|---|---|
| Analisi: 8 reel + 11 articoli | 1,9 h | 1,9 h |
| Nomi dei temi (0-4) | 0-0,15 h | 0-0,15 h |
| Trascrizione di 8 reel (9-39 minuti di audio) | 0,2-2,3 h | 0,6-4,9 h |
| Chat: 2-9 domande | 0,1-0,6 h | 0,1-0,6 h |
| Upload del cliente, in media | 0,1-0,25 h | 0,3-0,7 h |
| **Totale** | **2,3-5,2 h, tipico circa 3** | **2,9-8,2 h, tipico circa 4,5** |

Con un modello di analisi più grande: 1,9 ore in più. Giorni con tanti upload
(come il 13-15/9: 5,1 ore di audio) chiedono da soli 8-18 ore con il turbo.
Dopo la prima settimana questi numeri si sostituiscono con quelli veri di
`llm_calls`.

### 6. Tre PR, in quest'ordine

**PR A - Fondamenta e prova** (`feat/analisi-in-casa`, questo file). Con
`LOCAL_ONLY=0` non cambia niente di ciò che fa la piattaforma.

| File | Perché |
|---|---|
| `BEC/llm/client.py` | interruttore in `_providers()`, `model_for()`, `available()`; cintura sulle funzioni esterne; modello locale per tipo di lavoro; `num_ctx`, `keep_alive`, tempi; errore chiaro sulla risposta tagliata; niente secondo tentativo su «occupato» |
| `BEC/llm/batch.py` | `available()` falso con l'interruttore |
| `BEC/pipeline/agents/transcriber_agent.py` | salta il remoto; lucchetto a pezzi; nome vero del modello nel testo salvato |
| `BEC/pipeline/agents/enrich_agent.py`, `knowledge_agent.py` | un filo; tetto per giro |
| `BEC/core/management/commands/run_pipeline.py`, `BEC/core/pipeline_run.py` | un giro alla volta |
| `BEC/core/management/commands/eval_local.py` (nuovo) | la prova |
| `BEC/core/ops.py` | `models()` dice i modelli veri (fatto 18) |
| `BEC/core/queue_eta.py` | solo se la stima «quanto manca» risulta falsa: da guardare in collaudo |
| `BEC/config/settings/base.py`, `BEC/.env.example` | `LOCAL_ONLY`, `OLLAMA_MODEL_ANALYSIS/_REASONING/_BULK/_CHAT`, `OLLAMA_NUM_CTX`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_PIPELINE_TIMEOUT`, `PIPELINE_LOCAL_MAX_ITEMS`, `WHISPER_CPU_THREADS=6` |
| test: `test_ollama_options.py` (esteso), `test_local_only.py` (nuovo) | nessuna richiesta esce; `num_ctx` e `keep_alive` nel payload; tagliata = errore; secondo giro rifiutato; tetto lascia `pending` |
| `documentation/low-level/03-llm-and-embeddings.md`, `02-pipeline.md`, `.claude/architecture-summary.md`, `CLAUDE.md`, drawio pagina 2 | chi fa cosa, tempi misurati, limiti |

Poi: scaricamenti approvati, `eval_local` di notte, Giuseppe legge il rapporto.

**PR B - Le persone** (ramo e file di lavoro suoi, li apre il capo).

| File | Perché |
|---|---|
| `BEC/core/knowledge.py` | `answer_stream` (usa `_prepare`, nato per questo); in locale 4 fonti, niente riordino, risposta corta; frasi d'errore in chiaro; modello della chat |
| `BEC/core/views.py`, `BEC/core/urls.py` | `knowledge/ask/stream/` (nginx c'è già, fatto 13) |
| `BEC/llm/client.py` | interruzione della chiamata di pipeline quando arriva una persona |
| `BEC/core/strategy.py`, `editorial.py`, `ideation.py`, `blog_workflow.py` | precedenza su tutte (fatto 14), barra vera, testi sui tempi |
| `BEC/core/upload_workflow.py` | barra vera della trascrizione |
| `FEC/src/api/knowledge.ts`, `FEC/src/pages/KnowledgeBank.tsx`, pagina Stato, pagina `Documentazione` | fonti subito, testo a flusso, stati «in coda / legge / scrive», riga dei modelli |
| `documentation/low-level/05-rest-api.md`, `06-frontend.md`, `04-mcp-connector.md`, drawio pagina 1 | endpoint nuovo, ricerca MCP senza riordino, tempi detti al cliente |

**Accensione**: la fa il rilasciatore, chiedendo conferma, solo con A e B fuse
e la prova letta: `LOCAL_ONLY=1`, i modelli scelti, `BATCH_ENABLED=0`, crontab
(22:00 giro completo; 14:15 solo `scrape,download`).

**PR C - Pulizia**, dopo due settimane tranquille: via le chiavi dal `.env`,
via il codice spento che Giuseppe vuole togliere.

**Cosa si riusa**: `_ollama_slot` e la sua precedenza; `on_token` e il flusso
di `_ollama_chat` (già scritti, mai arrivati alla pagina); `_prepare`;
`usage.scope` e `llm_calls` per i tempi veri; `ctx.limit` come modello per il
tetto; `eval_mcp` come stampo per `eval_local`; `build_enrich_prompt`,
`build_doc_enrich_prompt`, `build_doc_arguments_prompt` e il controllo delle
citazioni; il blocco nginx esistente; il «Riprova» dei lavori e degli upload.

### Rischi

- **`owner_type`**: nessun valore nuovo, nessuna scrittura nuova. Ma il
  rischio vero si sposta nella chat: un modello piccolo può attribuire a
  Medyca una frase di un competitor. È l'errore che il progetto considera il
  peggiore, e nella prova è l'unica soglia a zero.
- **I falliti restano `failed`**: l'interruzione per precedenza e il tetto per
  giro lasciano `pending` solo ciò che non è stato provato fino in fondo. Va
  nel test, perché è il punto dove sarebbe facile "azzerare in silenzio".
- **Credenziali**: nessuna nuova. Escono Anthropic e `flow` subito, Groq dopo
  due settimane.
- **Nessuna riserva.** Se Ollama cade, o il VDS è occupato, tutto si ferma
  finché qualcuno guarda. Oggi Groq copriva.
- **Qualità non dimostrata.** Su 3 contenuti il 7b ha dato temi più generici
  e inventato citazioni (fatto 18 del primo file). Il corpus avrà due mani:
  1617 reel letti da Claude e Groq, i nuovi dal 7b. Se la prova boccia il 7b e
  anche il modello più grande, **«tutto locale» non regge per l'analisi** e
  Giuseppe deve scegliere (domanda 3).
- **Trascrizione stimata, non misurata.** Se il turbo sbaglia i termini medici
  si va sul `large-v3`: un upload da mezz'ora chiede fino a 4 ore, e i giorni
  con molti upload fanno la coda.
- **La chat peggiora molto**, e si vede: da pochi secondi a minuti, con meno
  fonti e senza riordino.
- **L'interruzione per precedenza non è provata.** Se Ollama non si libera
  subito, una domanda fatta durante un giro aspetta fino a 10 minuti.
- **Licenza del 3b**: va tolto da `OLLAMA_MODEL` anche se resta tutto com'è.
- **Macchina condivisa**: i tempi misurati oggi cambiano del 70% tra una
  prova e l'altra (fatto 2). Le ore al giorno sono forbici, non promesse.

### Cosa resta fuori

- Il Claude del cliente che legge via MCP: è una scelta sua, non passa da noi.
- Rifare le 1460 trascrizioni e le analisi già fatte.
- Risposte in parallelo di Ollama (serve `sudo`), GPU, un secondo server.
- Avvisi via email quando il modello cade.
- Cancellare il codice di batch, Anthropic, Groq, Apify: PR C, se Giuseppe vuole.
- whisper.cpp.
- Spostare le regole fisse in testa ai prompt di analisi per non rileggerle
  (possibile risparmio visto nel fatto 11, non misurato sull'analisi).
- Tutto ciò che è della PR 1.

### Domande aperte per Giuseppe

1. **Posso scaricare i modelli per la prova?** Whisper `large-v3-turbo` (1,6
   GB) e `large-v3` (3,1 GB); un modello di analisi più grande (8-9 GB) e uno
   piccolo libero per la chat (3 GB). Proposta: sì a tutti e quattro, c'è
   spazio (549 GB liberi). Senza, si accende alla cieca.
2. **La chat così lenta va bene?** Fonti in 3 secondi, prima parola in 1-2
   minuti, risposta in 2-4. Proposta: sì, con «solo fonti» se la prova trova
   anche un solo scambio Medyca/competitor. L'alternativa è tenere fuori da
   «tutto locale» la sola chat.
3. **Se la prova boccia l'analisi locale** (soglie sopra): si accende lo
   stesso accettando temi più generici, o l'analisi resta su Groq finché non
   troviamo un modello che passa? Proposta: non si accende sotto soglia.
4. **I 310 falliti**: li facciamo riprovare una volta, dopo l'accensione
   (circa 18 ore, spalmate su più notti)? Proposta: sì, una volta sola, perché
   le cause scritte sono della macchina.
5. **Giro completo alle 22:00 e pomeriggio solo raccolta**: va bene che i
   reel del pomeriggio siano analizzati la mattina dopo? Proposta: sì.
6. **Groq resta nel `.env` due settimane come via di ritorno**, spento
   dall'interruttore? Proposta: sì. Se lo togliamo subito, tornare indietro
   non è più un minuto.

## 3. Sviluppo           (sviluppatore)
## 4. Revisione          (revisore)
## 5. Collaudo           (collaudatore)
## 6. Rilascio           (rilasciatore)
## Registro delle decisioni

- 2026-11-14 - File aperto dall'architetto su incarico del capo, dopo la
  risposta di Giuseppe «Shifta tutto locale» (registro di
  `2026-11-14-pipeline-in-casa.md`, punto 2). Sostituisce la sezione «PR 2»
  di quel file. Disegno scritto, in attesa dell'OK di Giuseppe.
- 2026-11-14 - Rispetto al primo disegno cambia una proposta, e dico perché:
  il 3b non è più candidato (licenza «non commerciale», fatto 16), mentre
  prima lo indicavo come possibile scelta più veloce.
