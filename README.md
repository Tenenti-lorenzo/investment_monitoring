# PortfolioLab 📊

Dashboard portafoglio con FastAPI backend + sito HTML con slot pubblicitari.

## Struttura

```
portfoliodash/
├── backend/
│   └── main.py          # FastAPI app
├── frontend/
│   ├── index.html       # Sito principale (AdSense-ready)
│   └── static/
│       ├── css/style.css
│       └── js/app.js
├── requirements.txt
└── run.sh
```

## Setup

```bash
# 1. Installa dipendenze
pip install -r requirements.txt

# 2. Avvia il server (dalla root del progetto)
uvicorn backend.main:app --reload --port 8000

# Oppure:
bash run.sh
```

Il sito è disponibile su → http://localhost:8000

## API Endpoints

| Metodo | Path | Descrizione |
|--------|------|-------------|
| GET | `/api/search?q=ISIN_OR_TICKER` | Ricerca strumento |
| POST | `/api/portfolio/analyze` | Analizza portafoglio |

### Esempio search
```
GET /api/search?q=IE00B3RBWM25
GET /api/search?q=MSFT
GET /api/search?q=ETH-USD
```

### Esempio analyze
```json
POST /api/portfolio/analyze
{
  "holdings": [
    { "isin": "IE00B3RBWM25", "ticker": "SWRD", "name": "iShares MSCI World",
      "category": "ETF", "allocation": 60.0, "geography": {"Nord America": 68, "Europa": 20, "Asia-Pacifico": 12} },
    { "isin": "", "ticker": "MSFT", "name": "Microsoft",
      "category": "Azioni", "allocation": 30.0, "geography": {"Nord America": 100} }
  ],
  "liquidita": 10.0
}
```

## Pubblicità

Gli slot pubblicitari sono già presenti nel HTML con commenti AdSense.
Per attivare Google AdSense, sostituisci i blocchi `<!-- Google AdSense -->` in `index.html`
con il tuo codice publisher (`ca-pub-XXXXXXXX`).

Slot disponibili:
- **Top leaderboard** (728×90) — sopra navbar
- **Mid content** (336×280) — tra form e dashboard
- **Sidebar half page** (300×600) — sidebar destra sticky
- **Sidebar rectangle** (300×250) — sidebar destra bassa
- **Mid right** (300×250) — colonna destra dashboard
- **Footer leaderboard** (728×90) — footer

## Note tecniche

- **ISIN resolution**: OpenFIGI API (gratuita, no API key necessaria)
- **Dati mercato**: Yahoo Finance via `yfinance`
- **Esposizione geografica**: stima euristica basata su categoria e metadati ETF
- **Composizione ETF**: `yfinance` `funds_data.top_holdings` (dove disponibile)
