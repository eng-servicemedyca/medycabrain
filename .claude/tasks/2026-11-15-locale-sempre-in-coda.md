---
id: 2026-11-15-locale-sempre-in-coda
titolo: Se Groq finisce si va sul modello locale, sempre in coda
stato: pronto
ramo: feat/locale-sempre-in-coda
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Parole di Giuseppe (15/11/2026, dopo aver fuso la PR #23):

> se groq termina allora vai sul locale, sempre fai queue in locale

Lettura del capo (interpretazione mia): quando Groq non può più rispondere, il
lavoro passa al modello locale e si mette in fila, uno alla volta. Non deve
restare fermo «per il giro dopo» perché un tetto è stato raggiunto.

## 2. Disegno            (capo: lavoro piccolo, niente architetto)

Cosa fa già il codice fuso con la PR #23 (`BEC/llm/client.py`):

- Groq rifiuta «al minuto»: aspetta fino a 6 volte, poi va sul locale.
- Groq ha finito il tetto del giorno: prova i modelli fratelli sullo stesso
  Groq, poi va sul locale.
- Il locale è già una coda: un lucchetto (`_ollama_slot`) fa passare una
  generazione alla volta su tutta la macchina, e chi ha una persona che aspetta
  passa davanti.

Due punti in cui oggi il locale **smette** di mettere in coda:

1. `PIPELINE_LOCAL_MAX_CALLS=40`: dopo 40 chiamate locali il giro si ferma e
   lascia il resto in attesa per il giro dopo.
2. `OLLAMA_LOCK_WAIT=900`: chi aspetta il proprio turno rinuncia dopo 15
   minuti. Una sola risposta locale può durare fino a 1500 s
   (`OLLAMA_PIPELINE_TIMEOUT`), quindi si può rinunciare mentre la fila è sana.

Modifica:

1. `PIPELINE_LOCAL_MAX_CALLS`: predefinito **0** (nessun tetto). Il meccanismo
   resta, spento: è un freno che si può riaccendere dal `.env`.
2. `OLLAMA_LOCK_WAIT`: predefinito **1800** s, più lungo della risposta locale
   più lunga ammessa.
3. Niente altro cambia: la ricerca MCP resta `remote_only` (non aspetta mai il
   locale), un testo tagliato da Groq resta un errore visibile.

Conseguenza da scrivere nei documenti (limite noto): con Groq fuori uso un giro
grosso sul 7b può durare ore (141 chiamate × ~4 minuti ≈ 9 ore). Il giro delle
14:15 trova il lucchetto del giro ancora in corso e salta (codice di uscita 3):
non si accavallano.

File da toccare: `BEC/config/settings/base.py`, `BEC/.env.example`,
`BEC/llm/client.py` (commenti in testa e in `_take_local_call`),
`BEC/pipeline/agents/enrich_agent.py` e `BEC/pipeline/dag.py` (solo commenti, se
parlano del tetto come regola), `BEC/core/tests/test_llm_chain.py`,
`documentation/low-level/02-pipeline.md` e `03-llm-and-embeddings.md`,
`FEC/src/i18n/it.json` se la pagina Documentazione nomina il tetto,
`docs/medycabrain-pipeline-cliente.drawio` se lo nomina.

## Registro

- 15/11 capo: lavoro piccolo e chiaro, niente architetto. Giuseppe ha dato
  l'ordine direttamente; il disegno è due valori predefiniti e i documenti.
- 15/11 capo: i collaudi NON usano la chiave Groq di produzione (ieri ha
  esaurito il tetto del giorno). Solo test con risposte finte.

## 3. Sviluppo           (sviluppatore)

### Cosa ho cambiato
- `BEC/config/settings/base.py` e `BEC/.env.example`: `PIPELINE_LOCAL_MAX_CALLS` predefinito 0 (spento);
  `OLLAMA_LOCK_WAIT` predefinito 1800 (più di `OLLAMA_PIPELINE_TIMEOUT`, 1500). Nell'esempio ho
  aggiunto anche `OLLAMA_LOCK_WAIT=1800`, che prima non c'era.
- Commenti: `BEC/llm/client.py` (testa, `LLMLocalBudget`, `_take_local_call`),
  `enrich_agent.py` (testa), `dag.py`. Il meccanismo non è toccato.
- Il testo «usate le N chiamate» (`note_stopped`) compare solo se il tetto è acceso (con 0
  `_take_local_call` non conta e non solleva mai), quindi nessun «usate le 0 chiamate».
- Documenti: `03-llm-and-embeddings.md` (tabella + paragrafo, con il limite noto 141 x ~4 min ≈ 9 h e
  giro delle 14:15 che salta, uscita 3), `02-pipeline.md` (due punti), `FEC/src/i18n/it.json`
  (pagina Documentazione, parole semplici), `.claude/architecture-summary.md`.
- Drawio: non toccato. Nomina solo il tetto AL MINUTO di Groq, non il tetto delle chiamate locali.
- Test (`test_llm_chain.py`): nuova classe `NoCapByDefaultTests` (2 test): i predefiniti letti da
  `base.py` con l'ambiente ripulito (0, 1800, 1800 > 1500), e 50 chiamate locali di fila in un giro
  `pipeline:enrich` senza `LLMLocalBudget` e senza contare. I test con `PIPELINE_LOCAL_MAX_CALLS=2`
  restano. Nessun test dipendeva dal 40 predefinito.

### Prove (output vero)
```
$ manage.py test core --noinput   (Postgres 16 usa-e-getta a lato, porta 55452; chiavi Groq svuotate, OLLAMA_URL su porta morta)
Ran 338 tests in 51.436s
OK
```
Solo risposte finte, nessuna chiamata a Groq.

### Non provato / rimasto fuori
- Nessuna prova con un giro vero sul 7b (ore). Il limite noto è scritto, non misurato di nuovo.
- Il frontend non è stato ricompilato: ho cambiato solo una stringa di `it.json` (JSON valido).
- Se `.env` di produzione ha già `PIPELINE_LOCAL_MAX_CALLS=40` o `OLLAMA_LOCK_WAIT=900`, vince il `.env`:
  va cambiato a mano al rilascio.

## 4. Revisione          (revisore)

**Verdetto: PASSA.** Nessun blocco. Quattro rilievi, nessuno impedisce il merge.

Controllato:
- Predefiniti: `PIPELINE_LOCAL_MAX_CALLS` 0 e `OLLAMA_LOCK_WAIT` 1800 in `base.py` e `.env.example`; 1800 > 1500 (`OLLAMA_PIPELINE_TIMEOUT`). Il test li legge da `base.py` a ambiente pulito.
- Nessun punto assume un tetto > 0: `_take_local_call` esce subito con `cap <= 0`; `note_stopped` (`enrich_agent.py:136`) usa `n` solo se arriva un `LLMLocalBudget` o un `LLMLocalUnavailable` (il secondo ha un testo suo), quindi niente «usate le 0 chiamate». Nessuna divisione per il tetto.
- Ricerca MCP: `core/knowledge.py:412`, `core/editorial.py:131`, `eval_mcp.py:350` restano `remote_only=True`. Non toccati dal diff.
- Documenti (`02-pipeline.md`, `03-llm-and-embeddings.md`, `it.json`, `architecture-summary.md`) dicono il vero e riportano il limite noto (giro di ore, ~9 h per 141 chiamate, 14:15 salta con uscita 3). Il drawio nomina solo il tetto al minuto di Groq: non serve toccarlo.
- Invarianti: `owner_type` non toccato, nessun stato `failed` azzerato, nessun segreto nel diff, un solo commit sul ramo, nessun commit su `main`.

Rilievi (dal più pesante):
1. **Il lavoro può ancora NON andare in coda sul locale, per tre vie rimaste** (`BEC/llm/client.py`, `chat`):
   - `LLMBusy` dopo 1800 s (`_ollama_slot`, righe 282 e 291): se un lavoro del cliente (priorità) tiene il locale a lungo, il giro rinuncia. Lo stadio si ferma e lascia `pending` (`NOT_THE_ITEMS_FAULT`, riga 127). Non è un errore, ma è «non in coda».
   - `LLMLocalUnavailable` se Ollama è spento (riga 204): stesso effetto, stadio fermo e `pending`. Voluto, ma non è una coda.
   - `requests.exceptions.Timeout` (righe 719-724): silenzio oltre `OLLAMA_READ_TIMEOUT` (600 s) o risposta oltre il tetto. Non è in `NOT_THE_ITEMS_FAULT`, quindi quel reel diventa `failed` e non torna in attesa. È il comportamento già fuso con la PR #23, non nuovo, ma con il tetto spento i giri lunghi lo rendono più probabile.
   Nessuna delle tre è un cambio di questo diff.
2. Il 14:15 che salta (limite noto, scritto): se il giro lungo si ferma per `LLMBusy` o Ollama spento, i reel restano `pending` fino al prossimo giro utile; con giri di ore il «prossimo» può essere anche il giorno dopo. Il documento non lo dice esplicitamente.
3. Al rilascio `.env` di produzione vince sul predefinito: se contiene `PIPELINE_LOCAL_MAX_CALLS=40` o `OLLAMA_LOCK_WAIT=900`, la modifica non ha effetto (già annotato dallo sviluppatore). Non l'ho verificato: non ho toccato la produzione.
4. Il test dei predefiniti carica `base.py` come modulo a parte con `clear=True` sull'ambiente: regge oggi (338 test verdi, dichiarati dallo sviluppatore), ma si rompe se `base.py` un giorno richiede una variabile obbligatoria.

`stato:` resta `revisione`; passa a `pronto` se anche il collaudo passa.

## 5. Collaudo           (collaudatore)

**Verdetto: PASSA.** Nessuna chiamata a Groq: chiavi svuotate e indirizzo di Groq puntato su una porta morta (`127.0.0.1:1`). Database usa-e-getta (Postgres 16, porta 55461, già fermato e cancellato); lucchetti miei in una cartella a parte, non quelli di produzione.

1. **Suite intera** (`manage.py test core --noinput`, ambiente ripulito):
   `Ran 338 tests in 61.033s` / `OK`.
2. **Predefiniti letti da Django** con `PIPELINE_LOCAL_MAX_CALLS` e `OLLAMA_LOCK_WAIT` tolti dall'ambiente: stampa `0 1800`.
3. **Comportamento chiesto da Giuseppe, dal vivo** (modello vero `qwen2.5:7b-instruct-q4_K_M`, stadio `pipeline:enrich`, 3 testi brevi, `max_tokens=12`): Groq irraggiungibile (3 tentativi falliti per chiamata), poi tutti e 3 sul locale: ok in ~109 s (la prima, carica il modello; il server era sotto carico), 2,1 s e 4,3 s. `local_calls_used: 0`, nessun `LLMLocalBudget`, nessun «restano in attesa». Righe `LLMCall`: 3 `ollama ... done`.
4. **Coda, due processi insieme** (2 chiamate ciascuno): tutte e 4 finite `done`, una dopo l'altra, con attese nel lucchetto di 0, 2,0, 2,1 e 4,0 s. Nessun `LLMBusy`.
5. **FEC**: `npm ci` e `npm run build` dentro il worktree: `tsc -b && vite build` fine, `✓ built in 27.30s`. La frase nuova di Documentazione è in italiano semplice e corretta; è un po' lunga (cinque frasi in una voce), ma si capisce. Nota: non l'ho vista sulla pagina in browser.

**Non provato**: un giro grosso vero (ore); la pagina Documentazione a schermo (nessun browser, e `:9093` è produzione, che non gira da questo ramo); Ollama non era occupato da altro, ma il carico della macchina era alto (la prima chiamata locale ha impiegato 109 s). Il `.env` di produzione con `=40`/`=900` (già annotato dallo sviluppatore) va cambiato al rilascio.

`stato:` può passare a `pronto`.
