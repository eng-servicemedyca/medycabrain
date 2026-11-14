---
id: 2026-11-14-pipeline-in-casa
titolo: Raccolta di Instagram senza Apify (PR 1 di "pipeline in casa")
stato: revisione
ramo: feat/pipeline-in-casa
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Parole di Giuseppe (13/11/2026, appena passati al nuovo VDS):

> now we have IProyal and a new VDS which is superpowerful despite it's only CPU,
> who cares we can find optimization to run our LLM there even though the token
> per second are slow. [...] I don't want to use the Anthropic API call and the
> Apify stuff because I have a powerful machine that I can run my process on.

Il 13/11 questo lavoro era stato messo dopo la pagina Avanzamento («prima si
misura quanto costa in tempo il modello locale, poi si decide il passaggio»,
registro di `.claude/tasks/2026-11-13-processi-locali.md`). Il 14/11, a PR #20
fusa e rilasciata, Giuseppe ha scritto: «continue in the topic of the chat for
the llm, pr merged 20 you can go on».

Fatti raccolti dal capo il 14/11/2026 (misurati, non supposti):

- **Apify è già fermo.** Dal giro del 12/11 alle 14:15 risponde
  `401 user-or-token-not-found` per tutti i 23 account
  (`BEC/scraper/apify_provider.py`, riga 109). Nei giri dell'11/11 e della
  notte del 12/11 lo scraper si fermava per budget (`budget_stopped: True`).
  Da almeno quattro giorni non entra nessun reel nuovo. Lo stadio `scrape`
  finisce `done` con 23 falliti su 23.
- **Il modello locale è ancora la riserva.** In `BEC/.env`:
  `LLM_PROVIDER_ORDER=fast,ollama`, `OLLAMA_MODEL=qwen2.5:3b-instruct-q4_K_M`.
  Lo stadio `batch` consegna l'analisi di massa al Batch API di Anthropic;
  `enrich` è la via immediata.
- **Velocità misurata** (PR #19): qwen2.5 7b Q4_K_M a 6 thread fa 3,8-4,0
  token al secondo; 16 risposte in parallelo nello stesso processo arrivano a
  7,1 token/s totali. Il tetto è la memoria, non i core (EPYC Zen 1, 18 core,
  94 GB, niente GPU).
- **La misura è pronta ma vuota.** `stage_runs` e `llm_calls` esistono
  (migrazione 0026) e la pagina `/avanzamento` è live. Il giro del 14/11 alle
  14:15 ha scritto 7 righe in `stage_runs` e 0 in `llm_calls`: non c'era
  niente da analizzare, perché lo scraper non porta niente.
- **Proxy residenziale IPRoyal**: già usato per i download di YouTube e Vimeo
  (PR #16).
- Database: 1617 reel, tutti già con vettore.

Cosa serve dal disegno:

1. **Scraping di Instagram senza Apify**: come si leggono i reel dei 23
   account dal VDS (proxy IPRoyal o altro), con quali limiti e rischi di
   blocco. Dire chiaramente cosa oggi dipende da Apify (scrape, e nel log
   `download` cita `apify_accounts`/`apify_urls`).
2. **Analisi senza Anthropic API**: cosa oggi passa da Anthropic (stadio
   `batch`, `enrich`, `knowledge`, altro?), quanto tempo-macchina costerebbe
   farlo con Ollama su un giro tipico e sull'arretrato, e se la qualità del
   3b/7b basta per ogni compito. Numeri, non aggettivi.
3. **Un lavoro o due?** Proporre se conviene una PR sola o due separate
   (scraper prima, perché è quello rotto oggi?).
4. Cosa resta fuori e le domande aperte per Giuseppe.

Vincoli che valgono sempre: il contenuto `owned` non si mescola mai con quello
dei competitor; niente credenziali di terze parti rivendute; i fallimenti
restano `failed`; documentazione nello stesso commit.

## 2. Disegno            (architetto)

### In cinque righe

1. **Le due dipendenze sono già morte tutte e due**, non solo Apify. La chiave
   Anthropic è rifiutata dal 14/10, l'ultima consegna in blocco è del 3/10.
   Da un mese l'analisi la fa Groq (gratis, un altro fornitore esterno) e
   quello che Groq non prende cade sul modello locale e fallisce.
2. **Instagram si legge dal VDS passando dal proxy IPRoyal**, senza account
   nostro e senza Apify: provato oggi. Limite: si vedono solo gli ultimi 6
   post di ogni account.
3. **L'analisi in casa si può fare, ma è lenta e va accesa con tre correzioni**
   (finestra, tempi di attesa, un lavoro alla volta). Senza, fallisce come sta
   già fallendo oggi.
4. **Qualità del modello locale: non dimostrata.** Su 3 contenuti provati ha
   sbagliato il tema di uno e inventato metà delle citazioni di un altro.
   Prima di accenderlo serve una prova vera su 50 contenuti.
5. **Due PR.** Prima la raccolta (è ferma dal 2/11), poi l'analisi.

### Fatti misurati (14/11/2026, su questo VDS)

Ogni riga dice come è stata accertata. Dove è una stima, c'è scritto.

**Raccolta**

1. **Nessun reel nuovo dal 2/11 alle 02:35 UTC: 12 giorni, non 4.** Dal 2/11
   pomeriggio all'11/11 lo stadio si fermava per il tetto di spesa
   (`budget_stopped: True`), dal 12/11 risponde 401.
   (`grep "✓ scrape done" logs/pipeline.log`)
2. **Apify compare in 10 file Python, 111 righe**
   (`grep -ci apify` sui file di `BEC`, esclusi `venv`). Elenco in «Cosa
   dipende da Apify».
3. **Il download non dipende da Apify.** Scarica con `yt-dlp` dal link
   pubblico del reel, o dall'indirizzo già in tasca. `apify_accounts` e
   `apify_urls` nel log sono solo un "pre-riempimento" degli indirizzi
   (`downloader_agent._prefetch_urls`), a zero in tutti i giri guardati
   (dal 31/10).
4. **Il proxy funziona ed esce da un IP italiano di casa** (una prova:
   Italia, operatore Dimensione S.r.l.). È già nel `.env` come `YTDLP_PROXY`,
   con il segnaposto `{session}` che cambia IP a ogni richiesta.
5. **Dal proxy la pagina pubblica di un profilo risponde 200, senza muro di
   login** (743 KB). Dal vecchio IP di datacenter rimandava al login
   (`02-pipeline.md`, tabella «What is closed»). Una prova, su un account
   generico molto grande, non su uno dei 23.
6. **La pagina "embed" del profilo (`instagram.com/<utente>/embed/`) dà gli
   ultimi 6 post**, in anonimo, dal proxy: 245 KB, 1,5 secondi. Per ogni post:
   codice del reel, se è un video, data, didascalia, "mi piace", commenti,
   proprietario. **Mancano**: indirizzo del video, numero di visualizzazioni,
   durata. Una prova, stesso account generico.
7. **`web_profile_info` resta chiuso anche dal proxy** (404, due prove).
8. **Non provato**: la strada più profonda (la stessa interrogazione che fa il
   browser di un visitatore non loggato, 12 reel per pagina e pagine
   successive). Il sistema dei permessi ha bloccato la prova: serve l'OK
   esplicito di Giuseppe per farla. **Non provato** nemmeno: l'embed senza
   proxy, e `yt-dlp` dal nuovo IP del VDS (gli ultimi download riusciti sono
   del 2/11).
9. **Ritmo di pubblicazione** (36 giorni prima del 2/11, shell Django): 19
   account su 23 hanno pubblicato; il più attivo fa 30 reel in 12 giorni
   (1,25 ogni mezza giornata), gli altri da 10 in giù. Con 6 post per
   lettura e due letture al giorno, **a regime non si perde niente**.
10. **Il buco di 12 giorni**: attesi circa 94 reel (stima dal ritmo sopra).
    Con 6 per account se ne recuperano circa 61; **circa 33 restano fuori**,
    tutti di 5 account molto attivi.
11. **Un giro tipico porta 3-5 reel**: 194 reel in 62 giri a ottobre (3,1 a
    giro); 4-5 a giro negli ultimi giorni buoni.
12. **La pipeline non ha un lucchetto "un giro alla volta"** tra i due cron
    (`grep -n "lock" run_pipeline.py pipeline_run.py`: niente). Oggi un giro
    dura minuti; con il modello locale durerà ore.

**Analisi**

13. **Chiave Anthropic rifiutata dal 14/10** (`invalid x-api-key`, 182 righe
    nel log, tutti i giorni in cui c'era lavoro). Ultima consegna in blocco:
    3/10 (`BatchRun`, 26 righe tutte ritirate).
14. **Chi ha analizzato i reel pubblicati dal 14/10**: Groq 162
    (`gpt-oss-120b` 101, `gpt-oss-20b` 61), modello locale 3b 9. Nessuno
    Anthropic. Il terzo fornitore della catena (`flow`) risponde 403 "saldo
    insufficiente".
15. **Falliti oggi nel database**: affermazioni dei reel 117, analisi articoli
    34, affermazioni articoli 159 (121 di queste dal 14/10). Cause scritte
    sulle righe: risposta tagliata a metà (`Unterminated string`, 142) e
    attesa scaduta verso Ollama (`ReadTimeout`, 81).
16. **Perché il locale fallisce oggi**: il 7b legge il prompt a 14 token al
    secondo (misurato). Un prompt da 2044 token richiede 136 secondi di
    silenzio, e `client.py` (riga 141) chiude la connessione dopo 120: è
    coerente con gli 81 `ReadTimeout`, ma il legame non l'ho riprodotto. Poi la
    risposta ha un tetto di 240 secondi (riga 139): un elenco di affermazioni
    ne ha chiesti 296 solo per scrivere. In più Ollama carica 4096 token di
    finestra, e prompt più risposta ne chiedono fino a 4900.
17. **Tempi veri del modello locale** (prompt veri presi dal database,
    6 thread, finestra 8192, risposta JSON, modello già caricato):

    | Contenuto | Chiamata | Token letti / scritti | 7b | 3b |
    |---|---|---|---|---|
    | Reel medio (982 caratteri di parlato) | analisi | 1391 / 217 | 175 s | 76 s |
    | | affermazioni | 865 / 485 | 240 s | 102 s |
    | Reel lungo (3018 caratteri) | analisi | 2044 / 190 | 198 s | 101 s |
    | | affermazioni | 1518 / 871 | 399 s | 98 s |
    | Articolo medio (4467 caratteri) | analisi | 1617 / 182 | 150 s | non provato |
    | | affermazioni | 1599 / 122 | 149 s | non provato |

    Velocità: 7b legge 13,5-16 token/s e scrive 2,7-3,8; 3b legge 30-35 e
    scrive 5,7-6,8. Caricare il 7b a freddo: 123 secondi, una volta per giro.
    Dieci chiamate su dieci hanno dato JSON valido.
18. **Qualità, sugli stessi 3 contenuti** (campione minuscolo: indica, non
    dimostra). Riferimento: l'analisi già salvata, fatta da Claude Opus.

    | | Riferimento | 7b | 3b |
    |---|---|---|---|
    | Tema del reel medio | «caffè in menopausa» | «caffè» | «caffè in menopausa» |
    | Tema del reel lungo | «glicemia e disfunzione erettile» | «intimità» | «glicemia alta» |
    | Tema dell'articolo | «endocrino-senescenza e ormoni bioidentici» | «endocrino-senescenza» | - |
    | Citazioni vere, reel medio | 6 salvate | 6 su 6 | 6 su 6 |
    | Citazioni vere, reel lungo | 0 salvate | 3 su 6 | 2 su 6 |
    | Citazioni vere, articolo | 2 salvate | 0 su 1 | - |

    Le citazioni false non entrano comunque nel database: il controllo
    "la citazione deve esistere nel testo" le scarta (`enrich_agent.py` riga
    310). Si perde l'affermazione, non si salva un'invenzione.
19. **I punti che chiamano un modello sono 16 in 10 file**, tutti passano da
    `chat()`. Dentro la pipeline: `enrich` (2), `knowledge` (2), `cluster`
    (nomi dei temi), `blogscrape` (riconoscere gli articoli).
20. **`enrich` e `knowledge` lanciano 5 chiamate insieme** (`ENRICH_WORKERS`),
    ma il modello locale ne fa una alla volta e chi aspetta più di 900
    secondi fallisce. Con chiamate da 150-400 secondi il quinto in fila
    aspetta 600-1600 secondi: **fallirebbe, e resterebbe `failed`**.
21. **La trascrizione è Groq, non Anthropic**: 1460 trascrizioni su 1473 sono
    `whisper-large-v3` remoto. Il Whisper locale installato è solo `small`.
22. **Volumi**: 1618 reel (1366 con parlato, 227 solo didascalia, 24 vuoti;
    il 18% ha più di 3000 caratteri di parlato), 2211 articoli, circa 80
    articoli nuovi a settimana nelle ultime due.

### Cosa dipende oggi da Apify e da Anthropic

**Apify**

| File | Cosa fa |
|---|---|
| `BEC/scraper/apify_provider.py` | la chiamata che elenca i reel di un account (riga 109: il 401) |
| `BEC/scraper/apify_budget.py` | il tetto di spesa |
| `BEC/pipeline/agents/scraper_agent.py` | `_scrape_account_apify`, `_apify_depth`, e la scelta in `run()`: senza Graph e senza Apify la raccolta è «sospesa» |
| `BEC/pipeline/agents/downloader_agent.py` | `_prefetch_urls`: solo comodità, il download va anche senza |
| `BEC/core/views.py` | il tetto di spesa mostrato in Stato e quando si aggiunge un account (2 punti) |
| `BEC/core/queue_eta.py`, `core/management/commands/import_apify.py`, `config/settings/base.py`, 2 test | riferimenti minori |

**Anthropic**

| File | Cosa fa |
|---|---|
| `BEC/llm/batch.py`, `BEC/pipeline/agents/batch_agent.py`, comando `sonnet_batch` | lo stadio `batch`: solo Anthropic. Copre analisi dei reel, analisi e affermazioni degli articoli |
| `BEC/llm/client.py` (`_anthropic_chat`) | Anthropic è il **primo** della catena (`LLM_ENDPOINTS=anthropic,groq,flow`): ogni chiamata prova lì per prima. Vale per tutti i 16 punti: `enrich`, `knowledge`, `cluster`, `blogscrape`, la chat del Second Brain, il riordino della ricerca MCP, strategia, piano editoriale, ideazione, bozze blog |
| `BEC/.env` | `BATCH_ENABLED=1`, `BATCH_MODEL`, le righe `LLM_ANTHROPIC_*` |

In pratica (fatti 13-14) oggi Anthropic non fa più niente: ogni chiamata
perde un tentativo lì e poi va su Groq.

### Proposta: due PR, in quest'ordine

**PR 1 - Raccolta senza Apify.** È la cosa rotta, ed è indipendente
dall'analisi. Da sola rimette in moto tutto: i reel nuovi vengono scaricati,
trascritti e analizzati dalla catena di oggi (Groq).

**PR 2 - Analisi in casa.** Porta codice che non cambia niente finché non si
cambia il `.env`. Dentro c'è prima la prova di qualità; l'interruttore lo gira
il rilasciatore solo dopo che Giuseppe ha letto il risultato.

Perché non una sola: la raccolta è urgente e si collauda in un'ora; l'analisi
ha una decisione di qualità che può richiedere giorni. Unite, la seconda
terrebbe ferma la prima.

### PR 1 - Come si leggono i 23 account

Un fornitore nuovo, `BEC/scraper/embed_provider.py`, che per ogni account:

1. chiede `https://www.instagram.com/<utente>/embed/` attraverso il proxy,
   con un IP nuovo per ogni account e l'impronta di Chrome (`curl_cffi`,
   come fa già `ig_client.py`);
2. legge il blocco `contextJSON` della pagina e ne tira fuori i post;
3. tiene solo i video **il cui proprietario è proprio quell'account** (vedi
   rischi), e li consegna nello stesso formato degli altri fornitori
   (`ReelMeta`, `ProfileMeta`).

Tutto il resto resta com'è: `_upsert_reel` salva, il download scarica con
`yt-dlp` dal codice del reel, come già fa quando non ha un indirizzo in tasca.

Scelte:

- **Nessun account Instagram, nessuna sessione, nessun cookie.** È la stessa
  regola di prima: si legge solo ciò che un visitatore anonimo vede.
- **Chi raccoglie si decide in un punto solo**: `scraper_agent.run()`. Ordine:
  Graph API se configurata (oggi no), poi `embed` se c'è il proxy, altrimenti
  «sospeso» con la frase in chiaro. **Apify non viene più chiamato**, nemmeno
  se il token è ancora nel `.env`.
- **Impostazione nuova `IG_PROXY`**, che se vuota usa `YTDLP_PROXY`. Nessun
  segreto nuovo.
- **Il pre-riempimento Apify del download si spegne** (`_prefetch_urls` non
  viene più chiamato). Le chiavi `apify_accounts`/`apify_urls` spariscono dal
  log.
- **Download: prima diretto, poi dal proxy solo se Instagram blocca.** Il
  proxy si paga a gigabyte e un video pesa circa 13 MB: tutti dal proxy
  sarebbero circa 3 GB al mese (stima), diretti costano zero. Il blocco è già
  riconosciuto (`IGThrottled` in `_ytdlp_fetch`).
- **Durata del video**: la scrive il download leggendola dal file (`ffprobe`,
  già usato lì), perché l'embed non la dà.
- **Passo tra un account e l'altro**: 5-10 secondi a caso (`min_delay_s` in
  `ScraperConfig`, oggi 20). 23 account, circa 4 minuti.
- **Blocco riconosciuto, mai insistito**: risposta 401/403/429, rimando al
  login, o pagina senza `contextJSON`. Un solo secondo tentativo con un IP
  nuovo, poi l'account è fallito per quel giro (`IGBlocked` /
  `IGSchemaChanged`, già esistenti) e la pipeline va avanti. Se falliscono
  tutti, la nota dello stadio lo dice («Instagram non risponde»), e lo stadio
  non finisce più «riuscito con 23 falliti su 23» in silenzio.
- **Avviso di buco**: se tutti i 6 post letti sono nuovi, è probabile che ce
  ne siano altri più vecchi non visti. Si scrive nello stato dell'account e
  nella nota dello stadio. Non si finge di averli.
- **Stato**: il riquadro del tetto di spesa Apify non ha più senso; mostra
  «Raccolta: lettura diretta dal VDS» e l'esito dell'ultimo giro.

Peso sul proxy: 245 KB per account, 23 account, 2 giri al giorno: circa
11 MB al giorno, 0,35 GB al mese (misura di una pagina, il resto è conto). Il
prezzo al GB di IPRoyal non l'ho verificato.

**File da toccare (PR 1)**

| File | Perché |
|---|---|
| `BEC/scraper/embed_provider.py` (nuovo) | leggere e interpretare la pagina embed |
| `BEC/scraper/proxy.py` (nuovo, piccolo) | l'indirizzo del proxy e la pulizia degli errori, oggi dentro `core/link_ingest.py` (`_proxy`, `_scrub`): spostati qui e importati da lì, così c'è una copia sola |
| `BEC/pipeline/agents/scraper_agent.py` | ramo `embed` in `_scrape_one`, scelta del fornitore in `run()`, avviso di buco, nota «tutti falliti» |
| `BEC/pipeline/agents/downloader_agent.py` | via `_prefetch_urls`, proxy di riserva sul blocco, durata dal file |
| `BEC/config/settings/base.py`, `BEC/.env.example` | `IG_PROXY` |
| `BEC/core/views.py`, pagina Stato (`FEC`) | togliere il tetto di spesa dalla vista |
| `BEC/core/tests/test_embed_provider.py` (nuovo) | pagina salvata come campione; proprietario diverso scartato; pagina senza dati = `IGSchemaChanged`; login = `IGBlocked`. In CI Instagram non c'è |
| `documentation/low-level/02-pipeline.md`, `07-content-lineage.md`, `.claude/architecture-summary.md`, `CLAUDE.md`, drawio (pagine 1 e 2), pagina `Documentazione` | la raccolta cambia strada: tabella «cosa è chiuso» aggiornata con la prova dal proxy, sezione sui soldi di Apify archiviata, limiti nuovi |

**Cosa si riusa (PR 1)**: `_upsert_reel`, `_dump_raw`, `_apply_profile`,
`_scrape_one` e il conteggio `progress.*` in `scraper_agent.py`;
`ReelMeta`, `ProfileMeta`, `IGBlocked`, `IGSchemaChanged` in
`scraper/types.py`; la sessione Chrome di `ig_client.build_session`;
`_proxy`/`_scrub` di `link_ingest.py`; `_ytdlp_fetch` e `_has_audio` nel
download; `scrape_state.consecutive_failures` già tenuto per account.

### PR 2 - Analisi in casa

**1. Chi risponde si sceglie per tipo di lavoro.** Impostazione nuova
`LLM_PIPELINE_PROVIDER_ORDER`. Se vuota non cambia niente. Con `ollama`, le
chiamate fatte dentro la pipeline usano solo il modello locale; chat,
strategia e ricerca MCP continuano con l'ordine generale. Si legge in un punto
solo, `client._providers()`, guardando l'etichetta che ogni chiamata porta già
(`usage.current()["process"]`, che per la pipeline comincia con `pipeline:`).
I 16 punti non si toccano.

Perché non spegnere tutto con il solo `.env` (`LLM_PROVIDER_ORDER=ollama`):
funzionerebbe senza codice, ma anche la chat passerebbe al locale. Una
risposta di chat legge circa 2000 token e ne scrive 400: sul 7b sono circa
4-5 minuti (stima dai tempi del fatto 17), e la ricerca MCP con riordino
andrebbe fuori tempo.

**2. Tre correzioni senza le quali il locale fallisce** (fatti 16 e 20):

- `OLLAMA_NUM_CTX` (proposto 8192), mandato a Ollama come `num_thread`. Con
  8192 il 7b occupa 5,5 GB su 94.
- Tempi di attesa per le chiamate di pipeline: silenzio ammesso mentre legge
  il prompt da 120 a 600 secondi; tetto della risposta da 240 a 1500 secondi
  (`OLLAMA_PIPELINE_TIMEOUT`). E una risposta JSON tagliata dal tetto diventa
  un errore con il suo nome («risposta locale tagliata dopo N secondi»),
  non un `Unterminated string` che manda a cercare il difetto nel prompt.
- Un lavoro alla volta: quando la pipeline è solo locale, `_parallel`
  (`enrich_agent.py`, usato anche da `knowledge`) usa 1 filo invece di 5.

**3. Lo stadio `batch` si spegne con `BATCH_ENABLED=0`.** Già previsto dal
codice: lo stadio dice «non configurato» e `enrich`/`knowledge` fanno il
lavoro dal vivo. Il codice del batch resta, spento. Non ci sono consegne
aperte da ritirare (fatto 13).

**4. Un giro alla volta.** Lucchetto su file in `run_pipeline` e nel giro
lanciato a mano: se un giro è in corso, il secondo esce dicendolo. Senza, il
giro del pomeriggio parte sopra quello della notte (fatto 12).

**5. Tetto per giro.** `PIPELINE_LOCAL_MAX_ITEMS` (proposto 40): oltre, i
contenuti restano `pending` per il giro dopo. Non `failed`: non sono stati
provati. Così un arretrato si smaltisce in più notti invece di un giro da 10
ore che blocca temi e ricerca.

**6. La prova di qualità, prima di accendere.** Comando nuovo
`manage.py eval_local`, sola lettura sui contenuti: prende N reel e N articoli
già analizzati da Claude, li fa rianalizzare dal modello locale, e scrive un
rapporto in `logs/evals/` (come fa già `eval_mcp`). Per ogni modello: JSON
valido, tema uguale o vicino a quello di riferimento, tema "ombrello"
rifiutato, citazioni vere su citazioni proposte, secondi per contenuto. Non
scrive niente nelle tabelle dei contenuti. Con 30 reel e 20 articoli: circa
5 ore di macchina sul 7b, circa 2 sul 3b (stima).

**File da toccare (PR 2)**

| File | Perché |
|---|---|
| `BEC/llm/client.py` | ordine per la pipeline in `_providers()`; `num_ctx`; tempi; errore chiaro sulla risposta tagliata |
| `BEC/config/settings/base.py`, `BEC/.env.example` | `LLM_PIPELINE_PROVIDER_ORDER`, `OLLAMA_NUM_CTX`, `OLLAMA_PIPELINE_TIMEOUT`, `PIPELINE_LOCAL_MAX_ITEMS` |
| `BEC/pipeline/agents/enrich_agent.py` | 1 filo se locale; tetto per giro. Serve anche `knowledge_agent.py` per il tetto |
| `BEC/core/management/commands/run_pipeline.py`, `BEC/core/pipeline_run.py` | un giro alla volta |
| `BEC/core/management/commands/eval_local.py` (nuovo) | la prova di qualità |
| `BEC/core/queue_eta.py` | solo se la stima «quanto manca» risulta falsa con i tempi nuovi: da guardare in collaudo |
| test: `test_ollama_options.py` (esteso), `test_provider_order.py` (nuovo) | `num_ctx` nel payload; pipeline → solo locale, chat → ordine generale; risposta tagliata = errore; secondo giro rifiutato |
| `documentation/low-level/03-llm-and-embeddings.md`, `02-pipeline.md`, `.claude/architecture-summary.md`, `CLAUDE.md`, drawio pagina 2, pagina `Documentazione` | chi analizza, con i tempi misurati e i limiti |

Il `.env` vero lo cambia il rilasciatore, chiedendo conferma:
`LLM_PIPELINE_PROVIDER_ORDER=ollama`, `BATCH_ENABLED=0`, `OLLAMA_MODEL` scelto
dopo la prova, e via `anthropic` da `LLM_ENDPOINTS`.

**Cosa si riusa (PR 2)**: `usage.scope`/`usage.current()` (PR #20) per sapere
chi chiama; `_ollama_slot` con la precedenza alle richieste di una persona
(`priority=True`, già usata dalla strategia); `OLLAMA_NUM_THREAD` come modello
per `OLLAMA_NUM_CTX`; `build_enrich_prompt`, `build_doc_enrich_prompt`,
`build_doc_arguments_prompt` e il controllo delle citazioni (`_norm`) per la
prova di qualità; `llm_calls` e la pagina Avanzamento, che da qui si riempiono
da sole; `Enrichment.llm_model`, che già scrive `ollama:<modello>`.

### Quante ore-macchina (stima costruita sulle misure del fatto 17)

Per contenuto, a modello caldo: reel medio 7 minuti sul 7b (175 + 240 s),
reel lungo 10; articolo medio 5. Media pesata sui reel: circa 6,6 minuti
(84% con parlato, di cui 18% lunghi; i «solo didascalia» stimati a 2,5).
Sul 3b: reel circa 3 minuti (misurato su due), articolo circa 2 (stimato).

| Lavoro | Quanti | 7b | 3b |
|---|---|---|---|
| Giro del pomeriggio | 4 reel | 0,5 h | 0,2 h |
| Giro della notte | 4 reel + 11 articoli | 1,4 h | 0,6 h |
| **Un giorno tipico** | | **circa 1,9 h** | **circa 0,8 h** |
| In attesa oggi | 35 affermazioni di articoli, 1 reel | 1,5 h | 0,6 h |
| Buco di 12 giorni | 61-94 reel | 7-10 h | 3-5 h |
| Falliti, **solo se** Giuseppe li fa riprovare | 117 + 34 + 159 chiamate | circa 18 h | circa 8 h |
| Rifare tutto il corpus (**non proposto**) | 1618 reel + 2211 articoli | circa 360 h, 15 giorni | circa 6-7 giorni |

Sono misure di 10 chiamate moltiplicate per i volumi del database: stime, da
sostituire con i numeri veri di `llm_calls` dopo la prima notte. Il 7b può
arrivare al massimo a 1,8 volte tanto con le risposte in parallelo (7,1
token/s misurati contro 3,9), ma serve `sudo` e rifare il lucchetto: fuori da
questo lavoro.

### Rischi

- **`owner_type` (binario, mai un terzo valore)**: nessun valore nuovo; il
  reel prende il proprietario dall'account seguito, come oggi. Ma c'è un punto
  che la modifica sfiora: `_upsert_reel` riga 98 riassegna il reel all'account
  che lo sta leggendo. Un reel **in collaborazione** tra Medyca e un
  concorrente compare su tutti e due i profili e cambierebbe parte a ogni
  giro. Il fornitore nuovo deve consegnare solo i post il cui proprietario è
  l'account richiesto, e scartare la pagina se il nome nel `contextJSON` non
  è quello chiesto. Va nel test.
- **I falliti restano `failed`**: un account bloccato fallisce per quel giro
  e basta; una risposta locale tagliata è `failed` con la causa vera; il
  tetto per giro lascia `pending` solo ciò che non è stato provato. Nessun
  azzeramento. I 310 falliti di oggi non si toccano senza un ordine.
- **Credenziali**: nessun account Instagram, nessun cookie, nessuna chiave
  nuova. Il proxy è un servizio pagato da Medyca, già nel `.env`; il suo
  indirizzo contiene una password e non deve finire in log o messaggi
  (`_scrub`). Da togliere dal `.env` a fine lavoro: `APIFY_TOKEN`, la chiave
  Anthropic morta. Da segnalare: il fornitore `flow` (`aiapiflow.com`, un
  rivenditore di modelli Claude) è ancora nella catena, senza saldo.
- **Instagram può chiudere la strada embed quando vuole.** È una pagina
  pubblica non documentata, provata una volta su un account. Se cambia, la
  raccolta si ferma e lo dice; non c'è una seconda strada pronta.
- **Solo 6 post per lettura.** Se un account pubblica più di 6 post tra due
  letture, i più vecchi si perdono. Oggi il massimo è 1,25 a mezza giornata.
- **Niente visualizzazioni sui reel nuovi.** `core/weighting.py` conta
  visualizzazioni + 5 × "mi piace": un reel senza visualizzazioni sembrerà
  debole rispetto alla mediana del suo account, che le visualizzazioni le ha.
  Tocca classifiche, strategia e ordine di download (6 file usano
  `view_count`). Da decidere, vedi domanda 5.
- **Qualità dell'analisi locale** (fatto 18): temi più generici e meno
  affermazioni salvate. I temi generici sono proprio il difetto che aveva
  prodotto «menopausa» su mezzo corpus. Il corpus avrebbe due mani diverse:
  1617 reel letti da Claude e Groq, i nuovi dal modello locale.
- **Nomi dei temi**: `cluster` chiede al modello il nome di ogni tema nuovo.
  È un testo che il cliente legge. Con il locale va guardato nella prova.
- **Giri lunghi**: un giro di ore tiene occupato il modello; una richiesta di
  una persona passa davanti solo tra una chiamata e l'altra (fino a 6-7
  minuti di attesa).
- **Il download dal nuovo IP non è stato riprovato.** Se Instagram lo blocca,
  ogni video passa dal proxy e costa traffico.
- **Groq è gratuito e ha tetti giornalieri**: finché l'analisi resta lì (dopo
  PR 1, prima di PR 2), un giorno di recupero con 60-90 reel può finire sul
  locale e fallire come oggi. Per questo il recupero del buco va fatto con il
  tetto basso (`--limit`) o dopo PR 2.

### Cosa resta fuori

- Reel più vecchi degli ultimi 6 per account (i circa 33 del buco, e tutto lo
  storico di un account aggiunto da zero).
- Storie, caroselli e foto: solo video, come oggi.
- Visualizzazioni, se `yt-dlp` non le dà (da misurare in sviluppo).
- Cancellare il codice di Apify e del batch: restano spenti. Pulizia a parte.
- Trascrizione in casa: resta Groq Whisper con il locale `small` di riserva.
  Il `large-v3` locale non è installato (3 GB) e non è misurato.
- Chat, strategia, piano editoriale, bozze e ricerca MCP: restano sulla
  catena remota (senza Anthropic, quindi Groq).
- Risposte in parallelo di Ollama, modelli locali diversi da quelli già
  installati, spostare le regole fisse in testa al prompt per non rileggerle
  ogni volta (circa 800 token su 1391: risparmio possibile, non misurato).
- Riprovare i 310 falliti e rianalizzare il corpus.
- Graph API ufficiale di Meta: resta nel codice, non configurata.

### Domande aperte per Giuseppe

1. **«Senza Anthropic» vuol dire anche senza Groq?** Oggi il lavoro lo fa
   Groq, gratis, ma è un fornitore esterno. Proposta: la pipeline passa al
   VDS, chat e strategia restano su Groq perché in locale una risposta
   richiede 4-5 minuti. Oppure tutto locale, sapendolo.
2. **Quale modello locale?** Sul campione piccolo il 3b non è peggio del 7b
   ed è 2,3 volte più veloce. Posso far girare la prova su 50 contenuti
   (circa 7 ore di macchina per i due modelli) prima di decidere? E vuoi
   provare anche un modello più grande (serve scaricarlo)?
3. **Se la prova dice che la qualità non basta**, cosa preferisci: restare su
   Groq per l'analisi, o accettare temi più generici?
4. **Il buco di 12 giorni**: va bene recuperare circa 61 reel e perderne
   circa 33 di 5 account molto attivi? L'alternativa è provare la strada più
   profonda (fatto 8), che richiede il tuo OK esplicito e non so se funziona.
5. **Reel nuovi senza visualizzazioni**: va bene pesarli solo con i "mi
   piace" finché non troviamo il numero? Altrimenti le classifiche li
   mostrano più deboli di quanto sono.
6. **I 310 falliti** (117 + 34 + 159): li facciamo riprovare una volta, a
   mano, dopo PR 2 (circa 18 ore sul 7b), o restano così?
7. **Apify e batch**: codice spento ma presente, o cancellato subito? E posso
   far togliere dal `.env` il token Apify, la chiave Anthropic e il
   rivenditore `flow`?
8. **Leggere Instagram più spesso** (ogni 6 ore invece di 2 volte al giorno)
   per stare larghi sui 6 post: costa circa 0,7 GB al mese di proxy (stima).
   Lo vuoi?
9. **La trascrizione resta su Groq** per ora, o deve venire in casa anche
   quella? È un lavoro a sé, con la sua misura da fare.

## 3. Sviluppo           (sviluppatore)

Solo la PR 1 (raccolta senza Apify). Niente della PR 2.

### Cosa è stato fatto

- **`BEC/scraper/embed_provider.py` (nuovo)**: legge `instagram.com/<utente>/embed/`
  dal proxy (IP nuovo a ogni richiesta, impronta Chrome), estrae `contextJSON`,
  consegna `ReelMeta`/`ProfileMeta`. Tiene **solo i video il cui proprietario è
  l'account richiesto**; scarta la pagina se il nome nel `contextJSON` è un altro.
  Blocco (401/403/429, login, pagina senza dati) = un solo secondo tentativo con IP
  nuovo, poi `IGBlocked`/`IGSchemaChanged`. 404 non si ritenta.
  "Mi piace" nascosti dall'account (`like_and_view_counts_disabled`) = `None`, non 0,
  così `_upsert_reel` non sovrascrive niente con uno zero finto.
- **`BEC/scraper/proxy.py` (nuovo)**: `scrub`, `ytdlp_proxy`, `ig_proxy`
  (`IG_PROXY`, se vuoto `YTDLP_PROXY`). `core/link_ingest.py` li importa e tiene i
  nomi `_scrub`/`_proxy` (i test li patchano così): una copia sola.
- **`scraper_agent.py`**: `run()` sceglie in un punto: Graph se configurata, poi
  `embed` se c'è il proxy, altrimenti "sospeso". **Apify non è più chiamato**
  (codice e funzioni restano, spente). Medyca (`owned`) letta per prima. Pausa
  5-10 s tra account (`embed_delay_s`). Tetto di 10 reel nuovi per giro
  (`embed_max_new_per_run`, i più recenti prima). 3 account bloccati di fila fermano
  il giro. `gap_possible` e `deferred` in `scrape_state` e nella nota dello stadio.
  **Se nessun account è stato letto lo stadio fallisce** (`ClientError` "Instagram
  non risponde...") invece di chiudersi `done`.
- **`downloader_agent.py`**: via `_prefetch_urls` e le chiavi `apify_*` dal log.
  `yt-dlp` prima diretto, poi **un** tentativo dal proxy solo se bloccato
  (`IGThrottled` se blocca ancora, come prima: il reel non paga un tentativo).
  Durata letta dal file (`ffprobe`); visualizzazioni/like/commenti presi da yt-dlp
  se li ha. Errori di yt-dlp passati da `scrub`.
- **Stato**: `core/views.py` non chiama più `apify_budget`; `budget` è `null`,
  nuovo `collection` (modo + esito dell'ultimo stadio `scrape`);
  `collection_paused_until` sempre `null`. Frontend: `CollectionBox` al posto di
  `BudgetBar` (`PipelineQueue.tsx`, `Status.tsx`, `it.json`). `tsc` pulito.
- **Impostazioni**: `IG_PROXY` in `config/settings/base.py` e `.env.example`.
- **Documentazione**: `02-pipeline.md` (nuova sezione, tabella "cosa è chiuso",
  diagramma del download, limiti), `05-rest-api.md`, `06-frontend.md`,
  `07-content-lineage.md`, `.claude/architecture-summary.md`, drawio (le due
  viste), pagina `Documentazione` (testi in `it.json`: raccolta, limiti, visualizzazioni).
  `CLAUDE.md` non nomina Apify: non toccato. Brain: `apis/instagram-embed-profile.md`.

### Prove (esito vero)

- **Test**: `manage.py test core` su un Postgres usa-e-getta a lato (il database di
  produzione non è stato toccato; l'utente non può creare database): **267 test,
  OK**. Nuovi: 31 in `core/tests/test_embed_provider.py` (parsing, proprietario
  diverso scartato, reel in collaborazione che NON cambia parte in un giro
  completo, pagina di altro nome, senza dati, login, un solo secondo tentativo con
  IP diverso, 404 senza retry, password mai nell'errore, tetto per giro, nessun
  buco falso se ci sono reel noti, un account bloccato fallisce da solo, tutti
  falliti = stadio fallito, 3 blocchi = stop, senza proxy = sospeso, Apify mai
  chiamato, download diretto-poi-proxy). Cambiati 2 test di Stato.
- **Prova vera, una sola lettura dei 23 account** dal proxy, senza scrivere nel
  database (script a lato, 211 s): **22 su 23 letti**. 4 account con 0 video negli
  ultimi 6 post (foto/caroselli), il più attivo ne ha 6. `elena,palliotto` (virgola
  nel nome) fallisce: pagina senza dati, dopo il secondo tentativo. Medyca: 6 post,
  4 video, "mi piace" nascosti (-> `None`). Un solo 504 dal proxy visto nelle prime
  prove, passato al secondo tentativo con IP nuovo.
- **Download vero**: un reel di Medyca con yt-dlp **diretto**, senza proxy, dal nuovo
  IP: 17 MB in circa 1 s, file valido. yt-dlp **non** dà `view_count` né `duration`
  (conferma: niente visualizzazioni sui reel nuovi); dà `like_count` e
  `comment_count`.

### Differenze dal disegno

- **Tetto per giro** (decisione 7): il disegno chiedeva "un tetto o equivalente".
  Scelta più semplice: `embed_max_new_per_run` in `scraper_config`, default **10**
  reel nuovi per giro, i più recenti. Non è "niente recupero": al primo giro entrano
  10 reel nuovi, al successivo altri 10, finché i vecchi restano tra gli ultimi 6
  dell'account. Per **tenere chiuso il buco fino alla PR 2** il rilasciatore può
  scrivere `embed_max_new_per_run = {"value": 3}` (o 0) in `scraper_config` al
  rilascio: nessun codice da cambiare. Decisione per il capo.
- **Fermo dopo 3 blocchi di fila** (non nel disegno): evita di chiedere 20 volte a
  un IP già rifiutato.
- **Stadio `failed` se nessun account è stato letto** (il disegno diceva "la nota
  lo dice"): ho scelto `failed` perché la nota da sola non cambia il colore della
  barra. Se tutti falliscono, il giro continua (lo stadio non è fatale).
- **yt-dlp dà like/commenti/visualizzazioni**: li scrivo sul reel se presenti
  (il disegno prevedeva solo la durata).
- **`budget` resta nella risposta, a `null`**, e `collection_paused_until` a `null`,
  per non rompere pagine vecchie. `addedBudgetPaused` resta in `it.json`, inutilizzato.
- Medyca letta per prima (`order_by("-owner_type")`): non nel disegno, evita che
  tetto o blocco tolgano proprio i contenuti del cliente.
- Cambiato `queue_eta.py` solo nel commento.

### Cosa NON ho potuto provare

- **yt-dlp dal proxy** (il ramo "bloccato, riprovo dal proxy"): coperto solo dai test
  con mock; dal nuovo IP il diretto funziona, quindi non c'era un blocco da provocare.
- **Il giro intero scritto nel database**: non fatto di proposito (produzione). Il
  percorso scraper -> `_upsert_reel` è provato dai test su database a lato.
- **La pagina Stato nel browser** (mobile e desktop): ho solo `tsc`, non il gesto vero.
  Tocca al collaudatore.
- Prezzo al GB di IPRoyal: non verificato.
- Il sorgente `view_count` NULL: in Postgres `ORDER BY view_count DESC` mette i NULL
  per primi, quindi i reel nuovi si scaricano prima dei vecchi. Non l'ho cambiato
  (non c'è nel disegno); è scritto nei limiti.

### Cosa va fatto in produzione al rilascio

1. Nessuna variabile obbligatoria: `IG_PROXY` vuoto usa `YTDLP_PROXY`, già nel `.env`.
2. Riavviare i servizi (backend per views/pipeline; rebuild del frontend per
   `CollectionBox`).
3. Decidere il tetto del primo giro: lasciare 10, oppure
   `ScraperConfig` `embed_max_new_per_run` = `{"value": 3}` per non recuperare il
   buco prima della PR 2 (decisione 7). Nessuna migrazione.
4. Da togliere dal `.env` quando Giuseppe dice sì (non ora): `APIFY_TOKEN`.
5. Un giro a mano (`Aggiorna ora`) e guardare `/stato`: «Raccolta: lettura diretta dal
   server» + esito. Atteso: 22 account letti, `elena,palliotto` fallito
   (il nome va corretto o l'account disattivato: serve una decisione di Giuseppe).

## 4. Revisione          (revisore)
## 5. Collaudo           (collaudatore)
## 6. Rilascio           (rilasciatore)
## Registro delle decisioni

- 2026-11-14 - Lavoro aperto dal capo dopo il rilascio della PR #20. Lo
  scraper fermo (Apify 401 dal 12/11) rende urgente la parte «senza Apify».
- 2026-11-14 - **Giuseppe approva la direzione con una correzione**: alle
  proposte del capo sulle domande aperte ha risposto «Shifta tutto locale».
  Lettura del capo (interpretazione, non parole sue): niente fornitori esterni
  di modelli, quindi nemmeno Groq, né per l'analisi né per chat/strategia né
  per la trascrizione. Scelte chiuse:
  1. **Questo file e questo ramo coprono solo la PR 1, la raccolta senza
     Apify**, come da disegno (fornitore embed dal proxy IPRoyal, solo i post
     il cui proprietario è l'account richiesto). La risposta di Giuseppe non
     cambia nulla della PR 1.
  2. **La PR 2 cambia portata**: non più "solo la pipeline sul locale, chat su
     Groq", ma tutto sul VDS (analisi, nomi dei temi, chat, strategia,
     trascrizione). Il disegno della PR 2 scritto qui sopra è superato su
     questi punti: l'architetto lo rifà in
     `.claude/tasks/2026-11-14-analisi-in-casa.md`. Lo sviluppatore della PR 1
     non implementa nulla della PR 2 e non committa quel file.
  3. Strada più profonda di Instagram (12 reel per pagina): **non approvata**.
     Si recuperano i circa 61 reel raggiungibili con l'embed.
  4. Reel nuovi pesati con i soli "mi piace" finché mancano le visualizzazioni;
     va scritto tra i limiti noti.
  5. Due letture al giorno, come oggi.
  6. Il codice di Apify resta, spento; non si cancella in questa PR.
  7. Recupero del buco di 12 giorni: non in automatico al primo giro. Si fa
     dopo la PR 2, perché senza le correzioni il locale fallirebbe e i
     contenuti resterebbero `failed`.
