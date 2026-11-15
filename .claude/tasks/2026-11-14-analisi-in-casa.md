---
id: 2026-11-14-analisi-in-casa
titolo: Groq o modello locale, niente Anthropic, niente chat (PR 2 di "pipeline in casa")
stato: pronto
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

### Revisione del disegno (15/11): Groq o locale, niente Anthropic, niente chat

**Questa sezione sostituisce tutto il disegno qui sopra.** Di quello restano
validi solo i «Fatti misurati oggi» (1-19) e i fatti del primo file. Tutto il
resto (interruttore `LOCAL_ONLY`, chat a flusso, Whisper in casa, tre PR,
domande 1-6) è superato dalla decisione di Giuseppe del 15/11 (registro).

Misure nuove: 15/11/2026 tra le 10:00 e le 10:40, tutte in sola lettura. Non ho
fatto prove di velocità su Ollama: alle 10:07 era in corso un giro a mano
(`jobs` 87) e il 7b era già caricato da qualcun altro (`/api/ps`). I tempi del
7b qui sotto sono quindi **calcolati** dalle velocità già misurate (fatto 9),
non cronometrati di nuovo.

#### In sei righe

1. **Si toglie**: la chat dentro l'app, lo stadio `batch`, tutto il codice che
   parla con Anthropic, il rivenditore `flow`, il fornitore dormiente `hf`.
   Quasi tutto è cancellare: circa 1.200 righe in meno.
2. **Resta**: Groq come prima scelta (analisi e trascrizione), il modello locale
   come riserva. Il connettore MCP resta com'è per il cliente.
3. **Modello locale: il 7b già scaricato** (`qwen2.5:7b-instruct-q4_K_M`,
   licenza Apache 2.0, verificata). Nessun download.
4. **Perché oggi Groq "fallisce"**: non è spento. Mandiamo 5 richieste insieme
   e superiamo il suo tetto al minuto. Bastava aspettare 20 secondi; invece il
   codice ripiega sul modello locale. Con un filo solo e un po' di pazienza il
   locale lavora quasi mai.
5. **Con il 7b e il codice di oggi la riserva si romperebbe**: una risposta
   media chiede 251 secondi e il codice la taglia a 240. Per questo le
   correzioni vanno nella stessa PR del cambio di modello.
6. **Una PR sola**, una migrazione, nessun cambio al crontab.

#### Fatti nuovi (R1-R14)

**Il giro del 15/11 alle 03:30** (`llm_calls`, 329 righe, tutte di quel giro)

- R1. Groq: 287 chiamate, 118 riuscite e 169 fallite. **Tutte le 169 hanno lo
  stesso errore: «rate limited, retry in N s», con N tra 1 e 21 secondi.**
  È il tetto *al minuto*. Nessun errore di tetto giornaliero, nessun errore di
  rete, nessuna chiave rifiutata.
- R2. Il tetto pubblico di Groq gratuito per `openai/gpt-oss-120b` è 8.000
  token al minuto e 200.000 al giorno (tabella sul sito di Groq; **il livello
  del nostro conto non l'ho verificato**: si legge solo dalla console). Noi
  abbiamo consumato 5.200 token al minuto di media durante `knowledge`, e
  **170.240 token in un giro solo: l'85% del tetto giornaliero**.
- R3. `enrich` e `knowledge` lavorano con **5 fili insieme** (`ENRICH_WORKERS`,
  `enrich_agent.py` riga 46). `chat()` riprova 3 volte e poi passa al fornitore
  dopo. Cinque fili che riprovano insieme si pestano i piedi: tre rifiuti di
  fila e il contenuto finisce al modello locale.
- R4. Modello locale (3b): 23 chiamate, tutte riuscite, nessuna tagliata. In
  media **97 secondi** l'una (da 50 a 222), 37 minuti di macchina in tutto.
  Leggeva 36-39 token al secondo, scriveva 7,2-7,5. Prompt medio 1.507 token,
  risposta media 389, la più lunga 1.180.
- R5. Le chiamate locali hanno fatto la coda: attesa media circa 160 secondi,
  **massima 811, con il limite a 900** (`OLLAMA_LOCK_WAIT`). La più lunga è
  durata 222 secondi **con il taglio a 240** (`chat()`, `timeout=240`). Il 3b
  ce l'ha fatta per poco.
- R6. Il locale ha toccato 5 reel su 10 e 12 articoli su 54. Ogni contenuto
  chiede circa 2 chiamate (analisi + affermazioni): 126 chiamate riuscite per
  64 contenuti, più 15 per i nomi dei temi.
- R7. Anthropic: 5 chiamate, tutte «chiave rifiutata» (401). `flow`: 4, tutte
  «saldo insufficiente» (403). Lo stadio `batch` ha provato a consegnare e ha
  ricevuto 401. **L'ultima consegna riuscita è del 3 ottobre**: da 43 giorni
  lo stadio non fa niente.
- R8. Trascrizione su Groq Whisper: 10 su 10, 11 secondi in tutto.

**Il codice**

- R9. `batch_runs`: 26 righe, tutte `collected`, tra il 13/9 e il 3/10, 1.063
  contenuti consegnati. **Zero righe nello stato `batched`** in `reels` e
  `knowledge_documents`: niente è rimasto a metà.
- R10. Il connettore MCP **usa un modello in un punto solo**: il riordino dei
  risultati (`mcp_bridge/server.py` riga 209, `semantic_search(rerank=True)` →
  `knowledge._rerank` → `chat_json`, modello «bulk», senza secondo tentativo).
  Se il modello non risponde, restituisce l'ordine "per significato + parole":
  non dà mai errore. Tutto il resto del connettore è lettura dal database.
- R11. Licenze (`/api/show`): 7b Apache 2.0 (testo di 11.343 caratteri, nessun
  «non-commercial»); 3b «Qwen Research License», non commerciale. Sulla
  macchina ci sono solo questi due modelli. Il 7b pesa 4,7 GB.
- R12. Ollama oggi apre il 7b con una finestra di 4.096 token (`/api/ps`): il
  codice non la imposta. Un'analisi chiede fino a 1.836 token di prompt più
  2.000 di risposta: ci sta per 260 token.
- R13. Il silenzio ammesso verso Ollama è 120 secondi (`client.py` riga 141).
  Il 7b, tra caricamento (96-123 s, fatto 12) e lettura del prompt (112 s),
  resta zitto più di 200.
- R14. Le funzioni interattive sono tutte lavori in sottofondo (`run_job`),
  tranne la chat. Ultimo uso: strategia 27/7, piano 4/8, ideazione 24/7, bozza
  blog 27/7 (fatto 15). Il piano editoriale chiede 3.600 token di risposta con
  attesa massima 900 secondi (`editorial.py` riga 126).

#### 1. Inventario: cosa nomina Anthropic e `flow`

| Dove | Cosa c'è | Che fine fa |
|---|---|---|
| `BEC/llm/batch.py` (202 righe) | il client del Batch API | **si cancella** |
| `BEC/pipeline/agents/batch_agent.py` (350) | consegna e ritiro | **si cancella** |
| `BEC/core/management/commands/sonnet_batch.py` (157) | comando a mano | **si cancella** |
| `BEC/pipeline/dag.py` | `batch` in `STAGE_NAMES`, `STAGE_LABELS`, `build_steps()` | esce dalla lista degli stadi (da 9 a 8). L'etichetta resta, segnata «non più in uso», perché i giri vecchi in `stage_runs` hanno ancora quel nome |
| `BEC/llm/client.py` | `_anthropic_chat` (righe 250-312), i due rami `dialect == "anthropic"` in `chat()`, `_hf_chat` e `_get_hf_client`, il ramo `hf` in `_providers()` e `available()` | **si cancellano**. La testata del file (parla ancora di HuggingFace) si riscrive |
| `BEC/config/settings/base.py` | `BATCH_ENABLED/MODEL/MAX_REQUESTS`, il dialetto `anthropic`, `HF_API_TOKEN`, `HF_LLM_MODEL`, i commenti che citano Anthropic | **si cancellano**. Il meccanismo `LLM_ENDPOINTS` resta: è quello che serve Groq |
| `BEC/core/models.py` | `BatchRun`, lo stato `BATCHED` | vedi punto 2 |
| `BEC/core/progress_report.py` (righe 233-247) | il blocco `batches` di `GET /ops/progress/` | **si cancella** |
| `FEC/src/components/progress/BatchBlock.tsx`, `pages/Progress.tsx`, `api/progress.ts` | riquadro «In consegna» della pagina Avanzamento | **si cancella** |
| `FEC/src/components/uploads/UploadPanel.tsx`, `api/uploads.ts` | lo stato `batched` di un upload | **si cancella** |
| `FEC/src/components/ops/RunTimeline.tsx` | il colore dello stadio `batch` | **resta**: serve a disegnare i giri vecchi |
| `FEC/src/i18n/it.json` | 6 righe su Anthropic/Sonnet, 11 su «in blocco» (pagina Avanzamento e pagina `Documentazione`: la tabella dei modelli dice 5 volte «Claude Sonnet 5») | si riscrivono: Groq, poi modello locale |
| `BEC/requirements.txt` riga 30 | `anthropic==1.5.0` | **si cancella**. `requirements-ci.txt` non lo contiene. `huggingface_hub` resta: serve ai vettori |
| `BEC/.env.example` | blocco Anthropic (5 righe), blocco Batch (5), `HF_*` | **si cancellano**; `LLM_ENDPOINTS=groq` |
| Test | `test_progress.py` (7 righe su `BatchRun`), `test_sources_and_status.py` (2 prove su `batch`). Non esiste una prova di `batch_agent` | si adattano |
| Documentazione | `02-pipeline.md` (13 righe su batch), `03-llm-and-embeddings.md` (18 su Anthropic, 12 su batch, la tabella dei fornitori con `aiapiflow`), `01-data-model.md` (8), `05-rest-api.md`, `06-frontend.md`, `07-content-lineage.md` | si riscrivono |
| `docs/medycabrain-pipeline-cliente.drawio` | 6 etichette, su tutte e due le pagine («di notte, in blocco: costa la metà», «Sonnet 5 (a lotti)», «Opus 4.8») | si riscrivono |
| `CLAUDE.md` (righe 10-13), `.claude/architecture-summary.md` (righe 36-41 e 59-63) | descrivono lo stadio `batch` e la chat | si aggiornano nella stessa PR; Giuseppe le legge nel diff |
| `flow` | **nel codice non c'è niente**: esiste solo nel `.env` di produzione (5 righe `LLM_FLOW_*` e la voce in `LLM_ENDPOINTS`) e in `03-llm-and-embeddings.md` | si toglie dal `.env` al rilascio e dalla documentazione |
| `mcp_bridge/server.py` righe 520-526 | commenti su «Origin: https://claude.ai» | **restano**: parlano del Claude del cliente che si collega, non di una nostra chiamata |
| `.claude/rules/`, `08-agent-team.md` | Sonnet e Fable della squadra di agenti | **restano**: sono gli strumenti di lavoro, non la piattaforma |

**Il connettore MCP non si rompe.** Dopo la modifica la ricerca usa
`gpt-oss-20b` su Groq per il riordino (2-3 secondi, misura scritta in
`knowledge.py`). Propongo che **il riordino non passi mai al modello locale**:
se Groq rifiuta, si usa subito l'ordine "per significato + parole", che è già
la riserva di oggi. Il motivo: sul 7b il riordino chiederebbe circa 1 minuto e
45 (stima del disegno sopra) e farebbe la coda dietro la pipeline fino a 15
minuti. Il cliente vedrebbe la ricerca bloccata. Serve un parametro nuovo in
`chat()` («solo remoto»), una riga in `_rerank`.

Catena dopo la modifica: **Groq (`gpt-oss-120b`, poi i fratelli della sua
catena) → 7b locale.** Per riordino MCP e piano editoriale: **solo Groq.**

#### 2. Lo stadio `batch` e la tabella `batch_runs`

Lo stadio esce dal DAG. Non perde niente: è fermo dal 3/10 (R7) e nessuna riga
è rimasta a metà (R9). Per la tabella, due strade:

| | Cosa si fa | Rischio |
|---|---|---|
| **A. Si toglie** (proposta) | migrazione `0027`: cancella `batch_runs` e toglie `batched` dagli stati. Prima il rilasciatore salva le 26 righe in `BEC/logs/batch_runs-2026-11.json` | i dati non tornano indietro senza quel file. La migrazione deve **rifiutarsi di partire** se trova anche una sola riga `batched` (oggi sono zero) |
| B. Resta in sola lettura | nessuna migrazione; il modello resta in `models.py`, nessuno ci scrive | nessun rischio sui dati; resta in casa un pezzo che parla di Anthropic, e fra sei mesi qualcuno si chiederà a cosa serve |

Le 26 righe valgono poco: quale modello ha analizzato cosa è già scritto in
`enrichments.llm_model` (947 Opus 5, 406 Sonnet 5, 138 gpt-oss-120b...).

#### 3. La chat, e le altre funzioni che usano un modello

**«La chat» è questo, e si toglie:**

- `FEC/src/pages/KnowledgeBank.tsx` (402 righe), la rotta `/knowledge-bank` in
  `App.tsx`, la voce «Chat sui contenuti» in `Sidebar.tsx`.
- `askKnowledge` e i suoi tipi in `FEC/src/api/knowledge.ts` (il resto del file
  resta: lo usano altre 5 pagine). `searchKnowledge` non lo chiama nessuno: via.
- `KnowledgeAskView` in `views.py` e `knowledge/ask/` in `urls.py`.
- In `core/knowledge.py`: `answer`, `_prepare`, `_sources_block`, `_mark_cited`,
  `_reference_hits`, `_inventory_line`. Lo sviluppatore controlla con `grep`,
  una per una, che non le usi nessun altro prima di cancellarle.
- Le chiavi `kb.*` e `nav.knowledgeBank` in `it.json`.
- Nessuna tabella: la chat non salvava niente. Nessuna migrazione.

Due fili da non lasciare penzolare: `ContentDetail.tsx` riga 45 torna a
`/knowledge-bank` quando si arriva da un link MCP (va cambiato in Home, e il
testo «Torna alla chat sui contenuti» con lui); il campo «vai al contenuto»
(`GoToContent`) vive solo dentro la pagina della chat e sparisce con lei.

**Resta** `knowledge/search/` (`KnowledgeSearchView`): non usa nessun modello.
**Resta** `semantic_search` con `_rerank`: è il motore del connettore MCP.

**Le altre funzioni.** La lettura del capo regge per tutte tranne una.

| Funzione | Dove | Risposta fino a | Proposta | Sul 7b (calcolato) |
|---|---|---|---|---|
| Analisi di reel e articoli, affermazioni | `enrich_agent`, `knowledge_agent` | 2.000 token | Groq → locale | 4-9 minuti a chiamata |
| Nomi dei temi | `cluster_agent` | 300 | Groq → locale | circa 1,5 minuti |
| Riconoscere gli articoli | `blog_discovery` | 700 | Groq → locale | 2-4 minuti |
| Analisi di un upload | `upload_workflow` (usa `knowledge_agent`) | 2.000 | Groq → locale | 4-9 minuti |
| Riordino ricerca MCP | `knowledge._rerank` | 2.000 | **solo Groq**, poi ordine semplice | non ci va |
| Brief di strategia, bozza | `strategy.py` | 900, 1.200 | Groq → locale | 7-9 minuti; attesa massima 900 s: ci sta |
| Ideazione | `ideation.py` | 1.200 | Groq → locale; attesa massima da 600 a 900 s | 7-9 minuti: oggi sarebbe al limite |
| Bozze blog (3 passi) | `blog_workflow.py` | 1.200-1.600 | Groq → locale; attesa massima da 700 a 1.200 s | 8-11 minuti a passo |
| **Piano editoriale** | `editorial.py` | 3.600 | **solo Groq.** Se Groq rifiuta, il lavoro fallisce subito con «Riprova più tardi» | **non regge**: 3.600 token a 2,8 al secondo sono 21 minuti più la lettura, contro un'attesa massima di 15. E un JSON così lungo dal 7b esce facilmente rotto |
| Giudice di `eval_mcp` (comando a mano) | `eval_mcp.py` | 4.000 | solo Groq | non regge, come sopra |
| Chat | `knowledge.answer` | 900 | **si toglie** | - |

Una cosa non misurata: strategia, piano e bozze **non hanno mai girato su
Groq**. Le ultime volte (luglio-agosto) rispondeva Claude tramite `flow`. La
qualità della scrittura con `gpt-oss-120b` va guardata in collaudo, una prova
per funzione.

#### 4. La riserva locale

**Modello: `qwen2.5:7b-instruct-q4_K_M`.** Già scaricato, Apache 2.0 (R11).
Basta cambiare `OLLAMA_MODEL` nel `.env`: è già il valore predefinito nel
codice. **Non propongo nessun download.**

**Quanto dura una chiamata sul 7b** (calcolo, con i token veri di R4 e le
velocità del fatto 9: legge 13,4 token al secondo, scrive 2,8):

| | Legge | Scrive | Totale |
|---|---|---|---|
| Chiamata media (1.507 + 389 token) | 112 s | 139 s | **251 s, circa 4 minuti** |
| La più lunga del 15/11 (1.180 token di risposta) | 112 s | 421 s | **533 s, circa 9 minuti** |
| Prima chiamata, modello da caricare | | | + 96-123 s |

Il 3b ne chiedeva 97 in media: il 7b è **2,6 volte più lento**.

**Perché si romperebbe senza correzioni**: 251 secondi di media contro un
taglio a 240 (R5); oltre 200 secondi di silenzio contro 120 ammessi (R13);
cinque fili in coda da 4 minuti l'uno contro un'attesa massima di 15 minuti.
Sono le stesse cause dei 310 falliti storici («risposta tagliata» 142, «attesa
scaduta» 81).

**Le correzioni, il minimo indispensabile** (tutte in `client.py` salvo dove
dico altro):

1. **Un filo solo**: `ENRICH_WORKERS` predefinito da 5 a 1. Serve al locale
   (una chiamata alla volta) e serve a Groq (R3). Non rallenta: il limite è il
   tetto al minuto di Groq, non il numero di fili. Attenzione per lo
   sviluppatore: con un filo solo `_parallel` salta `_with_retry`, quindi la
   pazienza sui limiti va spostata dove valga anche lì.
2. **Sul tetto al minuto si aspetta, non si ripiega.** Oggi: 3 tentativi, poi
   locale. Proposta: fino a 6 attese (ognuna lunga quanto dice Groq: mai più di
   21 secondi il 15/11), poi locale. Aspettare 20 secondi costa 12 volte meno
   di una chiamata da 4 minuti. Sul tetto *giornaliero* resta com'è: si passa
   ai modelli fratelli su Groq, poi al locale.
3. **Finestra**: `OLLAMA_NUM_CTX=8192` nel payload (R12). Memoria: 5,5 GB su 82
   liberi (fatto 12).
4. **Tempi**: silenzio ammesso da 120 a 600 secondi; tetto della risposta
   locale 1.500 secondi per la pipeline (la più lunga calcolata è 533 + 123).
5. **Una risposta tagliata è un errore con il suo nome**, non un testo a metà
   restituito in silenzio: oggi finisce in un errore di JSON che nasconde la
   causa.
6. **Niente secondo tentativo su «occupato» e su «tagliata»** (fatto 17): oggi
   può costare 45 minuti prima di fallire.
7. **Il modello resta in memoria** (`keep_alive` 30 minuti): si risparmiano
   96-123 secondi a ogni ripresa.
8. **«Solo remoto»** per riordino MCP, piano editoriale, giudice (punti 1 e 3).
9. **Tetto del locale per giro**: `PIPELINE_LOCAL_MAX_CALLS=40` (circa 2,8
   ore). Superato, lo stadio si ferma dicendolo e ciò che non è stato provato
   resta `pending` per il giro dopo. Senza, una notte con Groq spento
   chiederebbe 9 ore e si accavallerebbe con il giro delle 14:15.
10. **Un giro alla volta** (`run_pipeline.py`, `pipeline_run.py`): il cron che
    parte mentre un altro giro lavora si rifiuta e lo scrive nel log. In
    `run_pipeline.py` oggi non c'è nessun lucchetto (`grep` vuoto); quello dei
    giri a mano c'è ma non vede il cron. Da verificare in sviluppo.

**Ore-macchina della riserva, con il 7b**

| Giro | Chiamate, token | Come il 15/11 (nessuna correzione al traffico) | Con le correzioni 1 e 2 | Groq spento del tutto |
|---|---|---|---|---|
| Tipico: 8 reel + 11 articoli | 38 chiamate, circa 62.000 token | 0-0,5 h | **0 h** (sta nel tetto giornaliero tre volte) | 2,7 h |
| Grosso: 10 reel + 54 articoli | 141 chiamate, circa 230.000 token | **1,6 h** (23 chiamate per 251 s; con il 3b furono 0,6 h) | **0-1,3 h**: 0 se i modelli fratelli su Groq rispondono; 1,3 se non rispondono e i 30.000 token oltre il tetto giornaliero vanno al locale | 9,2 h, fermate a 2,8 dal tetto: il resto al giro dopo |

Sono stime: i token sono misurati, la velocità del 7b viene da una prova sola
(fatto 9) su una macchina i cui tempi cambiano anche del 70% (fatto 2). Dopo la
prima settimana si sostituiscono con i numeri veri di `llm_calls`.

Tempo di orologio su Groq, con il tetto al minuto: giro tipico 12 minuti, giro
grosso 45 (misurato il 15/11: 49).

#### 5. Una PR, e cosa si fa in produzione

**Una PR sola**, sul ramo `feat/analisi-in-casa`, in tre commit leggibili uno
per volta: (1) via Anthropic, `flow`, `hf` e lo stadio `batch`; (2) via la
chat; (3) la riserva locale. Non la divido perché il cambio di modello senza
le correzioni rompe la riserva, e togliere Anthropic e `flow` non cambia niente
di ciò che succede oggi: sono già morti tutti e due (R7).

File, oltre a quelli dell'inventario:

| File | Perché |
|---|---|
| `BEC/llm/client.py` | correzioni 2-9; parametro «solo remoto» |
| `BEC/pipeline/agents/enrich_agent.py`, `knowledge_agent.py` | un filo; il tetto lascia `pending`; via la nota vecchia «HF_API_TOKEN not set» |
| `BEC/core/knowledge.py` | via la chat; `_rerank` solo remoto |
| `BEC/core/editorial.py`, `ideation.py`, `blog_workflow.py`, `eval_mcp.py` | solo remoto o attese più lunghe (tabella al punto 3) |
| `BEC/core/management/commands/run_pipeline.py`, `BEC/core/pipeline_run.py` | un giro alla volta |
| `BEC/core/ops.py` | `models()` dice la catena vera: Groq, poi il nome del modello locale |
| `BEC/core/migrations/0027_...py` | via `batch_runs` e lo stato `batched` (se Giuseppe sceglie A) |
| `BEC/config/settings/base.py`, `BEC/.env.example` | `OLLAMA_NUM_CTX`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_PIPELINE_TIMEOUT`, `PIPELINE_LOCAL_MAX_CALLS` |
| Test nuovi | la catena con `.env.example` è solo Groq + locale; `num_ctx` e `keep_alive` nel payload; tagliata = errore; niente secondo tentativo su «occupato»; «solo remoto» non chiama mai Ollama; sei attese sul tetto al minuto prima del locale; il tetto lascia `pending` e non `failed`; `knowledge/ask/` risponde 404; il DAG ha 8 stadi; la ricerca MCP restituisce risultati anche se Groq rifiuta |

**Cosa si riusa**: `_ollama_slot` e il flusso di `_ollama_chat`; l'eccezione
`LLMRateLimit` con il suo `retry_after` e `daily`; la catena dei modelli
fratelli (`chain`); la riserva "ordine semplice" già scritta in `_rerank`;
`ctx.limit` come stampo per il tetto; il «Riprova» dei lavori; `llm_calls` per
verificare tutto dopo.

**In produzione, al rilascio** (lo fa il rilasciatore, chiedendo conferma a
ogni passo):

1. Copia del `.env` in `BEC/.env.bak.20261115` (i file `.env.bak*` sono già
   fuori da git).
2. Nel `.env`: `LLM_ENDPOINTS=groq`; via le righe `LLM_ANTHROPIC_*` (5),
   `BATCH_*` (2), `LLM_FLOW_*` (5), `HF_*` (2);
   `OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M`.
3. Salvataggio delle 26 righe di `batch_runs` in un file, poi la migrazione.
4. Build del frontend, riavvio dei **due** servizi: l'app e `medycabrain-mcp`
   (il connettore è un processo a parte e carica lo stesso `client.py`).
5. **Crontab: non cambia.** Le due righe non nominano `batch`.
6. Controllo: una ricerca vera dal connettore MCP, un giro a mano, e
   `llm_calls` deve mostrare solo `groq`, `whisper` e `ollama`.

**Tornare indietro**: Giuseppe annulla la PR su GitHub; `migrate core 0026`
(ricrea `batch_runs` vuota; le 26 righe sono nel file); si rimette il `.env`
salvato; riavvio dei due servizi. Dieci minuti. Si torna a uno stato in cui
Anthropic e `flow` fallivano comunque.

#### Rischi

- **Senza Anthropic, qualità e capacità dipendono da Groq gratuito e dal 7b.**
  Groq può cambiare i tetti o ritirare un modello senza avviso (l'ha già fatto
  due volte: nota in `~/brain`). Un giro grosso consuma da solo l'85% del tetto
  giornaliero (R2): il giro delle 14:15 e le funzioni interattive dello stesso
  giorno trovano poco. Quando Groq non basta lavora il 7b, che su 3 contenuti
  ha dato temi più generici e citazioni inventate (fatto 18 del primo file). Il
  controllo delle citazioni le scarta, ma i temi generici passano.
- **Il corpus ha più mani**: 1.353 analisi di Claude, 204 di Groq, 13 del 3b.
  Le nuove saranno di Groq e, ogni tanto, del 7b. `llm_model` lo registra.
- **`owner_type`**: nessun valore nuovo, nessuna scrittura nuova. Il rischio
  più grosso (la chat che attribuisce a Medyca una frase di un competitor)
  **sparisce con la chat**.
- **I falliti restano `failed`**: il tetto del locale e il «un giro alla
  volta» lasciano `pending` solo ciò che non è stato provato. È il punto dove
  è facile azzerare in silenzio: c'è un test apposta. Gli stati oggi `failed`
  sugli articoli (34 analisi, 159 affermazioni) non si toccano.
- **Credenziali**: ne escono tre (Anthropic, `flow`, HuggingFace), non ne
  entra nessuna. Le chiavi vecchie restano nei due file `.env.bak*` sul server
  e valide presso i fornitori finché Giuseppe non le revoca.
- **Il connettore MCP**: cambia una riga del suo percorso (riordino solo
  remoto). È la strada del cliente: il collaudo deve fare una ricerca vera,
  prima e dopo, e confrontare.
- **Il piano editoriale senza riserva**: se Groq rifiuta, fallisce. Lo dice
  in chiaro, ma è una funzione in meno nei momenti di tetto.
- **Storia dei giri**: la pagina Stato e Avanzamento disegnano anche i giri
  vecchi, che hanno lo stadio `batch`. Se si toglie l'etichetta si vedono male:
  per questo l'etichetta e il colore restano.
- **Tempi del 7b calcolati, non cronometrati** su prompt di analisi. Il primo
  giro vero dice se 1.500 secondi bastano.
- **Chi apre un vecchio link a `/knowledge-bank`** finisce in Home (la rotta
  di riserva c'è già).

#### Cosa resta fuori

- Whisper in casa, `LOCAL_ONLY`, chat a flusso, precedenza alle persone,
  `eval_local`, giro alle 22:00: tutto il disegno vecchio.
- Un modello locale più grande o diverso dal 7b (servirebbe un download).
- Far riprovare i falliti (i 310 storici dei reel; sugli articoli 34 analisi
  e 159 affermazioni): serve un ordine di Giuseppe, a parte.
- Il recupero del buco di 12 giorni: dopo questo lavoro, come già deciso.
- Passare a Groq a pagamento (domanda 3).
- Il campo «vai al contenuto»: sparisce con la pagina della chat. I link del
  connettore MCP aprono già il contenuto direttamente. Se serve, si rimette
  altrove con un lavoro suo.
- I blocchi di nginx per `knowledge/ask/`: restano, inutili e innocui (serve
  `sudo` per toglierli).
- Il codice di Apify spento: resta com'è.
- Un elenco chiuso di fornitori ammessi nel codice: la catena la decide il
  `.env`, che è in mano a Giuseppe. Un test controlla solo `.env.example`.

#### Domande aperte per Giuseppe

1. **La tabella `batch_runs` (26 righe di storia): la togliamo?** Proposta: sì,
   con una migrazione, dopo averle salvate in un file. L'alternativa è lasciarla
   ferma dov'è.
2. **Piano editoriale e riordino della ricerca MCP «solo Groq», mai sul
   locale: va bene?** Proposta: sì. Sul 7b il piano chiederebbe più di 20 minuti
   e uscirebbe spesso rotto; la ricerca del cliente resterebbe bloccata per
   minuti invece di rispondere subito con l'ordine semplice.
3. **Groq resta gratuito?** Un giro grosso usa l'85% del tetto di un giorno.
   Proposta: sì per ora, e fra due settimane guardiamo in `llm_calls` quante
   chiamate sono finite sul 7b. Se sono molte, il conto a pagamento di Groq
   alza i tetti: è una spesa, la decide Giuseppe.
4. **Pulizia sul server al rilascio**: tolgo il 3b da Ollama (`ollama rm`, 1,9
   GB, licenza non commerciale) e il pacchetto `anthropic` dall'ambiente?
   Proposta: sì a tutti e due. La revoca delle chiavi di Anthropic e di `flow`
   presso i fornitori la può fare solo Giuseppe.

## 3. Sviluppo           (sviluppatore)

Sviluppo del 15/11/2026, ramo `feat/analisi-in-casa`, tre commit come da disegno
(`7f4a7cb`, `e2345fa`, `c2aa079`). Vale solo la «Revisione del disegno (15/11)» e le
sei scelte chiuse. Niente push, niente PR. Produzione non toccata: nessuna modifica a
`BEC/.env`, crontab, servizi, database vero, `FEC/dist`; niente `ollama rm` né
`pip uninstall` (`anthropic` è tolto da `requirements.txt` ma installato).

### Cosa è stato fatto

**Commit 1 - via Anthropic, `flow`, `hf`, stadio `batch`**
- Cancellati: `llm/batch.py`, `pipeline/agents/batch_agent.py`,
  `core/management/commands/sonnet_batch.py`, `FEC/.../BatchBlock.tsx`.
- `llm/client.py`: via `_anthropic_chat`, `_hf_chat`, `_get_hf_client`, il ramo `hf` in
  `_providers()`/`available()`, i due rami `dialect`. Testata riscritta.
  `settings/base.py`: via `HF_*`, `BATCH_*`, `dialect`. `requirements.txt`: via `anthropic`
  (`huggingface_hub` resta, serve ai vettori).
- `pipeline/dag.py`: 8 stadi. **Nuovo `HISTORY_ORDER`** (i vecchi nove) e `STAGE_LABELS["batch"]`
  = «Analisi in blocco (non più in uso)», usati da `ops.py` (due punti) e `progress_report.py`
  solo per disegnare i giri vecchi. `_STAGE_WHO["batch"]` e il colore in `RunTimeline` restano.
- `core/models.py`: via `BatchRun` e `BATCHED`. **Migrazione `0027_drop_batchrun`**: prima un
  controllo che si rifiuta di partire se una sola riga è `batched` (in 8 colonne di stato),
  poi le 8 `AlterField` e `DeleteModel`. Reversibile nella struttura.
- `progress_report.py`: via il blocco `batches` (cinque letture invece di sei: test e doc
  aggiornati). Frontend: via `BatchBlock`, il tipo `BatchData`, lo stato `batched` degli upload.
- `.env.example`, `it.json`, pagina `Documentazione`, `README.md`, `CLAUDE.md`,
  `architecture-summary.md`, `01/02/03/05/06`, drawio (due file).

**Commit 2 - via la chat**
- Via `KnowledgeBank.tsx`, `GoToContent.tsx`, la rotta, la voce di menu, `IconChat`,
  `askKnowledge`/`searchKnowledge`/`AskResult`/`KnowledgeHit`, le chiavi `kb.*` (resta
  `kb.untitled`: la usa `ArticleCard`), `nav.knowledgeBank`, `content.goto*`.
- Backend: via `KnowledgeAskView` e `knowledge/ask/` (ora **404**, c'è un test); da
  `core/knowledge.py` via `answer`, `_prepare`, `_sources_block`, `_mark_cited`,
  `_reference_hits`, `_inventory_line`, `ANSWER_*`, `MAX_REFERENCES`, `_GROUPS`. `grep` una
  per una: nessun altro le usava. Resta `semantic_search` con `_rerank`.
- Nessun testo né link restano sulla chat (grep su `FEC/src`: zero in codice e `it.json`).
  `ContentDetail` torna alla **Home** («Torna alla Home»; se arrivi da un upload resta
  «Torna indietro»). Il campo «vai al contenuto» non lascia buchi: la sezione `docs.goto` è
  riscritta (il link del connettore apre il contenuto; un codice nudo `blog:843` non si apre
  da solo, e lo dice). `docs.rag` è riscritta come «Come funziona la ricerca del connettore».
- Un vecchio link a `/knowledge-bank` finisce in Home (rotta `*` già presente).

**Commit 3 - la riserva locale che regge** (tutto in `llm/client.py` salvo dove detto)
- Sul tetto AL MINUTO si aspetta fino a `LLM_RATE_WAITS`=6 volte (quanto dice Groq, 1-60 s)
  prima del locale (`_patient`); sul tetto GIORNALIERO si passano i modelli fratelli come prima.
  Con `retries=0` non si aspetta (è il caso del riordino MCP).
- `ENRICH_WORKERS` predefinito 1. `OLLAMA_NUM_CTX`=8192 e `keep_alive`=30m nel payload;
  silenzio `OLLAMA_READ_TIMEOUT`=600 (era 120); risposta intera `OLLAMA_PIPELINE_TIMEOUT`=1500
  (`chat(timeout=None)` ora significa «il tetto della pipeline»).
- Risposta locale tagliata (tetto di token o di tempo) = `LLMTruncated`; slot occupato =
  `LLMBusy`; nessuno dei due si riprova. `usage.Call.fail` ora conserva `truncated` e i token,
  così la riga dice «fallita + tagliata».
- Tetto di chiamate locali per giro `PIPELINE_LOCAL_MAX_CALLS`=40 (solo processi `pipeline:*`,
  un Job del cliente non è mai limitato). `enrich` e `knowledge` si fermano, scrivono la nota
  sullo stadio («Fermato: usate le 40 chiamate… N restano in attesa per il giro dopo») e
  **lasciano `pending`**; il resto torna come `deferred`/`stopped`. Gli errori veri restano `failed`.
- `chat(remote_only=True)` per `_rerank` (MCP), piano editoriale, giudice di `eval_mcp`.
  `LLMRemoteUnavailable`: il piano dice «Riprova più tardi» (`_client_message`), la ricerca
  usa l'ordine semplice. Attese: ideazione 600→900, bozze blog 600/700→1200.
- Un giro alla volta: lucchetto `flock` in `DAG.run` (`PIPELINE_LOCK_PATH`), il secondo giro
  scrive «un altro giro sta già lavorando» nel log e esce con codice 3 (`ROUND_BUSY`); il Job
  manuale fallisce con una frase chiara. Dry run senza lucchetto.
- `ops.models()` dice la catena vera («modello → riserva: qwen…», «solo Groq» dove è così).
- Doc: `02`, `03` (sezione nuova «The local backstop», con i limiti), `04`, `05`, drawio.

### Scelte e differenze dal disegno

- **Il lucchetto sta in `DAG.run`, non in `run_pipeline.py`/`pipeline_run.py`**: così copre
  cron-contro-cron e cron-contro-bottone con un punto solo (il disegno diceva «da verificare»;
  verificato: in `run_pipeline.py` non c'era nulla). `pipeline_run.py` trasforma il «rifiutato»
  in una frase per il Job.
- **`HISTORY_ORDER`** non era nel disegno: serve perché `run_history()` capisce che comincia
  un nuovo giro quando uno stadio parte «prima» del precedente, e senza `batch` nell'ordine i
  log vecchi si disegnerebbero doppi. C'è un test con un log vecchio e uno nuovo.
- **`fetch_reference`/`_get`/`MAX_TEXT`** (`core/external_ref.py`) tolti: servivano solo alla
  chat. `safe_get` e `_check_public` restano (blog, link).
- **Etichetta `web:chat`** in `process_label` resta («Chat sui contenuti (funzione tolta)»):
  `llm_calls` tiene 90 giorni e ha righe vecchie con quel nome.
- Aggiunte rispetto alle quattro impostazioni del disegno: `OLLAMA_READ_TIMEOUT`,
  `LLM_RATE_WAITS`, `PIPELINE_LOCK_PATH` (tutte con valore predefinito; `ENRICH_WORKERS` e le
  altre sono in `.env.example`).
- Il timeout locale predefinito (1500 s) vale per **ogni** chiamata che non ne dichiara uno,
  non solo per la pipeline: gli unici chiamanti senza timeout sono i quattro della pipeline e
  il riordino (che non va mai al locale). Strategia (900) e gli altri hanno il loro.
- `_with_retry`/`_RATE_RETRIES` in `enrich_agent` restano ma sono quasi morti: `chat()` non
  lascia più uscire un `LLMRateLimit`. Non l'ho tolto (fuori portata; con `ENRICH_WORKERS=1`
  non gira nemmeno).
- Una risposta **Groq** tagliata (`finish_reason: length`) torna ancora come stringa: il
  disegno parla della risposta locale. Scritto nei limiti di `03`.
- I test dei giri (`test_progress.py`) usano un file di lucchetto proprio: la prima versione
  prendeva quello vero in `/tmp` (lasciando un file vuoto) e avrebbe potuto far rifiutare un cron
  che partiva in quel momento. Corretto prima del commit.
- Per il «solo Groq» del riordino ho usato un parametro (`remote_only`) come proposto, ma
  il riordino con `retries=0` non aspetta nemmeno il minuto di Groq: risponde subito in ordine
  semplice (il cliente aspetta).

### Prove (output vero)

```
$ manage.py test core --noinput          (Postgres 16 usa-e-getta a lato, porta 55451)
Ran 317 tests in 34.612s
OK
$ manage.py makemigrations --check --dry-run
No changes detected
$ npx tsc --noEmit -p tsconfig.json
tsc=0
```
Erano 277 test nella PR precedente; ora 317 (+40: `test_llm_chain.py` 33, `test_migration_0027.py` 2,
chat rimossa 3, ricerca MCP con Groq che rifiuta 1, giro vecchio con `batch` 1; altri vecchi
test adattati: tetto di token = errore, cinque letture invece di sei, 8 stadi). I test non escono
dalla macchina: chiavi svuotate e `OLLAMA_URL` verso una porta morta.

I test che il disegno chiedeva, uno per uno: catena di `.env.example` = solo Groq + locale;
`num_ctx`/`keep_alive`/silenzio nel payload; tagliata = errore (anche per tempo);
niente secondo tentativo su «occupato» e «tagliata»; «solo remoto» non chiama mai Ollama né
il lucchetto (4 tipi di rifiuto di Groq); **sei attese** sul tetto al minuto e poi il locale;
il tetto lascia `pending` (4 reel, uno fatto, tre `pending`, zero `failed`) e un errore vero
resta `failed`; `knowledge/ask/` 404; il DAG ha 8 stadi; **la ricerca MCP restituisce gli
stessi risultati quando Groq rifiuta, senza chiamare Ollama né aspettare**; un giro vecchio
con lo stadio `batch` si disegna al suo posto.

**Migrazione 0027 su Postgres vero a lato** (righe finte, non quelle di produzione):
```
migrate core 0026 -> INSERT 0 26 (righe finte in batch_runs)
manage.py dbshell -- -c "\copy (select * from batch_runs order by id) to '...csv' csv header"  -> COPY 26 (27 righe col titolo)
migrate core 0027 -> Applying core.0027_drop_batchrun... OK
migrate core 0026 -> Unapplying core.0027_drop_batchrun... OK ; select count(*) from batch_runs -> 0
```
Il rifiuto con una riga `batched` è un test (`test_migration_0027`): errore chiaro, tabella
ancora lì.

**Prove vere ai modelli** (database a lato, `LLM_ENDPOINTS=groq` e `OLLAMA_MODEL` del 7b dati a
mano, chiave di Groq letta dal `.env` senza stamparla; ore 10:50, lontano da 03:30 e 14:15):
```
chain: [('fast','groq'), ('ollama',None)]   analysis: openai/gpt-oss-120b | bulk: openai/gpt-oss-20b
Groq 1 (analisi di un reel finto): 1.1s, 9 chiavi giuste, primary_topic "vampate di calore"   in/out 912/378
Groq 2 (remote_only, retries=0):  0.3s -> {'ordine': [1, 0, 2]}                                 in/out 146/54
7b locale (client.chat_json, senza timeout dato): 145s, JSON completo, nulla tagliato
   riga llm_calls: ollama qwen2.5:7b-instruct-q4_K_M done, prompt/out 905/174,
   carico 38s, lettura 55s (16,5 tok/s), scrittura 52s (3,3 tok/s)
```
Un campione solo, prompt piccolo (905 token, non i 1.500 di un'analisi media).

### Cosa NON ho potuto provare

- **Nessun giro vero della pipeline**, né sul database vero né a lato: la riserva è provata
  con test e con una chiamata, non con 40 analisi in fila. Il lucchetto «un giro alla volta» è
  provato con un lock tenuto da un altro descrittore, non con due processi cron reali.
- **L'attesa su un vero 429 di Groq** non l'ho vista accadere (Groq oggi non rifiutava): è
  provata con un finto che solleva `LLMRateLimit`.
- **Tempi del 7b su un'analisi vera** (1.500 token in, 400 fuori): restano calcolati
  (~251 s); la mia misura è un campione piccolo. **Qualità del 7b non valutata.** Qualità di
  `gpt-oss-120b` su strategia, piano, bozze: non guardata (un campione di analisi sì).
- **Nessun gesto vero sull'interfaccia** (browser, mobile, desktop): solo `tsc`. Non ho
  eseguito `npm run build` (scriverebbe `FEC/dist`, di produzione). Tocca al collaudatore:
  menu senza «Chat sui contenuti», `/knowledge-bank` in Home, una scheda aperta da un link,
  pagina Avanzamento con un giro vecchio che ha `batch`, pagina `Documentazione`.
- **Il connettore MCP vivo** non l'ho interrogato: il servizio gira con il codice vecchio in
  memoria e non l'ho riavviato. Provata solo la funzione (`cerca_tutto`) con Groq finto che
  rifiuta. «Una ricerca vera prima e dopo» è lavoro del collaudo e del rilascio.
- `ProgressView` su un giro vecchio vero: provato con righe `stage_runs` finte (`batch`).
- Dopo la mia prova il 7b resta caricato in Ollama per 30 minuti (`keep_alive` nuovo): si
  scarica da solo, non ho toccato altro.

### Rimasto fuori (come da disegno, o scoperto)

- Whisper in casa, `LOCAL_ONLY`, chat a flusso, `eval_local`: non fatti, come detto.
- I blocchi nginx per `knowledge/ask/`: restano, inutili e innocui (serve `sudo`).
- Il codice di Apify spento: com'è. Un elenco chiuso di fornitori ammessi nel codice: no.
- `_with_retry` quasi morto (sopra). `eval_mcp` stampa «nessun voto del giudice» se Groq
  rifiuta (già così: `except Exception: return None`).
- Una risposta Groq tagliata torna ancora come stringa (sopra).
- I falliti storici (310 reel, 34 analisi e 159 affermazioni di articoli): non toccati.
- Se un cron parte e trova il lucchetto occupato, esce con codice 3: cron può mandare una
  mail di errore. È voluto (si vede), ma Giuseppe lo sappia.

### Da fare in produzione al rilascio (nell'ordine; il rilasciatore chiede conferma a ogni passo)

0. **Prima di tutto**: nessun giro in corso (`pgrep -af 'run_pipeline|run_job'` vuoto) e non
   tra le 03:15-06:00 né vicino alle 14:15.
1. **Copia del `.env`**: `cp -p BEC/.env BEC/.env.bak.20261115` (i `.env.bak*` sono già fuori da git).
2. **Sola lettura, prima di `migrate`: nessuna riga `batched` e salvataggio delle 26 righe.**
   ```
   cd /home/medyca-admin/projects/medycabrain/BEC
   venv/bin/python manage.py dbshell -- -At -c "select 'reels', count(*) from reels where 'batched' in (enrich_status, argument_status, media_status, transcribe_status) union all select 'knowledge_documents', count(*) from knowledge_documents where 'batched' in (enrich_status, argument_status, embed_status) union all select 'uploaded_media', count(*) from uploaded_media where transcribe_status='batched'"
   # atteso: tre righe con 0
   venv/bin/python manage.py dbshell -- -v ON_ERROR_STOP=1 -c "\copy (select * from batch_runs order by id) to 'logs/batch_runs-2026-11.csv' csv header"
   wc -l logs/batch_runs-2026-11.csv       # atteso 27 (titolo + 26)
   ```
   Il file va in `BEC/logs/` (fuori da git: dentro ci sono id dei contenuti e il testo degli
   errori del fornitore). Se `COPY` non dice 26, **ci si ferma**.
3. **`.env`, subito prima di cambiare il codice** (funziona sia con il codice vecchio sia con
   il nuovo): `LLM_ENDPOINTS=groq`; via le 5 `LLM_ANTHROPIC_*`, le 2 `BATCH_*`, le 5
   `LLM_FLOW_*`, le 2 `HF_*`; `OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M`;
   `LLM_PROVIDER_ORDER=fast,ollama` (oggi già così). Le nuove impostazioni hanno un valore
   predefinito giusto: non serve scriverle. Senza questo passo, col codice nuovo gli endpoint
   `anthropic` e `flow` verrebbero tentati con il dialetto sbagliato (404/401, saltati ma rumorosi).
4. Merge della PR (lo fa Giuseppe), poi nella cartella di produzione `git checkout main && git pull`.
5. `venv/bin/python manage.py migrate` (applica `0027`; se trova righe `batched` si rifiuta).
6. Build del frontend (`FEC`: `npm run build`) e **riavvio dei due servizi**:
   `medycabrain-backend` e `medycabrain-mcp` (il connettore carica lo stesso `client.py`).
7. **Controlli**: una ricerca vera dal connettore (risultati e tempo, confrontati con una
   fatta prima del passo 4); la pagina Avanzamento e Stato con un giro vecchio; il menu senza
   la chat; `/knowledge-bank` porta in Home; poi un giro a mano («Aggiorna ora») e
   `select provider, count(*) from llm_calls where created_at > now() - interval '1 day' group by 1`:
   devono comparire solo `groq`, `whisper`, `ollama`. Il crontab **non cambia** (le due righe
   non nominano `batch`).
8. **Solo dopo i controlli** (decisione 4 di Giuseppe, a conferma): `ollama rm
   qwen2.5:3b-instruct-q4_K_M` (1,9 GB, licenza non commerciale) e `venv/bin/pip uninstall -y
   anthropic`. Il 3b non va rimosso prima di aver riavviato con `OLLAMA_MODEL` del 7b.
9. La revoca delle chiavi di Anthropic, `flow` e HuggingFace presso i fornitori la può fare
   solo Giuseppe (restano nei due `.env.bak*`).
10. **Circa il 29/11**: guardare in `llm_calls` quante chiamate sono finite su `ollama`
    (e `select count(*) from llm_calls where truncated`), come deciso.

**Tornare indietro** (dieci minuti), **in questo ordine**:
1. Con il codice NUOVO ancora in cartella: `venv/bin/python manage.py migrate core 0026`
   (ricrea `batch_runs` vuota; serve il file `0027` per annullarla, quindi prima di cambiare codice).
2. Poi il codice precedente (`git revert` della PR via una nuova PR, o `git checkout` del
   commit di prima, a scelta di Giuseppe) e `npm run build`.
3. Rimettere `BEC/.env.bak.20261115` come `BEC/.env`.
4. Se serve la storia: `venv/bin/python manage.py dbshell -- -c "\copy batch_runs from 'logs/batch_runs-2026-11.csv' csv header"`, poi
   `select setval(pg_get_serial_sequence('batch_runs','id'), (select max(id) from batch_runs))`.
5. Se il passo 8 è già stato fatto: `venv/bin/pip install anthropic==1.5.0` (e `ollama pull` del
   3b solo se serve davvero; si tornerebbe a uno stato in cui Anthropic e `flow` fallivano comunque).
6. Riavvio di `medycabrain-backend` e `medycabrain-mcp`.

### Secondo giro (correzioni dopo revisione e collaudo)

Lavoro nella copia separata (`scratchpad/wt-analisi`); produzione non toccata, un commit nuovo
sopra i tre. Punto per punto:

- **R1** `_rerank` aspetta Groq al massimo `RERANK_TIMEOUT`=10 s, poi ordine semplice. Test con
  Groq che accetta e poi tace (`ReadTimeout`): il timeout passato è 10, ordine semplice, Ollama
  e attese mai chiamati.
- **R2** Chiave rifiutata: `client.remote_problem()` e nota sullo stadio in corso («Groq non
  risponde: chiave rifiutata; il lavoro va sul modello locale»), anche a fine stadio e dentro la
  nota di «fermato». Un endpoint spento si riprova dopo `LLM_RETRY_DISABLED_AFTER`=600 s (il
  connettore non resta spento fino al riavvio). Test.
- **R3** `LLMBusy` e Ollama irraggiungibile sono `LLMLocalUnavailable`: insieme al tetto fanno
  `NOT_THE_ITEMS_FAULT`; `enrich` e `knowledge` lasciano `pending`, si fermano e la nota dice
  «il modello locale non era disponibile (occupato o spento)». Una chiamata che non ha avuto lo
  slot restituisce il suo posto nel tetto. Un errore vero resta `failed`. Test (4 reel, 0 `failed`).
- **D1** `finish_reason=length` di Groq = `LLMTruncated`: riga `llm_calls` `failed` + `truncated`,
  il lavoro dice «Riprova: la risposta del modello è stata tagliata…», non va al 7b (sarebbe
  tagliata allo stesso punto dopo minuti) e nessun testo a metà arriva al cliente. Tetti:
  brief 900→1800, bozza di strategia 1200→2400, bozze blog 1600/1200/1400→3200/2400/2800, attese 1800 s.
- **D2** `LLM_ENDPOINTS`: solo nomi noti (`groq`); gli altri (`anthropic`, `flow`, `hf`…) ignorati
  con **un** avviso all'avvio e nessuna richiesta di rete; il test prova che la chiave vecchia non
  compare né nella catena né nel log.
- **D3** Messaggio del Job: «Riprova più tardi: il servizio dei modelli non risponde o è al suo
  limite.» (l'azione prima; non dice più «limite» da solo per una chiave rifiutata); `StatusBar`
  non taglia più il messaggio di un lavoro fallito (va a capo).
- **D4** Nessuna stima «mancano…»/«velocità» mentre c'è una chiamata locale aperta (test);
  «le 1 chiamate» corretto (nota del tetto, plurale i18n di `progress.calls`).
- **D5/D6, R4, R6 e dosaggi**: scritti tra i limiti noti (`03` e pagina `Documentazione`).
- Il file di lucchetto: `core/tests/__init__.py` dà a ogni processo di test un lucchetto suo,
  tolto a fine corsa (tolto anche l'override locale in `test_progress.py`, che lasciava un file
  per ogni corsa). Dopo la suite: nessun file in `/tmp`.

Prove (output vero, copia separata, Postgres a lato):
```
Ran 336 tests in 38.392s   OK      (erano 317: +19)
makemigrations --check --dry-run   No changes detected
npx tsc --noEmit                   tsc=0
```
Tre chiamate vere a Groq con i prompt veri di strategia e bozze (materiale finto), tetti nuovi:
```
brief strategia: OK, 2.2s, tetto 1800, usati 834 token, finisce «...gestione delle vampate di calore.»
bozza strategia: OK, 3.5s, tetto 2400, usati 1429 token (col vecchio 1200 sarebbe stata tagliata)
bozza blog:      OK, 1.6s, tetto 2800, usati 672 token
```
(Il codice solleva se `finish_reason` è `length`: «OK» vuol dire `stop`.) Il testo a metà frase col
tetto vecchio non l'ho riprodotto con Groq: è coperto da un test che simula `finish_reason: length`.

Da aggiungere ai passi di rilascio (R6): **`migrate` e riavvio di backend e `medycabrain-mcp` uno
dopo l'altro, senza pause** (tra i due il backend vecchio dà 500 su Stato/Avanzamento); il passo 3
(pulire `.env`) resta consigliato ma ora una chiave vecchia rimasta non esce più. I blocchi nginx
per `knowledge/ask/` (`deploy/nginx-medycabrain.conf`, righe ~22 e ~60) vanno tolti con root:
fuori da questa PR.

Non provato nel secondo giro: gesto vero sull'interfaccia (toast a 380 px, pagina Avanzamento
senza stima), solo `tsc` e test del backend; nessuna prova con Ollama spento davvero (solo la
`ConnectionError` simulata).

## 4. Revisione          (revisore)

*(Testo del revisore, primo giro su `98d07bd`, incollato dal capo in versione ridotta; nessun rilievo tolto.)*

**Verdetto: PASSA.** Nessun bloccante. `owner_type` non toccato, nessun
segreto nel diff né in `.env.example`, nessun fornitore rivenduto rimasto.
I 9 strumenti MCP non dipendono da codice tolto. Migrazione 0027 sana e
reversibile nella struttura. Documentazione aggiornata nello stesso lavoro.

**Non bloccanti, per gravità**

- **R1. Ricerca MCP con Groq lento** (`core/knowledge.py:416-420`,
  `llm/client.py:513`): `_rerank` chiama senza `timeout`, quindi con Groq che
  accetta e poi risponde piano il cliente aspetta fino a 120 s prima
  dell'ordine semplice. I rifiuti immediati (tetto al minuto, al giorno,
  chiave morta, rete) rispondono subito. Rimedio: `timeout` di circa 10 s.
- **R2. Chiave Groq rifiutata** (`client.py:602-608`, `enrich_agent.py`
  `note_local_budget`): Groq viene saltato per tutto il processo con un solo
  `logger.warning`; la nota dello stadio dice «usate le 40 chiamate» senza
  dire perché. Nel connettore MCP, processo lungo, un 403 passeggero spegne il
  riordino fino al riavvio del servizio.
- **R3. Locale occupato = `failed` per sempre** (`enrich_agent.py`,
  `knowledge_agent.py`): `LLMBusy` (slot occupato oltre 900 s) e collegamento
  rifiutato da Ollama arrivano come `LLMError` generico e il contenuto resta
  `failed` senza colpa. `_take_local_call` (`client.py:481-485`) conta la
  chiamata anche se lo slot è occupato.
- **R4. Nessun tetto complessivo all'attesa su Groq** (`client.py:539-555`):
  fino a 360 s per chiamata, circa 1.080 s sul tetto giornaliero con i modelli
  fratelli. Un 429 «troppo grande per il minuto» spreca le 6 attese. Da
  scrivere nei limiti noti di `03`.
- **R5. Lucchetto**: giusto (`flock`, non resta orfano; i job del cliente non
  passano da `DAG.run`). Il giro rifiutato esce con codice 3.
- **R6. Rilascio e residui**: tra `migrate` e riavvio il backend vecchio dà
  500 su Stato/Avanzamento: farli di seguito. Codice nuovo con `.env` vecchio
  non crasha ma prova `anthropic` a ogni chiamata. Residui innocui:
  commento `core/models.py:894`, blocchi nginx per `knowledge/ask/`
  (`deploy/nginx-medycabrain.conf:22,60`), `_with_retry` quasi morto. Una
  risposta di testo libero tagliata da Groq torna tagliata senza segnale.

### Secondo giro (revisione su `8e5d1bd`)

*(Testo del revisore, incollato dal capo in versione ridotta.)*

**Verdetto: PASSA.** Nessun bloccante. R1, R2, R3, D1-D4 corretti. Commit con
i soli 20 file attesi, file di lavoro integro, nessun segreto, `owner_type`
non toccato.

**Non bloccanti, lasciati aperti:**

- **N1.** `core/ideation.py:131` (1.200 token) e `core/editorial.py:123`
  (3.600): tetti non rialzati. Con «risposta tagliata = errore», se uno dei
  due viene tagliato il cliente legge «Riprova» e può ritrovare lo stesso
  taglio. Nel collaudo del primo giro sono usciti interi su Groq.
- **N2.** `llm/client.py` `_ollama_chat`: Ollama che cade a metà risposta
  (errore nel ciclo `iter_lines`) marca ancora `failed` il contenuto.
- **N3.** Dopo un `LLMLocalUnavailable` lo stadio si ferma al primo elemento;
  gli altri aspettano il giro dopo anche se Groq avrebbe potuto servirli.
- **N4.** `LLM_ENDPOINTS` vuoto (`config/settings/base.py`): nessun avviso,
  tutto va sul locale. Al rilascio va scritto `LLM_ENDPOINTS=groq`.
- **N5.** `client.py:447`: `del _fast_disabled[name]` può dare un `KeyError`
  raro con più thread (innocuo nel riordino; `.pop(name, None)` lo toglie).
- **N6.** Una risposta tagliata da Groq non prova il 7b e resta `failed`:
  da riguardare il 29/11 con la quota del locale.

## 5. Collaudo           (collaudatore)

Collaudo del 15/11/2026 (10:59-11:50), ramo `feat/analisi-in-casa` (`98d07bd`), eseguito in una
copia di lavoro a lato con un Postgres 16 usa-e-getta (porta 55461) caricato con una **copia di sola
lettura dei dati di produzione** (`pg_dump` -> restore; 345 MB, 1.633 reel, 2.265 articoli, schema a 0026,
26 righe in `batch_runs`). Backend a lato su :9193, ponte MCP a lato su :8125/:8126, interfaccia a lato
su :9194 (le due ultime servivano `FEC/dist` della copia). Produzione mai scritta: `main`, `BEC/.env`
(ultima modifica 13/11), crontab, servizi e `FEC/dist` intatti; nessun giro vero (cron) era in corso
(`pgrep` vuoto) e le prove sono finite alle 11:47, ben prima delle 14:15. Chiave Groq vera presa dal
`.env` senza stamparla; per «Groq rifiuta» una chiave finta (401), per «ambiente vecchio» chiavi finte
anche per Anthropic, flow e HF (nessuna chiave vera è andata verso quei fornitori).

### Verdetto: PASSA, con un difetto serio non bloccante e cinque piccoli

Nessun difetto bloccante: migrazione, chiave di ricerca MCP, catena Groq -> 7b, tetto di chiamate,
lucchetto «un giro alla volta», menu/rotte/pagine senza chat, pagine Stato e Avanzamento con i giri
vecchi: tutto si comporta come dice il disegno. **Ma le tre funzioni di scrittura lunga (brief di
strategia, bozza di strategia, bozza blog) con Groq arrivano tagliate a metà frase** (sotto, D1). Non è
nato in questo ramo (su `main` oggi la catena `anthropic -> groq` darebbe lo stesso testo tagliato), ma
il ramo dice che queste funzioni «restano su Groq» e il cliente le troverebbe rotte: la decisione è di
Giuseppe prima di dire che «funzionano».

### 1. Suite, migrazioni, tipi, build

```
$ manage.py makemigrations --check --dry-run        -> No changes detected
$ manage.py check                                   -> System check identified no issues (0 silenced).
$ manage.py test core --noinput   (chiavi svuotate, OLLAMA_URL su porta morta)
Found 317 test(s).
Ran 317 tests in 40.944s
OK
$ cd FEC && npm run build     (tsc -b && vite build, node_modules copiato nella copia, dist della copia)
✓ built in 19.54s
```
317 test come atteso. Il build non ha errori di tipo. Nota: la suite lascia un file vuoto
`/tmp/medycabrain-test-<pid>.lock` (innocuo; ho tolto il mio).

### 2. Migrazione 0027 su copia realistica (schema 0026, 26 righe in `batch_runs`)

Passi di produzione copiati alla lettera (dal punto 2 della sezione 3):
```
reels|0   knowledge_documents|0   uploaded_media|0                    <- nessuna riga 'batched'
COPY 26      wc -l logs/batch_runs-2026-11.csv -> 27 (titolo + 26)       <- il file va in BEC/logs, ignorato da git
```
Rifiuto (messo `reels.enrich_status='batched'` su una riga, poi ripristinato a `done`):
```
$ migrate core 0027
RuntimeError: Ci sono ancora righe nello stato 'batched' {'reel.enrich_status': 1}: consegnate ad Anthropic
e mai ritirate. Vanno risolte prima di togliere lo stato (riportarle a 'pending' o ritirarle), poi si rilancia la migrazione.
-> batch_runs ancora 26 righe, ultima migrazione ancora 0026_llmcall_stagerun
```
Poi, senza la riga `batched`:
```
migrate core 0027   -> Applying core.0027_drop_batchrun... OK     (to_regclass('batch_runs') vuoto)
migrate core 0026   -> Unapplying core.0027_drop_batchrun... OK    (batch_runs ricreata, 0 righe)
migrate             -> Applying core.0027_drop_batchrun... OK
makemigrations --check -> No changes detected
```
Non provato: il rientro del file CSV nella tabella ricreata (passo 4 del «tornare indietro»).

### 3. Connettore MCP da client vero (bridge del ramo contro la copia dati, confronto con il bridge di produzione :8025, sola lettura)

Client: SDK `mcp` in Python, trasporto streamable-HTTP, stesso percorso `/<segreto>/mcp` del cliente.
Gli strumenti elencati sono gli stessi nei due bridge (panoramica, cerca_reel, cerca_articoli, cerca_tutto,
leggi_reel, leggi_articolo, leggi, cerca_riferimenti, fonti_blog, temi). Esito, ramo (nuovo) contro produzione:

| Chiamata | Risultato | Secondi nuovo / prod |
|---|---|---|
| `panoramica` | testo identico | 0,04 / 0,08 |
| `temi` (all, 34.657 caratteri) | identico | 1,48 / 0,74 |
| `fonti_blog` | identico | 0,04 / 0,04 |
| `cerca_reel` «vampate di calore e terapia ormonale bioidentica» | stessi 5 id, stesso ordine, testo identico | 3,26 / 38,21 (prod a freddo) |
| `cerca_articoli` «progesterone e sonno» | stessi 5 id, stesso ordine | 2,02 / 3,84 |
| `cerca_tutto` «perimenopausa sintomi ansia» (competitor) | stessi 5 id, stesso ordine | 16,29 / 13,80 (caricamento dei vettori a freddo, uguale in prod) |
| `cerca_riferimenti` «progesterone e sonno» | stessi 5 id, stesso ordine | 0,89 / 0,73 |
| `cerca_tutto` «testosterone nella donna» | ordine diverso nelle posizioni 3-5 | 2,67 / 1,74 |
| `leggi_reel reel:415`, `leggi_articolo blog:1713`, `leggi blog:275` | identici | 0,02-0,04 |
| errori: `reel:99999999`, `pippo` | stesso messaggio chiaro | 0,01 |

(Il testo differisce solo nel dominio dei link `apri_nel_brain`, perché la copia ha un altro `BRAIN_BASE_URL`: normalizzato, identico.)
L'unica differenza vera è «testosterone»: l'ordine dipende dal riordino fatto da Groq e **cambia da una
chiamata all'altra anche sul bridge di produzione** (3 prove ciascuno: prod ha dato due ordini diversi, il
ramo lo stesso ordine tre volte). Differenza spiegata, non regressione.

**Groq che rifiuta** (chiave finta -> 401; bridge a lato :8126; Ollama caricato con il 7b nel frattempo):
```
cerca_reel      28,63 s  (primo uso: caricamento dei vettori; non è Groq)   ordine semplice
cerca_articoli   2,11 s
cerca_tutto      2,22 s
cerca_riferimenti 4,05 s
llm_calls: una riga groq 'failed' (LLMCreditError ... 401); nessuna riga ollama; il log dice
"[rerank] fallito, tengo l'ordine del blend: LLMRemoteUnavailable(...)"; 0 menzioni di ollama/11434.
```
La ricerca risponde lo stesso, in 2-4 secondi a caldo, senza toccare Ollama. (Provato solo il 401; il 429 «al
minuto» sul riordino è coperto dai test, non l'ho provocato.)

### 4. Giro vero della pipeline a lato (3 reel + 3 articoli rimessi in attesa nella copia)

Reel 765, 697, 848 (`enrich` e `argument` -> `pending`), articoli 234, 1938, 330 (idem). Parcheggiati nella copia 6
reel «da trascrivere» (audio non presenti nella copia) e 35 articoli con affermazioni in attesa, così il giro tocca
solo i sei scelti. `--skip-scrape --skip-blogscrape` (non ho voluto fare richieste vere a Instagram né ai blog: vedi sotto).

`run_pipeline --dry-run`: elenca 8 stadi (scrape, download, transcribe, enrich, embed, blogscrape, knowledge,
cluster), nessun `batch`, nessun lucchetto preso.

**A. Groq vero** (`--limit 3`): 
```
download 0.1s · transcribe 0.0s · enrich 12.2s {'enriched': 3, 'arguments': 18, 'enrich_failed': 0} · embed 37.1s
knowledge 43.3s {'enriched': 3, 'arguments': 18, 'enrich_failed': 0} · cluster 55.8s
stage_runs: 6 righe, nessun 'batch', tutte done
llm_calls: groq/gpt-oss-120b 12 riuscite (1,3 s l'una); 5 'failed' = rate limit, ciascuna seguita da attesa vera:
  "[llm] groq rate-limited — waiting 3s (1/6)", 9s, 12s, 12s, "2s (2/6)"   -> nessun contenuto è finito sul 7b
```
Zero chiamate `ollama`; `enrichments.llm_model` = `openai/gpt-oss-120b`; `owner_type` invariato (competitor).
L'attesa sul tetto al minuto l'ho vista accadere davvero (5 volte), non solo nel test con il finto.

**B. Groq rifiuta** (chiave finta; `PIPELINE_LOCAL_MAX_CALLS=2` per non aspettare ore):
```
enrich 289.3s {'enriched': 2, 'deferred': 3, 'stopped': 'tetto di chiamate al modello locale'}
knowledge 0.1s {... 'deferred': 3, 'stopped': 'tetto di chiamate al modello locale'}
"Fermato: usate le 2 chiamate al modello locale del giro. 3 restano in attesa per il giro dopo."  (nota di stage_runs)
stato finale: reel 697 e 848 enrich=done argument=pending; reel 765 enrich=pending; 3 articoli enrich=pending; ZERO failed
llm_calls: 1 riga groq failed (401, 0 s), poi ollama qwen2.5:7b-instruct-q4_K_M, una alla volta (11:15:49-11:18:32, poi 11:18:33-11:20:38), 0 troncate
```
Secondi veri sul 7b (analisi di un reel, 840-1.513 token letti, 163-299 scritti, tetto 1.200-2.000):

| Chiamata | Totale | Caricamento | Lettura | Scrittura |
|---|---|---|---|---|
| 1ª (a freddo) | 163 s | 22 s | 97 s | 44 s |
| 2ª | 126 s | 0 | 70 s | 55 s |
| 3ª (giro C) | 99 s | 0 | 65 s | 34 s |
| 4ª (giro C, affermazioni) | 119 s | 0 | 55 s | 64 s |
| 5ª (giro D: Ollama riavviato da un altro servizio, vedi D5) | **342 s** | **184 s** | 62 s | 96 s |

Media sulle prime quattro **127 s** (non i 251 s del calcolo del disegno: i prompt erano più corti, 840-1.500 token).
Con il caricamento rifatto, 342 s. Nessuna chiamata è arrivata vicino al tetto di 1.500 s.
Qualità del 7b: JSON valido e italiano leggibile sui 3 reel; ma su un reel traduce «brain fog» con «fuga del cervello»
(il 120b aveva scritto «brain fog»). I temi sono più generici, come previsto dal disegno.

**C. Un job di link mentre un giro lavora** (giro locale in corso con il lucchetto preso; `POST /uploads/from-links/`
con una pagina NHS): il job `link_transcribe` finisce in <10 s su Groq (2 chiamate `job:link_transcribe`, 0,8 s e 1,4 s), crea l'articolo 2269
(`owner_type=competitor`). Il lucchetto non lo tocca e il suo lavoro non passa dal 7b. (Provato con un link, non con un file audio/video.)

### 5. Lucchetto (percorso a lato in `PIPELINE_LOCK_PATH`, mai quello vero)

```
giro 1 in corso (enrich locale)  ->  secondo giro:
[10:16:53 UTC] ✗ un altro giro sta già lavorando: questo non parte (uno alla volta; riprova quando ha finito)
exit=3        (nessuna riga in stage_runs dal secondo giro)
POST /ops/run/ (bottone «Aggiorna ora») con un giro vivo -> {"detail":"L'aggiornamento automatico è già in corso in questo momento. Riprova quando è finito.","already_running":true}
kill -9 del primo giro (cluster, dopo 12 s) -> il file del lucchetto resta (0 byte) ma un terzo giro parte subito e finisce exit=0
```
Dopo il `kill -9` la riga `stage_runs` del giro ucciso (id 40, cluster) resta `running` per sempre; la pagina Avanzamento
la ignora e dice «Non sta girando niente» (comportamento già così; lo scrivo perché si vede nei dati).

### 6. L'app da utente vero (Chromium headless a 1280 px e a 380 px, accesso dalla pagina di login)

- **La chat non c'è più**: il menu (desktop e mobile, aperto con l'hamburger) ha Libreria, Analytics, Timeline, Cluster,
  Piano editoriale, Mappa (DAG), Workspace, Fonti, Documentazione, Stato pipeline, Avanzamento. `/knowledge-bank` e
  `/knowledge-bank?q=x` finiscono in Home (desktop e mobile). Su 11 pagine controllate il testo non contiene mai «chat»;
  17 link interni distinti raccolti: nessuno verso `knowledge`/`chat`. `POST /knowledge/ask/` = 404, `GET /knowledge/search/` = 200.
- **Pagina `Documentazione`**: nessuna parola su Anthropic, Sonnet, Opus, Claude (salvo «il tuo Claude» del connettore), batch, flow,
  HuggingFace; «Analisi in blocco (non più in uso)» compare solo nello storico dei giri vecchi. La tabella dei modelli dice:
  Analisi `gpt-oss-120b -> riserva: qwen2.5:7b-instruct-q4_K_M`; Piano editoriale e Riordino «solo Groq, nessuna riserva».
- **`ContentDetail`** (`/content/blog/275`, `/content/reel/415`) si apre da link diretto, desktop e mobile; il tasto «Chiudi» porta
  in `/`; un id inesistente (`/content/blog/99999999`) mostra «Questo contenuto non esiste più...» e «Torna alla Home» porta in `/`.
- **Stato e Avanzamento**: lo storico dei giri (15 nov 10:07, 03:30...) disegna i giri vecchi con «Analisi in blocco (non più in uso)»,
  senza riquadro «In consegna». Durante il giro B la pagina Avanzamento mostrava lo stadio «Analisi dei contenuti — In corso — modello
  locale», la riga «@manupausa · ... sta scrivendo qwen2.5:7b... 2 min 160 token», e dopo il giro D la nota **«Fermato: usate le 1 chiamate
  al modello locale del giro. 1 restano in attesa per il giro dopo.»** (desktop e mobile). Stato mostra «3 reel da lavorare» (i `pending`).
- **Vuoto / caricamento / errore**: Workspace vuoto «Niente qui ancora.»; piano editoriale in caricamento («Costruisco il piano...», pulsante
  con rotellina, toast con barra) e in errore (toast rosso «Fallita»).
- **Funzioni di scrittura con Groq vero** (`openai/gpt-oss-120b`), una prova ciascuna:
  - **Piano editoriale** (dal bottone «Genera un piano», 6 contenuti): 6,1 s, 2.643 token su 3.600. **Usabile.** Italiano corretto, argomenti
    plausibili con il «perché» ancorato ai numeri (es. «Competitor ha 12 reel su cortisol e sonno, Medyca non ha contenuti...»).
    Piccolo difetto: trattini non separabili (U+2011) in «anti‑aging», «GLP‑1».
  - **Ideazione** (4 idee): 1,4 s, 509 token. **Usabile** (argomento e motivazione ok; gancio e formato vuoti, come da prompt attuale).
  - **Brief di strategia** («progesterone bioidentico e sonno in perimenopausa»): 2,2 s, **900 token su 900 = tagliato** (3.177 caratteri,
    finisce con «Azione sul GABA e»). **Non usabile così com'è.**
  - **Bozza di strategia**: 2,7 s, **1.200 su 1.200 = tagliata** (finisce dentro una tabella: «Assenza di utero + insonnia»). Contiene
    dosaggi precisi («100 mg mattina + 100 mg sera»): il testo medico va riletto da una persona.
  - **Bozza blog** («Espandi articolo» da `ClusterDetail`, via UI): 3,0 s, **1.200 su 1.200 = tagliata** a metà frase («...per via transdermica o vaginale,»).
  - **Piano con Groq che rifiuta**: il lavoro fallisce subito con **«Errore: Il servizio dei modelli ha raggiunto il suo limite in questo
    momento. Riprova più tardi.»** (job 98: `LLMRemoteUnavailable`, 1 riga `groq failed`, 0 chiamate ollama). I 38 s del job sono il caricamento
    dei vettori a freddo, non l'attesa di Groq.

Screenshot guardati (cartella `.../scratchpad/coll/shots/`): home, libreria, menu mobile aperto, Avanzamento (in corso, fermo, con nota del tetto),
Stato (coda e storico), Documentazione (storico e modelli), ContentDetail (desktop/mobile/404), piano in caricamento e in errore (380 px).

### 7. Ambiente vecchio con codice nuovo (`LLM_ENDPOINTS=anthropic,groq,flow`, `BATCH_*`, `ANTHROPIC_*`, `HF_*`)

```
manage.py check                   -> System check identified no issues (0 silenced).
client._providers()               -> [anthropic(base https://api.anthropic.com), groq, flow]   (le chiavi Anthropic/flow erano finte)
chat_json x3                      -> {'ok': True} in 0,48 / 0,62 / 0,50 s
WARNING llm.client [llm] anthropic: anthropic has no model 'claude-sonnet-5'      (ad ogni chiamata)
llm_calls: anthropic failed x3 (LLMModelMissing) + groq done x3
```
**Va avanti, senza errore e senza crash**, ma *rumoroso e sprecone*: l'endpoint `anthropic` resta il primo della catena, viene tentato con il
dialetto OpenAI (`/chat/completions` su `api.anthropic.com`, risposta 404), scrive una riga `failed` in `llm_calls` e un WARNING **a ogni chiamata**,
poi passa a Groq. Con la chiave vera sarebbe stata mandata a Anthropic a ogni chiamata (D2). Dimenticare il `.env` quindi non rompe nulla, ma sporca
`llm_calls` (le righe `anthropic` non sparirebbero dal controllo del passo 7 del rilascio) e allunga ogni chiamata di ~0,3 s.

### Difetti

**Bloccanti: nessuno.**

**Non bloccanti (in ordine di gravità)**

- **D1 (serio). Brief di strategia, bozza di strategia e bozza blog escono tagliati a metà frase con Groq** (900/900, 1.200/1.200, 1.200/1.200 token).
  Tre prove su tre: è il caso normale, non un caso raro. Sul 120b i token di ragionamento contano nel tetto. In più `llm_calls.truncated` resta `false`
  (la risposta Groq tagliata torna come stringa: è il limite già scritto nella sezione 3), quindi nessuno se ne accorge e la pagina Avanzamento non lo mostra.
  Non è una regressione del ramo (su `main` la catena `anthropic -> groq` darebbe lo stesso), ma il ramo dichiara che queste funzioni restano su Groq.
  Da decidere: alzare i tetti (strategia 900 -> ~1.800, bozze 1.200 -> ~2.400) e/o trattare `finish_reason=length` di Groq come `truncated`.
- **D2. Ambiente vecchio: ogni chiamata prova prima `anthropic`** (sezione 7). Basta il passo 3 del rilascio (pulire il `.env`) o ignorare nel codice
  gli endpoint con nome sconosciuto. Se il `.env` non viene pulito, la chiave Anthropic vecchia continua a uscire verso `api.anthropic.com`.
- **D3. Mobile 380 px: il toast di errore taglia «Riprova più tardi»** («Errore: Il servizio dei modelli ha raggiunto il suo...»): la frase che dice
  cosa fare è proprio quella nascosta. Il messaggio dice «limite» anche quando la chiave è rifiutata (401).
- **D4. Avanzamento, stima del 7b ottimistica**: durante una chiamata locale la pagina diceva «MANCANO circa 12 s» e «velocità 5,2 al min» mentre la riga
  sotto diceva «di solito ancora circa 4 min · al massimo 21 min». Testo: «le 1 chiamate» (singolare).
- **D5. Il 7b condivide la macchina**: durante il giro D un altro servizio (`medyca-crm-dev/transcriber`, 226% CPU) girava e Ollama si è riavviato alle 11:43: la
  chiamata ha chiesto 342 s (184 s di solo caricamento) contro 99-163 s delle altre. Il tetto di 40 chiamate vale quindi 1,1-3,8 ore, non 2,8.
- **D6. Qualità del 7b** su un reel («fuga del cervello» per «brain fog»); atteso dal disegno, ma conferma che i temi generati dal locale vanno guardati.

**Già presenti su `main`, non del ramo (non verificati su main, solo visto che i file non sono toccati)**: tabella «Ultime esecuzioni» di `Documentazione`
tagliata a destra a 380 px (colonne «Quando/Durata»); nella stessa pagina «ogni giorno alle 04:00 — Aggiornamento completo» mentre il crontab alle 04:00 lancia
`prune_llm_calls`; titoli di fonti con testo rovinato («â» al posto del trattino) nei brief; riga `stage_runs` che resta `running` dopo un `kill -9`;
immagini dei reel rotte nella mia copia (mancano i file in `media/`: è la copia, non il ramo).

### Cosa NON ho potuto provare, e perché

- **Stadi `scrape` e `blogscrape`**: saltati nel giro (non volevo fare richieste vere a Instagram dall'IP di produzione né ai blog). Il dry-run li elenca; il loro
  codice non è toccato da questo ramo, salvo che `blogscrape`/`knowledge` usano la catena nuova.
- **Trascrizione vera**: nella copia non ci sono i file audio (6 reel «da trascrivere» parcheggiati). Provato solo un link-articolo; **non un upload di file audio/video** né un link YouTube.
- **Il servizio vero `medycabrain-mcp`** (riavvio, passaggio da Caddy/Cloudflare, accesso OAuth di claude.ai): ho provato il codice del ramo in un bridge a lato; il riavvio dei due
  servizi, il `.env` pulito e la ricerca «vera» dal Claude del cliente restano al rilascio.
- **Il cron vero** (03:30/14:15) contro il lucchetto: provato con processi a mano e un percorso di lucchetto a lato, non con due `cron` reali.
- **Un 429 di Groq sul riordino MCP** (provato solo il 401), e il tetto *giornaliero* di Groq con i modelli fratelli (coperto da test, non provocabile senza consumare il tetto).
- **Giro grosso e tetto di 40 chiamate**: usato 1-2 come tetto; non 40 in fila (sarebbero ore). Le ore reali vanno guardate in `llm_calls` il 29/11, come deciso.
- **Il rientro del CSV** nel «tornare indietro» e `ollama rm` / `pip uninstall anthropic` (passi di rilascio, non toccati).
- **La rete di test** resta sottile sulla parte visiva: un verde dei 317 test non dice nulla sul toast a 380 px o sul testo tagliato; li ho visti solo guardando.

### Fine prova

Postgres a lato fermato e cartella dati cancellata; backend (:9193), ponti MCP (:8125, :8126) e interfaccia (:9194) spenti, porte libere; file di ambiente con le chiavi,
token di prova, copie dati e log con il percorso segreto cancellati; `BEC/logs` della copia cancellato; `/tmp/medycabrain-test-*.lock` tolto. Cartella principale: ancora su
`main`, `git status` vuoto, `BEC/.env` non toccato; `:9093` risponde 200. In `/tmp` resta solo `medycabrain-ollama.lock` (è il lucchetto vero di Ollama, non mio).
Il file `.claude/tasks/2026-11-14-analisi-in-casa.md` **della copia** ha la sezione 5 scritta e non è committato.
### Secondo giro (collaudo del 15/11, 12:00-12:25, commit `8e5d1bd`)

Stessa impostazione del primo giro: copia a lato, Postgres usa-e-getta (porta 55461) con una copia nuova di sola lettura dei dati di
produzione, backend :9193, ponte MCP :8125, interfaccia :9194. Per forzare i casi difficili ho scritto un **finto Groq a lato** (:9300, compatibile
OpenAI) che a comando inoltra al Groq vero, risponde «tagliata» (`finish_reason: length`), risponde 401 o accetta e non risponde mai; e due
**ascoltatori finti** (:9291, :9292) al posto di Anthropic e flow per contare le richieste. Controllato `pgrep -af run_pipeline`: nessun giro vero
(il cron delle 14:15 è lontano). Produzione, `.env` (ultima modifica 13/11), crontab, servizi, `FEC/dist`: non toccati.

**Verdetto: PASSA.** Nessun bloccante; tutti i rilievi del primo giro sono risolti nei casi provati. Restano tre osservazioni piccole (sotto).

**1. Suite, migrazione, tipi, build**
```
Found 336 test(s).   Ran 336 tests in 39.400s   OK
makemigrations --check --dry-run -> No changes detected      manage.py check -> no issues
npx tsc --noEmit -> tsc=0                                    npm run build -> ✓ built in 20.55s
/tmp dopo la suite: solo medycabrain-ollama.lock (quello vero di Ollama); nessun medycabrain-test-*.lock
migrate sulla copia nuova -> Applying core.0027_drop_batchrun... OK
```

**2. D1 da utente vero.** Con Groq vero (note: il limite giornaliero del 120b a un certo punto si è esaurito per i miei test e la catena è passata ai modelli fratelli, vedi sotto):
- Brief di strategia: 2,8 s, 1.172 token su tetto 1.800, 4.187 caratteri, finisce con una frase intera («...sul timing di assunzione.»).
- Bozza di strategia: 4,1 s, 1.727 su 2.400 (col vecchio tetto 1.200 sarebbe stata tagliata), 5.981 caratteri, finisce con l'elenco delle fonti, completo.
- Bozza blog (bottone «Espandi articolo» nell'interfaccia, `ClusterDetail`): 3,4 s, 1.399 su 2.400, 5.099 caratteri, chiude con una nota entro la frase.
- (Il brief e la bozza di strategia non hanno un bottone nell'interfaccia: li ho lanciati con `POST /second-brain/briefs/analyze/` e `/briefs/<id>/draft/`, come nel primo giro.)

Taglio forzato (finto Groq in modalità `length`):
```
job 95 strategy        failed  «Errore: Riprova: la risposta del modello è stata tagliata prima della fine e non la mostro a metà.»
job 96 strategy_draft  failed  idem
job 97 blog            failed  idem
llm_calls: 3 righe groq status=failed, truncated=TRUE, error "LLMTruncated: groq: risposta tagliata al tetto di 2400 (1800) token"
strategy_briefs 8 -> 8, blog_drafts 5 -> 5, draft_md del brief invariato (5.981): nessun testo a metà salvato
risposte HTTP: tutte 202; nessun 500 nel log del backend; nessuna riga `ollama` (non va al 7b)
```
Screenshot a 380 px (`shots/blog2-len-mob-2.png`): il toast «Generazione articolo blog — Fallita» mostra il messaggio intero, a capo.
Piccola cosa: sulle righe `failed+truncated` la colonna `output_tokens` resta vuota (si vede solo il tetto).

**3. R1, ricerca MCP con Groq che pende** (finto Groq che accetta e non risponde; `cerca_tutto` da client MCP vero):
```
Groq normale (a caldo)          3,65 s
Groq pende, ricerca 1          13,69 s   risultati veri (4.887 caratteri), isError=False
Groq pende, ricerca 2          13,28 s
llm_calls: mcp:cerca failed 10,0 s «ReadTimeout ...»; log «[llm] groq timed out after 10s — not retrying» e «[rerank] fallito, tengo l'ordine del blend»
righe ollama: 0
```
Circa 10 s di attesa Groq più 3 s di lavoro di ricerca (stessi 3 s della ricerca normale): non più 120 s.

**4. R2, chiave rifiutata, e ripartenza senza riavvio** (bridge a lato con `LLM_RETRY_DISABLED_AFTER=20`):
```
chiave 401 -> ricerca 2,03 s (ordine semplice); 1 richiesta arrivata al finto Groq; log «groq key rejected/depleted — disabling it»
ricerca subito dopo, e con la chiave già tornata buona ma dentro i 20 s -> richieste al finto Groq ancora 1 (Groq saltato)
dopo 22 s, ricerca -> richieste 2, ultima riga llm_calls «groq done mcp:cerca»: il riordino è ripartito senza riavviare il bridge
```
Nota di stadio e pagina Avanzamento (giro con chiave finta):
```
stage_runs enrich: «Groq non risponde: chiave rifiutata; il lavoro va sul modello locale. Fermato: usata la chiamata al modello locale del giro. 3 restano in attesa per il giro dopo.»
stage_runs knowledge: «Groq non risponde: chiave rifiutata; il lavoro va sul modello locale»
```
La stessa frase è nella pagina Avanzamento (box dello stadio, 380 px e 1280 px, `shots/av2-end-mob.png`).

**5. R3, locale non disponibile, Groq che rifiuta** (3 reel + 3 articoli in attesa):
```
Ollama irraggiungibile (OLLAMA_URL su porta morta): enrich 0,2 s {'deferred': 3, 'stopped': 'modello locale non disponibile'}
  llm_calls: groq failed (401) + ollama failed «LLMLocalUnavailable: Ollama non raggiungibile: ConnectionError»
  nota: «...Fermato: il modello locale non era disponibile (occupato o spento). 3 restano in attesa per il giro dopo.»
Slot occupato (lucchetto di Ollama a lato tenuto da un'altra processo, attesa 8 s): enrich 8,1 s e knowledge 8,2 s, ciascuno
  «LLMBusy: ollama busy: no free slot after 8s», nota uguale
stato dopo entrambi: reel 3 x pending/pending, articoli 3 x pending/pending, FAILED = 0
giro dopo con tutto a posto (Groq vero): enrich {'enriched': 3, 'arguments': 16}, knowledge {'enriched': 3, 'arguments': 17}, cluster ok
  -> reel 3 x done/done, articoli 3 x done/done
```
Non ho fermato il vero Ollama: per «spento» ho usato l'indirizzo sbagliato, per «occupato» il lucchetto a lato. Piccola cosa: se Groq è spento e Ollama
irraggiungibile, lo stadio `knowledge` salta da solo (`client.available()` falso) in 0,0 s e la sua nota dice solo la frase su Groq, non «3 restano in
attesa»; i contenuti restano comunque `pending`.

**6. D2, ambiente vecchio** (`LLM_ENDPOINTS=anthropic,groq,flow`, chiavi finte, `BATCH_*`, `HF_*`; i finti Anthropic e flow su :9291/:9292):
```
LLM_ENDPOINTS: fornitori sconosciuti ignorati (anthropic, flow); ammessi: groq. Si possono togliere dal .env.     <- un solo avviso per processo
catena: [('fast','groq'), ('ollama', None)]
chat_json x3 -> {'ok': True}; richieste arrivate ai finti Anthropic e flow: NESSUNA (0)  (il finto risponde: verificato a mano con una richiesta di prova)
la chiave vecchia non compare nell'avviso né nei log
```
- `LLM_ENDPOINTS` con **solo nomi sconosciuti** (`anthropic,flow,hf`): stesso avviso, nessun crash, `check` pulito; la catena diventa il vecchio endpoint
  «fast» (indirizzo e chiave `FAST_LLM_*`, modello `llama-3.3-70b-versatile`, che Groq ora non serve: «fast has no model...») e poi Ollama.
- `LLM_ENDPOINTS` **vuoto**: **nessun avviso**, stessa catena («fast» e poi Ollama). Non crasha, ma tutto va a finire sul modello locale senza che nessuno lo dica.
  Il caso reale (`.env` con la riga persa) darebbe un sistema «tutto sul 7b» silenzioso: osservazione, non bloccante.

**7. D3 e D4** (Chromium, 380 px e 1280 px):
- Piano editoriale con Groq che rifiuta, 380 px: toast «Piano editoriale — Fallita — **Errore: Riprova più tardi: il servizio dei modelli non risponde o è al suo limite.**» intero, a capo (`shots/plan2-401-mob-2-fine.png`).
- Avanzamento durante una chiamata locale (380 px): «Analisi dei contenuti — In corso — modello locale», FATTI 0/3, **VELOCITÀ —**, **MANCANO —**,
  «sta leggendo qwen2.5:7b... 49 s», nessuna stima «mancano circa 12 s» (`shots/av2-mid-mob.png`). Al secondo controllo: «sta scrivendo ... 3 min 177 token 0,9 token/s
  di solito ancora circa 5 min · al massimo 34 min» (il 7b era rallentato da un altro servizio sulla macchina: la chiamata è durata 190 s).
- Plurale: «Fermato: usata **la chiamata** al modello locale del giro» (prima «le 1 chiamate»).

**8. Non-regressione**
- Ricerca MCP normale: `cerca_articoli` 3,65 s a caldo con Groq vero (via finto che inoltra), `cerca_tutto` 2-3 s; risultati veri.
- Giro corto con Groq vero (`--limit 3`, salta scrape/blogscrape): download 0 s, transcribe 0 s, enrich 17,3 s (3 reel, 16 affermazioni), embed 33 s, knowledge 109,7 s
  (3 articoli, 17 affermazioni), cluster 60 s; tutti `done`, nessun `failed`, nessuna chiamata riuscita su Ollama.
- Costo dei miei test: il 120b ha esaurito il suo tetto giornaliero («daily token budget exhausted», 9 chiamate) e la catena è passata a `qwen/qwen3.8-27b`,
  che ha lavorato (9 chiamate riuscite, 7 rifiutate al minuto e aspettate): conferma dal vivo che sul tetto giornaliero si passa ai fratelli. Avverto che **la chiave è la stessa
  di produzione**: i miei test (due giri e le prove di D1) hanno consumato token del giorno anche per il cron delle 14:15.

**Cosa NON ho potuto provare**
- Il servizio vero `medycabrain-mcp` e il suo riavvio, il `.env` vero, `migrate` e riavvio «uno dopo l'altro» di R6 (passi di rilascio).
- Ollama davvero spento (non l'ho fermato, come chiesto): coperto da indirizzo sbagliato e slot occupato.
- Un taglio vero di Groq (non l'ho visto accadere con i tetti nuovi: l'ho forzato con il finto `finish_reason: length`).
- 429 di Groq sul riordino MCP (solo 401 e attesa).
- Il toast a 1280 px nel caso di errore (guardato solo a 380 px; il codice è lo stesso, ma non ho aperto lo screenshot desktop).
- Una chiamata vera con la chiave Anthropic/flow: non è stata e non doveva essere fatta (chiavi finte).

**Osservazioni non bloccanti**: (a) `LLM_ENDPOINTS` vuoto cade in silenzio su «fast» + locale (sezione 6); (b) `knowledge` salta senza «N restano in attesa» quando nulla può servire;
(c) `llm_calls.output_tokens` vuoto sulle chiamate tagliate.

**Fine prova**: backend, ponte MCP, interfaccia, finto Groq e ascoltatori spenti, porte libere; Postgres a lato fermato e cartella dati cancellata; file di ambiente con le chiavi,
token, copie dati e log cancellati; `BEC/logs` della copia cancellato; in `/tmp` solo `medycabrain-ollama.lock` (vero). Cartella principale su `main`, `git status` vuoto, `BEC/.env` non toccato;
`:9093` risponde 200.

## 6. Rilascio           (rilasciatore)
## Registro delle decisioni

- 2026-11-14 - File aperto dall'architetto su incarico del capo, dopo la
  risposta di Giuseppe «Shifta tutto locale» (registro di
  `2026-11-14-pipeline-in-casa.md`, punto 2). Sostituisce la sezione «PR 2»
  di quel file. Disegno scritto, in attesa dell'OK di Giuseppe.
- 2026-11-14 - Rispetto al primo disegno cambia una proposta, e dico perché:
  il 3b non è più candidato (licenza «non commerciale», fatto 16), mentre
  prima lo indicavo come possibile scelta più veloce.
- 2026-11-15 - **Giuseppe cambia la portata** dopo aver letto i numeri del
  disegno (chat locale: circa 2 minuti a risposta). Parole sue:

  > Puoi chiudere la chat, con il modello sotto, alla fine il mio cliente usa
  > l'mcp quindi bene così. Rimovi le dipendenze delle api call di antrhophic.
  > O groq o chiamate al modello locale, punto

  Lettura del capo (interpretazione): «tutto locale» è superato. Il disegno
  qui sopra **non si esegue** così com'è. La portata nuova è più piccola:
  1. **La chat dentro l'app si chiude** (pagina e modello sotto). Il cliente
     usa il connettore MCP.
  2. **Via ogni dipendenza da Anthropic API**: lo stadio `batch`, il fornitore
     `anthropic` nella catena, la chiave. Via anche `flow` (rivende modelli
     Claude: è Anthropic per altra via, ed è contro la regola sulle
     credenziali rivendute).
  3. **La catena dei modelli resta di due anelli: Groq, poi il modello
     locale.** Niente altro. Groq resta, quindi la trascrizione resta su Groq
     Whisper e non serve Whisper in casa.
  4. Dal disegno vecchio restano validi i fatti misurati e le correzioni che
     fanno funzionare la riserva locale (finestra, tempi di attesa, un filo
     solo, lucchetto "un giro alla volta") e la sostituzione del 3b per la
     licenza non commerciale. Cadono: `LOCAL_ONLY`, chat a flusso, precedenza
     alle persone, Whisper locale, le tre PR.
  Fatto nuovo, giro del 15/11 alle 03:30 (`llm_calls`): Groq 118 chiamate
  riuscite e 169 fallite; modello locale 3b 23 riuscite; Anthropic 5 e `flow`
  4, tutte fallite. 10 reel e 54 articoli analizzati, zero falliti.
  L'architetto riscrive il disegno in una sezione nuova in fondo alla sua.
- 2026-11-15 - **Giuseppe approva la «Revisione del disegno (15/11)»** («Ok
  puoi andare»), con le proposte sulle quattro domande. Scelte chiuse:
  1. La tabella `batch_runs` si toglie con la migrazione `0027`, dopo aver
     salvato le 26 righe in un file (fuori dal repo se contengono testo del
     cliente; nel repo solo se sono puri numeri e date).
  2. Piano editoriale, riordino della ricerca MCP e giudice di `eval_mcp`:
     solo Groq, mai il locale. Se Groq rifiuta: il piano dice «riprova più
     tardi», la ricerca usa l'ordine semplice.
  3. Groq resta al livello gratuito. Fra due settimane (circa il 29/11) si
     guarda in `llm_calls` quanto lavoro è finito sul 7b.
  4. Al rilascio: `ollama rm` del 3b e via il pacchetto `anthropic`.
  5. Si tolgono anche `flow` e `hf` dalla catena (aggiunta dell'architetto,
     dentro «o Groq o locale, punto»).
  6. Si toglie solo la chat; strategia, ideazione, bozze blog restano su
     Groq → locale (lettura del capo, non contestata da Giuseppe).
  Vale solo la sezione «Revisione del disegno (15/11)»; tutto il disegno sopra
  è superato, tranne i fatti misurati.
- 2026-11-15 - **Primo giro: revisione passa (R1-R6), collaudo passa (D1-D6).**
  Nessun bloccante, ma il capo rimanda allo sviluppatore per un giro di
  correzione prima della PR, perché quattro punti toccano il cliente:
  R1 (ricerca MCP che può aspettare 120 s), R2 (Groq fuori uso senza dirlo),
  R3 (contenuti `failed` senza colpa), D1 (strategia e bozze tagliate a metà
  frase su Groq, 3 prove su 3, senza segnale). Si correggono anche D2 (nomi
  di fornitore sconosciuti nel `.env` ignorati con un avviso, così una chiave
  vecchia non esce più), D3, D4. R4, R5, R6, D5, D6 vanno nei limiti noti e
  nei passi di rilascio. D6 e i dosaggi nella bozza di strategia: la qualità
  dei testi va riletta da una persona, è scritto tra i limiti.
- 2026-11-15 - **Secondo giro: revisione passa, collaudo passa** (336 test).
  Il capo apre la PR. Restano aperti come limiti noti, non corretti qui:
  N1-N6 della revisione e le tre osservazioni del collaudo (`LLM_ENDPOINTS`
  vuoto cade in silenzio sul locale; nota di `knowledge` senza «N restano in
  attesa» quando Groq e Ollama mancano insieme; `output_tokens` vuoto sulle
  chiamate tagliate). Fatto da sapere: il collaudo ha usato la chiave Groq di
  produzione e il 15/11 ha esaurito il tetto giornaliero di `gpt-oss-120b`
  (la catena è passata al modello fratello). I prossimi collaudi devono
  contare i token o usare una chiave a parte.
