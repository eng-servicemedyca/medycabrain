---
id: 2026-11-18-locale-parallelo
titolo: Il modello locale lavora su 3 lavori alla volta
stato: revisione
ramo: feat/locale-parallelo
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Giuseppe, 18/11/2026, dopo la prova degli slot paralleli:
- «I'm saying to send the same items to multiple core CPU. So basically we can distribute and we can parallelize the computation.»
- Alla proposta «3 pezzi dello stesso articolo lungo» o «3 contenuti diversi» insieme: «the 7 billion now is fine, but we should test everything else… proceed with everything that can be used».

Quindi: usare i 3 slot di Ollama in tutti e due i modi, pezzi dello stesso testo lungo in parallelo e contenuti diversi in parallelo. Il modello resta il 7b. Il MoE (gpt-oss-20b) è in prova a parte, fuori da questo lavoro.

### Fatti già misurati (non da rifare)

- Ollama gira con `OLLAMA_NUM_PARALLEL=3` (drop-in `/etc/systemd/system/ollama.service.d/parallel.conf`, attivo dal 17/11 21:02).
- Prova del 18/11, 6 contenuti veri, analisi + affermazioni:
  | thread × slot | contenuti/ora | rispetto a oggi |
  |---|---|---|
  | 6 × 1 (oggi) | 14,4 | 1,00× |
  | 6 × 2 | 22,8 | 1,58× |
  | **6 × 3** | **27,9** | **1,94×** |
  | 8 × 3 | 20,7 | 1,43× |
  | 12 × 3 | 20,0 | 1,39× |
  | 8 × 2 | 16,4 | 1,14× |
  - Più thread peggiora: resta `num_thread=6`.
  - La cache dell'inizio comune (PR #29) regge per slot: la lettura delle affermazioni resta 6-14 s.
  - JSON sempre valido. Citazioni scartate: 8 con 3 slot contro 3 con 1 (probabilmente rumore).
  - Un contenuto da solo diventa più lento (fino a ~9 min), il totale per ora sale.
  - RAM del server ~14 GB su 94.
- Dati: `/home/medyca-admin/ricerche/banco-7b-2026-11-16/parallelo/` (`risultati.md`, `raw.jsonl`, `par.py`).

### Vincoli

- Owned e competitor mai nella stessa chiamata: ogni chiamata resta un solo contenuto (o un pezzo di un solo contenuto).
- Oggi il lucchetto `_ollama_slot` (flock) lascia passare una chiamata sola: va trasformato in N posti, N preso dalla configurazione e mai più alto di `OLLAMA_NUM_PARALLEL`.
- Chi chiama Ollama oltre la pipeline (MCP rerank è `remote_only`, lavori del cliente, blog_workflow) non deve restare bloccato per ore.
- I fallimenti restano `failed`; «modello non disponibile» lascia `pending`, come oggi. Un pezzo fallito porta il testo lungo a `failed`, come oggi.
- Il lock del giro (03:30 e 14:15) resta: i giri non si sovrappongono.
- Niente Anthropic nel giro quotidiano. Niente chiamate vere a Groq nei test.
- Documentazione nello stesso commit (02, 03, drawio, pagina Documentazione).

## 2. Disegno            (architetto, 18/11/2026)

Stato: **in attesa dell'OK di Giuseppe.** Nessuna riga di codice è stata scritta.

### 2.0 In sei righe

1. Il lucchetto del modello locale passa da 1 posto a N posti (N = 3 in produzione, 1 se non si scrive niente nel `.env`: così la PR, da sola, non cambia nulla finché non si accende).
2. I contenuti **corti** (fino a 8 000 caratteri) si lavorano 3 alla volta. I contenuti **lunghi** si lavorano uno alla volta, ma con 3 pezzi insieme. Così il modello locale non ha mai più di 3 richieste nostre: è esattamente la situazione misurata (27,9 contenuti l'ora contro 14,4).
3. **Groq resta uno alla volta.** Non è una scelta di gusto: negli ultimi 7 giorni, con un solo lavoro alla volta, Groq ha già rifiutato 397 richieste su 823 per il tetto al minuto. Mandargliene 3 insieme non lo fa andare più veloce, lo fa rifiutare di più.
4. Quindi il guadagno si vede **solo quando Groq è fuori** e il lavoro cade sul modello locale: lì il giro dura circa la metà (un giro grosso calcolato a ~9 ore scende a ~4,7 ore). Con Groq che funziona non cambia niente.
5. Un lavoro avviato dal cliente (carica un'intervista, genera una bozza) passa davanti al giro notturno: il giro finisce le risposte che ha in corso e non ne inizia di nuove finché il cliente non ha avuto la sua.
6. Una sola PR. Nessuna tabella nuova, nessuna migrazione, nessun endpoint nuovo.

### 2.1 Vincoli misurati (e cosa è solo supposto)

**Misurato oggi** (comandi di sola lettura; il database è quello di produzione, solo `SELECT`):

| Fatto | Numero | Come l'ho accertato |
|---|---|---|
| Ollama ha 3 posti | `OLLAMA_NUM_PARALLEL=3` | `systemctl show ollama -p Environment` e `/etc/systemd/system/ollama.service.d/parallel.conf` |
| L'app non sa quanti posti ha Ollama | Ollama non lo dice via API (`/api/ps` non lo riporta) | lettura di `/api/ps`; quindi il numero va scritto anche nel nostro `.env` |
| In produzione oggi si lavora 1 contenuto alla volta | `ENRICH_WORKERS` non è nel `.env` (vale 1) | `grep` sui nomi delle variabili in `BEC/.env` (senza leggere le chiavi) |
| Groq è già al suo tetto con 1 lavoro alla volta | 426 risposte buone, **397 rifiuti** in 7 giorni, tutti «riprova tra 1-15 s» (tetto al minuto) | `LLMCall` raggruppate per provider e stato, ultimi 7 giorni |
| Il modello locale lavora poco | 46 chiamate in 7 giorni (41 `pipeline:knowledge`, 5 `pipeline:enrich`), contro 823 tentativi su Groq | stessa query, per `process` |
| Nessun altro stadio ha usato il modello locale | 0 chiamate locali da `cluster`, `blogscrape`, lavori del cliente in 7 giorni | stessa query |
| Con 3 posti i tempi restano lontani dai tetti | risposta più lunga 386 s (tetto 1 500 s), lettura più lunga 44 s (tetto di silenzio 600 s) | `raw.jsonl` della prova, configurazione 6 × 3 |
| Testi lunghi che esistono | 554 articoli su 2 311 e 189 trascrizioni su 1 518 superano 8 000 caratteri; il più lungo 85 699 (15 pezzi) | `Length()` su `content_text` e `Transcript.text` |
| In coda adesso | 1 reel da analizzare, 10 articoli senza affermazioni, 0 testi lunghi | conteggi per stato |
| Le connessioni al database bastano | 7 in uso su 100 | `show max_connections`, `pg_stat_activity` |
| La pagina Avanzamento sa già mostrare più chiamate insieme | elenca tutte le chiamate aperte di uno stadio, non una sola | lettura di `BEC/core/progress_report.py` (`progress_snapshot`) |
| Il «quanto manca» si corregge da solo | usa i secondi **di orologio** per elemento degli ultimi 5 giri | lettura di `BEC/core/queue_eta.py` |
| Solo la strategia oggi chiede la precedenza | `priority=True` in 2 punti (`core/strategy.py`); caricamenti, bozze blog e idee no | `grep priority` |
| Chi chiama il modello | 16 punti; quelli che lavorano più contenuti in fila sono solo `enrich_agent`, `knowledge_agent`, `reprocess` | `grep` su `chat(` / `chat_json(` |

**Supposto, non misurato** (lo dico perché cambia quanto fidarsi):

- Che 3 **pezzi** dello stesso testo vadano veloci come 3 contenuti diversi. La prova è stata fatta su contenuti diversi; i pezzi sono richieste della stessa taglia (~1 750 token contro i 780-2 460 misurati), quindi è ragionevole, ma il numero vero lo dà il collaudo.
- Che un lavoro del cliente oggi resti indietro rispetto al giro. Lo deduco dal codice (chi aspetta riprova ogni secondo, il giro riprende il posto in pochi millesimi), non l'ho visto succedere: in 7 giorni nessun lavoro del cliente è finito sul modello locale.
- Il «~9 ore diventano ~4,7» è un calcolo (9 diviso 1,94), non una misura.

### 2.2 Come funziona, punto per punto

**a) Il lucchetto da 1 a N posti** — `BEC/llm/client.py`, `_ollama_slot`

- Oggi è un file-lucchetto solo. Diventano N file: il primo è quello di oggi (`OLLAMA_LOCK_PATH`), poi `.1`, `.2`. Chi vuole lavorare prova i posti in fila e prende il primo libero; se sono tutti occupati riprova ogni secondo, come oggi, fino a `OLLAMA_LOCK_WAIT` (1 800 s), poi «occupato» (il contenuto resta `pending`, non `failed`: regola di oggi).
- Tenere il file di oggi come posto numero 0 ha un vantaggio: un processo partito col codice vecchio durante il rilascio occupa un posto vero, e il totale non supera mai N.
- N viene da due righe nel `.env`: `OLLAMA_NUM_PARALLEL` (quanti posti ha Ollama: stesso nome della sua variabile, valore predefinito 1) e `LOCAL_SLOTS` (quanti ne usiamo: predefinito, tutti). Il codice usa il più piccolo dei due, mai meno di 1. Con niente scritto vale 1: comportamento di oggi.
- Limite onesto: il codice non può *leggere* il numero vero da Ollama. Se nel nostro `.env` si scrive 3 e Ollama ne ha 1, le richieste in più aspettano dentro Ollama in silenzio e dopo 600 s falliscono. Per questo il rilascio controlla i due numeri con `systemctl show ollama -p Environment` prima di accendere.

**b) Contenuti diversi insieme** — `enrich_agent._parallel`, usato anche da `knowledge_agent` e da `reprocess`

- Il meccanismo esiste già (`_parallel`, con i fili e la chiusura della connessione al database a fine filo). Si riusa; cambiano quattro cose:
  1. Il numero di fili non viene più da `ENRICH_WORKERS` ma da N (una manopola sola invece di due). Con N = 1 resta il giro semplice di oggi, senza fili.
  2. Prima i corti, N insieme; poi i lunghi, uno alla volta (ognuno usa N pezzi insieme, punto c). Senza questa divisione si avrebbero fino a 9 richieste in fila per 3 posti: più attesa, e il rischio di perdere il risparmio della PR #29 (il modello ritrova in memoria il testo appena letto solo se nel frattempo il suo posto non è stato usato da altri).
  3. I risultati si raccolgono **appena pronti**, non nell'ordine di partenza: oggi un primo contenuto lento tiene fermo il salvataggio dello stato di quelli dopo.
  4. Quando il modello non è disponibile (o il freno scatta) oggi il giro esce subito e butta via i risultati dei fili ancora al lavoro. Diventa: si alza una bandierina, i contenuti non ancora partiti non partono (restano `pending`), quelli in corso finiscono e **vengono registrati**. I tre contatori dei cicli in `enrich_agent.run` e `knowledge_agent.run` si adattano (non più `break`, si conta ogni rimandato).
- Ogni chiamata resta un solo contenuto: owned e competitor non si incontrano mai nella stessa richiesta. Niente in questo lavoro tocca `owner_type`.

**c) Pezzi dello stesso testo lungo insieme** — `pipeline/whole_text.py`, `read_whole`

- I pezzi partono su N fili. Ogni risposta torna al suo numero di pezzo, quindi appunti e affermazioni si ricompongono **nell'ordine del testo** qualunque pezzo finisca prima. Il resto (unione delle affermazioni, riassunto finale, un solo salvataggio) non cambia di una riga.
- **Niente salvataggi parziali**, come oggi: i fili dei pezzi non scrivono nulla del contenuto. Il salvataggio è uno solo, alla fine, in una transazione, nel filo che ha chiesto il lavoro (`save_whole_reel` / `save_whole_doc`, già esistenti).
- Un pezzo fallito: bandierina, i pezzi non partiti non partono (si risparmiano minuti), il contenuto è `failed` con «pezzo 3 di 7», come oggi. Se falliscono più pezzi vince quello col numero più basso, così l'errore scritto è sempre lo stesso a parità di causa. Un fallimento vero vince su «modello non disponibile»: i falliti restano falliti.
- Se nessun pezzo è fallito ma il modello è sparito a metà: il contenuto resta `pending` e i pezzi fatti si buttano (regola di oggi, già scritta nel modulo).
- Tre dettagli tecnici che lo sviluppatore deve rispettare: (1) ogni filo di pezzo parte con una copia del contesto (`contextvars.copy_context()`), altrimenti la chiamata perde il nome del contenuto e la pagina Avanzamento mostra righe senza nome (`llm/usage.py`, `_item_var`); (2) ogni filo chiude la sua connessione al database quando finisce (scrive solo la riga di `llm_calls`); (3) l'etichetta della chiamata diventa «… · pezzo 3/7», così il cliente non vede tre righe uguali.
- Vale per tutti quelli che usano `read_whole`: il giro, `reprocess` e il caricamento del cliente (`upload_workflow`). Un'intervista lunga caricata dal cliente va quindi più veloce anche lei.

**d) Connessioni al database e transazioni nei fili**

- Ogni filo Django ha la sua connessione. I fili dei contenuti scrivono l'analisi (come già oggi quando `ENRICH_WORKERS` > 1) e chiudono la connessione alla fine; il filo principale scrive gli stati. Nessuna transazione attraversa due fili. Al massimo 1 + 3 + 3 connessioni: 7 in più su 93 libere.
- `cluster_agent._get_embedder` (il modello dei vettori, usato per togliere le affermazioni doppie) oggi non ha lucchetto: tre fili insieme lo caricherebbero tre volte. Si aggiunge un lucchetto di tre righe, come quello che c'è già in `core/knowledge.py`.
- Per i test: un `TestCase` normale di Django chiude tutto in una transazione che i fili non vedono. I test coi fili usano finti modelli senza database, oppure `TransactionTestCase` (già usato in `test_migration_0027/0028`).

**e) Groq e i lavori insieme**

- Un cancello da 1 posto, dentro `client.chat()`, attorno al tentativo su Groq (attesa del tetto al minuto compresa). Con 3 fili, verso Groq si va comunque uno alla volta: identico a oggi. Il numero è in una riga di configurazione (`LLM_REMOTE_PARALLEL`, predefinito 1) per il giorno in cui Groq avrà un piano più largo.
- Le chiamate «solo remoto» (riordino della ricerca MCP, piano editoriale, giudice delle prove) **non** passano dal cancello: lì una persona aspetta, e oggi non fanno la fila.
- Niente chiamate vere a Groq nei test: il cancello si prova con un Groq finto.

**f) Se Groq torna (o sparisce) a metà**

- Chi risponde si decide chiamata per chiamata, già oggi. Quindi: le risposte che il modello locale sta scrivendo finiscono lì (non si interrompe un lavoro di minuti); la chiamata successiva prova Groq per prima. Capita che i tre fili lavorino uno su Groq e due sul locale: è voluto, si usano tutti e due.
- Già oggi lo stesso testo può avere il pezzo 1 su Groq e il pezzo 2 sul 7b (scritto in `whole_text.py`): non cambia.

**g) Il freno `PIPELINE_LOCAL_MAX_CALLS`**

- Il contatore ha già il suo lucchetto: con 3 fili conta giusto e non sfora. Quando scatta, vale la bandierina del punto b. Resta spento (0) come oggi.
- Cambia solo il conto scritto nei documenti: 40 chiamate non sono più ~2,8 ore ma circa la metà.

**h) Chi altro chiama il modello locale**

- Regola nuova, una riga: ogni chiamata fatta da un lavoro del cliente (etichetta `job:…`: caricamenti, bozze del blog, idee, strategia) ha la precedenza da sola, senza che ogni punto del codice debba ricordarsi di chiederla. Il giro (`pipeline:…`) e i comandi a mano (`cmd:…`) no.
- La precedenza oggi funziona così e resta così: finché una persona aspetta o è servita, il giro non inizia risposte nuove. Con 3 posti la persona aspetta che si liberi **il primo dei tre** (in media un terzo dell'attesa di oggi) e poi ha la macchina sempre più per sé.
- Una correzione necessaria: oggi due persone con precedenza si mettono in fila una dietro l'altra, senza limite di tempo. Con i pezzi in parallelo un caricamento lungo del cliente si bloccherebbe da solo. La bandierina della precedenza diventa «condivisa»: più persone la alzano insieme e poi si dividono i posti.
- La ricerca MCP non tocca mai il modello locale (già oggi): non è coinvolta.

**i) La pagina Avanzamento**

- Barra e conteggi: hanno già il lucchetto, tre fili contano giusto (c'è già un test con 4 fili in `test_progress.py`).
- Righe «chi sta lavorando»: la pagina elenca già tutte le chiamate aperte; se ne vedranno fino a 3 insieme, con «pezzo 3/7» per i testi lunghi. Nessuna modifica al frontend prevista; il collaudo lo guarda dal vero, mobile e desktop.
- «Quanto manca»: si corregge da solo dopo i primi giri (media degli ultimi 5). Per qualche giro resterà pessimista: sbaglia dalla parte giusta.
- Ogni singola risposta locale sarà più lenta (1,8 token al secondo invece di 3,2): la riga «velocità del modello locale» scenderà anche se il totale sale. Va detto nella pagina Documentazione, altrimenti sembra un peggioramento.

### 2.3 File da toccare

| File | Perché |
|---|---|
| `BEC/config/settings/base.py` | `OLLAMA_NUM_PARALLEL`, `LOCAL_SLOTS`, `LLM_REMOTE_PARALLEL`, con il commento e i numeri della prova |
| `BEC/.env.example` | le righe nuove; `ENRICH_WORKERS` sparisce |
| `BEC/llm/client.py` | lucchetto a N posti, precedenza condivisa e automatica per `job:`, cancello di Groq, commento in cima al modulo |
| `BEC/pipeline/whole_text.py` | pezzi in parallelo, ordine, bandierina, etichetta «pezzo i/n» |
| `BEC/pipeline/agents/enrich_agent.py` | `_parallel` (N, corti/lunghi, raccolta appena pronti, bandierina), i due cicli di `run`, commento in cima |
| `BEC/pipeline/agents/knowledge_agent.py` | i due cicli di `run` (stessa forma) |
| `BEC/core/management/commands/reprocess.py` | usa la stessa divisione corti/lunghi; la dimensione dei blocchi oggi dipende da `_WORKERS` |
| `BEC/pipeline/agents/cluster_agent.py` | lucchetto sul caricamento del modello dei vettori |
| `BEC/llm/usage.py`, `BEC/core/progress.py` | solo i commenti che nominano `ENRICH_WORKERS` |
| `BEC/core/tests/test_llm_chain.py`, `test_progress.py`, `test_whole_text.py`, nuovo `test_parallel.py` | 4 punti oggi usano `_WORKERS`; prove nuove: N posti, il quarto aspetta; precedenza condivisa; ordine dei pezzi con arrivi mescolati; pezzo fallito = niente salvato; bandierina = in corso registrati, non partiti `pending`; Groq uno alla volta |
| `documentation/low-level/02-pipeline.md`, `03-llm-and-embeddings.md` | stadi enrich/knowledge, tabella delle impostazioni, numeri della prova, limiti |
| `.claude/architecture-summary.md` | oggi dice «hence one worker» |
| `docs/medycabrain-pipeline-cliente.drawio` | pagina tecnica (e una riga in quella del cliente) |
| `FEC/src/i18n/it.json` | il testo della pagina Documentazione (vicino alla riga 378, dove si parla del modello locale) |

**Cosa si riusa**: `enrich_agent._parallel`, `_tracked`, `_with_retry` (fili e chiusura connessione); `client._ollama_slot` e `_prio_held` (stessa tecnica, più file); `save_whole_reel` / `save_whole_doc` (il salvataggio unico); il contatore `_take_local_call`; `usage.scope` per riconoscere i lavori del cliente; `progress_report` così com'è.

### 2.4 Rischi

1. **`owner_type`**: non toccato. Ogni chiamata resta un contenuto o un pezzo di un contenuto; nessun valore nuovo, nessuna richiesta mista.
2. **I falliti restano `failed`**: il rischio vero è al contrario, cioè marcare `failed` un contenuto sano per colpa della configurazione (N più alto dei posti di Ollama: attesa muta, 600 s, errore). Difesa: predefinito 1 e controllo al rilascio. Non c'è una difesa nel codice, e lo dico.
3. **Stato scritto a metà**: i fili finiscono sempre il loro contenuto prima che lo stadio chiuda; nessun filo viene ucciso. Se il processo muore, vale quello che vale oggi: analisi salvata, stato ancora `pending`, si rifà al giro dopo.
4. **Il giro si ferma se il cliente tiene occupato il modello più di 30 minuti di fila** (un'intervista lunga caricata mentre Groq è fuori): i contenuti restano `pending` con la nota «modello locale non disponibile» e ripartono al giro dopo. Succede già oggi con la strategia; con la precedenza automatica può succedere più spesso. È la conseguenza diretta della domanda 1.
5. **Qualità**: nella prova le citazioni scartate sono state 8 con 3 posti contro 3 con 1, su un solo giro. Probabilmente è caso, ma non è dimostrato. Il collaudo ripete il confronto.
6. **Niente credenziali di terzi**: nessun servizio nuovo, nessuna chiave nuova.
7. **Rilascio**: gunicorn e il connettore MCP vanno riavviati insieme, così nessuno resta col lucchetto vecchio. Tornare indietro è togliere una riga dal `.env`.

### 2.5 Alternative scartate

- **Tre fili anche verso Groq**: scartata dai numeri (397 rifiuti su 823 già con uno; il 15/11 con cinque fili erano stati 169 su 287).
- **Contenuti e pezzi tutti insieme senza divisione** (fino a 9 richieste per 3 posti): meno codice, ma è una situazione mai misurata e mette a rischio il risparmio della PR #29.
- **Tre processi separati invece di tre fili**: i contatori della barra e il freno vivono nella memoria di un processo; andrebbero rifatti nel database. Troppo per quello che dà.
- **Un posto riservato alle persone, il giro sugli altri due**: il giro non si fermerebbe mai, ma la persona andrebbe a 1,8 token al secondo invece di 3,2, e una bozza di blog rischierebbe il tetto dei 30 minuti.
- **Salvare i pezzi già fatti di un testo lungo** per non rifarli: serve una tabella; già scartato e scritto in `whole_text.py`. Non lo riapro.

### 2.6 Cosa resta fuori (dichiarato)

- Con Groq che funziona non si va più veloci: il limite è il suo tetto al minuto.
- Gli altri stadi che chiamano un modello (nomi dei temi in `cluster`, scelta degli articoli in `blogscrape`) restano uno alla volta: 0 chiamate locali in 7 giorni.
- La trascrizione locale (faster-whisper) non usa Ollama e non è toccata.
- Il numero di thread resta 6 e il modello resta il 7b. Il MoE è in prova a parte.
- Nessuna coda «giusta» (chi arriva prima passa prima): chi aspetta riprova ogni secondo, come oggi.
- I pezzi già fatti si buttano se il modello sparisce a metà di un testo lungo.
- Il codice non verifica da solo che Ollama abbia davvero N posti.

### 2.7 Domande per Giuseppe

1. **Se il cliente avvia un lavoro mentre il giro notturno sta usando il modello locale, chi passa?** Propongo: il cliente. Il giro finisce le risposte in corso e aspetta; se il cliente tiene occupato il modello più di 30 minuti, il giro lascia il resto al giro dopo (niente va perso, niente è segnato come fallito). L'alternativa è lasciare tutto com'è: il cliente si mette in fila col giro e può aspettare a lungo.
2. **Si accende al rilascio?** La PR arriva spenta (1 lavoro alla volta, come oggi). Propongo di scrivere 3 nel `.env` al rilascio, dopo che il collaudo ha rifatto la prova su una copia del database. L'alternativa è una notte a 2 prima di passare a 3.
3. **Va bene che Groq resti uno alla volta?** Vuol dire che nei giorni normali non si vede differenza: il guadagno arriva solo quando Groq è fuori. Se vuoi più velocità anche nei giorni normali, la strada è un piano Groq più largo, non questa PR.

## 3. Sviluppo           (sviluppatore, 20/11/2026)

Ramo `feat/locale-parallelo`, un commit. La PR arriva **spenta**: senza niente nel `.env`, `local_slots()` vale 1 e il comportamento è quello di prima.

### Cosa è stato fatto, file per file

| File | Cosa |
|---|---|
| `BEC/config/settings/base.py` | `OLLAMA_NUM_PARALLEL` (1), `LOCAL_SLOTS` (0 = tutti), `LLM_REMOTE_PARALLEL` (1), con il commento e i numeri della prova |
| `BEC/.env.example` | le tre righe nuove; `ENRICH_WORKERS` tolto |
| `BEC/llm/client.py` | `local_slots()`; `_ollama_slot` a N file (`OLLAMA_LOCK_PATH`, `.1`, `.2`: il file di prima è il posto 0); precedenza **condivisa** (`LOCK_SH` sul file `.priority`; chi è batch prova `LOCK_EX|NB` e fallisce se qualcuno la tiene); `_is_client_job()`: chiamate con processo `job:` hanno la precedenza da sole; cancello di Groq (`Semaphore(LLM_REMOTE_PARALLEL)`) attorno a `_patient`, saltato da `remote_only`; commento in cima |
| `BEC/pipeline/whole_text.py` | `_read_pieces`: pezzi su N fili, risposte rimesse in ordine di pezzo, bandierina, errore col numero di pezzo più basso, un fallimento vero batte «modello non disponibile»; ogni filo parte con `copy_context()`, aggiunge «· pezzo i/n» e chiude la connessione |
| `BEC/llm/usage.py` | `tag_item(suffix)` (l'etichetta è tagliata a 80: cede il titolo, non il suffisso); commento sul contesto copiato |
| `BEC/pipeline/agents/enrich_agent.py` | `_WORKERS` sparisce. `_parallel`: N da `local_slots()`; con 1 è il giro semplice di prima; con più: corti N insieme in filo (con `_with_retry`), poi lunghi uno alla volta; raccolta con `as_completed`; bandierina (anche quando l'errore dei *claims* è `NOT_THE_ITEMS_FAULT`, che `_enrich_then_claims` restituisce e non alza): chi non è partito torna con quell'errore e viene contato `skipped` sulla barra, chi è in corso finisce ed è registrato. I due cicli di `run` contano ogni rimandato (`deferred += 1`, `continue`, niente più `break`) |
| `BEC/pipeline/agents/knowledge_agent.py` | stessi due cicli di `run` |
| `BEC/core/management/commands/reprocess.py` | blocchi da `local_slots()`; un `NOT_THE_ITEMS_FAULT` ora ferma il comando e lo dice (prima finiva tra i «falliti» a video, senza toccare lo stato) |
| `BEC/pipeline/agents/cluster_agent.py` | lucchetto su `_get_embedder` (stessa forma di `core/knowledge.py`) |
| `BEC/core/progress.py` | solo un commento |
| Test | nuovo `core/tests/test_parallel.py` (38 prove); `test_progress.py` e `test_llm_chain.py` non nominano più `_WORKERS`; `_ChainCase` ora usa un file-lucchetto temporaneo (vedi sotto) |
| Documentazione | `02-pipeline.md` (righe enrich/knowledge, sezione nuova «Several at once», contatori), `03-llm-and-embeddings.md` (tabella impostazioni, paragrafo con i numeri), `architecture-summary.md`, `docs/medycabrain-pipeline-cliente.drawio` (due nodi tecnici + uno del cliente), `FEC/src/i18n/it.json` (pagina Documentazione) |

I tre punti segnalati dall'architetto: contesto copiato (pezzi **e** contenuti, c'è un test che apre lo scope in un filo non principale, il caso di un lavoro del cliente sul server web); precedenza condivisa; lucchetto sull'embedder.

### Scelte non ovvie

- **Precedenza condivisa con `LOCK_SH`**: i detentori non si aspettano tra loro, e il codice di chi controlla (`_prio_held`) non cambia di logica. Durante il rilascio un processo ancora col codice vecchio prende `LOCK_EX`: in quel caso i nuovi detentori aspettano che finisca (come prima); nessun danno.
- **Etichetta «pezzo i/n» solo con più posti**: con 1 posto i pezzi restano nel filo del chiamante e non si tocca la sua etichetta (così con la PR spenta non cambia nulla).
- **La divisione corti/lunghi** guarda `content_text` (articoli) o la trascrizione (reel, solo se `evidence == "transcript"`), la stessa regola di `_enrich_one` / `_read_whole_doc`. Se non riesce a deciderlo (oggetto strano) dice «corto»: sbagliare l'ordine non rompe niente.
- `_with_retry` (che chiude la connessione) si usa solo nei fili del pool; i lunghi girano nel filo principale con `_tracked`, come il caso N=1.

### Prove

- `manage.py test core`: **528 verdi** (erano 490 prima dei lavori precedenti; con `test_parallel` 38 nuove). `makemigrations --check`: pulito. `npm run build`: ok.
- Postgres usato per i test: una istanza **privata** avviata in `/tmp` sulla porta 5544 (non il database di produzione, di cui non ho letto le credenziali). Spenta a fine lavoro.
- Niente chiamate vere a Groq (`FAST_ENDPOINTS` finti, `_fast_chat` finto) e niente Ollama: il modello locale non è stato avviato per prove.
- Coperto dai test: N posti e il quarto che aspetta (poi `LLMBusy`), il file di prima come posto 0, precedenza condivisa, `job:` automatica, Groq uno alla volta (e 2 se impostato), `remote_only` non in coda, pezzi in ordine con arrivi rovesciati, pezzo fallito = non partono i successivi, errore col pezzo più basso, fallimento vero > «modello via», solo «modello via» passa intatto, contesto e processo ereditati dal filo, connessione chiusa, `_parallel` (ordine, corti poi lunghi, bandierina anche col N=1, errore dei claims che alza la bandierina), embedder caricato una volta.

### Cosa NON è stato provato (per il collaudo)

- Nessuna prova vera su Ollama con 3 posti e pezzi veri: che 3 **pezzi** dello stesso testo vadano come 3 contenuti diversi resta non misurato. Da fare sulla copia del database, e confronto delle citazioni scartate (8 con 3 posti, 3 con 1 nella prova del 18/11).
- La pagina Avanzamento dal vero, mobile e desktop, con 3 righe insieme e «pezzo 3/7».
- Il precedenza-del-cliente su due processi veri (i test la provano nello stesso processo: `flock` tra descrittori diversi si comporta come tra processi, ma non è la stessa cosa).
- Rilascio: prima di scrivere `OLLAMA_NUM_PARALLEL=3` nel `.env`: `systemctl show ollama -p Environment`; riavviare insieme gunicorn e il connettore MCP.

### Da sapere (per revisore e Giuseppe)

1. **Groq vivo ma al tetto: i fili non vanno sul locale.** Il cancello da 1 posto sta attorno anche all'attesa del tetto al minuto (come da disegno 2.2e): mentre un filo aspetta Groq, gli altri due aspettano il cancello, non vanno sul modello locale. Il guadagno c'è solo con Groq *fuori* (chiave rifiutata, o dopo che ha esaurito le attese). Va nella documentazione come limite; se Giuseppe vuole di più è un'altra decisione (cancello solo attorno alla richiesta, non all'attesa).
2. **Incidente di prova, già chiuso.** I test della catena (`_ChainCase`) usavano il lucchetto vero della macchina (`/tmp/medycabrain-ollama.lock`). Ora che una chiamata `job:` prende la precedenza, una prova partita mentre il modello era occupato è rimasta ferma a tenere il flag condiviso sul file `.priority` **di produzione** per circa 4-5 minuti (15:15-15:20 del 20/11), poi l'ho fermata io: il giro batch, se stava per iniziare una risposta, ha aspettato. Corretto: `_ChainCase` ora usa un file temporaneo; i miei lanci successivi usano anche `OLLAMA_LOCK_PATH` temporaneo. Il file `/tmp/medycabrain-ollama.lock.priority` esiste ancora (vuoto, nessun detentore: non blocca).
3. I test di `test_parallel` si appoggiano a tempi reali brevi (0,05-0,4 s) con margini larghi; se su una CI lenta uno fosse instabile, i punti sono i `sleep` dei test di `_parallel` e dei pezzi.
4. Righe «velocità» e «quanto manca» della pagina Avanzamento: non toccate, dette nella pagina Documentazione.
5. Cancellazione dei file `/tmp/test-*` lasciati dai test: abitudine già esistente dei test, non toccata.

### Cosa resta fuori (come da disegno 2.6)

Con Groq che funziona non si va più veloci; `cluster` e `blogscrape` restano uno alla volta; faster-whisper non toccato; thread 6 e modello 7b invariati; i pezzi già fatti si buttano se il modello sparisce; il codice non verifica che Ollama abbia davvero N posti; nessuna coda «giusta»; nessuna tabella, migrazione o endpoint nuovo.

## Registro

- 18/11 — capo: aperto il lavoro, lanciato l'architetto.
- 18/11 — architetto: disegno scritto (sezione 2). Scelte proposte: N posti dal `.env` (predefinito 1), corti 3 insieme e lunghi uno alla volta con 3 pezzi insieme, Groq uno alla volta, lavori del cliente con precedenza. Tre domande aperte in 2.7. In attesa dell'OK di Giuseppe.
- 20/11 — Giuseppe: OK al disegno. Risposte a 2.7: (1) sì, passa il cliente; (2) sì, 3 posti nel `.env` al rilascio, dopo la prova del collaudo su una copia del database; (3) sì, Groq resta uno alla volta. `stato: approvato`.
- 20/11 — sviluppatore: scritto il codice (un commit sul ramo), 528 test verdi, documentazione aggiornata. `stato: revisione`. Dettaglio e punti da guardare in sezione 3.
