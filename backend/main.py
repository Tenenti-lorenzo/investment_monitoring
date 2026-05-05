from fastapi import FastAPI, HTTPException, Query, File, UploadFile, Depends
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as _FutTimeout
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List
import yfinance as yf
import requests
import re
import os
import io
import json
import secrets
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import anthropic
import pypdf
import bcrypt as _bcrypt_lib
from jose import jwt, JWTError
from backend.database import (
    init_db,
    get_user_by_username,
    get_user_by_email,
    get_user_by_reset_token,
    create_user,
    set_reset_token,
    set_password,
    save_portfolio_dynamo,
    list_portfolios_dynamo,
    load_portfolio_dynamo,
    delete_portfolio_dynamo,
)

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-use-a-long-random-string")
TOKEN_EXPIRE_HOURS = 24 * 7  # 7 days

_http_bearer = HTTPBearer()

init_db()

app = FastAPI(title="Portfolio Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_path / "static")), name="static")


@app.get("/")
def root():
    return FileResponse(str(frontend_path / "index.html"))


@app.get("/login")
def login_page():
    return FileResponse(str(frontend_path / "login.html"))


# ─── Auth helpers ────────────────────────────────────────────────────────────

def _hash_pw(pw: str) -> str:
    return _bcrypt_lib.hashpw(pw.encode()[:72], _bcrypt_lib.gensalt()).decode()

def _verify_pw(plain: str, hashed: str) -> bool:
    return _bcrypt_lib.checkpw(plain.encode()[:72], hashed.encode())

def _create_token(username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": exp}, SECRET_KEY, algorithm="HS256")

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_http_bearer),
) -> str:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        username: str = payload.get("sub", "")
        if not username:
            raise HTTPException(401, "Token non valido")
        return username
    except JWTError:
        raise HTTPException(401, "Sessione scaduta, effettua di nuovo il login")


# ─── Auth models ─────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class ForgotRequest(BaseModel):
    email: str

class ResetRequest(BaseModel):
    token: str
    new_password: str


# ─── Auth routes ─────────────────────────────────────────────────────────────

@app.post("/api/auth/register")
def auth_register(req: RegisterRequest):
    if len(req.password) < 6:
        raise HTTPException(400, "La password deve avere almeno 6 caratteri")
    hashed = _hash_pw(req.password)
    try:
        create_user(req.username.strip(), req.email.strip().lower(), hashed)
    except ValueError as e:
        raise HTTPException(400, "Username o email già in uso")
    token = _create_token(req.username.strip())
    return {"status": "ok", "token": token, "username": req.username.strip()}


@app.post("/api/auth/login")
def auth_login(req: LoginRequest):
    user = get_user_by_username(req.username.strip())
    if not user or not _verify_pw(req.password, user["hashed_password"]):
        raise HTTPException(401, "Credenziali non valide")
    return {"token": _create_token(req.username.strip()), "username": req.username.strip()}


@app.post("/api/auth/forgot-password")
def auth_forgot_password(req: ForgotRequest):
    user = get_user_by_email(req.email.strip().lower())
    # Always return OK to avoid revealing whether the email is registered
    if not user:
        return {"status": "ok", "message": "Se l'email è registrata riceverai le istruzioni."}

    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    set_reset_token(user["username"], token, expires)

    app_url = os.getenv("APP_URL", "http://localhost:8000")
    reset_url = f"{app_url}/login?reset_token={token}"

    smtp_host = os.getenv("SMTP_HOST")
    if smtp_host:
        try:
            msg = MIMEText(
                f"Clicca il link per reimpostare la password:\n\n{reset_url}\n\n"
                "Il link scade tra 1 ora."
            )
            msg["Subject"] = "Reimposta la tua password – PortfolioLab"
            msg["From"] = os.getenv("SMTP_USER", "noreply@portfoliolab")
            msg["To"] = req.email
            with smtplib.SMTP(smtp_host, int(os.getenv("SMTP_PORT", "587"))) as s:
                s.starttls()
                s.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASS", ""))
                s.sendmail(msg["From"], [req.email], msg.as_string())
            return {"status": "ok", "message": "Email inviata. Controlla la tua casella di posta."}
        except Exception:
            pass  # Fall through to local-mode response

    # SMTP not configured: return the link directly (local / dev mode)
    return {
        "status": "ok",
        "reset_url": reset_url,
        "message": "SMTP non configurato. Usa il link qui sotto per reimpostare la password.",
    }


@app.post("/api/auth/reset-password")
def auth_reset_password(req: ResetRequest):
    user = get_user_by_reset_token(req.token)
    if not user:
        raise HTTPException(400, "Token non valido")
    expires = datetime.fromisoformat(user["reset_token_expires"])
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(400, "Token scaduto. Richiedi un nuovo link di recupero.")
    if len(req.new_password) < 6:
        raise HTTPException(400, "La password deve avere almeno 6 caratteri")
    set_password(user["username"], _hash_pw(req.new_password))
    return {"status": "ok", "message": "Password reimpostata con successo."}


@app.get("/api/auth/me")
def auth_me(current_user: str = Depends(get_current_user)):
    user = get_user_by_username(current_user)
    if not user:
        raise HTTPException(404, "Utente non trovato")
    return {
        "username": user["username"],
        "email": user["email"],
        "created_at": user.get("created_at", ""),
    }


# ─── ISIN to Ticker resolution via OpenFIGI ─────────────────────────────────

# Exchange priority for European ETF ISINs: EUR listings > CHF > GBP > USD
# Higher number = preferred. Codes: GR=Xetra, MI/IM=Milan, PA=Paris, NA/AM=Amsterdam.
_EUR_EXCH_PRIORITY = {
    "GR": 10, "MI": 9, "IM": 9, "PA": 8, "NA": 7, "AM": 7,  # EUR
    "SW": 3,                                                    # CHF
    "LN": 2,                                                    # GBP
    "US": 1, "UW": 1, "UA": 1, "UP": 1,                       # USD
}
_ALL_PREF_EXCHANGES = set(_EUR_EXCH_PRIORITY.keys())

def isin_to_ticker(isin: str) -> dict:
    """Resolve ISIN to ticker via OpenFIGI.
    For European ETF domiciles (IE/LU/GB/FR) prefers EUR-denominated exchanges."""
    try:
        url = "https://api.openfigi.com/v3/mapping"
        payload = [{"idType": "ID_ISIN", "idValue": isin}]
        resp = requests.post(url, json=payload, timeout=8,
                             headers={"Content-Type": "application/json"})
        if resp.status_code == 200:
            data = resp.json()
            if data and data[0].get("data"):
                items = data[0]["data"]
                et = [x for x in items if x.get("exchCode") in _ALL_PREF_EXCHANGES]
                candidates = et if et else items

                # For European ETF/UCITS domiciles, prefer fund/ETP types
                etf_domiciles = {"IE", "LU", "GB", "FR", "DE", "LI", "CH"}
                if isin[:2] in etf_domiciles:
                    fund_kw = {"etf", "etp", "open-end fund", "fund"}
                    fund_cands = [
                        x for x in candidates
                        if any(k in (x.get("securityType") or "").lower() for k in fund_kw)
                    ]
                    if fund_cands:
                        candidates = fund_cands
                    # Sort by EUR-priority so Xetra/Milan/Paris beat London
                    candidates = sorted(
                        candidates,
                        key=lambda x: _EUR_EXCH_PRIORITY.get(x.get("exchCode", ""), 0),
                        reverse=True,
                    )

                best = candidates[0]
                return {
                    "ticker": best.get("ticker", ""),
                    "name": best.get("name", ""),
                    "exchCode": best.get("exchCode", ""),
                    "securityType": best.get("securityType", ""),
                }
    except Exception:
        pass
    return {}


SUFFIX_MAP = {
    "LN": ".L",
    "GR": ".DE",
    "MI": ".MI",
    "IM": ".MI",   # Milan alt code in OpenFIGI
    "SW": ".SW",
    "PA": ".PA",
    "AM": ".AS",
    "NA": ".AS",   # Euronext Amsterdam alt code in OpenFIGI
}

def build_yf_ticker(ticker: str, exch: str) -> str:
    return ticker + SUFFIX_MAP.get(exch, "")


# ─── Category detection ──────────────────────────────────────────────────────

BOND_KEYWORDS = [
    "bond", "fixed income", "treasury", "gilt", "aggregate", "credit",
    "corporate bond", "government bond", "sovereign", "inflation", "tips",
    "duration", "debt", "obligat", "obbligaz", "reddito fisso",
    "high yield", "investment grade", "floating rate", "convertible",
    "short-term bond", "intermediate bond", "long-term bond", "liabilities",
]

def guess_category_from_name(name: str, sec_type: str) -> str:
    name_l = (name or "").lower()
    sec_l = (sec_type or "").lower()
    if any(k in name_l for k in ["etf", "ucits", "index fund", "ishares", "vanguard", "xtrackers", "amundi", "lyxor", "spdr"]):
        return "ETF"
    if any(k in name_l for k in ["bitcoin", "ethereum", "crypto", "btc", "eth", "coin"]):
        return "Criptovalute"
    if "fund" in sec_l or "etf" in sec_l or "etp" in sec_l:
        return "ETF"
    return "Azioni"


def classify_etf_type(info: dict, name: str) -> str:
    """Return 'ETF Azionario' or 'ETF Obbligazionario' based on category and name."""
    category = (info.get("category") or "").lower()
    name_l = (name or "").lower()
    if any(k in category for k in BOND_KEYWORDS) or any(k in name_l for k in BOND_KEYWORDS):
        return "ETF Obbligazionario"
    return "ETF Azionario"


# ─── ETF Geography ───────────────────────────────────────────────────────────

def get_etf_geography(info: dict) -> dict:
    country = info.get("country", "")
    category = (info.get("category") or info.get("fundFamily") or "").lower()

    if any(k in category for k in ["world", "global", "msci world", "all world"]):
        return {"Nord America": 68, "Europa": 20, "Asia-Pacifico": 9, "Altre": 3}
    if any(k in category for k in ["emerging", "em"]):
        return {"Asia-Pacifico": 55, "Europa Emergente": 10, "Latam": 18, "Africa/ME": 17}
    if any(k in category for k in ["europe", "euro", "stoxx"]):
        return {"Europa": 85, "Nord America": 10, "Altre": 5}
    if any(k in category for k in ["s&p", "sp500", "nasdaq", "us equity", "usa"]):
        return {"Nord America": 95, "Altre": 5}
    if any(k in category for k in ["japan"]):
        return {"Asia-Pacifico": 95, "Altre": 5}
    if country == "United States":
        return {"Nord America": 100}
    if country in ("Germany", "France", "Italy", "Netherlands", "Spain", "Switzerland", "United Kingdom", "Sweden"):
        return {"Europa": 100}
    if country in ("Japan", "China", "Hong Kong", "South Korea", "Australia"):
        return {"Asia-Pacifico": 100}
    return {"Globale": 100}


def get_etf_composition(info: dict, ticker_obj) -> list:
    try:
        holdings = ticker_obj.funds_data.top_holdings if hasattr(ticker_obj, "funds_data") else None
        if holdings is not None and not holdings.empty:
            result = []
            for idx, row in holdings.head(10).iterrows():
                result.append({
                    "name": row.get("Name", idx),
                    "weight": round(float(row.get("Holding Percent", 0)) * 100, 2)
                })
            return result
    except Exception:
        pass
    return []


# ─── Search endpoint ─────────────────────────────────────────────────────────

@app.get("/api/search")
def search_asset(
    q: str = Query(..., description="ISIN or Ticker"),
    _: str = Depends(get_current_user),
):
    q = q.strip().upper()

    figi_data = {}
    yf_ticker_str = q

    is_isin = bool(re.match(r"^[A-Z]{2}[A-Z0-9]{10}$", q))
    if is_isin:
        figi_data = isin_to_ticker(q)
        if not figi_data:
            raise HTTPException(404, f"ISIN {q} non trovato su OpenFIGI")
        yf_ticker_str = build_yf_ticker(figi_data["ticker"], figi_data.get("exchCode", ""))

    ticker_obj = yf.Ticker(yf_ticker_str)
    info = ticker_obj.info or {}

    if not info or info.get("quoteType") is None:
        ticker_obj = yf.Ticker(figi_data.get("ticker", q))
        info = ticker_obj.info or {}

    if not info:
        raise HTTPException(404, f"Nessun dato per {yf_ticker_str}")

    name = info.get("longName") or info.get("shortName") or figi_data.get("name") or q
    quote_type = info.get("quoteType", "EQUITY")
    sec_type = figi_data.get("securityType", "")

    # Category detection: distinguish ETF Azionario / Obbligazionario
    category = guess_category_from_name(name, sec_type)
    etf_domiciles = {"IE", "LU", "GB", "FR", "DE", "LI"}
    sec_type_lower = (sec_type or "").lower()

    # Treat as ETF if: Yahoo says ETF, name suggests ETF, ISIN from ETF domicile with ETP/fund type,
    # or OpenFIGI securityType is fund/etp
    is_likely_etf = (
        quote_type in ("ETF", "MUTUALFUND")
        or category == "ETF"
        or any(k in sec_type_lower for k in ("etp", "fund", "etf"))
        or (is_isin and q[:2] in etf_domiciles and quote_type == "EQUITY"
            and any(k in name.lower() for k in ["etf", "ucits", "index", "vanguard", "ishares",
                                                 "xtrackers", "amundi", "lyxor", "spdr", "fund"]))
    )
    if is_likely_etf:
        category = classify_etf_type(info, name)
    elif quote_type == "CRYPTOCURRENCY":
        category = "Criptovalute"

    # Warn if ISIN from ETF domicile resolved to a commodity ETC
    COMMODITY_NAMES = ["heating oil", "crude oil", "natural gas", "gold", "silver",
                       "copper", "wheat", "corn", "soybean", "coffee", "sugar"]
    isin_mismatch = bool(
        is_isin and q[:2] in etf_domiciles
        and any(k in name.lower() for k in COMMODITY_NAMES)
    )

    geography = get_etf_geography(info)
    composition = get_etf_composition(info, ticker_obj)

    price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
    currency = info.get("currency", "")
    sector = info.get("sector", "")
    industry = info.get("industry", "")
    fund_family = info.get("fundFamily", "")
    description = (info.get("longBusinessSummary") or "")[:400]

    raw_ter = info.get("annualReportExpenseRatio") or info.get("expenseRatio")
    ter = round(float(raw_ter) * 100, 4) if raw_ter else None

    return {
        "isin": q if is_isin else "",
        "ticker": figi_data.get("ticker") or q,
        "yf_ticker": yf_ticker_str,
        "name": name,
        "category": category,
        "quoteType": quote_type,
        "price": price,
        "currency": currency,
        "sector": sector,
        "industry": industry,
        "fundFamily": fund_family,
        "description": description,
        "geography": geography,
        "composition": composition,
        "exch": figi_data.get("exchCode", ""),
        "isin_mismatch": isin_mismatch,
        "ter": ter,
    }


# ─── Portfolio analysis ───────────────────────────────────────────────────────

class Holding(BaseModel):
    isin: str
    name: str
    ticker: str
    yf_ticker: Optional[str] = None
    category: str
    allocation: float
    geography: Optional[dict] = None
    currency: Optional[str] = None
    ter: Optional[float] = None           # TER in % e.g. 0.20
    amount: Optional[float] = None        # EUR position value
    quantity: Optional[float] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[str] = None

class PortfolioRequest(BaseModel):
    holdings: list[Holding]
    liquidita: float = 0.0

_ETF_CATEGORIES = {"ETF Azionario", "ETF Obbligazionario", "ETF Bilanciato", "ETF Materie Prime", "ETF"}

def _fetch_ter_yf(ticker: str) -> float | None:
    try:
        info = yf.Ticker(ticker).info
        raw = info.get("annualReportExpenseRatio") or info.get("expenseRatio")
        return round(float(raw) * 100, 4) if raw else None
    except Exception:
        return None

@app.post("/api/portfolio/analyze")
def analyze_portfolio(req: PortfolioRequest, _: str = Depends(get_current_user)):
    total = sum(h.allocation for h in req.holdings) + req.liquidita
    if total == 0:
        raise HTTPException(400, "Portafoglio vuoto")

    # Aggregate geography weighted
    geo_agg: dict[str, float] = {}
    for h in req.holdings:
        geo = h.geography or {"Globale": 100}
        weight = h.allocation / total
        for region, pct in geo.items():
            geo_agg[region] = geo_agg.get(region, 0) + pct * weight
    geo_total = sum(geo_agg.values())
    if geo_total > 0:
        geo_agg = {k: round(v / geo_total * 100, 1) for k, v in geo_agg.items()}

    # By category
    cat_agg: dict[str, float] = {}
    for h in req.holdings:
        cat_agg[h.category] = cat_agg.get(h.category, 0) + h.allocation
    if req.liquidita > 0:
        cat_agg["Liquidità"] = cat_agg.get("Liquidità", 0) + req.liquidita
    cat_pct = {k: round(v / total * 100, 1) for k, v in cat_agg.items()}

    # Currency exposure (weighted by allocation, liquidità = EUR)
    cur_agg: dict[str, float] = {}
    for h in req.holdings:
        cur = (h.currency or "N/D").upper()
        cur_agg[cur] = cur_agg.get(cur, 0) + h.allocation
    if req.liquidita > 0:
        cur_agg["EUR"] = cur_agg.get("EUR", 0) + req.liquidita
    currency_exposure = {
        k: round(v / total * 100, 1)
        for k, v in sorted(cur_agg.items(), key=lambda x: -x[1])
        if k != "N/D"
    }

    # Heuristic metrics using ETF sub-types
    equity_pct = (
        cat_pct.get("Azioni", 0)
        + cat_pct.get("ETF Azionario", 0)
        + cat_pct.get("ETF", 0)
    ) / 100
    bond_pct = cat_pct.get("ETF Obbligazionario", 0) / 100
    crypto_pct = cat_pct.get("Criptovalute", 0) / 100
    cash_pct = cat_pct.get("Liquidità", 0) / 100

    expected_return_low = round(
        equity_pct * 7 + bond_pct * 3 + crypto_pct * 15 + cash_pct * 1.5, 1
    )
    expected_return_high = round(
        equity_pct * 11 + bond_pct * 5 + crypto_pct * 30 + cash_pct * 2, 1
    )
    volatility_low = round(max(1.0, equity_pct * 12 + bond_pct * 4 + crypto_pct * 35), 1)
    volatility_high = round(max(2.0, equity_pct * 20 + bond_pct * 8 + crypto_pct * 65), 1)
    sharpe_low = round(expected_return_low / max(volatility_high, 1), 2)
    sharpe_high = round(expected_return_high / max(volatility_low, 1), 2)

    risk_score = equity_pct + crypto_pct * 3 - bond_pct * 0.5
    if risk_score < 0.25:
        aggressiveness = "Conservativo"
    elif risk_score < 0.5:
        aggressiveness = "Moderato"
    elif risk_score < 0.75:
        aggressiveness = "Moderatamente Aggressivo"
    else:
        aggressiveness = "Aggressivo"

    etf_no_ter = [(h, h.yf_ticker or h.ticker) for h in req.holdings
                  if h.ter is None and h.category in _ETF_CATEGORIES and (h.yf_ticker or h.ticker)]
    if etf_no_ter:
        with ThreadPoolExecutor(max_workers=min(4, len(etf_no_ter))) as ex:
            futures = {ex.submit(_fetch_ter_yf, t): h for h, t in etf_no_ter}
            try:
                for fut in as_completed(futures, timeout=2.0):
                    val = fut.result()
                    if val:
                        futures[fut].ter = val
            except _FutTimeout:
                pass

    ter_holdings = [h for h in req.holdings if h.ter and h.ter > 0]
    if ter_holdings:
        ter_alloc = sum(h.allocation for h in ter_holdings)
        ter_medio = round(sum(h.ter * h.allocation for h in ter_holdings) / ter_alloc, 4) if ter_alloc else None
    else:
        ter_medio = None

    return {
        "total": total,
        "category_pct": cat_pct,
        "geography": geo_agg,
        "currency_exposure": currency_exposure,
        "metrics": {
            "expected_return": f"{expected_return_low}% – {expected_return_high}%",
            "volatility": f"{volatility_low}% – {volatility_high}%",
            "sharpe": f"{sharpe_low:.2f} – {sharpe_high:.2f}",
            "aggressiveness": aggressiveness,
            "ter_medio": ter_medio,
        }
    }


# ─── Document extraction via LLM ────────────────────────────────────────────


class ExtractedInstrument(BaseModel):
    isin: str = ""
    ticker: str = ""
    name: str = ""
    quantity: Optional[float] = None
    purchase_price: Optional[float] = None   # prezzo medio di acquisto per unità in EUR
    value: Optional[float] = None            # controvalore corrente in EUR
    purchase_date: Optional[str] = None      # data acquisto YYYY-MM-DD


class ExtractionResponse(BaseModel):
    items: List[ExtractedInstrument]


def _extract_pdf_text(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
    except Exception as e:
        return f"[Errore lettura PDF: {e}]"


@app.post("/api/extract-from-documents", response_model=ExtractionResponse)
async def extract_from_documents(
    files: List[UploadFile] = File(...),
    _: str = Depends(get_current_user),
):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY non configurata nel file .env")

    combined_text = ""
    for f in files:
        raw = await f.read()
        name = (f.filename or "").lower()
        if name.endswith(".pdf"):
            text = _extract_pdf_text(raw)
        else:
            text = raw.decode("utf-8", errors="ignore")
        combined_text += f"\n\n=== DOCUMENTO: {f.filename} ===\n{text}"

    if not combined_text.strip():
        raise HTTPException(400, "Impossibile estrarre testo dai documenti caricati")

    prompt = (
        "Analizza questi documenti bancari/finanziari ed estrai tutti gli strumenti finanziari "
        "(azioni, ETF, fondi, obbligazioni). "
        "Per ogni strumento restituisci un oggetto JSON con:\n"
        "- isin: codice ISIN (12 caratteri, es. IE00B3RBWM25) se presente, altrimenti stringa vuota\n"
        "- ticker: simbolo ticker (es. MSFT) se presente, altrimenti stringa vuota\n"
        "- name: nome completo dello strumento\n"
        "- quantity: numero di titoli/quote posseduti (numero con decimali, null se assente)\n"
        "- purchase_price: prezzo medio di acquisto per singola unità in EUR (numero, null se assente)\n"
        "- value: controvalore corrente in EUR (numero, null se assente)\n"
        "- purchase_date: data di acquisto nel formato YYYY-MM-DD (stringa, null se assente)\n\n"
        "Escludi: conti correnti, depositi bancari, liquidità/cash.\n"
        "Rispondi SOLO con JSON valido, nessun testo aggiuntivo:\n"
        '{"items": [{"isin": "...", "ticker": "...", "name": "...", "quantity": 10.5, '
        '"purchase_price": 45.20, "value": 3500.00, "purchase_date": "2023-04-15"}]}\n\n'
        f"DOCUMENTI:\n{combined_text[:18000]}"
    )

    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()
    start = raw_text.find("{")
    end = raw_text.rfind("}") + 1
    if start < 0 or end <= start:
        raise HTTPException(500, "La risposta AI non contiene JSON valido")
    try:
        parsed = json.loads(raw_text[start:end])
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"Errore parsing JSON: {e}")

    try:
        return ExtractionResponse(**parsed)
    except Exception as e:
        raise HTTPException(500, f"Risposta AI non valida: {e}")


# ─── Portfolio save / load (DynamoDB) ────────────────────────────────────────

class PortfolioSave(BaseModel):
    name: str = "Il mio portafoglio"
    holdings: list
    liquidita: float = 0.0
    inputMode: str = "pct"
    savedAt: Optional[str] = None


@app.post("/api/portfolio/save")
def save_portfolio(req: PortfolioSave, current_user: str = Depends(get_current_user)):
    data = req.model_dump()
    if not data.get("savedAt"):
        data["savedAt"] = datetime.now(timezone.utc).isoformat()
    pid = save_portfolio_dynamo(current_user, req.name, data)
    return {"status": "saved", "portfolio_id": pid, "savedAt": data["savedAt"]}


@app.get("/api/portfolio/list")
def list_portfolios_endpoint(current_user: str = Depends(get_current_user)):
    return list_portfolios_dynamo(current_user)


@app.get("/api/portfolio/load/{portfolio_id}")
def load_portfolio_endpoint(portfolio_id: str, current_user: str = Depends(get_current_user)):
    data = load_portfolio_dynamo(current_user, portfolio_id)
    if data is None:
        raise HTTPException(404, "Portafoglio non trovato")
    return data


@app.delete("/api/portfolio/saved/{portfolio_id}")
def delete_portfolio_endpoint(portfolio_id: str, current_user: str = Depends(get_current_user)):
    delete_portfolio_dynamo(current_user, portfolio_id)
    return {"status": "deleted"}


# ─── Portfolio performance ────────────────────────────────────────────────────

class PerformanceHolding(BaseModel):
    yf_ticker: str
    amount: float   # EUR value at purchase

class PerformanceRequest(BaseModel):
    holdings: List[PerformanceHolding]
    liquidita: float = 0.0


@app.post("/api/portfolio/performance")
def portfolio_performance(req: PerformanceRequest, _: str = Depends(get_current_user)):
    import pandas as pd

    series_list = []
    for h in req.holdings:
        if not h.amount or h.amount <= 0 or not h.yf_ticker:
            continue
        try:
            hist = yf.Ticker(h.yf_ticker).history(period="1y")["Close"]
            if hist.empty or len(hist) < 5:
                continue
            series_list.append(hist / hist.iloc[0] * h.amount)
        except Exception:
            continue

    if not series_list:
        return {"dates": [], "values": [], "return_pct": 0, "initial_value": 0, "current_value": 0}

    combined = pd.concat(series_list, axis=1).ffill().bfill().sum(axis=1) + req.liquidita
    initial  = float(combined.iloc[0])
    current  = float(combined.iloc[-1])
    return_pct = round((current / initial - 1) * 100, 2) if initial > 0 else 0

    return {
        "dates":         [str(d.date()) for d in combined.index],
        "values":        [round(float(v), 2) for v in combined.values],
        "return_pct":    return_pct,
        "initial_value": round(initial, 2),
        "current_value": round(current, 2),
    }
