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

## Registro

- 16/11 15:10 — capo: aperto il lavoro. Lanciati insieme il banco di prova (passo 1, sola
  misura) e l'architetto (passi 2-4). Il disegno aspetta l'OK di Giuseppe.
