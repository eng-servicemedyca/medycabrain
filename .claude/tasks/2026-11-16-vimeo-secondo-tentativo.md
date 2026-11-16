---
id: 2026-11-16-vimeo-secondo-tentativo
titolo: Vimeo, secondo tentativo automatico e pulsante Riprova sul telefono
stato: revisione
ramo: feat/vimeo-secondo-tentativo
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Giuseppe, 15/11/2026, sulla schermata Gestione fonti → Interviste con tre errori Vimeo:

> Qui non capisco il problema, ha sempre funzionato.

16/11/2026, dopo la proposta del capo (secondo tentativo automatico + pulsante «Riprova»
tagliato sul telefono):

> fai questinlittle tweak

## 2. Disegno            (capo: lavoro piccolo, niente architetto)

Cosa si sa (15/11, interviste 21, 22, 23 della puntata «Menopausa»):

- Vimeo, passando dal proxy residenziale con `player.vimeo.com/video/<id>` e
  `--referer https://vimeo.com/`, funziona ma **rifiuta a caso** con «only works when
  logged-in» oppure «No video formats found!». Un secondo tentativo con un **indirizzo
  nuovo** (nuova `{session}` del proxy) passa. L'intervista 21 è passata al terzo tentativo
  a mano.
- Nota in `~/brain`: `errors/vimeo-ytdlp.md#vimeo-proxy-transient-refusal`.

Modifica 1, `BEC/core/link_ingest.py` `fetch_audio`:
- Solo sul percorso col proxy (`proxy` non vuoto): se yt-dlp fallisce con un testo che
  indica un rifiuto passeggero (gli `auth_needles` del fornitore, più «No video formats
  found» per Vimeo), si riprova **in automatico con un proxy nuovo** (`_proxy()` di nuovo:
  nuova sessione, nuovo IP). Al massimo **2 tentativi in più** (3 in tutto), poi l'errore
  di oggi, invariato.
- Ogni tentativo pulisce la cartella temporanea (niente pezzi del tentativo prima).
- Il log scrive ogni tentativo fallito (testo ripulito con `_scrub`, mai l'indirizzo del proxy).
- Tutto il resto non cambia: senza proxy un solo tentativo, timeout di 30 minuti per
  tentativo, i messaggi al cliente restano gli stessi. YouTube ha già i suoi `auth_needles`:
  il secondo tentativo vale anche lì.
- Commento sul perché (rifiuto a caso di Vimeo, misurato il 15/11) e riga nel file
  `documentation/` che parla dei link (cercalo: probabilmente `02-pipeline.md` o il file
  degli upload) come limite noto: «Vimeo rifiuta a caso; si fanno fino a 3 tentativi con
  indirizzi diversi».
- Test con `subprocess.run` finto: (a) primo rifiuto Vimeo, secondo ok → file prodotto e
  due proxy diversi usati; (b) tre rifiuti → `LinkRefused(_PROXY_BLOCKED)`; (c) un errore
  non passeggero (es. video privato / non trovato) → nessun secondo tentativo; (d) senza
  proxy → un solo tentativo.

Modifica 2, frontend, Gestione fonti → Interviste (probabilmente
`FEC/src/components/uploads/UploadPanel.tsx`, pulsante `retry` intorno alla riga 496):
- Sul telefono (larghezza 375-390 px) il pulsante «Riprova» della riga in errore esce
  dallo schermo. Deve stare tutto dentro, leggibile e toccabile (almeno 44 px di altezza),
  per esempio andando sotto il testo dell'errore sulle larghezze piccole.
- Seguire `.claude/skills/ui-design/`. Desktop invariato.

## Registro

- 16/11 capo: lavoro piccolo, niente architetto. Giuseppe ha detto di procedere.
- 16/11 capo: nessun download vero di prova dal proxy residenziale oltre a uno o due
  (si paga a GB); per la UI usare la pagina live solo in lettura.

## 3. Sviluppo           (sviluppatore)

### Cosa ho cambiato
- `BEC/core/link_ingest.py`: `fetch_audio` ora fa un ciclo di tentativi; un tentativo è la nuova
  funzione `_download` (corpo di prima, spostato). Solo col proxy: se yt-dlp fallisce con un
  `auth_needles` o con il nuovo campo `transient_needles` (Vimeo: «No video formats found»),
  `_download` restituisce False e il ciclo richiama `_proxy()` (nuova sessione, nuovo IP).
  `_PROXY_RETRIES = 2`, quindi 3 tentativi in tutto; all'ultimo solleva `LinkRefused(_PROXY_BLOCKED)`
  come prima. Ogni tentativo ha la sua cartella temporanea; il log dice «tentativo N» con il testo
  ripulito da `_scrub`. Senza proxy un tentativo. Timeout, messaggi e altri errori invariati.
- `FEC/src/components/uploads/UploadPanel.tsx`: la tabella Interviste ora è `stacked` (sotto 768 px
  ogni riga diventa una scheda: file, stato con l'errore, risultato, poi le azioni a riga intera).
  Causa vera: `minWidth=600` e nessuna conversione, quindi «Riprova» stava nella colonna a destra,
  fuori schermo. Aggiunti `data-label` a Stato e Risultato; lo Stato occupa tutta la riga
  (`max-md:col-span-2`) perché il testo dell'errore non sia stretto in mezza colonna.
- `FEC/src/components/manage/parts.tsx`: `RowAction` `max-md:min-h-11` (44 px sul telefono, 40 su
  desktop come prima; vale per tutte e tre le liste, solo sotto 768 px); commento di `TableFrame`
  aggiornato (diceva «uploads non ha etichette»).
- Documenti: `02-pipeline.md` (paragrafo «Vimeo rifiuta a caso» + limite noto), `06-frontend.md`
  (tabella caricamenti ora a schede). Pagina `Documentazione` dell'app, drawio e
  `architecture-summary.md` non toccati: nessuna funzione nuova per il cliente, nessuno stadio nuovo.
- Test (`test_link_ingest.py`, classe `RetryWithNewProxy`, 7 test): (a) rifiuto poi ok -> file
  prodotto e due proxy diversi; anche «No video formats found» ritentato (3 proxy diversi);
  (b) tre rifiuti -> `_PROXY_BLOCKED` e 3 chiamate; (c) video non disponibile e errore ignoto -> 1
  chiamata; (d) senza proxy -> 1 chiamata; log con «tentativo 1» e senza password.

### Prove (output vero)
```
$ manage.py test core --noinput   (Postgres 16 usa-e-getta, porta 55471, spento e cancellato; Groq vuoto, OLLAMA_URL su porta morta; python del venv di produzione in sola lettura)
Ran 345 tests in 33.522s
OK
$ npm ci && npm run build   (dentro il worktree)   ->  built in 15.51s, 0 errori tsc
```
`node_modules` e `dist` del worktree cancellati. Nessun download vero, nessuna chiamata a Groq.

### Non provato / rimasto fuori
- Il pulsante sul telefono vero non l'ho visto: solo compilazione, nessuno screenshot a 375/390 px.
  Va guardato dal collaudatore (le classi `max-md:*` sono quelle già usate da Fonti/Blog).
- Nessun download vero dal proxy: il secondo tentativo è provato solo con `subprocess.run` finto.
  Non so se tre tentativi bastano sempre (il 15/11 la 21 è passata al terzo a mano).
- I tentativi falliti consumano un po' di traffico del proxy (si fermano prima dell'audio, non misurato).
- «Riprova» sul telefono resta 40 px per le altre tabelle? No: 44 px ovunque sotto 768 px.

## 4. Revisione          (revisore)

**Verdetto: PASSA.** (16/11/2026, diff `origin/main...HEAD`, un solo commit `d27cb53`, ramo giusto, nessun commit su `main`.)

Controllato e a posto:
- Tentativi solo col proxy (`attempts = 1 + _PROXY_RETRIES if proxy else 1`), solo su `auth_needles` o `transient_needles`; ogni tentativo chiama `_proxy()` (nuova `{session}`); massimo 3; all'ultimo `LinkRefused(_PROXY_BLOCKED)`. Un fallimento resta `failed` (il chiamante in `upload_workflow.py` non cambia), nessun ciclo infinito.
- Segreto: `_scrub(proxy)` usa il parametro `proxy` di QUEL tentativo; log ed eccezioni ricevono solo `err` ripulito. Nessun indirizzo in messaggi al cliente. Nessuna chiave nel diff.
- Cartella temporanea nuova a ogni tentativo; `TimeoutExpired` e `ToolMissing` escono subito (non ritentati).
- Frontend: `stacked` e `max-md:*` toccano solo sotto 768 px; desktop invariato (`md:min-w`, `min-h-10`); le chiavi `accounts.status` e `uploads.result` esistono; stati vuoto/caricamento/errore non toccati. 44 px solo sul telefono.
- Documenti: `02-pipeline.md` e `06-frontend.md` aggiornati con il vero comportamento.

Rilievi (non bloccanti):
1. Durata nel caso peggiore: ogni tentativo ha ancora `timeout=1800`, quindi in teoria 3 x 30 min = 90 min. Un timeout però non si ritenta (esce subito), e i rifiuti passeggeri arrivano in secondi: nella pratica il caso peggiore è breve. Il job ha l'heartbeat di `run_job`. Accettabile; il limite teorico non è scritto nel documento.
2. Se `YTDLP_PROXY` non contiene `{session}`, `_fresh` restituisce lo stesso indirizzo e il «tentativo nuovo» riusa lo stesso IP. Il `.env.example` e `02-pipeline.md` (riga 227) già spiegano `{session}`, ma il nuovo paragrafo non dice che senza segnaposto i tentativi in più non servono. Una riga basterebbe.
3. Il test del log mocka `_proxy` con lo stesso indirizzo per tutti i tentativi: non prova che il `_scrub` usi il proxy del tentativo giusto quando cambia. Il codice è corretto (usa il parametro), ma il test è più debole di quanto dica il nome.
4. Telefono non visto da occhio umano (lo dice anche lo sviluppatore): resta al collaudatore. Sulla scheda, «Risultato» occupa mezza riga da solo: ok, non è un difetto.
