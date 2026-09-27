# Architettura

[← Indice](README.md) · Correlati: [Backend](backend.md) · [Analisi](analisi.md) · [Frontend](frontend.md) · [Database](database.md) · [Infrastruttura](infrastruttura.md)

## Riassunto

PortfolioLab e' un'applicazione serverless a tre strati:

1. **Frontend statico** — tre pagine HTML in JS vanilla, nessun build step, grafici con Chart.js (CDN):
   dashboard (`index.html` + `app.js` + `superinvestors.js`), login (`login.html`) e analisi
   approfondita (`analisi.html` + `analisi.js` + `analisi-charts.js`).
2. **Backend FastAPI** — `backend/main.py` (rotte) piu' moduli dedicati per obbligazioni
   (`bonds.py`, `bond_market.py`), superinvestitori (`superinvestors.py`) e analisi approfondita
   (`deep_analysis.py`, `look_through.py`, `portfolio_metrics.py`, `price_history.py`,
   `analysis_models.py`). Gira sia in locale (uvicorn) sia su AWS Lambda tramite l'adapter ASGI
   **Mangum** (`handler = Mangum(app)`). L'accesso ai dati e' isolato in `backend/database.py`.
3. **Infrastruttura AWS** — definita in `terraform/`: CloudFront → (S3 | API Gateway → Lambda),
   con DynamoDB, Secrets Manager ed ECR.

In locale, FastAPI serve anche il frontend (`/`, `/login`, `/analisi`). In produzione il frontend e' servito
da S3 via CloudFront, e solo le rotte `/api/*` raggiungono Lambda.

## Diagramma architetturale (deploy AWS)

```mermaid
flowchart TD
  browser(["Browser utente"])

  cf["CloudFront<br/>+ Function url-rewrite<br/>(/login, /analisi → *.html)"]
  s3[("S3 bucket privato<br/>index.html, login.html,<br/>analisi.html, static/*")]
  oac["Origin Access Control"]

  apigw["API Gateway HTTP v2<br/>route: ANY /api/{proxy+}"]
  lambda["Lambda (container Image)<br/>backend.main.handler<br/>FastAPI + Mangum"]
  logs["CloudWatch Logs"]

  ddbU[("DynamoDB<br/>portfoliolab_users")]
  ddbP[("DynamoDB<br/>portfoliolab_portfolios")]
  sm["Secrets Manager<br/>ANTHROPIC_API_KEY, SECRET_KEY,<br/>FRED_API_KEY"]
  ecr["ECR<br/>immagine container"]

  figi["OpenFIGI API"]
  yahoo["Yahoo Finance (yfinance)"]
  justetf["justETF (scraping TER)"]
  claude["Anthropic Claude"]
  borsa["Borsa Italiana (scraping quotazioni obbligazioni)"]
  dataroma["Dataroma (scraping 13F)"]
  fred["FRED API (rendimenti 10Y)"]

  browser -->|HTTPS| cf
  cf -->|"default behavior, cache"| oac --> s3
  cf -->|"/api/* behavior, no cache"| apigw
  apigw -->|AWS_PROXY| lambda
  lambda -. read .-> sm
  lambda --> ddbU
  lambda --> ddbP
  lambda --> logs
  ecr -. image_uri:latest .-> lambda

  lambda --> figi
  lambda --> yahoo
  lambda --> justetf
  lambda --> claude
  lambda --> borsa
  lambda --> dataroma
  lambda --> fred
```

## Flusso di una richiesta API

```mermaid
sequenceDiagram
  participant B as Browser (app.js)
  participant CF as CloudFront
  participant GW as API Gateway
  participant L as Lambda (FastAPI)
  participant SM as Secrets Manager
  participant DDB as DynamoDB
  participant EXT as Servizi esterni

  Note over L: cold start → _load_aws_secrets() + init_db()
  L->>SM: get_secret_value (solo se SECRETS_ARN)
  L->>DDB: describe/create tables (idempotente)

  B->>CF: GET/POST /api/...  (Bearer JWT)
  CF->>GW: inoltra /api/* (no cache)
  GW->>L: evento AWS_PROXY
  L->>L: get_current_user() valida JWT
  alt token mancante/scaduto
    L-->>B: 401 → il client fa redirect a /login
  else token valido
    L->>EXT: OpenFIGI / Yahoo / justETF / Borsa Italiana / Dataroma / FRED / Claude (a seconda dell'endpoint)
    L->>DDB: lettura/scrittura (save/load/list portafogli, utenti)
    L-->>B: 200 JSON
  end
```

## Bootstrap del backend (avvio processo / cold start)

All'import di `backend/main.py` avviene, in ordine:

1. `load_dotenv()` — carica `.env` in locale.
2. `_load_aws_secrets()` — se `SECRETS_ARN` e' settato, legge il segreto JSON da Secrets Manager
   e popola `ANTHROPIC_API_KEY` / `SECRET_KEY` / `FRED_API_KEY` con `os.environ.setdefault`.
3. `init_db()` ([database.md](database.md)) — crea le tabelle DynamoDB se assenti (PAY_PER_REQUEST).
4. Costruzione `FastAPI()`, CORS aperto (`*`), mount di `/static` e rotte `/`, `/login`, `/analisi` (solo se
   esiste la cartella `frontend/`, quindi solo in locale; su Lambda l'immagine contiene solo `backend/`).
5. In fondo al file: `handler = Mangum(app, lifespan="off")` — entry point invocato da Lambda.

## Strati e dipendenze del codice

```mermaid
flowchart LR
  subgraph frontend
    idx["index.html"]
    appjs["app.js"]
    sijs["superinvestors.js"]
    login["login.html"]
    an["analisi.html"]
    anjs["analisi.js + analisi-charts.js"]
  end
  subgraph backend
    main["main.py<br/>(rotte, auth, ricerca,<br/>analisi base, P&L)"]
    db["database.py<br/>(DynamoDB)"]
    bonds["bonds.py<br/>bond_market.py"]
    si["superinvestors.py"]
    deep["deep_analysis.py<br/>look_through.py"]
    core["portfolio_metrics.py<br/>(math pura)"]
    ph["price_history.py"]
    models["analysis_models.py"]
  end

  idx --> appjs & sijs
  an --> anjs
  appjs -->|"fetch /api/*"| main
  sijs -->|"/api/superinvestors*"| main
  anjs -->|"/api/analysis/*"| main
  login -->|"fetch /api/auth/*"| main
  appjs -. "localStorage.analysis_portfolio" .-> anjs
  main --> db & bonds & si & deep
  deep --> core & ph & bonds & models
```

> Nota: il backend non segue ancora lo split `domain/services/adapters/api` consigliato nelle
> preferenze del progetto. I moduli recenti separano pero' contratti (`analysis_models.py`),
> matematica pura (`portfolio_metrics.py`), I/O (`price_history.py`, scraper) e orchestrazione;
> `main.py` (~1190 righe) resta monolitico. Vedi [Backend](backend.md#note-e-drift).

## Riferimenti

- [Backend / API](backend.md) — dettaglio endpoint e funzioni.
- [Analisi](analisi.md) — metodologia della pagina di analisi approfondita.
- [Database](database.md) — `init_db`, tabelle, funzioni CRUD.
- [Frontend](frontend.md) — come il client orchestra le chiamate.
- [Infrastruttura](infrastruttura.md) — risorse Terraform mostrate nel diagramma.
- [Riferimenti](riferimenti.md) — servizi esterni e variabili d'ambiente.
