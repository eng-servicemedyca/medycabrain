---
id: 2026-11-15-locale-sempre-in-coda
titolo: Se Groq finisce si va sul modello locale, sempre in coda
stato: revisione
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
