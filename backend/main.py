from fastapi import FastAPI, HTTPException, Query, File, UploadFile, Depends, Response
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as _FutTimeout
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List
import yfinance as yf
import requests
import math
import re
import os
import io
import json
import base64
import secrets
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _load_aws_secrets() -> None:
    """Fetch ANTHROPIC_API_KEY and SECRET_KEY from Secrets Manager when running in AWS."""
    secret_arn = os.getenv("SECRETS_ARN")
    if not secret_arn:
        return
    import boto3
    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "eu-central-1"))
    data = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])
    for key, value in data.items():
        os.environ.setdefault(key, value)

_load_aws_secrets()

import anthropic
import bcrypt as _bcrypt_lib
from jose import jwt, JWTError
from backend.bonds import classify_bond, fetch_sovereign_risk
from backend.bond_market import BondQuote, fetch_bond_quote
from backend.analysis_models import DeepAnalysisRequest, DeepAnalysisResponse, LookThroughResponse
from backend.deep_analysis import run_deep_analysis
from backend.exceptions import InsufficientDataError
from backend.look_through import run_look_through
from backend.superinvestors import (
    ConsensusStock,
    Manager,
    ManagerPortfolio,
    StockOwnership,
    fetch_consensus,
    fetch_manager_portfolio,
    fetch_portfolio_overlap,
    list_managers,
)
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
# Sliding session: every authenticated call returns a fresh token in REFRESH_HEADER,
# so the session only expires after this many minutes of inactivity.
TOKEN_EXPIRE_MINUTES = 30
REFRESH_HEADER = "X-Refreshed-Token"

_http_bearer = HTTPBearer()

init_db()

app = FastAPI(title="Portfolio Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[REFRESH_HEADER],
)

frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path / "static")), name="static")

    @app.get("/")
    def root():
        return FileResponse(str(frontend_path / "index.html"))

    @app.get("/login")
    def login_page():
        return FileResponse(str(frontend_path / "login.html"))

    @app.get("/analisi")
    def analysis_page():
        return FileResponse(str(frontend_path / "analisi.html"))


# ─── Auth helpers ────────────────────────────────────────────────────────────

def _hash_pw(pw: str) -> str:
    return _bcrypt_lib.hashpw(pw.encode()[:72], _bcrypt_lib.gensalt(rounds=10)).decode()

def _verify_pw(plain: str, hashed: str) -> bool:
    return _bcrypt_lib.checkpw(plain.encode()[:72], hashed.encode())

def _create_token(username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": username, "exp": exp}, SECRET_KEY, algorithm="HS256")

def get_current_user(
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(_http_bearer),
) -> str:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(401, "Sessione scaduta, effettua di nuovo il login")
    username: str = payload.get("sub", "")
    if not username:
        raise HTTPException(401, "Token non valido")
    response.headers[REFRESH_HEADER] = _create_token(username)
    return username


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

def openfigi_items(isin: str) -> list[dict]:
    """Raw OpenFIGI v3 mapping rows for an ISIN ([] on failure).

    Shared by isin_to_ticker (equity/ETF resolution) and classify_bond so the
    network round-trip happens once per search."""
    try:
        url = "https://api.openfigi.com/v3/mapping"
        payload = [{"idType": "ID_ISIN", "idValue": isin}]
        resp = requests.post(url, json=payload, timeout=8,
                             headers={"Content-Type": "application/json"})
        if resp.status_code == 200:
            data = resp.json()
            if data and data[0].get("data"):
                return data[0]["data"]
    except Exception:
        pass
    return []


def isin_to_ticker(isin: str, items: Optional[list[dict]] = None) -> dict:
    """Resolve ISIN to ticker via OpenFIGI.
    For European ETF domiciles (IE/LU/GB/FR) prefers EUR-denominated exchanges."""
    try:
        if items is None:
            items = openfigi_items(isin)
        if items:
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
                "securityType2": best.get("securityType2", ""),
                "marketSector": best.get("marketSector", ""),
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


# ─── Geography → Underlying Currency mapping ─────────────────────────────────
# Approximate currency weights by geographic region (based on MSCI index compositions)
GEO_TO_CURRENCY: dict[str, dict[str, float]] = {
    "Nord America":      {"USD": 95, "CAD": 5},
    "Europa":            {"EUR": 55, "GBP": 22, "CHF": 9, "SEK": 5, "DKK": 3, "NOK": 3, "_altri": 3},
    "Asia-Pacifico":     {"JPY": 45, "AUD": 20, "HKD": 12, "KRW": 10, "SGD": 7, "NZD": 6},
    "Mercati Emergenti": {"CNY": 27, "TWD": 15, "INR": 13, "KRW": 12, "BRL": 6, "ZAR": 4, "SAR": 4, "MXN": 3, "USD": 5, "_altri": 11},
    "Globale":           {"USD": 62, "EUR": 12, "JPY": 6, "GBP": 4, "CHF": 3, "CAD": 3, "AUD": 2, "_altri": 8},
    "Italia":            {"EUR": 100},
    "Altre":             {"USD": 40, "EUR": 25, "CNY": 10, "JPY": 8, "GBP": 7, "_altri": 10},
}
# Categories where trading currency = underlying currency (no geo mapping needed)
_DIRECT_CURRENCY_CATEGORIES = {"Azioni", "Obbligazioni", "Criptovalute"}

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


# ─── Crypto ticker mapping (Yahoo Finance uses TICKER-EUR) ───────────────────
CRYPTO_YF_MAP = {
    "BTC": "BTC-EUR", "ETH": "ETH-EUR", "SOL": "SOL-EUR",
    "ADA": "ADA-EUR", "XRP": "XRP-EUR", "DOT": "DOT-EUR",
    "DOGE": "DOGE-EUR", "MATIC": "MATIC-EUR", "AVAX": "AVAX-EUR",
    "LINK": "LINK-EUR", "LTC": "LTC-EUR", "UNI": "UNI-EUR",
    "IMX": "IMX-EUR", "OP": "OP-EUR", "ARB": "ARB-EUR",
}

# ─── Search endpoint ─────────────────────────────────────────────────────────

def _bond_search_response(isin: str, figi_data: dict, bond) -> dict:
    """Build the /api/search payload for a single bond.

    Price and market data come from Borsa Italiana (MOT/ExtraMOT/EuroTLX), quoted
    in % of nominal; bonds not listed in Milan keep a manual price."""
    risk = (
        fetch_sovereign_risk(bond.issuer_country, bond.currency)
        if bond.bond_type == "Governativo" and bond.issuer_country
        else None
    )
    quote = fetch_bond_quote(isin)
    name = (quote.name if quote and quote.name else None) or figi_data.get("name") or isin
    currency = (quote.currency if quote and quote.currency else None) or bond.currency
    desc = (
        "Obbligazione: prezzo in % del valore nominale. Quantità = valore nominale."
        if quote and quote.price
        else "Obbligazione non quotata su Borsa Italiana: inserisci valore nominale "
             "e prezzo (% del nominale) manualmente (o estrai cedola/scadenza dal PDF)."
    )
    return {
        "isin": isin,
        "ticker": figi_data.get("ticker") or isin,
        "yf_ticker": "",
        "name": name,
        "category": "Obbligazioni",
        "quoteType": "BOND",
        "price": quote.price if quote else None,
        "price_unit": "pct_of_par",
        "currency": currency,
        "sector": "", "industry": "", "fundFamily": "",
        "description": desc,
        "geography": bond.geography,
        "composition": [],
        "exch": quote.market if quote else figi_data.get("exchCode", ""),
        "isin_mismatch": False,
        "ter": None,
        # Bond-specific
        "bond_type": bond.bond_type,
        "issuer_country": bond.issuer_country,
        "sovereign_risk": risk.model_dump() if risk else None,
        "market_data": quote.model_dump() if quote else None,
    }


@app.get("/api/bond/quote/{isin}", response_model=BondQuote)
def bond_quote(isin: str, _: str = Depends(get_current_user)) -> BondQuote:
    """Live market data for a bond listed on Borsa Italiana (MOT/ExtraMOT/EuroTLX)."""
    isin = isin.strip().upper()
    if not re.match(r"^[A-Z]{2}[A-Z0-9]{10}$", isin):
        raise HTTPException(400, "ISIN non valido")
    quote = fetch_bond_quote(isin)
    if quote is None:
        raise HTTPException(404, f"Obbligazione {isin} non trovata su Borsa Italiana")
    return quote


@app.get("/api/search")
def search_asset(
    q: str = Query(..., description="ISIN or Ticker"),
    _: str = Depends(get_current_user),
):
    q = q.strip().upper()
    if q in CRYPTO_YF_MAP:
        q = CRYPTO_YF_MAP[q]

    figi_data = {}
    yf_ticker_str = q

    is_isin = bool(re.match(r"^[A-Z]{2}[A-Z0-9]{10}$", q))
    if is_isin:
        items = openfigi_items(q)
        if not items:
            raise HTTPException(404, f"ISIN {q} non trovato su OpenFIGI")
        figi_data = isin_to_ticker(q, items=items)

        bond = classify_bond(items, q)
        if bond.is_bond:
            return _bond_search_response(q, figi_data, bond)

        yf_ticker_str = build_yf_ticker(figi_data.get("ticker", q), figi_data.get("exchCode", ""))

    ticker_obj = yf.Ticker(yf_ticker_str)
    info = ticker_obj.info or {}

    if not info or info.get("quoteType") is None:
        ticker_obj = yf.Ticker(figi_data.get("ticker", q))
        info = ticker_obj.info or {}

    if not info:
        if figi_data:
            name = figi_data.get("name") or q
            sec_type = figi_data.get("securityType", "")
            sec_lower = sec_type.lower()
            bond_sec_kw = ["bond", "government", "treasury", "note", "bill", "gilt", "btp", "obbligaz"]
            isin_prefix = q[:2] if is_isin else ""
            if any(k in sec_lower for k in bond_sec_kw) or isin_prefix == "IT":
                category = "Obbligazioni"
                geo = {"Europa": 100} if isin_prefix in {"IT", "DE", "FR", "ES", "PT", "BE", "AT", "NL"} else {"Globale": 100}
                currency = "EUR"
            else:
                category = guess_category_from_name(name, sec_type)
                geo = {"Globale": 100}
                currency = ""
            return {
                "isin": q if is_isin else "",
                "ticker": figi_data.get("ticker") or q,
                "yf_ticker": "",
                "name": name,
                "category": category,
                "quoteType": "BOND",
                "price": None,
                "currency": currency,
                "sector": "", "industry": "", "fundFamily": "",
                "description": "Strumento non disponibile su Yahoo Finance. Inserisci il valore manualmente.",
                "geography": geo,
                "composition": [],
                "exch": figi_data.get("exchCode", ""),
                "isin_mismatch": False,
                "ter": None,
            }
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

    ter = _ter_from_info(info)
    if ter is None:
        try:
            ter = _ter_from_funds_data(ticker_obj.funds_data)
        except Exception:
            ter = None
    if ter is None and is_isin:
        ter = _fetch_ter_justetf(q)

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

_TER_MAX_PCT = 5.0  # no real ETF/fund costs more than this: anything above is a unit error


def valid_ter(ter: float | None) -> float | None:
    """TER in percent if plausible (0 < TER <= 5), else None."""
    if ter is None:
        return None
    try:
        val = float(ter)
    except (TypeError, ValueError):
        return None
    return round(val, 4) if math.isfinite(val) and 0 < val <= _TER_MAX_PCT else None


def _ter_from_info(info: dict) -> float | None:
    """TER (%) from ``yf.Ticker.info``.

    Yahoo uses different units per field: ``netExpenseRatio`` is already a
    percentage (0.2 = 0.20 %), while the legacy ``annualReportExpenseRatio`` /
    ``expenseRatio`` / ``totalExpenseRatio`` are fractions (0.002 = 0.20 %).
    Guessing the unit from the magnitude turned 0.2 % into 20 %.
    """
    net = info.get("netExpenseRatio")
    if net:
        return valid_ter(net)
    raw = (info.get("annualReportExpenseRatio")
           or info.get("expenseRatio")
           or info.get("totalExpenseRatio"))
    return valid_ter(float(raw) * 100) if raw else None


def _ter_from_funds_data(fd) -> float | None:
    """TER (%) from ``yf.Ticker.funds_data``: both sources are fractions (0.002 = 0.20 %)."""
    try:
        raw = fd.fund_operations.iloc[:, 0].get("Annual Report Expense Ratio")
        ter = valid_ter(float(raw) * 100) if raw is not None else None
        if ter is not None:
            return ter
    except Exception:
        pass
    try:
        fo = getattr(fd, "fund_overview", None) or {}
        if isinstance(fo, dict):
            raw = fo.get("expenseRatio") or fo.get("annualReportExpenseRatio")
            return valid_ter(float(raw) * 100) if raw else None
    except Exception:
        pass
    return None


def _fetch_ter_yf(ticker: str) -> float | None:
    try:
        t = yf.Ticker(ticker)
        return _ter_from_info(t.info or {}) or _ter_from_funds_data(t.funds_data)
    except Exception:
        return None


def _fetch_ter_justetf(isin: str) -> float | None:
    """Scrape TER from justETF profile page — covers UCITS ETFs missing from Yahoo Finance."""
    if not isin or len(isin) != 12:
        return None
    try:
        url = f"https://www.justetf.com/en/etf-profile.html?isin={isin}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        text = resp.text
        # justETF shows TER near "Total expense ratio" label; decimal can be "." or ","
        # NOTE: the generic "% p.a." pattern was removed — it matches performance figures too.
        patterns = [
            r'Total expense ratio[^%\d]{0,80}?(\d+[.,]\d+)\s*%',
            r'ter["\s:]+(\d+[.,]\d+)',     # JSON-LD / data attribute
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                val = float(m.group(1).replace(',', '.'))
                if 0 < val < 5:            # sanity: TER between 0 % and 5 %
                    return round(val, 4)
    except Exception:
        pass
    return None


def _fetch_ter_full(ticker: str, isin: str = "") -> float | None:
    """Try Yahoo Finance first, then justETF as fallback."""
    ter = _fetch_ter_yf(ticker)
    if ter is None and isin:
        ter = _fetch_ter_justetf(isin)
    return ter

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

    # Underlying currency exposure: maps geography → real currency weights for ETFs;
    # for individual stocks/bonds uses the trading currency directly.
    undl_agg: dict[str, float] = {}
    for h in req.holdings:
        geo = h.geography or {}
        if h.category in _DIRECT_CURRENCY_CATEGORIES or not geo:
            cur = (h.currency or "N/D").upper()
            if cur != "N/D":
                undl_agg[cur] = undl_agg.get(cur, 0) + h.allocation
        else:
            geo_total = sum(geo.values()) or 1
            for region, region_pct in geo.items():
                region_alloc = (region_pct / geo_total) * h.allocation
                cur_map = GEO_TO_CURRENCY.get(region, {"USD": 50, "EUR": 30, "_altri": 20})
                cur_total = sum(v for v in cur_map.values()) or 1
                for cur, cur_pct in cur_map.items():
                    if cur != "_altri":
                        undl_agg[cur] = undl_agg.get(cur, 0) + (cur_pct / cur_total) * region_alloc
    if req.liquidita > 0:
        undl_agg["EUR"] = undl_agg.get("EUR", 0) + req.liquidita
    underlying_currency_exposure = {
        k: round(v / total * 100, 1)
        for k, v in sorted(undl_agg.items(), key=lambda x: -x[1])
        if v / total * 100 >= 0.5
    }

    # Heuristic metrics using ETF sub-types
    equity_pct = (
        cat_pct.get("Azioni", 0)
        + cat_pct.get("ETF Azionario", 0)
        + cat_pct.get("ETF", 0)
    ) / 100
    bond_pct = (cat_pct.get("ETF Obbligazionario", 0) + cat_pct.get("Obbligazioni", 0)) / 100
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

    # Saved portfolios may carry TERs from an older ×100 unit bug (e.g. 20.0 for 0.20 %):
    # drop anything implausible and fetch it again.
    for h in req.holdings:
        h.ter = valid_ter(h.ter)
    etf_no_ter = [
        (h, h.yf_ticker or h.ticker, h.isin or "")
        for h in req.holdings
        if h.ter is None and h.category in _ETF_CATEGORIES and (h.yf_ticker or h.ticker)
    ]
    if etf_no_ter:
        with ThreadPoolExecutor(max_workers=min(4, len(etf_no_ter))) as ex:
            futures = {ex.submit(_fetch_ter_full, t, isin): h for h, t, isin in etf_no_ter}
            try:
                for fut in as_completed(futures, timeout=12.0):
                    val = fut.result()
                    if val:
                        futures[fut].ter = val
            except _FutTimeout:
                pass

    ter_holdings = [h for h in req.holdings if h.ter and 0 < h.ter <= 5]
    if ter_holdings:
        ter_alloc = sum(h.allocation for h in ter_holdings)
        ter_medio = round(sum(h.ter * h.allocation for h in ter_holdings) / ter_alloc, 4) if ter_alloc else None
    else:
        ter_medio = None

    ter_map = {h.ticker: h.ter for h in req.holdings if h.ter and 0 < h.ter <= 5}

    return {
        "total": total,
        "category_pct": cat_pct,
        "geography": geo_agg,
        "currency_exposure": currency_exposure,
        "underlying_currency_exposure": underlying_currency_exposure,
        "ter_map": ter_map,
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
    coupon: Optional[float] = None           # cedola annua % (solo obbligazioni)
    maturity: Optional[str] = None           # data scadenza YYYY-MM-DD (solo obbligazioni)


class ExtractionResponse(BaseModel):
    items: List[ExtractedInstrument]


@app.post("/api/extract-from-documents", response_model=ExtractionResponse)
async def extract_from_documents(
    files: List[UploadFile] = File(...),
    _: str = Depends(get_current_user),
):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY non configurata nel file .env")

    content_blocks: list = []
    for f in files:
        raw = await f.read()
        if not raw:
            continue
        name = (f.filename or "").lower()
        if name.endswith(".pdf"):
            content_blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(raw).decode(),
                },
                "title": f.filename,
            })
        else:
            text = raw.decode("utf-8", errors="ignore")
            content_blocks.append({
                "type": "text",
                "text": f"\n=== DOCUMENTO: {f.filename} ===\n{text[:16000]}",
            })

    if not content_blocks:
        raise HTTPException(400, "Impossibile estrarre contenuto dai documenti caricati")

    content_blocks.append({
        "type": "text",
        "text": (
            "Analizza questi documenti bancari/finanziari ed estrai tutti gli strumenti finanziari "
            "(azioni, ETF, fondi, obbligazioni, criptovalute). "
            "Per ogni strumento restituisci un oggetto JSON con:\n"
            "- isin: codice ISIN (12 caratteri, es. IE00B3RBWM25) se presente, altrimenti stringa vuota\n"
            "- ticker: simbolo ticker o codice cripto (es. BTC, ETH, MSFT) se presente, altrimenti stringa vuota\n"
            "- name: nome completo dello strumento\n"
            "- quantity: numero di titoli/quote/unità posseduti (numero con decimali, null se assente)\n"
            "- purchase_price: prezzo medio di acquisto per singola unità in EUR "
            "(null se il documento mostra solo il prezzo corrente e non quello di acquisto)\n"
            "- value: controvalore corrente in EUR (numero, null se assente)\n"
            "- purchase_date: data di acquisto nel formato YYYY-MM-DD (null se assente)\n"
            "- coupon: SOLO per obbligazioni, cedola annua in % (numero, es. 3.25; null altrimenti)\n"
            "- maturity: SOLO per obbligazioni, data di scadenza YYYY-MM-DD (null altrimenti)\n\n"
            "Includi le criptovalute (Bitcoin, Ethereum, ecc.).\n"
            "Per le obbligazioni (BTP, Bund, Treasury, corporate) compila coupon e maturity se presenti.\n"
            "Escludi: conti correnti, depositi bancari, liquidità/cash.\n"
            "Rispondi SOLO con JSON valido, nessun testo aggiuntivo:\n"
            '{"items": [{"isin": "IE00B3RBWM25", "ticker": "", "name": "iShares Core MSCI World", '
            '"quantity": 10.5, "purchase_price": null, "value": 3500.00, "purchase_date": null, '
            '"coupon": null, "maturity": null}]}'
        ),
    })

    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": content_blocks}],
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
    pac_entries: list = []
    savedAt: Optional[str] = None


class PLRequest(BaseModel):
    holdings: list  # {yf_ticker, ticker, name, quantity, purchase_price, currency}


@app.post("/api/portfolio/pl")
def get_portfolio_pl(req: PLRequest, _: str = Depends(get_current_user)):
    results = []
    to_fetch = [(h, h.get("yf_ticker") or h.get("ticker") or h.get("isin")) for h in req.holdings
                if h.get("quantity") and (h.get("yf_ticker") or h.get("ticker") or h.get("isin"))]

    def _fetch(h, yf_t):
        try:
            # Bonds: quantity is the nominal, price is % of nominal (Borsa Italiana).
            is_bond = h.get("category") == "Obbligazioni" and h.get("isin")
            if is_bond:
                quote = fetch_bond_quote(h["isin"])
                price = quote.price if quote else None
            else:
                price = getattr(yf.Ticker(yf_t).fast_info, "last_price", None)
            if price is None:
                return None
            qty = float(h["quantity"])
            buy = float(h["purchase_price"]) if h.get("purchase_price") else None
            unit = 0.01 if is_bond else 1.0
            cur_val = round(qty * price * unit, 2)
            cost = round(qty * buy * unit, 2) if buy else None
            pl_eur = round(cur_val - cost, 2) if cost is not None else None
            pl_pct = round(pl_eur / cost * 100, 2) if cost else None
            return {
                "ticker": h.get("ticker", yf_t),
                "name": h.get("name", ""),
                "quantity": qty,
                "purchase_price": round(buy, 4) if buy else None,
                "current_price": round(price, 4),
                "current_value": cur_val,
                "cost_basis": cost,
                "pl_eur": pl_eur,
                "pl_pct": pl_pct,
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(8, len(to_fetch) or 1)) as ex:
        futures = {ex.submit(_fetch, h, yf_t): (h, yf_t) for h, yf_t in to_fetch}
        try:
            for fut in as_completed(futures, timeout=10.0):
                r = fut.result()
                if r:
                    results.append(r)
        except _FutTimeout:
            pass

    total_value = sum(r["current_value"] for r in results)
    total_cost = sum(r["cost_basis"] for r in results if r.get("cost_basis") is not None)
    total_pl = round(total_value - total_cost, 2) if total_cost else None
    total_pl_pct = round(total_pl / total_cost * 100, 2) if total_cost else None

    return {
        "holdings": results,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2) if total_cost else None,
        "total_pl_eur": total_pl,
        "total_pl_pct": total_pl_pct,
    }


# ─── Superinvestors (Dataroma, 13F) ──────────────────────────────────────────

class OverlapRequest(BaseModel):
    symbols: List[str]


@app.get("/api/superinvestors", response_model=List[Manager])
def superinvestors_list(_: str = Depends(get_current_user)) -> List[Manager]:
    managers = list_managers()
    if not managers:
        raise HTTPException(502, "Dataroma non raggiungibile")
    return managers


@app.get("/api/superinvestors/consensus", response_model=List[ConsensusStock])
def superinvestors_consensus(
    limit: int = Query(50, ge=1, le=100),
    _: str = Depends(get_current_user),
) -> List[ConsensusStock]:
    stocks = fetch_consensus(limit)
    if not stocks:
        raise HTTPException(502, "Dataroma non raggiungibile")
    return stocks


@app.post("/api/superinvestors/overlap", response_model=List[StockOwnership])
def superinvestors_overlap(
    req: OverlapRequest, _: str = Depends(get_current_user),
) -> List[StockOwnership]:
    """Which superinvestors own the stocks in the user's portfolio."""
    return fetch_portfolio_overlap(req.symbols[:40])


@app.get("/api/superinvestors/{code}", response_model=ManagerPortfolio)
def superinvestor_portfolio(code: str, _: str = Depends(get_current_user)) -> ManagerPortfolio:
    if not re.match(r"^[A-Za-z0-9.]{1,12}$", code):
        raise HTTPException(400, "Codice gestore non valido")
    portfolio = fetch_manager_portfolio(code)
    if portfolio is None:
        raise HTTPException(404, f"Gestore {code} non trovato su Dataroma")
    return portfolio


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
    covered_amount = 0.0
    failed_tickers: list[str] = []
    total_submitted = sum(h.amount for h in req.holdings if h.amount and h.amount > 0)

    for h in req.holdings:
        if not h.amount or h.amount <= 0 or not h.yf_ticker:
            continue
        try:
            hist = yf.Ticker(h.yf_ticker).history(period="1y")["Close"]
            if hist.empty or len(hist) < 5:
                failed_tickers.append(h.yf_ticker)
                continue
            series_list.append(hist / hist.iloc[-1] * h.amount)
            covered_amount += h.amount
        except Exception:
            failed_tickers.append(h.yf_ticker)
            continue

    covered_pct = round(covered_amount / total_submitted * 100, 1) if total_submitted > 0 else 100.0

    if not series_list:
        return {"dates": [], "values": [], "return_pct": 0, "initial_value": 0, "current_value": 0,
                "covered_pct": covered_pct, "failed_tickers": failed_tickers}

    combined = pd.concat(series_list, axis=1).ffill().bfill().sum(axis=1) + req.liquidita
    initial  = float(combined.iloc[0])
    current  = float(combined.iloc[-1])
    return_pct = round((current / initial - 1) * 100, 2) if initial > 0 else 0

    return {
        "dates":          [str(d.date()) for d in combined.index],
        "values":         [round(float(v), 2) for v in combined.values],
        "return_pct":     return_pct,
        "initial_value":  round(initial, 2),
        "current_value":  round(current, 2),
        "covered_pct":    covered_pct,
        "failed_tickers": failed_tickers,
    }


# ─── Deep analysis (page /analisi) ────────────────────────────────────────────

@app.post("/api/analysis/deep", response_model=DeepAnalysisResponse)
def deep_analysis(req: DeepAnalysisRequest, _: str = Depends(get_current_user)) -> DeepAnalysisResponse:
    """Since-purchase performance, attribution, risk, frontier, Monte Carlo."""
    if not req.holdings:
        raise HTTPException(400, "Portafoglio vuoto")
    try:
        return run_deep_analysis(req)
    except InsufficientDataError as e:
        raise HTTPException(422, str(e))


@app.post("/api/analysis/look-through", response_model=LookThroughResponse)
def look_through(req: DeepAnalysisRequest, _: str = Depends(get_current_user)) -> LookThroughResponse:
    """X-Ray: asset classes, sectors, underlying positions, overlap, bonds, costs."""
    if not req.holdings:
        raise HTTPException(400, "Portafoglio vuoto")
    return run_look_through(req)


# AWS Lambda entry point via Mangum ASGI adapter
from mangum import Mangum
handler = Mangum(app, lifespan="off")
