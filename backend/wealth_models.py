"""Pydantic contracts for the assets outside the market portfolio (life insurance,
pension funds, real estate with mortgage, private investments) and for the
net-worth summary that adds them to the saved portfolios.

Only data classes live here: no I/O, no computation.
"""

from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator

ASSET_ID_PATTERN = r"^[0-9a-f]{32}$"


class AssetKind(StrEnum):
    LIFE_INSURANCE = "life_insurance"
    PENSION_FUND = "pension_fund"
    REAL_ESTATE = "real_estate"
    PRIVATE = "private"  # private equity / debt, club deals, crowdfunding, startups
    OTHER = "other"


class WealthCategory(StrEnum):
    """Net-worth bucket: the saved market portfolios plus every AssetKind."""

    PORTFOLIO = "portfolio"
    LIFE_INSURANCE = "life_insurance"
    PENSION_FUND = "pension_fund"
    REAL_ESTATE = "real_estate"
    PRIVATE = "private"
    OTHER = "other"


class InsuranceBranch(StrEnum):
    RAMO_I = "ramo_i"  # gestione separata, capital guaranteed
    RAMO_III = "ramo_iii"  # unit / index linked
    MULTIRAMO = "multiramo"
    TCM = "tcm"  # pure term life: protection only, no surrender value
    OTHER = "other"


class PensionProfile(StrEnum):
    CONSERVATIVE = "conservative"  # garantito / obbligazionario
    BALANCED = "balanced"
    DYNAMIC = "dynamic"  # azionario


# ─── Stored items ─────────────────────────────────────────────────────────────


class MortgageInput(StrEnum):
    PAYMENT_END = "payment_end"  # instalment + rate + last instalment date (what borrowers know)
    LOAN_TERMS = "loan_terms"  # amount + rate + duration + signing date (from the contract)


class Mortgage(BaseModel):
    """French (constant-instalment) amortisation, monthly payments, entered either way."""

    input_mode: MortgageInput = MortgageInput.LOAN_TERMS  # items saved before the option existed
    annual_rate_pct: float = Field(ge=0, le=30)
    principal: float | None = Field(None, gt=0)  # EUR borrowed; optional with PAYMENT_END (% repaid)
    years: int | None = Field(None, ge=1, le=40)
    start_date: date | None = None  # first instalment falls one month later
    end_date: date | None = None  # last instalment
    # PAYMENT_END: the instalment itself; LOAN_TERMS: optional cross-check against the bank's
    monthly_payment: float | None = Field(None, gt=0)
    balance_override: float | None = Field(None, ge=0)  # residual debt from the bank statement

    @model_validator(mode="after")
    def _required_for_mode(self) -> Self:
        need = (("monthly_payment", "end_date") if self.input_mode == MortgageInput.PAYMENT_END
                else ("principal", "years", "start_date"))
        missing = [f for f in need if getattr(self, f) is None]
        if missing:
            raise ValueError(f"missing for {self.input_mode.value}: {', '.join(missing)}")
        return self


class OtherAsset(BaseModel):
    """One asset entered by hand. Amounts are EUR and refer to the whole asset;
    `ownership_pct` scales both value and mortgage to the user's share."""

    asset_id: str | None = Field(None, pattern=ASSET_ID_PATTERN)  # assigned on first save
    kind: AssetKind
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field("", max_length=120)  # insurer, pension fund, bank, platform
    current_value: float = Field(0.0, ge=0)  # surrender value / accrued position / market value / NAV
    invested: float | None = Field(None, ge=0)  # paid in so far (premiums, contributions, cost)
    annual_contribution: float | None = Field(None, ge=0)  # yearly premium or contribution
    insurance_branch: InsuranceBranch | None = None
    pension_line: str = Field("", max_length=120)  # comparto
    # life insurance
    insured_capital: float | None = Field(None, ge=0)  # death benefit (TCM and mixed policies)
    maturity_date: date | None = None
    expected_return_pct: float | None = Field(None, ge=-5, le=15)  # None: default per branch
    ramo_i_share_pct: float | None = Field(None, ge=0, le=100)  # multiramo: part in gestione separata
    # pension fund
    pension_profile: PensionProfile | None = None
    birth_year: int | None = Field(None, ge=1930, le=2015)
    retirement_age: int = Field(67, ge=50, le=75)
    tax_pct: float | None = Field(None, ge=0, le=50)  # on the benefit at retirement
    ownership_pct: float = Field(100.0, gt=0, le=100)
    mortgage: Mortgage | None = None
    notes: str = Field("", max_length=500)
    updated_at: str | None = None


class SavedHolding(BaseModel):
    amount: float | None = None  # EUR, set in 'amount' mode


class SavedPortfolio(BaseModel):
    """The fields of a saved dashboard portfolio that determine its EUR value.

    In 'pct' mode `liquidita` is a percentage of `portfolioTotal`, in 'amount'
    mode it is EUR.
    """

    portfolio_id: str
    name: str = "Portafoglio"
    holdings: list[SavedHolding] = Field(default_factory=list)
    liquidita: float = 0.0
    inputMode: str = "pct"
    portfolioTotal: float = 0.0
    savedAt: str = ""


# ─── Net-worth summary ────────────────────────────────────────────────────────


class NetWorthRequest(BaseModel):
    """Input of `/api/wealth/summary`: which saved portfolios count as market assets."""

    portfolio_ids: list[str] = Field(default_factory=list, max_length=20)


class MortgageStatus(BaseModel):
    balance: float  # residual debt, user's share
    monthly_payment: float  # user's share
    months_paid: int | None  # None: signing date unknown (PAYMENT_END without amount)
    months_left: int
    end_date: date
    repaid_pct: float | None  # None: amount borrowed unknown
    from_statement: bool  # balance typed by the user instead of computed
    declared_payment: float | None = None  # user's share of the instalment typed from the bank
    payment_consistent: bool | None = None  # declared ≈ computed (None: nothing declared)
    implied_years: float | None = None  # duration implied by declared instalment + rate


class AssetValuation(BaseModel):
    asset_id: str
    kind: AssetKind
    name: str
    provider: str
    gross_value: float  # user's share
    liability: float
    net_value: float
    invested: float | None
    gain: float | None  # gross_value − invested
    mortgage: MortgageStatus | None = None


class PortfolioValuation(BaseModel):
    portfolio_id: str
    name: str
    value: float | None  # None: saved in % mode without a declared total
    saved_at: str


class CategoryTotal(BaseModel):
    category: WealthCategory
    gross: float
    liabilities: float
    net: float
    share_pct: float  # of total gross assets
    count: int


class NetWorthSummary(BaseModel):
    as_of: date
    total_assets: float
    total_liabilities: float
    net_worth: float
    liquid_assets: float  # market portfolios: sellable within days
    categories: list[CategoryTotal]
    assets: list[AssetValuation]
    portfolios: list[PortfolioValuation]
