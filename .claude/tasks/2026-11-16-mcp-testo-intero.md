---
id: 2026-11-16-mcp-testo-intero
titolo: leggi_articolo non taglia più le trascrizioni lunghe; puntate TVRS doppie
stato: revisione
ramo: feat/mcp-testo-intero
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Feedback del cliente sul Content Intelligence, girato da Giuseppe il 16/11/2026 (testo
integrale):

> leggi_articolo restituisce il campo "testo" tagliato a metà parola sulle trascrizioni
> lunghe, sempre nello stesso punto se lo rileggo. Esempi:
> - blog:2212 (Canale Salute 21/10/2026, Menopausa parte 1) finisce con "Questo è il mod"
> - blog:2214 (parte 2) finisce con "corre ai"
> - blog:896 e blog:890, già a settembre
>
> La trascrizione completa invece è salvata: cerca_riferimenti restituisce passaggi delle
> stesse puntate che vengono dopo il punto di taglio. Quindi sembra un limite di lunghezza
> nella risposta di leggi_articolo, non nello scraping.
>
> Si può togliere il limite, o almeno aggiungere un campo che dica che il testo è troncato
> e permettere di leggere il resto a pezzi?
>
> Due cose minori:
> - il riassunto di blog:2214 la chiama "L'articolo di Medyca", ma è una puntata TVRS;
>   andrebbe magari distinto tra contenuto di Medyca e di partner/collaboratore (quindi
>   diverso da competitor), ma sennò teniamo come Medyca senza problemi
> - blog:2198, 2199 e 2200 ("Canale salute - TVRS", 04/11/2026) non hanno trascrizione e
>   puntano agli stessi video Vimeo delle puntate del 21/10: sembrano duplicati.

## Primi fatti (capo, sola lettura sulla produzione)

- `BEC/mcp_bridge/server.py:323`: `testo = (d.content_text or d.content_md)[:12000]`.
  Stesso taglio per i reel, riga 308 (`trascrizione ... [:12000]`). Il carattere 12.000
  è esattamente il punto di taglio: 2212 è lunga 16.865 caratteri e il carattere
  11.985-12.000 è «Questo è il mod»; 2214 è 14.979 («dico e corre ai»); 896 è 20.336;
  890 è 16.919.
- 2198, 2199, 2200: `source_type=other`, `owner_type=owned`, 324 caratteri, create il
  12/11 alle 11:14, `source_url` = pagina `tvrs.it/programmi/canale-salute?v=<id Vimeo>`.
  Le puntate vere 2212, 2213, 2214 sono `source_type=video`, create il 13/11 dal link
  `vimeo.com/<id>`. Sembra la «scheda di riferimento» che `link_ingest` salva quando un
  link viene rifiutato, rimasta in piedi dopo che lo stesso video è entrato da un altro
  indirizzo. Da verificare.

## 2. Disegno            (architetto)

Tre lavori nello stesso ramo, in ordine di importanza. Tutti i numeri sono
misurati sulla produzione il 16/11/2026, in sola lettura. Dove suppongo, lo scrivo.

### In breve

1. **Testo tagliato.** Non è un caso isolato: il taglio a 12.000 caratteri
   colpisce **239 articoli su 2.302 e 176 reel su 1.498**. Proposta: testo
   intero fino a 30.000 caratteri; oltre, a pezzi tagliati a fine frase, con i
   campi `parte`, `parti_totali`, `troncato` e un parametro `parte` per chiedere
   il seguito.
2. **Puntate doppie.** La causa non è quella ipotizzata (scheda di un link
   rifiutato). I tre link `tvrs.it` sono stati incollati il 12/11 alle 11:13,
   **sei ore prima** che entrasse la correzione che li riconosce come video
   (PR #14, fusa il 12/11 alle 17:25). Allora erano letti come pagine web. La
   correzione per il futuro c'è già; restano da togliere le tre schede vecchie.
   Altri casi uguali nel DB: **zero**.
3. **«L'articolo di Medyca».** Lo scrive il modello perché glielo diciamo noi:
   il prompt dice sempre «articolo del blog di Medyca». Proposta: le parole del
   prompt seguono il tipo di contenuto.

### Vincoli misurati

| Fatto | Numero | Come l'ho accertato |
|---|---|---|
| Lunghezza del testo degli articoli attivi | metà sotto 4.572; 90% sotto 12.115; 99% sotto 24.570; massimo **42.123** (blog:296) | `Length("content_text")` su `KnowledgeDocument(is_active=True)` |
| Articoli tagliati oggi (>12.000) | **239** (226 blog, 13 video su 17) | stessa query |
| Articoli oltre 30.000 / oltre 40.000 | **13** / 1 | stessa query |
| Video e interviste trascritti | 17 video (massimo 25.929) + 1 intervista | stessa query, per `source_type` |
| Trascrizioni dei reel | metà sotto 1.013; 90% sotto 28.201; massimo **85.699** (reel:960) | `Length("text")` su `Transcript` |
| Reel tagliati oggi (>12.000) | **176**, tutti di competitor (video lunghi di `menopauseboost`, fino a 96 minuti) | stessa query |
| Reel oltre 30.000 | 146 | stessa query |
| `content_text` vuoto con `content_md` pieno | 0 (il ripiego su `content_md` oggi non scatta mai) | stessa query |
| Punti che tagliano a 12.000 nel connettore | 2: `server.py:308` (reel) e `:323` (articoli). `leggi` passa da lì | `grep -n "12000" BEC/mcp_bridge/server.py` |
| Quanto regge una risposta per Claude | **Non c'è un numero ufficiale per claude.ai** (cercato, non trovato). Claude Code avvisa sopra 10.000 token e rifiuta sopra 25.000. In italiano 30.000 caratteri sono circa 8-10.000 token (stima: 3-4 caratteri per token) | ricerca web; la stima dei token è una supposizione |
| La ricerca legge tutto il testo | sì: `_best_passage` sceglie tra pezzi da 700 caratteri di tutto il testo. Per questo `cerca_riferimenti` trova passaggi dopo il taglio | `core/knowledge.py:173` e `:433` |

### Punto 1 - Il testo intero, a pezzi quando è lungo

**File da toccare**

- `BEC/mcp_bridge/server.py`
  - Una costante sola, `TESTO_MAX_CARATTERI = 30_000`, con il perché nel commento.
  - Una funzione pura `_parti(testo, limite) -> list[str]`: divide il testo in
    pezzi lunghi al massimo `limite`. Taglia sull'ultima fine di frase
    (`. `, `? `, `! `, a capo) negli ultimi 2.000 caratteri del pezzo; se non
    c'è, sull'ultimo spazio; solo se manca anche quello, taglio netto.
    **Nessuna sovrapposizione**: i pezzi riattaccati danno il testo esatto.
  - `_leggi_articolo(pk, parte=1)` e `_leggi_reel(pk, parte=1)` usano `_parti`
    al posto di `[:12000]`.
  - `leggi_articolo`, `leggi_reel`, `leggi` prendono un parametro in più,
    `parte` (predefinito 1). Va accettato anche scritto come testo (`"2"`):
    Claude lo passa spesso così, come già fa con gli id.
  - Campi nuovi nella risposta, uguali per reel e articoli:
    `caratteri_totali`, `parte`, `parti_totali`, `troncato` (vero quando il
    pezzo non è tutto il testo), `parte_successiva` (numero, o vuoto all'ultima),
    `come_leggere_il_resto` (una frase pronta: «Testo lungo: questa è la parte
    1 di 3. Per il seguito chiama leggi_articolo con parte=2»).
  - Dalla parte 2 in poi la risposta è leggera: `tipo`, `titolo`, `di`,
    `apri_nel_brain`, `url` e il pezzo di testo con i suoi campi. Riassunto e
    affermazioni stanno solo nella parte 1: ripeterli costa token e non serve.
  - `parte` fuori misura: `{"errore": "questo contenuto ha 3 parti: chiedi una
    parte da 1 a 3"}`. Mai una risposta vuota.
  - `instructions` del server e descrizioni dei tre strumenti: oggi dicono
    «testo integrale» e «trascrizione integrale», che non era vero. Vanno
    riscritte: «se `troncato` è vero il testo continua: richiama lo stesso
    strumento con `parte` = `parte_successiva` finché serve; non dire che un
    contenuto finisce lì, e non citare ciò che non hai letto».
  - Un campo di onestà in più (piccolo, **consigliato ma si può togliere**):
    `nota_analisi`, presente solo quando il testo è più lungo di quanto la
    pipeline legge: «Riassunto e affermazioni sono stati fatti sull'inizio del
    testo (primi 6.000 caratteri): per il resto vale il testo.» Vedi sotto.
- `BEC/pipeline/agents/knowledge_agent.py` e `enrich_agent.py`: solo dare un
  nome ai numeri già lì (`6000`, `8000`, `3000`), così `nota_analisi` li legge
  e non può divergere. Nessun cambio di comportamento. Serve solo se si tiene
  `nota_analisi`.

**Cosa riuso**: `_parse_id` (stesso stile per il parametro), la forma degli
errori `{"errore": ...}`, il test cancello. `core.knowledge._chunks` **non** va
bene: fa pezzi fissi da 700 con sovrapposizione, taglia a metà parola.

**Perché 30.000 e non «nessun limite»**: senza limite il reel più lungo
manderebbe 85.699 caratteri (circa 25.000 token) in una risposta sola: è il
punto in cui i client di Claude noti rifiutano o tagliano loro, e sarebbe di
nuovo un taglio silenzioso, fuori dal nostro controllo. Con 30.000: tutte le
17 puntate arrivano in un pezzo solo; a pezzi restano 13 articoli e 146 reel.

**Alternative scartate**
- Soglia a 40.000: a pezzi resterebbe 1 articolo e 111 reel, ma ogni risposta
  lunga peserebbe circa 13.000 token. Poco guadagno, più rischio.
- Solo il campo `troncato` senza i pezzi: il cliente saprebbe del taglio ma non
  potrebbe leggere il resto. È metà della richiesta.
- Paginare per posizione (`da_carattere`): più flessibile, ma il modello sbaglia
  i conti. `parte=2` non si sbaglia.

**Altri punti che leggono solo l'inizio (trovati, NON corretti qui)**

| Dove | Legge | Chi ne risente |
|---|---|---|
| Riassunto, tema e argomenti di un articolo/puntata: `knowledge_agent.py:85` | primi **6.000** caratteri | **854** articoli su 2.302; **17 su 18** tra puntate e interviste. Il riassunto di una puntata da 17.000 caratteri è fatto sul primo terzo |
| Affermazioni con citazione: `knowledge_agent.py:130` e `:142` | primi **8.000** | 551 articoli |
| Analisi dei reel: `enrich_agent.py:230` e `:324` | primi **3.000** della trascrizione | 265 reel |
| Bozza di articolo da un'intervista: `blog_workflow.py:136` | primi **12.000** | le interviste lunghe |
| Confronto articolo/reel: `blog_workflow.py:180` | primi 4.000 | - |
| Vettore del documento: `knowledge_agent.py:189`, `cluster_agent.py:72` | primi 4.000 | attenuato: i vettori dei passaggi coprono tutto il testo |

Correggerli vuol dire far leggere al modello testi fino a 85.000 caratteri.
Groq ha un tetto di 8.000 token al minuto: un testo lungo non entra in una
chiamata sola, va riassunto a pezzi e poi ricucito. È un lavoro a sé, con costi
e tempi suoi. **Proposta: lavagna separata.** Qui si scrive il limite nei
documenti e, se Giuseppe vuole, lo si dice al modello con `nota_analisi`.

### Punto 2 - Le tre puntate doppie

**Causa, verificata**

- 2198, 2199, 2200 sono `source_type="other"`: è il percorso «pagina web»
  (`upload_workflow._run_article`), non la scheda di un link rifiutato (quella
  è `source_type="video"`, `upload_workflow.py:184`). Righe di carico 20, 19, 18,
  `kind="article"`, create il 12/11 alle 11:13.
- La regola che riconosce `tvrs.it/...?v=<id>` come video Vimeo
  (`link_ingest._TVRS_VIDEO`, commit `d784ea4`) è entrata in `main` il 12/11
  alle 17:25 (`git log --merges`: PR #14). Sei ore dopo.
- Il lettore di pagine ha quindi letto la **pagina del programma**: 324
  caratteri uguali per tutte e tre, che nominano l'ultima puntata in elenco
  («04 Novembre 2026 - Fegato e pancreas»). Da lì il riassunto, uguale e
  **sbagliato**: parla di fegato e pancreas, ma i tre link sono le puntate
  sulla menopausa del 21/10. Non sono solo doppioni: dicono una cosa falsa.
- Il 13/11 gli stessi link, incollati di nuovo, sono stati riconosciuti come
  Vimeo e sono nate 2212, 2213, 2214, con la trascrizione vera.
- Coppie (da `extract_links` sugli indirizzi salvati): 2200 ↔ 2212 (parte 1),
  2199 ↔ 2214 (parte 2), 2198 ↔ 2213 (parte 3).

**(a) Perché non si ripeta: c'è già.** Oggi `extract_links` porta
`tvrs.it/...?v=<id>` su `vimeo.com/<id>`, e `from_links` risponde «già
presente» (`views.py:432-452`). Coperto da `test_uploads.py:75` e `:92`.
Aggiungo solo un test che manca: incollare il link `tvrs.it` quando la puntata
Vimeo è già in banca dati deve dare `gia_presenti` e non creare nulla.
Non propongo di disattivare da soli la scheda vecchia quando arriva il video:
sarebbe una cancellazione silenziosa, e il caso nasce solo quando si aggiunge
una regola nuova su righe già salvate, cioè a un rilascio, dove si può guardare.

**(b) Le tre già nel DB: nessun codice nuovo.** Il tasto «Rimuovi» della pagina
Interviste fa già la cosa giusta (`UploadViewSet.perform_destroy`,
`views.py:473`): spegne il documento (`is_active=False`, resta nel DB) e toglie
la riga di carico. Passo di rilascio, **a conferma di Giuseppe**: rimuovere le
righe di carico 18, 19, 20 («Canale salute - TVRS», tipo pagina web). Lo fa
Giuseppe con tre clic, oppure il rilasciatore chiamando lo stesso indirizzo
(`DELETE /api/v1/uploads/<id>/`) dopo il suo sì. Niente script a mano sul DB.
Dopo: `leggi_articolo("blog:2198")` risponde «non trovato», la ricerca non le
propone più (l'indice si rifà da solo: `_corpus_stamp`), le 2212-2214 restano.
Reversibile a metà: il documento si riaccende a mano, la riga di carico no.

**Alternativa**: un comando `manage.py doppioni_link` (prova a secco, poi
`--applica`). Circa 60 righe più i test per un caso che oggi conta 3 righe e
zero altre. Lo sconsiglio; se Giuseppe vuole un controllo ripetibile, si fa.

**Altri doppioni nel DB**
- Stesso video sotto due indirizzi: **solo questi 3** (ho passato tutti i
  `source_url` dei documenti e dei carichi in `extract_links` e confrontato).
- Stesso titolo tra video, pagine e interviste: solo questi 3.
- Stesso testo identico (`content_hash`) tra documenti attivi: **9 gruppi**.
  Uno sono queste 3; gli altri 8 sono pagine di blog di competitor con il
  solito testo di contorno (schede dei medici, pagine modello, avvisi), quasi
  tutte già bocciate come fuori tema. È un altro problema, del lettore dei
  blog. **Fuori da questo lavoro**, lo segnalo.

### Punto 3 - «L'articolo di Medyca» per una puntata

**Causa**: `knowledge_agent.build_doc_enrich_prompt` (riga 78) scrive sempre
«Analizza questo articolo del blog di {fonte}». Senza fonte collegata la fonte
diventa «Medyca», e per `owned` aggiunge «(il blog di Medyca stessa)». Per le
puntate dei competitor il modello se l'è cavata da solo («Trascrizione di una
puntata televisiva…»); per quelle tenute come Medyca ha ripetuto il prompt.
Riassunti di video/interviste che dicono «articolo» o «blog»: **12** (2212,
2213, 2214, l'intervista 2311, e 842, 843, 844, 845, 889, 891, 892, 895).

**File da toccare**

- `BEC/pipeline/agents/knowledge_agent.py`: le parole seguono `source_type`.
  - `blog` e `other`: testo **identico a oggi**, carattere per carattere. I
    2.281 articoli di blog non devono cambiare analisi.
  - `video`: «la trascrizione di questo video (una puntata o un intervento) di
    {fonte}», dove la fonte è il canale (`doc.author`, per esempio «TVRS SRL»)
    e non «Medyca».
  - `manual`: «la trascrizione di questa intervista caricata da Medyca».
  - Per video e interviste una riga in più: «Nel riassunto chiamala puntata,
    video o intervista: mai articolo.» Se `is_inspiration`: «È materiale di
    riferimento scelto da Medyca: chi parla sono gli ospiti, non Medyca.»
  - `KB_SYSTEM`: «articoli di blog» diventa «articoli di blog e trascrizioni di
    video e interviste».
- `BEC/mcp_bridge/server.py`, campo `tipo` di `_leggi_articolo`: oggi è «video
  di riferimento» per ogni video e «articolo» per tutto il resto. Diventa:
  intervista caricata → «intervista»; video → «video di riferimento» se è
  materiale di riferimento, altrimenti «video». Nelle `instructions` una riga:
  `leggi_articolo` legge anche puntate e interviste trascritte; guarda `tipo`
  e chiamale per quello che sono.
- `BEC/core/management/commands/reprocess.py`: un'opzione `--ids 2212,2213`
  per `--stage knowledge`, che rimette in coda **solo** quei documenti. Serve
  a rifare i riassunti già scritti senza toccare il DB a mano. Oggi il comando
  rimette in coda solo i falliti.

**I riassunti già scritti**: non cambiano da soli. Passo di rilascio, a
conferma di Giuseppe: `reprocess --stage knowledge --ids <i 12>`. Sono 24
chiamate a Groq (riassunto + affermazioni), pochi minuti. Il riassunto nuovo
resta fatto sui primi 6.000 caratteri (vedi punto 1).

**Cosa non cambia**: `owner_type` resta com'è (2212-2214 restano `owned`, come
ha detto il cliente). Nel connettore queste puntate sono già presentate come
`di: "riferimento: <canale>"` e non come «Medyca» (sono `is_inspiration`): la
parola «Medyca» stava solo nel testo del riassunto.

### Rischi

- **`owner_type` binario**: non lo tocco. Nessun valore nuovo, nessuna
  migrazione. Il punto 3 cambia solo parole del prompt e un'etichetta.
- **I falliti restano falliti**: `--ids` rimette in coda solo ciò che una
  persona nomina. Non è un ritento automatico. Da scrivere nell'aiuto del comando.
- **Niente credenziali di terzi**: nessuna chiamata nuova a servizi esterni.
- **Cancellazioni**: nessuna in silenzio. Le tre schede si spengono con il
  percorso «Rimuovi» già esistente, dopo il sì di Giuseppe.
- **Il parametro nuovo e claude.ai**: claude.ai tiene in memoria l'elenco degli
  strumenti. Suppongo che basti riavviare `medycabrain-mcp` e, al più,
  scollegare e ricollegare il connettore. **Da provare dal vero nel collaudo**,
  non solo con i test.
- **Risposte più pesanti**: una puntata passa da 12.000 a fino a 30.000
  caratteri per lettura. È ciò che il cliente chiede, ma consuma più
  conversazione.
- **Citazione a cavallo di due pezzi**: tagliando a fine frase è raro, non
  impossibile. Le citazioni delle affermazioni stanno nei primi 8.000
  caratteri, quindi sempre nella parte 1: il controllo di `eval_mcp`
  («la citazione si trova nel testo») continua a valere.
- **Test cancello**: i testi di prova devono restare sotto 700 caratteri per
  non svegliare il modello dei vettori. Il testo lungo di prova va creato
  dentro il suo test e senza vettore, così la ricerca non lo vede.
- **Le parole del prompt cambiano per 18 documenti** (17 video + 1 intervista)
  e per quelli futuri. Per i blog il prompt deve restare identico: lo fissa un test.

### Cosa resta fuori (dichiarato)

- L'analisi che legge solo l'inizio (tabella sopra): lavagna separata.
- La bozza di articolo da un'intervista lunga (legge 12.000 caratteri).
- Gli 8 gruppi di pagine di blog con testo identico.
- Il comando per i doppioni e la disattivazione automatica della scheda vecchia.
- La categoria «partner» (proposta separata, qui sotto).
- Il diagramma drawio: nessuno stadio della pipeline cambia, non va toccato.
- `.claude/architecture-summary.md` dice ancora «quattro strumenti» (sono
  dieci): errore vecchio, trovato leggendo. Si può correggere di passaggio.

### Documenti da aggiornare (stesso commit)

- `documentation/low-level/04-mcp-connector.md`: sezione `leggi_*` (via
  «truncated to 12 000», dentro i campi nuovi, la regola dei pezzi e la soglia
  con i numeri misurati), le `instructions`, il campo `tipo`, il test cancello.
- `documentation/low-level/03-llm-and-embeddings.md` e il commento in cima a
  `knowledge_agent.py`: le parole del prompt per tipo; il limite noto
  «l'analisi legge i primi 6.000 / 8.000 / 3.000 caratteri» con i numeri.
- `documentation/low-level/02-pipeline.md`: `reprocess --ids`; la lezione dei
  doppioni (le righe salvate prima di una regola nuova sugli indirizzi non si
  sistemano da sole: al rilascio si controlla).
- `BEC/docs/mcp-connettore-claude.md`, se descrive `leggi_articolo`.
- Pagina `Documentazione` dell'app (`FEC/src/pages/Documentation.tsx`), parole
  del cliente: «I testi lunghi si leggono per intero: Claude li chiede un pezzo
  alla volta.»
- Commento in cima a `server.py`.

### Test

In `BEC/core/tests/test_mcp_tools.py`:
- testo corto: `parte` 1 di 1, `troncato` falso, testo identico a quello salvato;
- testo lungo (circa 70.000 caratteri): i pezzi riattaccati sono **uguali al
  testo salvato**; nessun pezzo supera la soglia; ogni pezzo tranne l'ultimo
  finisce a fine frase; `parte_successiva` porta fino in fondo;
- testo senza punti né spazi: taglio netto, senza giri infiniti;
- `parte` fuori misura, zero, negativa, non numerica: errore leggibile;
- `parte` scritta come testo (`"2"`) funziona;
- lo stesso per `leggi_reel` e per `leggi`;
- la parte 2 porta `titolo`, `di`, `apri_nel_brain`;
- le `instructions` nominano `parte` e `troncato`;
- `tipo`: intervista → «intervista»; il test esistente sul «video di
  riferimento» resta verde.

Altrove:
- `knowledge_agent`: per un blog il prompt è identico a prima; per un video
  non contiene «articolo del blog» e contiene il canale; per un'intervista
  dice «intervista».
- `reprocess --ids`: rimette in coda solo gli id dati; senza `--ids` fa come oggi.
- `test_uploads.py`: link `tvrs.it` incollato con la puntata Vimeo già
  presente → `gia_presenti`, nessuna riga nuova.

Collaudo dal vero, sul connettore di produzione dopo il rilascio: leggere
blog:2212 e blog:2214 (devono finire oltre «Questo è il mod» e «corre ai»),
blog:896 e blog:890, blog:296 (42.123 caratteri, due parti) e reel:960
(85.699, tre parti), chiedendo a Claude di leggere fino in fondo.

### Proposta separata - la categoria «partner / collaboratore»

**Raccomandazione: non aggiungere un terzo valore a `owner_type`.**

- Costo misurato: `owner_type` compare **106 volte in 23 file** Python (test e
  migrazioni esclusi) e **30 volte in 12 file** dell'interfaccia. In **13
  punti** il codice ragiona «è owned, altrimenti competitor» (o il contrario):
  lì un valore `partner` finirebbe da una parte senza che nessuno lo decida.
  È il rischio che la regola d'oro vieta.
- Quello che serve c'è già: `is_inspiration` («materiale di riferimento») più
  il canale. Nel connettore queste puntate si leggono già come «riferimento:
  <canale>», né Medyca né competitor.
- Se un giorno il cliente vuole proprio la parola «partner»: si cambia solo
  l'etichetta mostrata per i contenuti `owned` + `is_inspiration` («partner di
  Medyca: TVRS»). Due punti in `server.py`, nessuna migrazione. Mezza giornata.
- **Una conseguenza da sapere, che c'è già oggi**: tenute come `owned`, le tre
  puntate TVRS contano tra i contenuti di Medyca nei numeri di `panoramica` e
  nei temi di Medyca. Chi parla sono gli ospiti della trasmissione. Se al
  cliente va bene, nulla da fare; se no, è lì che va la decisione, non in un
  valore nuovo.

### Domande aperte per Giuseppe

1. **Soglia a 30.000 caratteri** va bene? (Tutte le puntate in un pezzo; 13
   articoli e 146 reel lunghi a pezzi.)
2. **`nota_analisi`**: diciamo al modello che riassunto e affermazioni sono
   fatti solo sull'inizio del testo? Io sì: è vero per 854 articoli.
3. **Le tre schede doppie**: le rimuovi tu con tre clic in Interviste, o lo fa
   il rilasciatore dopo il tuo sì?
4. **Riassunti già scritti**: rifacciamo tutti e 12, solo i tre TVRS del
   cliente, o nessuno (vale solo da ora in poi)? Io: tutti e 12.
5. **L'analisi che legge solo l'inizio**: apro una lavagna separata?
6. Le puntate TVRS che **contano come contenuti di Medyca** nei temi: va bene
   così, come ha detto il cliente?

## 3. Sviluppo           (sviluppatore)

### Cosa ho cambiato
- `BEC/mcp_bridge/server.py`: `TESTO_MAX_CARATTERI = 30_000` (con il perché in commento); `_parti`
  (pura: pezzi senza sovrapposizione, taglio dopo fine frase negli ultimi 2.000 caratteri, poi
  ultimo spazio, poi taglio netto); `_parse_parte` (accetta `"2"`, rifiuta 0, negativi, testo, bool);
  `_pezzo` (campi `caratteri_totali`, `parte`, `parti_totali`, `troncato`, `parte_successiva`,
  `come_leggere_il_resto`; errore chiaro se fuori misura); `_nota_analisi`; `_tipo_articolo`
  (intervista / video / video di riferimento / articolo). `_leggi_reel` e `_leggi_articolo` prendono
  `parte`; dalla parte 2 la risposta è leggera (`tipo`, `titolo`, `di`, `apri_nel_brain`, `url`, testo
  e campi). `leggi_reel`, `leggi_articolo`, `leggi` hanno `parte: int | str = 1`. `instructions` e
  descrizioni dei tre strumenti riscritte (via «integrale»; «se `troncato` è vero…»).
- `BEC/pipeline/agents/enrich_agent.py` e `knowledge_agent.py`: i numeri 3000 / 6000 / 8000 hanno un
  nome (`TRANSCRIPT_CHARS_READ`, `DOC_SUMMARY_CHARS_READ`, `DOC_CLAIMS_CHARS_READ`), nessun cambio di
  comportamento. `knowledge_agent`: `_intro(doc)` sceglie le parole del prompt secondo `source_type`.
  Blog e `other`: stessa frase di prima, a lettera (lo fissa un test). Video: «la trascrizione di
  questo video (una puntata o un intervento) di <canale>» + «mai articolo» (+ «chi parla sono gli
  ospiti» se è materiale di riferimento). Intervista: «questa intervista caricata da Medyca».
  `KB_SYSTEM` dice «articoli di blog e trascrizioni di video e interviste».
- Documenti: `04-mcp-connector.md` (sezione `leggi_*` riscritta con i numeri misurati, limiti noti,
  cancello), `03-llm-and-embeddings.md` (cosa legge l'analisi + parole del prompt), `02-pipeline.md`
  (lezione dei doppioni), `architecture-summary.md` (ora «dieci strumenti», prima «quattro»),
  `BEC/docs/mcp-connettore-claude.md`, pagina `Documentazione` (`FEC/src/i18n/it.json`: una riga nei
  risultati, un limite noto). Drawio non toccato: nessuno stadio cambia.
- Test: `test_mcp_tools.py` (classi `TestoPerParti`, 11 test su `_parti`/`_parse_parte`/`_pezzo`/
  `_nota_analisi`; `LeggiTestoLungo`, 9 test dal vero con testo da circa 70.000 caratteri per
  articolo e reel, e le tre vie `leggi_*`; più il test di `tipo`), `test_knowledge_prompt.py` (nuovo,
  5 test), `test_uploads.py` (link `tvrs.it` con la puntata Vimeo già presente -> `gia_presenti`).

### Prove (output vero)
```
$ manage.py test core --noinput   (Postgres 16 usa-e-getta, porta 55491, spento e cancellato; Groq vuoto, OLLAMA_URL su porta morta, YTDLP_PROXY vuoto; python del venv di produzione in sola lettura)
Ran 372 tests in 47.244s
OK
```
(345 di prima + 27 nuovi.) Nessuna chiamata vera a Groq, niente toccato in produzione.

### Non provato / rimasto fuori
- Il parametro `parte` su claude.ai dal vero: non provato. Servirà riavviare `medycabrain-mcp` e,
  se serve, scollegare e ricollegare il connettore; da collaudare su blog:2212, 2214, 896, 890, 296 e
  reel:960 (vedi il disegno). Lo schema generato per `parte: int | str` l'ho letto solo nei test
  (la proprietà c'è), non l'ho visto arrivare a un client vero.
- I 30.000 caratteri e le 8-10.000 parole-pezzo sono una stima: nessun limite ufficiale di claude.ai.
- `nota_analisi` sui reel usa 3.000; sugli articoli 6.000 (le affermazioni ne leggono 8.000: la nota
  dice solo il numero più stretto, come nel disegno).
- I riassunti già scritti (12) non si rifanno, come deciso. `reprocess --ids` non scritto.
- Resta fuori, come dichiarato: l'analisi che legge solo l'inizio, la bozza da intervista lunga
  (12.000), i gruppi di blog con testo identico.
- `KB_SYSTEM` è cambiato anche per i blog (era nel disegno): il prompt utente dei blog è identico a
  lettera, quello di sistema ha una frase in più. Se si vuole il blog identico anche lì, va diviso.
- Nessuna prova della UI: cambiata solo una stringa di `it.json` (JSON valido, nessuna build fatta).

## 4. Revisione          (revisore, 16/11/2026)

**Verdetto: PASSA**, con un rilievo da correggere prima del rilascio (parole, non logica).

Letto: il diff intero (`origin/main...HEAD`, un solo commit, nessun commit su `main`), la lavagna con le
«Decisioni di Giuseppe». Provato `_parti` a mano (estratta da `server.py`, python isolato) su: testo
vuoto, 30.000 esatti, 30.001, solo a capo (70.000), nessuno spazio, `"x. "*30000`. In tutti i casi
`"".join(parti) == testo`, nessun pezzo supera 30.000, nessun pezzo vuoto (tranne il testo vuoto, che
dà un solo pezzo vuoto, giusto), nessun ciclo.

**Invarianti: tutti rispettati.** `owner_type` non toccato (nessun terzo valore). `di` e citazione
restano calcolati come prima e compaiono anche dalla parte 2 (`tipo`, `titolo`, `di`, `apri_nel_brain`,
`url`). Strumenti ancora di sola lettura (solo `.filter/.first`). Nessun segreto nel diff. Nessun
fallito azzerato. `reprocess --ids` non scritto, come deciso. Le tre vie `leggi_*` passano per le
stesse `_parse_parte`/`_pezzo`.

**Rilievi, per gravità**

1. **Medio - `troncato` è vero anche sull'ultima parte, ma le `instructions` e le descrizioni dicono
   «se `troncato` è vero il testo continua: richiama con `parte` = `parte_successiva`»**
   (`server.py`, `instructions` e `_PARTE_DESC`). Con un testo di 3 parti, alla parte 3:
   `troncato: true`, `parte_successiva: null`. La frase promette un seguito che non c'è. Il
   modello ha anche `come_leggere_il_resto` che dice «finisce qui», quindi il danno è piccolo (al
   peggio `parte="None"` -> errore leggibile), ma è una promessa falsa. Il comportamento di `troncato`
   è quello del disegno approvato e documentato in `04`; va corretta la frase: «se `parte_successiva`
   non è vuoto il testo continua: richiama con `parte` = `parte_successiva`». Così `instructions`,
   descrizioni e documento dicono la stessa cosa del codice.
2. **Basso - `nota_analisi` dice «primi 6.000 caratteri» per riassunto E affermazioni**, ma le
   affermazioni leggono 8.000 (`DOC_CLAIMS_CHARS_READ`). È il lato prudente (dice il numero più
   stretto) e lo sviluppatore lo ha dichiarato; basta saperlo. I numeri vengono dalle stesse costanti
   della pipeline (`DOC_SUMMARY_CHARS_READ`, `TRANSCRIPT_CHARS_READ`): non possono divergere.
3. **Basso - taglio sullo spazio**: `_parti` cerca l'ultimo spazio in tutta la finestra da 30.000, non
   solo nel tratto finale. Un testo con uno spazio all'inizio e poi 40.000 caratteri senza spazi dà un
   primo pezzo di 1-6 caratteri. Non è un ciclo né un pezzo vuoto, il testo si riattacca esatto; capita
   solo con testi che non esistono in banca dati. Non blocca.

**`KB_SYSTEM` anche per i blog: rischio basso, accettabile.** La frase in più
(«articoli di blog e trascrizioni di video e interviste») non dice nulla di diverso per un blog; il
prompt utente dei blog è identico a lettera (lo fissa un test). Cambia solo per i documenti analizzati
da ora in poi (i 2.281 già fatti non si rifanno), quindi i riassunti futuri dei blog potrebbero
variare di una virgola, non di struttura. Era nel disegno approvato e nel documento `03`. Nota: il test
fissa il prompt utente, non quello di sistema; se un giorno si vuole il blog identico anche lì, si
divide `KB_SYSTEM`.

**Documentazione: completa.** `02`, `03`, `04`, `BEC/docs/mcp-connettore-claude.md`,
`architecture-summary.md` (corretto anche «quattro» -> «dieci»), pagina `Documentazione`
(`it.json`: una riga nei risultati, un limite noto), commento in cima a `server.py` e
`knowledge_agent.py`. Drawio non toccato: corretto, nessuno stadio cambia. Il limite noto «i riassunti
di testi lunghi leggono l'inizio» è scritto in tre posti.

**Non verificato da me**: i test non li ho rilanciati (lo sviluppatore riporta 372 OK); il parametro
`parte` su claude.ai dal vero spetta al collaudo.

`stato:` resta `revisione` finché il collaudo non scrive il suo esito; se passa e il rilievo 1 è
corretto, `pronto`.

## 5. Collaudo          (collaudatore, 16/11/2026)

**Verdetto: PASSA.** (Il rilievo 1 della revisione resta da correggere: l'ho visto anche dal vivo, vedi sotto.)
Commit provato: `9003d3a`, ramo `feat/mcp-testo-intero`. Non toccato nulla in produzione: nessun
`migrate`, build, riavvio, scrittura. Nessuna chiamata a Groq (chiavi svuotate, `OLLAMA_URL` su porta morta).

### 1. Suite intera su un Postgres usa-e-getta
Postgres 16 in una cartella del scratchpad, porta 55612, chiavi `LLM_GROQ_API_KEY`, `FAST_LLM_API_KEY`,
`LLM_API_KEY`, `HF_API_TOKEN`, `LLM_ENDPOINTS`, `YTDLP_PROXY` vuote. Python del venv di produzione, solo lettura.
```
$ manage.py test core --noinput
Ran 372 tests in 51.220s

OK
Destroying test database for alias 'default'...
```
Le righe `WARNING/ERROR core.link_ingest ... yt-dlp` nel log sono attese (test di errore).

### 2. Il codice del ramo contro i dati veri, in sola lettura
Codice di `BEC/mcp_bridge/server.py` del worktree, funzioni `leggi(...)` chiamate in-process sul DB di
produzione. La sessione era forzata a sola lettura dal server (`PGOPTIONS=-c default_transaction_read_only=on`):
```
transaction_read_only = on
```
Le parti 2.. chieste come testo (`"2"`), per provare anche questo.

| id | tipo | di | caratteri_totali (= DB) | parti | riattaccato == salvato | fine del testo |
|---|---|---|---|---|---|---|
| blog:2212 | video di riferimento | riferimento: TVRS SRL | 16.865 | 1 | sì | «...Per info e prenotazioni 0733 20 28 80.» |
| blog:2214 | video di riferimento | riferimento: TVRS SRL | 14.979 | 1 | sì | «...Pesaro e San Benedetto del Tronto.» |
| blog:896 | video di riferimento | riferimento: TVRS SRL | 20.336 | 1 | sì | «...diafrate 10 Osimo.» |
| blog:890 | video di riferimento | riferimento: YouTVRS | 16.919 | 1 | sì | «...via fratte 10 Osimo.» |
| blog:296 | articolo | competitor: Farmagalenica | 42.123 | 2 (29.959 + 12.164) | sì | «...e vedere che gli dicono.» |
| reel:960 | reel | competitor: @menopauseboost | 85.699 | 3 (29.719 + 29.999 + 25.981) | sì | «...ciao, è uno prossimo a settimana ciao» |

- 2212 non finisce più con «Questo è il mod»: arriva in fondo alla trascrizione. Stesso per 2214 («corre ai»).
- Tutte le fini sono fine frase o fine testo. Dove c'è un taglio (296 e 960) la parte 1 finisce a fine riga/frase
  (296: «...per preparare cannabis:\n»; 960: «...ci tengo perché? »), mai a metà parola.
- `nota_analisi` presente nella parte 1 di tutti e 6 («primi 6.000 caratteri su N» per i blog, «primi 3.000 su 85.699» per reel:960); assente dalla parte 2 in poi (verificato su 296 e 960).
- Parte 2 leggera, solo: `apri_nel_brain, caratteri_totali, come_leggere_il_resto, di, parte, parte_successiva, parti_totali, testo, tipo, titolo, troncato, url` (per 960 `trascrizione` al posto di `testo`).
- `come_leggere_il_resto` parte 1 di 296: «Testo lungo: questa è la parte 1 di 2. Per il seguito chiama leggi_articolo con parte=2.»
- Errori: `leggi_articolo("blog:296", 3)` -> `{'errore': 'questo contenuto ha 2 parti: chiedi una parte da 1 a 2'}`;
  `parte="0"` -> «`parte` parte da 1...»; `parte="x"` -> «`parte` deve essere un numero intero (1, 2, 3…)».
- Risposta JSON più grande: parte 1 di blog:296, **33.620 caratteri / 34.207 byte** (~11-12.000 token con la
  stima del disegno). Le altre: 32.755 byte (reel:960 p.1), 30.807, 26.758, 24.448 (896), 20.341, 20.108, 17.888.
- Rilievo 1 della revisione **confermato dal vivo**: blog:296 parte 2 (ultima) ha `troncato: true` e
  `parte_successiva: None`, mentre le `instructions` dicono «se `troncato` è vero il testo continua».
  `come_leggere_il_resto` dice giusto («Questa è l'ultima parte (2 di 2): il testo finisce qui.»). È parole,
  non logica; da correggere prima del rilascio come già scritto dal revisore.

Nota sui dati: per 2212 e 2214 il `tipo` è «video di riferimento» e `di` «riferimento: TVRS SRL»: non più
«articolo», e non «Medyca», come da disegno (sono `owned` + materiale di riferimento).

### 3. Una copia del server MCP del ramo, con una chiamata MCP vera
`uvicorn mcp_bridge.server:app` dal worktree su 127.0.0.1:18733 (non 8025), segreto di prova, DB in sola
lettura come sopra, client HTTP semplice (JSON-RPC, `initialize`, `tools/list`, `tools/call`):
- `instructions`: contengono `parte` e `troncato`, non contengono più «integrale».
- `tools/list`: `leggi_reel`, `leggi_articolo`, `leggi` hanno la proprietà `parte` (`anyOf integer | string`,
  non obbligatoria; obbligatorio solo `id`) e le descrizioni nuove («per intero fino a 30.000 caratteri,
  poi a pezzi», «Guarda `tipo`: articolo, video o intervista», «Se `troncato` è vero il testo continua...»).
- `tools/call leggi_articolo {id: "blog:296", parte: "2"}`: `isError: False`, `parte: 2`, `parti_totali: 2`,
  `testo` di 12.164 caratteri, `tipo/titolo/di/apri_nel_brain/url` presenti, 13.693 byte di risposta.

### 4. Pulizia
Server uvicorn fermato (porta 18733 libera), Postgres usa-e-getta fermato e cancellato (cartella dati e
socket), script temporanei cancellati. `git status` del worktree pulito prima di questa sezione.

### Non provato
- **claude.ai dal vero**: non si può provare prima del rilascio. Resta da fare dopo il riavvio di
  `medycabrain-mcp`: scollegare e ricollegare il connettore se serve, poi chiedere a Claude di leggere
  blog:2212, 2214, 896, 890, 296 (due parti) e reel:960 (tre parti) fino in fondo, e controllare che
  mandi `parte` come testo o numero senza errori. Indirizzo: il connettore di produzione (l'URL di invito), gesto: la conversazione in claude.ai.
- Le 13.000-34.000 byte per risposta sono accettate dal mio client: non so se claude.ai le accetta (nessun
  limite ufficiale noto, vedi disegno).
- La UI: non toccata da me (cambiata solo una stringa di `it.json`); `npm run build` non lanciato, perché
  vietato toccare la produzione e il worktree non ha `node_modules`. Non provato.
- Il prompt per i video (`knowledge_agent`) è provato solo dai test (nessuna chiamata a Groq, per vincolo).
- Rete di test sottile: il verde dice che il connettore regge su questi 6 contenuti reali, non che ogni
  contenuto lo sia (non ho scorso tutti i 2.302 articoli e 1.498 reel).

## Registro

- 16/11 capo: tocca uno strumento MCP (struttura) → architetto.
- 16/11 architetto: disegno scritto, in attesa dell'OK di Giuseppe. La causa dei doppioni non è la scheda di un link rifiutato: i link tvrs.it sono stati incollati sei ore prima della PR #14 e letti come pagine web. Nessun terzo valore per `owner_type`.

## Decisioni di Giuseppe (16/11/2026)

1. Disegno approvato **per intero**: soglia 30.000, pezzi oltre, `nota_analisi`, parole
   secondo il tipo nel prompt di `knowledge_agent.py`, campo `tipo` giusto nel connettore.
2. Doppioni 2198-2200: **fatto dal capo il 16/11**, con la stessa azione del tasto «Rimuovi»
   (`perform_destroy`): documenti 2198, 2199, 2200 `is_active=False`, righe di carico 18,
   19, 20 cancellate. Le puntate vere 2212-2214 restano attive. Nel ramo resta solo il test
   che lo stesso link `tvrs.it` oggi viene riconosciuto come video.
3. I 12 riassunti già scritti **non si rifanno**. Quindi l'opzione `reprocess --stage
   knowledge --ids` NON serve: non scriverla.
4. Lavoro separato, dopo questo, perché i riassunti leggano tutto il testo. Qui solo
   `nota_analisi`.
5. Le puntate TVRS restano `owned`; nessuna categoria «partner».
