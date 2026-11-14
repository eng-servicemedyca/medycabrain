---
id: 2026-11-14-pipeline-in-casa
titolo: Raccolta di Instagram senza Apify (PR 1 di "pipeline in casa")
stato: pronto
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
  5-10 s tra account (`embed_delay_s`). Tetto di 5 reel nuovi per giro
  (`embed_max_new_per_run`, i più recenti prima; era 10, vedi «Secondo giro»). 3 account bloccati di fila fermano
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

### Secondo giro (dopo revisione e collaudo)

Commit nuovo sul ramo, `b25776b` non riscritto. Cosa ho cambiato:

- **B1**: `embed_max_new_per_run` ora **5** nel codice (`scraper_agent.run()`, docstring, `_scrape_one`), in `02-pipeline.md`, `it.json`, drawio e in questo file. Tolto dal «da fare in produzione» il passo "decidere il tetto". Nuovo test del default (6 post nuovi: 5 entrano, 1 rinviato).
- **N1**: `_better_count` nel download: scarta negativi e `None`, non scrive mai un valore più basso di quello che c'è, e **non scrive mai i «mi piace» di yt-dlp se il reel ha i like nascosti** (`like_count is None`). Prova (una, `extract_info(download=False)` su due reel di Medyca): `like_count 3` su **tutti e due** (`Dfor_3UxXDk` 3, `Dfh27oyx418` 3) mentre i commenti sono 4 e 0, su un account da 3083 follower che nasconde i like. Giudizio: **non è un numero credibile** (costante uguale su reel diversi), quindi per i like nascosti resta `None`. Scritto nei limiti.
- **N2**: `nulls_last` per `view_count` nella lista reel (nuova `NullsLastOrdering`, anche per like e commenti), nelle miniature dei temi e nei 5 «top» della mappa Second Brain (`core/views.py`). **Download non cambiato, di proposito**: lì i NULL per primi sono giusti (sono i reel nuovi; con `nulls_last` finirebbero dietro ogni vecchio reel con un numero). Scritto nel commento e nei limiti. Test: lista ordinata per `-view_count` e mappa Second Brain (il reel senza numero non entra nei 5 top).
- **A**: nuova `AccountNotFound`. Un nome che non è un username Instagram (`^[A-Za-z0-9._]{1,30}$`, quindi `elena,palliotto`) o un 404 = `not_found`, senza richiesta e senza secondo tentativo. Una pagina senza dati mentre altri account si sono letti nello stesso giro = `not_found` (nome sbagliato), non «Instagram ha cambiato la pagina». Tolto il log «doc_id rotated»; `last_error` ha il suo tipo **una volta sola** (`not_found: …`, niente `error: error:`).
- **B**: senza proxy lo stadio ora **fallisce** con «La raccolta è sospesa: manca la connessione (proxy)…» invece di chiudersi `done` con la frase solo nel valore di ritorno. Così la pagina Stato non dice più «sospesa» e «tutto in ordine» insieme.
- **C**: se nessun account è letto, l'errore dello stadio è una frase breve per tipo (`_CLIENT_REASON`: rifiutato, pagina cambiata, nome non trovato, non raggiungo Instagram dal proxy). Niente testo curl nel riquadro; il dettaglio resta nel log e in `last_error`.
- **Documentazione**: N3 (peso zero dei reel nuovi di Medyca), N4 (tabella delle impostazioni `embed_delay_s`, `embed_max_new_per_run`, `impersonate`), N5 (vecchio reel in collaborazione può tornare al proprietario vero), N6 (reel cancellato/privato fa il tentativo dal proxy), D («possibile buco» atteso al primo giro) in `02-pipeline.md`; N3 e «nome non trovato» anche nella pagina `Documentazione` (`it.json`).

Output vero: `manage.py test core` (Postgres a lato) -> `Ran 277 tests in 33.400s OK` (erano 267: 10 nuovi); `npx tsc --noEmit -p tsconfig.json` -> exit 0.

Differenza dal disegno / dalla richiesta: per **B** ho scelto di far fallire lo stadio (non la nota), perché è la via che non può mentire in nessun punto della pagina; costa che una macchina senza proxy mostri rosso invece di grigio, ed è giusto: la raccolta non gira.

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

- **Tetto per giro**: `embed_max_new_per_run` in `scraper_config`, i più recenti prima. Al primo giro era 10; dopo la revisione è **5** (decisione 8, che sostituisce la 7): il buco rientra piano, senza passo manuale al rilascio.
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
3. Da togliere dal `.env` quando Giuseppe dice sì (non ora): `APIFY_TOKEN`.
4. Un giro a mano (`Aggiorna ora`) e guardare `/stato`: «Raccolta: lettura diretta dal
   server» + esito. Atteso: 22 account letti, `elena,palliotto` fallito come «non trovato»
   (il nome va corretto o l'account disattivato: serve una decisione di Giuseppe). Guardare anche i reel vecchi
   in collaborazione che tornano al proprietario vero (N5).

## 4. Revisione          (revisore)

*(Testo del revisore, primo giro, incollato dal capo: il revisore non scrive file. Versione ridotta; nessun rilievo tolto.)*

**Verdetto: NON PASSA, per un solo punto bloccante (B1).** Un solo commit sul
ramo (b25776b), niente su `main`, nessun segreto nel diff, niente della PR 2.
Il revisore non ha potuto lanciare i 267 test (li ha eseguiti il collaudo).

**Bloccante**

- **B1. Il default di `embed_max_new_per_run` (10) contraddice la decisione 7.**
  `scraper_agent.py`, `run()`: `cap = [int(_cfg("embed_max_new_per_run", 10))]`;
  la stessa cifra in `02-pipeline.md` e `it.json`. Con 10 a giro i circa 61
  reel del buco rientrano in 3-4 giorni, prima della PR 2; quello che Groq non
  prende cade sul 3b locale e fallisce per timeout. Oggi la protezione è solo
  un passo manuale del rilascio scritto come «decidere».

**Non bloccanti**

- **N1.** `downloader_agent.py` righe 282-286: il `like_count` di yt-dlp
  sovrascrive il `None` messo apposta per i «mi piace» nascosti. Se yt-dlp
  desse 0 o -1, finirebbe nel database (con -1 `raw_engagement` sottrae 5).
  Scartare negativi e verificare il valore reale su Medyca.
- **N2.** I NULL di `view_count` vanno per primi in `ORDER BY -view_count`:
  `core/views.py:1501` (i 5 «top» per tema, stampati «0 view»), `:686`
  (miniature dei temi), `:485` (ordinamento scelto dall'utente). Rimedio:
  `F("view_count").desc(nulls_last=True)`. Non scritto nei limiti.
- **N3.** Medyca nasconde i «mi piace» e l'embed non dà visualizzazioni: i suoi
  reel nuovi hanno peso esattamente 0. Va scritto tra i limiti noti.
- **N4.** `embed_delay_s` ed `embed_max_new_per_run` mancano dalla
  documentazione di configurazione.
- **N5.** `_upsert_reel` riga 118: un reel vecchio di collaborazione lasciato
  da Apify sotto l'account sbagliato torna al proprietario vero al primo giro
  (può passare da `owned` a `competitor` o viceversa). Direzione giusta, ma è
  una variazione visibile: da guardare al primo giro.
- **N6.** `_ytdlp_fetch` tratta come blocco ogni errore con "login", "rate",
  "429": un reel cancellato o privato fa partire il tentativo dal proxy (pochi
  KB). Ramo provato solo con mock.

**Gli 8 punti chiesti dal capo**: owned/competitor tiene (nome richiesto contro
`contextJSON` e `owner.username`, in minuscolo; `owner` mancante = scartato;
test di giro completo); segreti tengono (`scrub` su ogni eccezione di rete e
sul messaggio di yt-dlp; niente in doc né in `~/brain`); i fallimenti restano
`failed`; download senza regressioni per reel vecchi e link del cliente;
pagina Stato regge `budget`/`collection_paused_until` a `null`; documentazione
nello stesso commit, mancano solo N2, N3, N4.
### Secondo giro (revisione su 66a209e)

*(Testo del revisore, incollato dal capo in versione ridotta.)*

**Verdetto: PASSA.** Nessun bloccante. Due commit sul ramo (66a209e, b25776b),
niente su `main`, nessun segreto, niente della PR 2. Il revisore non ha
rilanciato i 277 test (li ha eseguiti il collaudo).

- **B1 chiuso**: il 5 è nel codice, in `02-pipeline.md`, `it.json`, drawio;
  nessun «10» residuo, nessun passo manuale.
- **N1** `_better_count` (`downloader_agent.py:228`): i like nascosti restano
  `None`, mai valori negativi o più bassi.
- **N2** `NullsLastOrdering`: solo per visualizzazioni, like e commenti; gli
  altri ordinamenti e la paginazione invariati.
- **A** `AccountNotFound`: resta `failed`, conta tra i non letti; i blocchi
  veri restano `blocked` e contano per lo stop dopo 3.
- **B** senza proxy lo stadio fallisce, non è fatale, gli stadi dopo girano.
- **C** frasi semplici per tipo; dettaglio nel log e in `last_error`, senza
  proxy nei messaggi.

**Non bloccanti, lasciati aperti (limiti noti):**

- **N7.** Un reel vecchio ancora `pending`, con like nascosti salvati a 0 o -1
  da Apify, può ricevere il «3» finto di yt-dlp. Pochi reel.
- **N8.** In `run()`, quando una pagina arriva senza dati mentre altri account
  si leggono, `last_error` diventa `not_found` e perde il motivo originale
  (resta nel log). Se Instagram cambiasse la pagina solo per alcuni account,
  sarebbero etichettati «nome non trovato».
- **N9.** La frase per il cliente quando nessun account è letto si sceglie dal
  primo errore, non dal più frequente.

## 5. Collaudo           (collaudatore)

**Verdetto: PASSA**, con 4 difetti non bloccanti (A-D, in fondo) e un elenco di cose non provate. Collaudo del 14/11/2026 sul ramo `feat/pipeline-in-casa` (b25776b). Tutto su una copia a lato: Postgres 16 temporaneo (porta 55441), `runserver` su 8041 e 8043, frontend del ramo servito su 8042 e 8044 (file statici + proxy). Dati e file scritti in una cartella di prova, non in `BEC/data` né `BEC/media`. Il sito vero (9093), il suo database, `BEC/.env`, `FEC/dist`, crontab e servizi non sono stati toccati: a fine collaudo porte 8041-8044 e 55441 libere, 9093 risponde 200, `git status` pulito, `logs/pipeline.log` ancora a 26472 righe.

### 1. Suite, migrazioni, tipi, build

```
$ python manage.py makemigrations --check --dry-run   ->  No changes detected
$ python manage.py check                              ->  System check identified no issues (0 silenced).
$ python manage.py test core --noinput                ->  Ran 267 tests in 40.047s   OK
$ npx tsc -b                                          ->  tsc=0
$ npx vite build --outDir <scratchpad>/dist           ->  ✓ built in 35.62s   (git status pulito: FEC/dist non toccata)
```

### 2. Un giro vero dello stadio `scrape` (3 account: Medyca + 2 competitor, db a lato)

Con `run_pipeline --only scrape`, Instagram vero attraverso il proxy:

```
@medyca.menopausa (embed): 4 video, 4 new, possibile buco
@manupausa (embed): 3 video, 3 new, possibile buco
@menopausa.serena (embed): 5 video, 3 new, 2 rinviati, possibile buco
✓ scrape done in 18.5s — {'accounts': 3, 'new_reels': 10, 'failed_accounts': 0, ... 'deferred': 2}
APIFY CALLS: 0        (apify_provider.fetch_reels sostituito da un contatore)
URLS: instagram.com/<utente>/embed/  x3   (tutte le richieste curl_cffi del giro: nessun altro host)
```
- Tetto per giro **rispettato**: 10 reel nuovi (4+3+3), 2 rinviati. Medyca letta per prima. Un secondo giro ha poi preso i 2 rinviati (`'menopausa.serena': 2`, `deferred: 0`): il tetto non perde niente.
- Reel con l'account giusto, `owner_type` giusto (owned per Medyca, competitor per gli altri). Medyca: `like_count None` (nascosti), `comment_count` 4/0/2/1. Le date vanno dal 28/10 al 12/11: coerenti.
- `scrape_state` scritto: `{'deferred': 0, 'provider': 'embed', 'last_error': '', 'gap_possible': True, 'consecutive_failures': 0}`.
- `stage_runs`: `status done`, `note 'possibile buco (6 post tutti nuovi) su 3 account; 2 reel rimandati al giro dopo (tetto per giro)'`, `total 3 done 3 failed 0`, unità `account`.
- `grep -ci apify BEC/logs/pipeline.log` = 3316: sono tutte righe storiche; il log di produzione non è cresciuto (26472 righe prima e dopo).

### 3. Download vero (`run_pipeline --only download --limit 2`, due reel di Medyca)

```
✓ download done in 21.2s — {'downloaded': 2, 'failed': 0, 'skipped': 0, 'stopped_early': False, 'deferred': 0}
Dfor_3UxXDk  done  duration_s 84.127  (ffprobe dell'mp3: 84.204 s)   like_count 3  comment_count 4  view_count None
Dfh27oyx418  done  duration_s 70.985  (ffprobe dell'mp3: 71.064 s)   like_count 3  comment_count 0  view_count None
```
mp3 da 346 KB e 298 KB, miniature jpg scritte. Durata letta dal file e coerente con l'audio. Nota: yt-dlp ha dato `like_count 3` a Medyca, che nell'embed è nascosto (`None`): il valore viene riempito dal download, come da sviluppo. `view_count` resta `None`, come dichiarato. Il download dalle richieste curl_cffi visibili è andato a `instagram.com` (`get_ruling_for_content`, `api/graphql`: la vecchia strada di dettaglio che esisteva già) e ai CDN, nessun Apify.

### 4. Casi di fallimento (2 account: `elena,palliotto` e `zzq_nonesiste_collaudo_91`)

| Caso | Esito |
|---|---|
| Nome sbagliato / inesistente | per entrambi: 2 tentativi, `last_error 'schema_changed: pagina embed senza contextJSON'`, `consecutive_failures 1`. Stadio `failed`: «Instagram non risponde: nessun account letto (2 falliti). Primo errore: ...», `note '2 account non letti'`, `done 0 failed 2` |
| Nessun proxy (`YTDLP_PROXY=""`) | `✓ scrape done ... 'note': 'sospeso: nessuna fonte configurata (serve IG_PROXY oppure IG_GRAPH_TOKEN)'`, 0 richieste a Instagram. Vedi difetto B |
| Proxy con password sbagliata | `curl: (7) CONNECT tunnel failed, response 407`, 2 tentativi per account, stadio `failed`, account `consecutive_failures` sale |
| Proxy irraggiungibile (127.0.0.1:9) | `Failed to connect ... over proxy 127.0.0.1 ... Could not connect to server`, stadio `failed` con messaggio leggibile |

Perdita della password: su tutti i 4 file di output dei giri (e le `last_error`/stage_runs letti dalla Stato) ho cercato la password vera e il nome-host vero del proxy (letti dal `.env` da uno script che stampa solo i conteggi): `real password occurrences: 0 | real proxy host occurrences: 0 | fake: 0`. Limite del test: gli errori curl non riportano l'indirizzo, quindi questa prova dice «nessuna fuga nei messaggi che curl produce», non esercita `scrub` a fondo (lo fanno i test unitari).

### 5. Proprietà dei contenuti (simulata con la pagina vera)

Ho preso la vera pagina embed di Medyca salvata, inserito un post `COLLAB000001` con proprietario `manupausa` sia nella pagina di Medyca sia in quella di manupausa, e lanciato `scraper_agent.run` due volte sul db a lato:

```
@medyca.menopausa: COLLAB000001 è di @manupausa (collaborazione?), scartato
giro 1 -> proprietario: manupausa competitor | nuovi: 1
giro 2 -> proprietario: manupausa competitor | nuovi: 0
reel collab di medyca: 0
```
Resta del proprietario in entrambi i giri. (Simulato: non ho trovato una collaborazione reale.)

### 6. Pagina Stato da utente vero (playwright-core con Chrome, 380 px e 1280 px, nessun errore di console, nessuno scroll orizzontale)

Screenshot nella cartella di prova (`.../scratchpad/col/shots/`): `errore-380`, `errore-1280`, `vuoto-380`, `sospeso-380`, `sospeso-1280`, `ok-380`, `ok-1280`, `caricamento-380`. Guardati: `errore-380`, `errore-1280`, `sospeso-380`, `ok-380`, `caricamento-380`.
- **OK**: «Raccolta: lettura diretta dal server» / «Ultima lettura (14 nov, 20:25): tutto in ordine», grigio, ordinato a 380 px.
- **Vuoto**: «Raccolta: lettura diretta dal server» / «Nessuna lettura ancora registrata.»
- **Errore**: riquadro in rosso con il messaggio: «Ultima lettura (14 nov, 20:21) non riuscita: Instagram non risponde: nessun account letto (2 falliti). Primo errore: ...». A 380 px il testo va a capo ed è leggibile ma lungo (vedi difetto C).
- **Caricamento** (richiesta di Stato ritardata di 6 s): scheletro grigio, nessun errore, nessun salto.
- **Sospeso**: «Raccolta sospesa: manca il proxy» (vedi difetto B).
- `/apify/i` nel testo della pagina: **false** in tutti i casi. Nel sorgente FEC restano solo `addedBudgetPaused` in `it.json`, un commento in `lib/utils.ts` e un tipo in `endpoints.ts` (ramo morto, `collection_paused_until` sempre `null`), come dichiarato dallo sviluppatore. Il campo `budget` della risposta è `null`.

### 7. Il resto della pipeline

`git diff main..HEAD -- pipeline/dag.py pipeline/agents/ llm/` tocca solo `scraper_agent.py` e `downloader_agent.py`: `dag.py` e `llm/` non sono cambiati. `run_pipeline --dry-run` (no-op per tutti i nove stadi) passa. Un giro vero di `transcribe`/`enrich`/`embed`/`cluster` **non l'ho fatto** (vedi sotto).

### Difetti trovati (non bloccanti)

- **A. Messaggio doppio e fuorviante.** Un nome sbagliato o inesistente non dà 404 ma una pagina senza dati: il log dice `doc_id rotated on embed: pagina embed senza contextJSON — trying fallback` (testo del vecchio fornitore) e l'account riceve `schema_changed`, quindi un nome scritto male (`elena,palliotto`) è indistinguibile da «Instagram ha cambiato la pagina». Inoltre `last_error` e il messaggio dello stadio hanno `error: error: ...`. Da migliorare il testo, non il comportamento (resta `failed`).
- **B. Raccolta sospesa = «tutto in ordine».** Senza proxy lo stadio chiude `done` con `stage_runs.note = ''` (la frase «sospeso: ...» sta solo nel valore di ritorno, non in `note`). La pagina Stato mostra allora «Raccolta sospesa: manca il proxy» e sotto, in rosso, «Ultima lettura ...: tutto in ordine»: contraddittorio (screenshot `sospeso-380`). Il disegno chiedeva la frase in chiaro; qui la frase non arriva in `stage_runs`. Va scritta nella `note` (o lo stadio `failed`).
- **C. Messaggio di errore tecnico e lungo** nel riquadro «Raccolta» (errore curl con link a curl.se, taglio a 300 caratteri a metà frase). Per un cliente non ingegnere è rumoroso; un testo breve («non riesco a raggiungere Instagram dal proxy») sarebbe meglio, col dettaglio nel log.
- **D. «Possibile buco» sul primo giro di un account vecchio.** `menopausa.serena` ha post di maggio ed è segnalato `possibile buco` perché tutti e 6 sono nuovi nel db a lato. In produzione i reel sono già noti, quindi lì non succede (nel secondo giro `gap_possible: []`); è un limite del primo giro di un account nuovo, già descritto nel disegno.

### Cosa NON ho potuto provare (e perché)

- **yt-dlp dal proxy di riserva** (ramo «il diretto è bloccato, riprovo dal proxy»): dal nuovo IP il diretto funziona, non c'era un blocco da provocare; resta coperto solo dai test con mock. Così pure la pulizia (`scrub`) di un errore reale di yt-dlp che nomini il proxy.
- **Un giro di `transcribe`, `batch`, `enrich`, `embed`, `cluster`, `knowledge`** sui reel nuovi: chiamerebbero Groq/Anthropic/modelli esterni; il sistema di permessi mi ha anche rifiutato un `run_pipeline --only batch`. Resta da guardare il primo giro notturno vero: soprattutto che i reel con `view_count NULL` si comportino bene in trascrizione, analisi e classifiche (`core/weighting.py` e `ORDER BY view_count DESC`, che in Postgres mette i NULL per primi: dichiarato dallo sviluppatore).
- **Tutti i 23 account**: ne ho letti 3 (+2 di prova per i fallimenti) per non caricare Instagram; il 22 su 23 dello sviluppatore non l'ho rifatto. Prezzo/traffico del proxy: non misurato.
- **Proprietà in collaborazione reale**: solo simulata con la pagina vera.
- **Pagina Stato in produzione (`:9093`)**: non guardata (il rilascio non è avvenuto; ho usato il frontend del ramo). Mi manca anche il giudizio visivo definitivo di Giuseppe: indirizzo da aprire dopo il rilascio `http://<sito>:9093/stato`, gesto: guardare il riquadro «Raccolta» in fondo a «Coda di lavorazione», prima e dopo «Aggiorna ora».
- Ollama non usato.
### Secondo giro (collaudo su 66a209e, 14/11/2026)

**Verdetto: PASSA**, con 2 note non bloccanti (E, F). Stessa copia a lato di prima (Postgres 16 su 55441, backend 8041/8043, frontend 8042/8044), rifatta da zero. Produzione, `.env`, `FEC/dist`, crontab, servizi e Ollama non toccati; a fine prova porte libere, 9093 risponde 200, `git status` pulito, `logs/pipeline.log` ancora a 26472 righe. La password vera del proxy e il suo host: 0 occorrenze in tutti gli output (`real password occurrences: 0 | real proxy host occurrences: 0`).

**1. Suite, migrazioni, tipi, build**
```
makemigrations --check --dry-run -> No changes detected
test core --noinput              -> Ran 277 tests in 38.979s   OK
tsc -b                           -> tsc=0
vite build --outDir (a lato)     -> built in 30.01s   (FEC/dist non toccata)
```

**2. Tetto a 5** (medyca.menopausa, manupausa, menopausa.serena, db vuoto, due giri veri)
```
giro 1: medyca 4 video 4 new | manupausa 3 video 1 new, 2 rinviati | serena 5 video 0 new, 5 rinviati
        scrape done — new_reels 5, deferred 7, APIFY CALLS: 0
giro 2: medyca 0 new | manupausa 2 new | serena 3 new, 2 rinviati
        scrape done — new_reels 5, deferred 2, APIFY CALLS: 0
```
Al massimo 5 per giro, Medyca per prima, i rimandati entrano al giro dopo. Richieste solo a `instagram.com/<utente>/embed/`.

**3. Difetto A** (account `elena,palliotto` e `zzq_nonesiste_collaudo_91`)
- `elena,palliotto`: `not_found: «elena,palliotto» non è un nome Instagram valido`, riconosciuto senza richiesta (nessuna URL a Instagram per quel nome), `consecutive_failures` sale, niente `error: error:`, niente «doc_id rotated».
- Il nome inesistente ma ben formato, **insieme a Medyca letta**: `not_found: pagina senza dati mentre gli altri account si leggono`; stadio `done`, `failed_accounts: 1`.
- Solo `elena,palliotto`: stadio `failed`, «Non ho trovato nessuno degli account: controlla i nomi nella lista.»
- Nota E (non bloccante): il nome inesistente ben formato **da solo** (nessun altro account letto nel giro) resta `schema_changed: pagina embed senza contextJSON`, perché la distinzione si fa solo se altri account si leggono. È dichiarato nel disegno del fix; in produzione ci sono sempre altri account.

**4. Difetto B** (senza proxy)
```
scrape FAILED: ClientError('La raccolta è sospesa: manca la connessione (proxy) per leggere Instagram. Serve chi gestisce il server.')
stage_runs: failed | stessa frase
$ run_pipeline --only scrape,download --limit 1   (senza proxy)
✗ scrape FAILED ...   ▶ agent: download   ✓ download done (downloaded 1, failed 0)   ✗ failed steps: scrape
```
Lo stadio fallisce con la frase semplice e gli stadi dopo partono lo stesso. Pagina Stato (`senzaproxy-380`, guardato): «Raccolta sospesa: manca il proxy» e sotto in rosso «Ultima lettura ... non riuscita: La raccolta è sospesa...»: non dice più «tutto in ordine».

**5. Difetto C** (riquadro «Raccolta», 380 e 1280 px, screenshot guardati: `nome-380`, `proxyirraggiungibile-1280`, `senzaproxy-380`; letti dal testo gli altri; nessun errore di console, nessuno scroll orizzontale, nessun «apify»)
- Nome sbagliato: «Non ho trovato nessuno degli account: controlla i nomi nella lista.»
- Proxy con password sbagliata (407) e proxy irraggiungibile: entrambi «Non riesco a raggiungere Instagram dal server. Controlla che la connessione (proxy) funzioni e riprova.»
- Niente più testo curl. Il dettaglio resta in `last_error` e nel log (che contiene ancora `curl: (7) ...`, ma non l'indirizzo del proxy).
- Nota F (non bloccante): il tipo dell'errore dello stadio si prende dal **primo** account fallito. Con un nome sbagliato e un proxy rotto insieme, se il nome sbagliato viene per primo il cliente leggerebbe «controlla i nomi» invece di «proxy». Provato: con 2 account (nome sbagliato e Medyca) e proxy rotto la frase giusta è uscita solo perché Medyca (owned) viene letta per prima. In produzione Medyca è prima, quindi di solito va bene.

**6. N1** (download vero di 2 reel di Medyca)
```
Dfor_3UxXDk done like None comm 4 views None dur 84.127007
Dfh27oyx418 done like None comm 0 views None dur 70.985011
```
`like_count` resta `None` (prima era 3); i commenti sono scritti, la durata è letta.

**7. N2** (lista reel, API e UI; ho messo a mano 500 e 90000 visualizzazioni su 2 reel nel db a lato)
```
ordering=-view_count : [(.., 90000), (.., 500), None, None, None, ...]    <- i NULL in fondo
ordering=view_count  : [500, 90000, None, ...]                            <- NULL in fondo anche in crescente
ordering=-like_count : [151, 85(None views), 78, 1, 1, 0, None...]        <- NULL in fondo
```
UI (`/competitor/library`, menù «Ordina» → «Più visti», richiesta `ordering=-view_count`, 1280 e 380 px, screenshot `lib-380` guardato): per primi ▶ 90k e ▶ 500, poi i reel senza numero (▶ —). I «top» del tema e le miniature dei temi: non c'erano cluster nel db a lato; li copre solo il test (nella suite verde), non li ho visti nella UI.

**Non provato in questo giro**
- «Top» del tema e mappa Second Brain nella UI (nessun cluster a lato): solo test.
- Il tipo di errore con un nome sbagliato che viene per primo e proxy rotto (nota F): non corretto, solo osservato a livello di logica.
- Resta tutto ciò che il primo giro non aveva potuto provare (yt-dlp dal proxy di riserva, stadi dopo `download` con modelli esterni, 23 account, collaborazione reale, pagina in produzione).
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
- 2026-11-14 - **Primo giro: la revisione boccia (B1), il collaudo passa con 4
  difetti non bloccanti (A-D).** Il capo rimanda allo sviluppatore. Scelte:
  8. **Sostituisce la decisione 7.** Il tetto `embed_max_new_per_run` ha
     default **5** nel codice, non 10. È il ritmo che la catena di oggi regge
     già (3-5 reel a giro, 162 su 171 analizzati da Groq dal 14/10): il buco
     rientra piano, circa 61 reel in una o due settimane, senza far cadere
     lavoro sul modello locale prima della PR 2. Nessun passo manuale al
     rilascio. Giuseppe è stato informato della scelta (proposta del capo: 5);
     se dice un altro numero, si cambia l'impostazione in `scraper_config`.
  9. Si correggono in questo giro anche N1, N2, N3, N4 e i difetti A, B, C del
     collaudo. N5, N6 e D si scrivono tra i limiti noti / cose da guardare al
     primo giro, senza codice.
- 2026-11-14 - **Secondo giro: revisione passa, collaudo passa** (277 test).
  Il capo apre la PR. N7, N8, N9 e le note E, F del collaudo restano aperti
  come limiti noti, non corretti in questa PR. Decisione ancora di Giuseppe:
  `elena,palliotto` (correggere il nome o disattivare l'account).
