---
id: 2026-11-18-locale-parallelo
titolo: Il modello locale lavora su 3 lavori alla volta
stato: pronto
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

1. Il lucchetto del modello locale passa da 1 posto a N posti (N = 3 in produzione, 1 se non si scrive niente nel `.env`: così la PR, da sola, cambia poco finché non si accende. Con N=1 restano uguali lucchetto, ordine, etichette e `_parallel`; cambiano la precedenza automatica dei `job:` (approvata), il cancello Groq da 1 posto anche fra fili dello stesso processo e la precedenza condivisa).
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

- Un cancello da 1 posto, dentro `client.chat()`, attorno al tentativo su Groq (attesa del tetto al minuto compresa). Con 3 fili, verso Groq si va comunque uno alla volta: come prima per un processo solo. Il numero è in una riga di configurazione (`LLM_REMOTE_PARALLEL`, predefinito 1) per il giorno in cui Groq avrà un piano più largo.
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

Ramo `feat/locale-parallelo`, un commit. La PR arriva **spenta**: senza niente nel `.env`, `local_slots()` vale 1. Lucchetto, ordine, etichette e `_parallel` sono come prima; cambiano la precedenza automatica dei `job:` (approvata), il cancello Groq da 1 posto anche fra fili dello stesso processo e la precedenza condivisa.

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
- **Etichetta «pezzo i/n» solo con più posti**: con 1 posto i pezzi restano nel filo del chiamante e non si tocca la sua etichetta (così con la PR spenta le etichette non cambiano).
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

## 4. Revisione          (revisore, 20/11/2026, commit ee96212)

**Verdetto: PASSA.** Nessun rilievo bloccante. Tre rilievi da leggere prima del rilascio (1-3) e tre minori. `stato:` resta `revisione` finché il collaudo non ha scritto il suo verdetto.

Invarianti: `owner_type` non toccato, nessun terzo valore; ogni chiamata resta un contenuto o un pezzo di uno; i falliti restano `failed` (pezzo fallito vince su «modello via»; «modello via» lascia `pending`); nessun segreto nel diff; nessuna credenziale di terzi; nessun commit su `main` (solo 3 commit del ramo); documentazione mossa (02, 03, drawio, it.json, summary).

### Rilievi, per gravità

1. **Media. Il CRM può restare senza precedenza per tutto un caricamento lungo del cliente.** `client.py`, `_ollama_slot`, riga `fcntl.flock(prio_fd, LOCK_SH)`. Il CRM (`/home/medyca-admin/MEDYCA/CRM-worktrees/*/shared/auth/src/ollama.ts`, `takeFlock`) prende la precedenza con `flock -x -w 1800`. Un EX non passa finché vive un solo SH. Linux non dà la preferenza a chi aspetta in EX: un nuovo SH passa lo stesso. Con 3 pezzi di un'intervista che prendono e rilasciano il SH sfalsati (ogni pezzo 4-9 min, fino a 15 pezzi), il SH non resta mai libero: il CRM aspetta i suoi 1800 s e riceve `model_busy`. Prima (EX contro EX) il CRM faceva la fila dietro un detentore alla volta. Succede solo con più posti accesi (o due lavori del cliente insieme) e con il CRM che chiede la precedenza. Non è uno stallo: finisce quando l'intervista finisce. Da dire al rilascio e scrivere nel doc 03; se non basta, una soglia (i nuovi SH non passano se esiste un EX in attesa) è un altro lavoro.
2. **Media. Il contratto col CRM non è scritto da nessuna parte nel repo.** Il CRM usa `OLLAMA_LOCK_PATH` come posto 0 e `.priority` in esclusivo. Il nuovo schema regge **perché** il posto 0 resta il file di prima e perché `_prio_held` prova EX (fallisce con un SH o un EX). Né `client.py` né `03-llm-and-embeddings.md` dicono che un altro programma dipende da questi due file. Il prossimo che sposta il posto 0 o cambia `_prio_held` rompe il CRM in silenzio. Aggiungere due righe nella docstring di `_ollama_slot` e in 03.
3. **Media-bassa. «Spenta, identica a main» è vera solo in parte.** Con N=1 restano diversi da `main`: (a) ogni chiamata `job:` prende la precedenza da sola (`_is_client_job`, approvato da Giuseppe, domanda 1); (b) il cancello Groq da 1 posto vale anche per più fili nello stesso processo (gunicorn con due lavori insieme); (c) la precedenza è condivisa. Lucchetto, ordine dei contenuti, etichette (niente «pezzo i/n» con 1 posto) e `_parallel` con N=1 sono invece uguali a prima. Il testo «la PR da sola non cambia nulla» (sez. 2.0, 3) va corretto, non il codice.
4. **Bassa.** `LOCK_SH` sulla precedenza è bloccante e senza scadenza (ignora `wait`): se il CRM tiene la precedenza e aspetta il posto 0 occupato da una risposta del giro (fino a 1500 s), un caricamento del cliente aspetta anche lui, senza limite. Come prima (prima era EX), ma ora con più fili è più visibile.
5. **Bassa.** I test non usano il file vero oggi (vedi risposta 4), ma nulla lo impedisce: un `OLLAMA_LOCK_PATH` temporaneo in `core/tests/__init__.py` sarebbe la difesa.
6. **Bassa.** Se la divisione corti/lunghi sbaglia (`_is_long_item` dice «corto» per un testo che poi si legge a pezzi) si arriva a 9 richieste in coda per 3 posti: il lucchetto a file le limita comunque a 3 contro Ollama. Nessun danno, solo attesa.

### Le domande del capo

**1. N=1 uguale a main?** Lucchetto: sì (un file, stesso nome, `LOCK_EX|NB`, stessa attesa e stesso `LLMBusy`). Ordine e `_parallel`: sì, ramo `workers <= 1` nel filo del chiamante con `_tracked`, `deferred` equivale al vecchio conto dei `pending`. Etichette: sì. Precedenza: no, vedi rilievo 3. Cancello Groq: no, vedi rilievo 3.

**2. Thread.** `copy_context().run` per ogni pezzo e per ogni contenuto corto (uno per filo: un Context non si entra da due fili): ok, c'è un test che apre lo scope in un filo non principale. `connection.close()` nel `finally` di `in_thread` e in `_with_retry`: ok. I fili dei pezzi non scrivono nulla del contenuto; un solo salvataggio nel chiamante. Risultati in ordine di pezzo (la lista `futures` è in ordine, il pool ha già fatto join). Pezzo fallito: errore col numero più basso, i pezzi non partiti restano non partiti, il contenuto va `failed`. «Modello via» senza altri errori: passa intatto, `pending`. Nessuna scrittura condivisa senza lucchetto (`why` è scritta sotto `if not why`: al peggio due fili scrivono due eccezioni, vince la prima; innocuo). Nessun difetto.

**3. Compatibilità col CRM** (ho letto `shared/auth/src/ollama.ts`; la cartella `MEDYCA-CRM` non esiste, il CRM sta in `/home/medyca-admin/MEDYCA/CRM-worktrees/…`, qui sola lettura).
- Il CRM prende `.priority` in EX, poi `OLLAMA_LOCK_PATH` (posto 0) in EX, e non crea mai il file del posto. Il ramo: `_prio_held` prova EX|NB sulla precedenza, quindi con il CRM che la tiene fallisce e il giro batch **si ferma ancora** (resta l'attesa fino a `OLLAMA_LOCK_WAIT`, poi `LLMBusy`, contenuto `pending`). Visto dal vero: ora c'è un `flock -x` del CRM (pid 4004344) che tiene `.priority` e un altro che aspetta il posto 0, tenuto da `banco.py`.
- Con 3 posti: i file sono 3 (posto 0, `.1`, `.2`). Il CRM entra solo dal posto 0, quindi in totale ≤ 3 richieste a Ollama (CRM 1 + giro 2, oppure giro 3). Mai 4, a patto che CRM e `OLLAMA_NUM_PARALLEL` restino su un solo file per il CRM. Altri programmi che parlano con Ollama senza lucchetto (non ne ho trovato nel CRM) non sono coperti.
- Stallo: no. L'ordine è sempre precedenza poi posto; nessuno aspetta la precedenza tenendo un posto; il CRM in EX non può convivere con un SH. Il caso peggiore è la fame del CRM del rilievo 1, che finisce da sola. Durante un rilascio un processo vecchio (EX sulla precedenza) fa solo aspettare i nuovi SH.
- Il posto 0 è il più conteso: il giro lo prova per primo, quindi il CRM aspetta spesso più del necessario mentre i posti 1 e 2 sono liberi dopo che il giro ha smesso di partire. Non è un errore, è un'attesa in più.

**4. Test e file veri.** Ho letto ogni test che arriva a `_ollama_slot`: `_ChainCase`, `test_parallel` (SeatsTests, SharedPriorityTests: file temporaneo; gli altri patchano `_ollama_slot`), `test_llm_usage` (temporaneo o patch), `test_mcp_tools` (patch), `TettiLocali` di `test_7b_veloce` (è un `_ChainCase`). Nessun test con scope `job:` arriva più al file vero. Controllo dal vero ora: `/proc/locks` non mostra nessun processo di test sul file vero e il collaudo in corso usa `OLLAMA_LOCK_PATH` temporaneo. Limite: una prova statica non garantisce che un test futuro non lo tocchi; il modo sicuro sarebbe un `OLLAMA_LOCK_PATH` temporaneo messo in `core/tests/__init__.py`, come già per il lucchetto del giro (non l'ho preteso: è fuori dal disegno).

**5. Cancello Groq da 1 posto.** Coerente con 2.2e («attorno al tentativo, attesa del tetto compresa»): il codice in `chat()` avvolge l'intero `_patient`, `remote_only` lo salta. È scritto come limite in `02-pipeline.md` («A thread waiting for Groq's per-minute cap holds the gate, so the others wait for it instead of going local») e in `3` della sez. 3; nella pagina Documentazione si dice «con Groq che funziona non cambia niente». Non c'è invece una riga che dica che con Groq **vivo ma al tetto** il locale resta fermo mentre i fili aspettano: è il caso più comune (397 rifiuti su 823) e conviene scriverlo nella pagina Documentazione del cliente. Non è un difetto di codice.

### Cosa non ho potuto fare
Non ho eseguito i test (il collaudo ne sta facendo la prova); ho letto il diff, i test relativi al lucchetto e `ollama.ts` del CRM.

### Giro 2 (revisore, 20/11/2026, commit 53c58be)

**Verdetto: PASSA.** Tutti i rilievi dei giri 1 sono chiusi davvero.

- **Rilievo 1 e 2 (CRM)**: scritti nella docstring di `_ollama_slot` e in `03` («Contract with the CRM»): stessi file (posto 0 e `.priority`, esclusivo), «mai rinominare il posto 0», fame fino a 1800 s e `model_busy`, tentativo a 1 s che perde contro il `flock` bloccante. Ripetuto in `02`. Chiusi.
- **Rilievo 3 («spenta = identica»)**: corretto in 2.0, 2.2e, 3. Chiuso.
- **Rilievo 5 (test sul file vero)**: `core/tests/__init__.py` mette `OLLAMA_LOCK_PATH` in una cartella temporanea del processo, cancellata a fine corsa. Il file `.priority` deriva da quel percorso, quindi finisce nella stessa cartella. Nessun test o altro codice cita `/tmp/medycabrain-ollama` (solo un commento); i test con `override_settings` ripristinano il valore temporaneo, non quello vero. Non può toccare i file veri e non rompe nulla.
- **R1 (suffisso «pezzo i/n»)**: la regex `^(.*?)(\s·\spezzo\s\d+\/\d+)$` senza suffisso non combacia e dà `[label, ""]`: la riga resta identica a prima (il suffisso vuoto non si disegna). La chiave React non è cambiata. Con il suffisso, il nome si taglia e «pezzo i/n» resta intero.
- **R2 (numeri)**: coerenti tra `it.json`, 02 e 03 e con la sezione 5: 1,94× il 18/11, 1,12× il 20/11, articoli 1,40×, pezzi 1,8×, reel nessuno. Il testo al cliente è semplice e senza promesse («non si può promettere un tempo preciso»; «poco più del 10%»). Aggiunta onesta anche la frase sul tetto di Groq.

Rilievi minori, non bloccanti:
- Il 18/11 è chiamato «macchina tranquilla» in 02 e 03: è una spiegazione plausibile, non provata (la sezione 5 la dà come ipotesi). Meglio «ipotesi» se si rilegge.
- In 2.0 (righe 2 e 4) il disegno cita ancora «27,9 contro 14,4» e «circa la metà»: è lo storico del disegno, ma non va ripetuto al cliente.
- Non ho eseguito test né build: ho letto il diff. Il capo riferisce 528 verdi e build ok.

## 5. Collaudo           (collaudatore, 20/11/2026)

**Verdetto: PASSA** come codice, con la PR spenta (così com'è). Ma tre cose da sapere, due delle quali vanno sistemate **prima di scrivere 3 nel `.env`** (rilievi R1 e R2 sotto). Il codice fa quello che il disegno promette; il guadagno di velocità promesso, oggi, **non si è ripetuto**.

Commit provato: `ee96212` sul ramo `feat/locale-parallelo`, in un worktree. Python e Node del progetto. Tutto su una **copia** del database (dump di produzione fatto con una connessione normale, le credenziali non lette né stampate; la copia e il dump sono stati cancellati a fine prova).

### 5.1 I comandi, in ordine (output vero)

Postgres privato in `/tmp` sulla porta 5561, `OLLAMA_LOCK_PATH` temporaneo per la suite.

```
$ python manage.py makemigrations --check --dry-run
No changes detected
$ python manage.py check
System check identified no issues (0 silenced).
$ python manage.py test core
Ran 528 tests in 102.180s
OK
$ cd FEC && npm run build          # tsc -b + vite
✓ built in 42.97s                  # (solo l'avviso di sempre: chunk > 500 kB)
```

### 5.2 Prova vera sul modello locale (7b, Ollama con `OLLAMA_NUM_PARALLEL=3`)

`systemctl show ollama -p Environment` → `Environment=PATH=... OLLAMA_NUM_PARALLEL=3` (verificato).
Ambiente del processo di prova (non il `.env`): `OLLAMA_NUM_PARALLEL=3 LOCAL_SLOTS=3`, nessuna chiave Groq (`FAST_ENDPOINTS` stampato: `[]`), stadi veri via `manage.py run_pipeline --only enrich,knowledge` sulla copia, **lucchetti veri** `/tmp/medycabrain-ollama.lock` e `.1`, `.2`.

Contenuti usati (14, sempre gli stessi nelle tre prove, tutti da zero): 6 reel corti (3 owned, 3 competitor), 6 articoli corti (3 owned, 3 competitor), 1 reel lungo competitor (11 028 caratteri, 2 pezzi) e 1 articolo lungo owned (15 493 caratteri, 3 pezzi).

**Tre giri, stessi contenuti**

| Giro | Posti | Orologio | Chiamate | Durata media di una chiamata | Token/s di una chiamata | Stato finale |
|---|---|---|---|---|---|---|
| A | 3 (ma il posto 0 era quasi sempre del CRM) | 15:41:45 → 17:15:19, **93,5 min** | 31 | 340 s | 1,15 | 14/14 `done`, 0 `failed` |
| B | **1** (come la PR spenta) | 17:17:19 → 19:01:45, 104 min, di cui **35 min di attesa del lucchetto** tenuto dal CRM; lavoro netto (somma delle durate) **4 039 s = 67 min** | 31 | 130 s | 2,52 | 14/14 `done`, 0 `failed` |
| A2 | **3 veri** (i tre lucchetti miei, CRM fuori) | 19:02:45 → 20:02:39, **59,9 min** (3 594 s) | 31 | 231 s | 1,27 | 14/14 `done`, 0 `failed` |

Cosa dicono i numeri, senza abbellirli:

- **Guadagno misurato oggi: 1,12×** (B netto 4 039 s contro A2 3 594 s). Per stadio: reel (enrich) A2 2 069 s contro B netto 1 906 s, cioè **nessun guadagno**; articoli (knowledge) A2 1 525 s contro B netto 2 133 s, **1,40×**. Il 18/11 il banco aveva dato 1,94×. Ogni chiamata, con 3 insieme, va 1,8 volte più piano (130 → 231 s; 2,52 → 1,27 token/s), come previsto dal disegno, ma il totale non è salito quanto allora.
- Perché potrebbe essere diverso dal 18/11 (ipotesi, non provate): il banco del 18/11 teneva sempre 6 richieste nella coda, qui lo stadio lavora a gradini (prima i corti, poi i lunghi uno alla volta: all'inizio di un lungo un posto resta vuoto, la lettura finale gira da sola); la macchina non era tranquilla (nel giro A c'era `banco.py` del CRM con un altro modello a ~500% di CPU; nel giro A2 il CRM era fuori ma Ollama teneva caricato l'altro modello). Il giro A2 è il più pulito che ho potuto avere; per un numero vero serve una notte tranquilla.
- **Contenuti corti insieme, owned e competitor separati**: tutti `done`; ogni chiamata ha un solo contenuto (tabella `llm_calls`: un'etichetta per chiamata, mai due contenuti). Ho controllato ogni affermazione salvata: tutte le 56 citazioni sono nel testo del **proprio** contenuto (articolo: testo; reel: trascrizione più didascalia, come da regola della strada corta); `owner_type` di ogni contenuto invariato (3 owned + 4 competitor tra i reel, 4 + 3 tra gli articoli).
- **Testo lungo a pezzi in parallelo**: articolo lungo (3 pezzi), A2: i 3 pezzi partiti insieme alle 19:55:48 e finiti in 266/316/319 s, poi la lettura finale (81 s). Con 1 posto (B): 252 + 174 + 156 s di pezzi uno dopo l'altro (582 s) e la lettura finale 100 s. **Pezzi: 582 → 319 s (1,8×)**. Reel lungo (2 pezzi): A2 210/198 s insieme; B 109 + 122 = 231 s uno dopo l'altro: **nessun guadagno** (ogni pezzo va 1,8 volte più piano). **Ordine giusto**: le affermazioni dell'articolo lungo escono in ordine di pezzo (posizioni nel testo 1 036, 2 030, 4 208 | 5 740, 5 463 | 8 180, 10 367: i pezzi sono ordinati, dentro il pezzo vale l'ordine del modello); reel lungo 3 112, 3 497, 5 466, 6 721, 9 208 (crescente). Le affermazioni salvate sui due lunghi: 7 (articolo) e 5 (reel) in tutti e tre i giri.
- **Citazioni scartate** (righe «affermazioni scartate» nei log): giro A 14, giro B (1 posto) **13**, giro A2 (3 posti) **10**. Affermazioni salvate: 56, 56, 56. **Nessun peggioramento di qualità con 3 posti**: l'8-contro-3 del 18/11 qui non si ripete (probabile rumore, ma su un solo confronto per parte).
- **Modello che sparisce a metà** (proxy TCP locale davanti a Ollama che smette di accettare dopo 150 s; copia separata del database): `{'enriched': 2, 'enrich_failed': 0, 'arg_reels': 1, 'deferred': 6, 'stopped': 'modello locale non disponibile'}` e stati: 129 `done/done`; 110 analisi `done`, affermazioni `pending`; 97, 104, 106, 123, 773 ancora `pending/pending`, `last_error` vuoto. **Nessun `failed`.** Testo lungo con la stessa prova (proxy chiuso dopo 60 s, i due pezzi in volo finiscono, la lettura finale trova la porta chiusa): `{'enriched': 0, 'enrich_failed': 0, 'deferred': 1, 'stopped': 'modello locale non disponibile'}`, il reel resta `pending/pending/pending`, **0 righe in `enrichments` e 0 in `reel_arguments`** (niente salvato a metà). Le righe di `llm_calls` delle chiamate rifiutate sono marcate `failed` (`LLMLocalUnavailable`): è il registro della chiamata, il contenuto no. (Una prima prova del lungo era invalida: il mio proxy teneva aperta la porta; rifatta con un proxy corretto.)
- **Lucchetti con altri utenti veri**: a 15:44 il CRM (`banco.py`) teneva il posto 0 da ore: i miei 2 posti (`.1`, `.2`) hanno lavorato, il terzo contenuto è comparso nella pagina come «in coda per il modello locale da 3 min» e ha preso il posto 0 quando il CRM l'ha lasciato (180 s dopo). Poi il CRM ha aspettato dietro di me (`WRITE*` in `lslocks`): **la mia prova ha rallentato il suo banco**; da dire a chi lo segue. Nel giro B (1 posto sul file vero) un altro script del CRM, in catena, ha tenuto il posto 0 e il mio contenuto è rimasto in attesa fino a 673 s (`wait_seconds`) più volte: vedi R3.
- **Precedenza del cliente su due processi veri** (solo lucchetti, file privati, nessun modello): un lavoro `job:` tiene posto + precedenza per 25 s; un secondo lavoro `job:` entra subito (`got a seat after 0.0s (priority shared)`); il giro `pipeline:` con attesa 3 s riceve `LLMBusy: ollama busy: interactive work has priority` dopo 4,0 s, e prende il posto 16 s dopo, quando i due hanno finito.
- L'embedder (`cluster_agent._get_embedder`) con 3 fili: una sola riga «[cluster] loading embedder» nel log del giro, non tre.

### 5.3 La pagina Avanzamento, dal vero (Vite sul ramo contro la copia, Chromium a 380 px e 1280 px)

- **Tre righe insieme**: sì. A 380 px (`a-mobile-1.png`): «@menopausa_insieme · Da7C3-tDvpl — sta leggendo — qwen2.5:7b-instruct-q4_K_M — 3 min», «… Da9nvuFEq1o — in coda per il modello locale da 3 min», «… Da5mIKDOhPG — sta leggendo». Su desktop le tre righe mostrano anche token e velocità («190 token 0,3 token/s»). Nessuno scorrimento orizzontale a 380 px (`scrollWidth > innerWidth` → falso, in tutte le prove).
- **«pezzo i/n» su desktop**: visibile, `@internationalmenopausesociety · CZ9kBgZo9AS · pezzo 1/2` e `pezzo 2/2`.
- **«pezzo i/n» su 380 px: NON si vede.** `FEC/src/components/progress/ModelLines.tsx` riga 31 mette `truncate` sul nome: il nome lungo di un account riempie la riga e il suffisso, che sta in fondo, viene tagliato. Il testo letto dalla pagina a 380 px: «@internationalmenopausesociety · CZ…» due volte, **due righe identiche**: proprio quello che l'etichetta doveva evitare (disegno 2.2c, punto 3). Con 1 posto non c'è il suffisso e non cambia niente. È R1.
- Stato **errore** (backend spento, token finto): «Non riesco a leggere l'avanzamento. Controlla la connessione e riprova.» con «Riprova», e lo stesso per i totali del giorno, a 380 px senza sforamenti. Stato **vuoto** (nulla gira): «Non sta girando niente. Ultimo giro: oggi alle 20:02, 60 min, 2 stadi su 2.» con link a Stato. Stato **in caricamento**: non l'ho potuto fermare per fotografarlo (la risposta arriva in pochi ms dalla copia): **non provato**.
- Con 1 posto (giro B): una riga sola, «sta scrivendo … 2,3 token/s», senza «pezzo».

### 5.4 Rilievi

- **R1 (UI, da sistemare prima di accendere)**: a 380 px il suffisso «· pezzo i/n» è tagliato da `truncate`; le righe dei pezzi di uno stesso testo sembrano uguali. Una correzione di frontend di due righe (a capo invece di troncare, o il suffisso fuori dal troncamento). Il disegno diceva «nessuna modifica al frontend»: il collaudo dal vero dice che serve.
- **R2 (numeri nella documentazione)**: `FEC/src/i18n/it.json` riga 379 dice al cliente «i contenuti analizzati in un'ora sono quasi il doppio (27,9 contro 14,4)», e `02-pipeline.md` e il disegno citano 1,94×. Nel giro più pulito di oggi si è avuto **1,12×** (1,0× sui reel, 1,40× sugli articoli, 1,8× sui pezzi di un testo lungo). O si rifà la misura in una notte tranquilla, o la frase per il cliente si riscrive con le due misure e l'avviso.
- **R3 (lucchetti, già così prima di questo ramo, ma ora si vede)**: chi aspetta un posto lo riprova ogni secondo con `LOCK_NB`; un altro programma che aspetta con un `flock` bloccante (come fa il CRM) viene svegliato dal sistema per primo e vince sempre. Il mio giro a 1 posto è rimasto fermo fino a 673 s più volte mentre il CRM concatenava le sue chiamate; sotto il tetto di 1 800 s, quindi niente è fallito. Con il giro notturno e il CRM insieme, la notte può durare di più senza avvisi. Non è un difetto di questo ramo e non lo blocca: va solo saputo.
- Piccola nota: il log di un giro con `huggingface_hub` tenta la rete per l'embedder («Connection reset by peer, Retrying in 1s») e costa ~35 s la prima volta. Non è di questo ramo.

### 5.5 Cosa NON ho provato

- Nessuna chiamata vera a Groq (come chiesto): il cancello a 1 posto resta provato solo dai test.
- Il guadagno vero su una macchina tranquilla (vedi R2); il giro «tutto insieme» con il traffico di un cliente vero (`job:`) sul 7b: solo i lucchetti, non il modello.
- `reprocess` e il caricamento del cliente (`upload_workflow`) con pezzi in parallelo: coperti dai test, non lanciati.
- Stato di caricamento della pagina Avanzamento.
- Il comando `systemctl show` dice 3 posti ora; non ho provato il caso «`.env` dice 3 e Ollama ne ha 1» (rischio già scritto nel disegno).

### 5.6 Pulizia

Fermati e cancellati: Postgres privato (porta 5561), copia e dump del database, server di prova (Django 8710, Vite 5710), proxy, Chromium. Nessun mio processo in vita; `lslocks` non mostra lucchetti miei. Restano i file vuoti `/tmp/medycabrain-ollama.lock.1` e `.2` (creati dai miei giri sui posti veri, come fa il codice) e il vecchio `.priority` dello sviluppatore. Nessun file tracciato è stato toccato; `.env`, crontab, servizi e produzione non sono stati toccati.

### Giro 2 (collaudatore, 20/11/2026, commit 53c58be)

**Verdetto: PASSA.** R1 e R2 chiusi dal vero. Prova breve, senza modello (niente Ollama, niente Groq).

**Comandi** (Postgres privato su 127.0.0.1:5571, chiavi LLM svuotate):

```
$ python manage.py makemigrations --check --dry-run
No changes detected
$ python manage.py check
System check identified no issues (0 silenced).
$ python manage.py test core
Ran 528 tests in 74.984s
OK
$ npm run build            # tsc -b + vite
✓ built in 26.52s          # solo l'avviso di sempre: chunk > 500 kB
```

**Lucchetti in /tmp durante la suite**: date di modifica prese prima e dopo, `diff` vuoto.
```
/tmp/medycabrain-ollama.lock          2026-11-13 17:50:56
/tmp/medycabrain-ollama.lock.1        2026-11-20 15:41:46
/tmp/medycabrain-ollama.lock.2        2026-11-20 15:41:46
/tmp/medycabrain-ollama.lock.priority 2026-11-20 15:15:24
```
La suite non li tocca più.

**Pagina Avanzamento** (Vite sul ramo, Chromium; l'API di avanzamento è un finto server locale con 5 righe: 3 pezzi di un testo con nome lungo `@internationalmenopausesociety_official_global · CZ9kBgZo9AS · pezzo i/3` e 2 righe normali senza suffisso, una «in coda»):
- 380 px: «· pezzo 1/3», «· pezzo 2/3», «· pezzo 3/3» **si vedono**, il nome è tagliato con i puntini (`@internationalmenopauses…`); le tre righe ora sono distinguibili. Le righe senza suffisso («@menopausa_insieme · Da7C3-tDvpl», «… Da9nvuFEq1o», la seconda «in coda per il modello locale da 3 min») sono normali, nome intero. Nessuno scorrimento orizzontale (`scrollWidth > innerWidth` falso).
- 1280 px: nome intero, suffisso a fianco, tutte le righe normali; nessuno sforamento.
- Nota sulla prova: nel finto ho scritto `who: "locale"`, e la scheda ha mostrato la chiave `progress.who.locale` non tradotta. È un valore inventato da me (il vero è un altro), non un difetto del ramo.

**Pagina Documentazione**: il paragrafo nuovo c'è («in una prova a macchina tranquilla è andato quasi due volte più svelto, ma quando sullo stesso server lavorava un altro programma il guadagno è sceso a poco più del 10% (sui reel non c'è stato guadagno)…»); la parola «doppio» non c'è. Leggibile a 380 px, tutto il testo a capo dentro la scheda, nessuno sforamento. (Per questa pagina il finto server dava `/ops/status/` con liste vuote: l'elenco servizi e orari non è stato guardato.)

**Screenshot** (cartella di lavoro `/tmp/claude-1001/-home-medyca-admin-projects-medycabrain/7ebcc0ed-5ca3-4cf8-9600-f40c5d3f8664/scratchpad/g2`): `avanz-380.png`, `avanz-380-fondo.png` (righe in fondo, compresa quella in coda), `avanz-1280.png`, `docs-380.png`, `docs-1280.png`.

**Non provato**: il caricamento reale con il vero backend (l'API era finta); lo stato di caricamento e di errore della pagina Avanzamento (già visti al giro 1, il codice di questo giro non li tocca); il «pezzo i/n» con etichette vere del backend (provato il formato `· pezzo i/n`, che è quello che l'espressione regolare cerca). Un verde qui non dice nulla sul guadagno di velocità: quello resta da misurare in una notte tranquilla.

**Pulizia**: spenti Postgres privato, finto server, Vite e Chromium; tolti il file di config di Vite e il collegamento a `node_modules` messi nel worktree; `git status` pulito prima della lavagna. Nessun mio processo in vita. `.env`, servizi e produzione non toccati.

## Registro

- 18/11 — capo: aperto il lavoro, lanciato l'architetto.
- 18/11 — architetto: disegno scritto (sezione 2). Scelte proposte: N posti dal `.env` (predefinito 1), corti 3 insieme e lunghi uno alla volta con 3 pezzi insieme, Groq uno alla volta, lavori del cliente con precedenza. Tre domande aperte in 2.7. In attesa dell'OK di Giuseppe.
- 20/11 — Giuseppe: OK al disegno. Risposte a 2.7: (1) sì, passa il cliente; (2) sì, 3 posti nel `.env` al rilascio, dopo la prova del collaudo su una copia del database; (3) sì, Groq resta uno alla volta. `stato: approvato`.
- 20/11 — sviluppatore: scritto il codice (un commit sul ramo), 528 test verdi, documentazione aggiornata. `stato: revisione`. Dettaglio e punti da guardare in sezione 3.
- 20/11 — revisore: passa. Rilievi: fame del CRM con precedenza condivisa, contratto col CRM non scritto, «spenta = identica» vero solo in parte. `stato` resta `revisione` in attesa del collaudo.
- 20/11 — collaudatore: suite 528 verdi, build ok; prova vera sul 7b con 3 posti sulla copia: 14/14 `done`, owned/competitor separati, pezzi in ordine, citazioni scartate 14/13/10 (3 posti, 1 posto, 3 posti), modello che sparisce = `pending` mai `failed`. **Passa** con la PR spenta. Rilievi: R1 «pezzo i/n» tagliato a 380 px, R2 guadagno misurato 1,12× (non 1,94×) contro la frase al cliente, R3 attesa dei lucchetti contro un `flock` bloccante del CRM. Dettaglio in sezione 5.
- 20/11 — sviluppatore, giro 2: chiusi R1 (suffisso «pezzo i/n» in uno span non troncato), R2 (niente «doppio»: 1,94× a macchina tranquilla, 1,12× con il banco del CRM), contratto col CRM e fame/attesa scritti (03, docstring `_ollama_slot`, 02), testo «N=1 identico» corretto, `OLLAMA_LOCK_PATH` temporaneo nei test (suite 528 verdi, i file in /tmp non vengono più toccati), riga sulla pagina Documentazione. Build ok.
- 20/11 — revisore, giro 2: passa. Rilievi dei giri 1 chiusi (CRM scritto, N=1 corretto, test isolati, suffisso non tagliato, numeri onesti). `stato: pronto` (collaudo giro 1 già passato).
- 20/11 — collaudatore, giro 2: suite 528 verdi, build ok, lucchetti in /tmp invariati durante la suite; «pezzo i/n» visibile a 380 px e righe senza suffisso normali; Documentazione senza «doppio», leggibile a 380 px. **Passa.**
