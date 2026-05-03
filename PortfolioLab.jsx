import { useState, useRef, useCallback } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid } from "recharts";

// ── Config ─────────────────────────────────────────────────────────────────
const API_BASE = "http://localhost:8000"; // ← punta al tuo FastAPI

// ── Demo data (quando backend non disponibile) ────────────────────────────
const DEMO_DB = {
  "IE00B3RBWM25": { isin: "IE00B3RBWM25", ticker: "SWRD", name: "iShares Core MSCI World UCITS ETF", category: "ETF", price: 98.42, currency: "USD", ter: 0.2, fund_size: 12400000000, source: "justetf", countries: [{ name: "Nord America", weight: 68 }, { name: "Europa", weight: 20 }, { name: "Asia-Pacifico", weight: 9 }, { name: "Altre", weight: 3 }], sectors: [{ name: "Technology", weight: 23 }, { name: "Financial", weight: 15 }, { name: "Healthcare", weight: 12 }, { name: "Consumer", weight: 11 }, { name: "Industrials", weight: 10 }], top_holdings: [{ name: "Apple Inc", weight: 4.8 }, { name: "Microsoft", weight: 4.2 }, { name: "NVIDIA", weight: 3.9 }, { name: "Amazon", weight: 2.8 }, { name: "Meta", weight: 2.1 }], returns: { ytd: 0.072, "1y": 0.18, "3y": 0.31 } },
  "IE00BKM4GZ66": { isin: "IE00BKM4GZ66", ticker: "EIMI", name: "iShares Core MSCI EM IMI UCITS ETF", category: "ETF", price: 31.20, currency: "USD", ter: 0.18, source: "justetf", countries: [{ name: "Asia-Pacifico", weight: 55 }, { name: "Latam", weight: 18 }, { name: "Europa Emergente", weight: 12 }, { name: "Africa/ME", weight: 15 }], sectors: [{ name: "Technology", weight: 20 }, { name: "Financial", weight: 22 }, { name: "Consumer", weight: 14 }], top_holdings: [{ name: "Samsung Electronics", weight: 3.1 }, { name: "Taiwan Semiconductor", weight: 5.8 }, { name: "Tencent", weight: 3.9 }], returns: { ytd: 0.04, "1y": 0.09 } },
  "MSFT": { isin: "", ticker: "MSFT", name: "Microsoft Corporation", category: "Azioni", price: 415.32, currency: "USD", sector: "Technology", industry: "Software", country: "United States", marketCap: 3090000000000, source: "yfinance", countries: [{ name: "Nord America", weight: 100 }], sectors: [{ name: "Technology", weight: 100 }], top_holdings: [] },
  "AAPL": { isin: "", ticker: "AAPL", name: "Apple Inc.", category: "Azioni", price: 211.18, currency: "USD", sector: "Technology", country: "United States", marketCap: 3200000000000, source: "yfinance", countries: [{ name: "Nord America", weight: 100 }], sectors: [{ name: "Technology", weight: 100 }], top_holdings: [] },
  "NVDA": { isin: "", ticker: "NVDA", name: "NVIDIA Corporation", category: "Azioni", price: 875.40, currency: "USD", sector: "Technology", country: "United States", source: "yfinance", countries: [{ name: "Nord America", weight: 100 }], sectors: [{ name: "Technology", weight: 100 }], top_holdings: [] },
  "NVO": { isin: "", ticker: "NVO", name: "Novo Nordisk A/S", category: "Azioni", price: 112.80, currency: "USD", sector: "Healthcare", country: "Denmark", source: "yfinance", countries: [{ name: "Europa", weight: 100 }], sectors: [{ name: "Healthcare", weight: 100 }], top_holdings: [] },
  "ETH-USD": { isin: "", ticker: "ETH-USD", name: "Ethereum", category: "Criptovalute", price: 3420.50, currency: "USD", source: "yfinance", countries: [{ name: "Globale", weight: 100 }], sectors: [], top_holdings: [] },
  "BTC-USD": { isin: "", ticker: "BTC-USD", name: "Bitcoin", category: "Criptovalute", price: 68200.0, currency: "USD", source: "yfinance", countries: [{ name: "Globale", weight: 100 }], sectors: [], top_holdings: [] },
};

// ── Palette ───────────────────────────────────────────────────────────────
const C = {
  ETF: "#7c6ff7", Azioni: "#3b9eff", Criptovalute: "#00e5a0", "Liquidità": "#ffb020",
  geo: { "Nord America": "#3b9eff", "Europa": "#7c6ff7", "Asia-Pacifico": "#00e5a0", "Latam": "#ffb020", "Europa Emergente": "#c084fc", "Africa/ME": "#f87171", "Globale": "#6366f1", "Altre": "#64748b" },
  sector: ["#7c6ff7","#3b9eff","#00e5a0","#ffb020","#f87171","#c084fc","#f472b6","#34d399","#60a5fa","#a78bfa"],
};

const fmt = {
  price: (p, cur) => p != null ? `${cur || ""} ${p.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "",
  billions: (n) => { if (!n) return null; if (n >= 1e9) return `€${(n / 1e9).toFixed(1)}B`; if (n >= 1e6) return `€${(n / 1e6).toFixed(0)}M`; return null; },
  pct: (v) => v != null ? `${(v * 100).toFixed(1)}%` : null,
};

// ── Mini components ───────────────────────────────────────────────────────
const Tag = ({ children, color }) => (
  <span style={{ background: color + "20", color, border: `1px solid ${color}40`, borderRadius: 6, padding: "2px 8px", fontSize: 11, fontFamily: "monospace", fontWeight: 700 }}>{children}</span>
);

const Pill = ({ label, val }) => val ? (
  <div style={{ background: "#ffffff08", border: "1px solid #ffffff12", borderRadius: 6, padding: "4px 10px", fontSize: 12 }}>
    <span style={{ color: "#64748b", marginRight: 4 }}>{label}</span>
    <span style={{ fontWeight: 600 }}>{val}</span>
  </div>
) : null;

const Bar2 = ({ value, max, color, h = 6 }) => (
  <div style={{ flex: 1, background: "#ffffff10", borderRadius: 3, height: h, overflow: "hidden" }}>
    <div style={{ width: `${Math.min((value / Math.max(max, 1)) * 100, 100)}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.6s ease" }} />
  </div>
);

const Spinner = () => (
  <div style={{ width: 18, height: 18, border: "2px solid #ffffff20", borderTopColor: "#7c6ff7", borderRadius: "50%", animation: "spin 0.7s linear infinite", flexShrink: 0 }} />
);

// ── Search Result Card ────────────────────────────────────────────────────
function ResultCard({ data, onAdd }) {
  const [alloc, setAlloc] = useState("10");
  const color = C[data.category] || "#888";
  const isJustETF = data.source === "justetf";

  return (
    <div style={{ background: "linear-gradient(135deg, #0f1629, #141c35)", border: `1px solid ${color}50`, borderRadius: 14, padding: 20, animation: "slideDown 0.3s ease" }}>
      {/* Header */}
      <div style={{ display: "flex", gap: 14, alignItems: "flex-start", marginBottom: 16 }}>
        <div style={{ width: 52, height: 52, borderRadius: 12, background: color + "20", border: `1.5px solid ${color}50`, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "monospace", fontSize: 10, fontWeight: 800, color, flexShrink: 0 }}>
          {data.ticker.slice(0, 5)}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 4, lineHeight: 1.2 }}>{data.name}</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontFamily: "monospace", fontSize: 12, color: "#818cf8" }}>{data.ticker}</span>
            <Tag color={color}>{data.category}</Tag>
            {isJustETF && <Tag color="#ffb020">JustETF ✓</Tag>}
            {data.source === "yfinance" && <Tag color="#3b9eff">Yahoo Finance</Tag>}
          </div>
        </div>
        {data.price != null && (
          <div style={{ textAlign: "right" }}>
            <div style={{ fontFamily: "monospace", fontWeight: 800, fontSize: 18 }}>{fmt.price(data.price, data.currency)}</div>
          </div>
        )}
      </div>

      {/* Meta pills */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
        {data.ter != null && <Pill label="TER" val={data.ter + "%"} />}
        {data.fund_size && <Pill label="AUM" val={fmt.billions(data.fund_size)} />}
        {data.replication && <Pill label="Replica" val={data.replication} />}
        {data.distribution && <Pill label="Distribuzione" val={data.distribution} />}
        {data.domicile && <Pill label="Domicilio" val={data.domicile} />}
        {data.sector && <Pill label="Settore" val={data.sector} />}
        {data.country && <Pill label="Paese" val={data.country} />}
        {data.marketCap && <Pill label="Cap" val={fmt.billions(data.marketCap)} />}
        {data.benchmark && <Pill label="Indice" val={data.benchmark} />}
      </div>

      {/* Returns */}
      {data.returns && Object.values(data.returns).some(Boolean) && (
        <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
          {[["YTD", data.returns.ytd], ["1A", data.returns["1y"]], ["3A", data.returns["3y"]], ["5A", data.returns["5y"]]].filter(([, v]) => v != null).map(([l, v]) => (
            <div key={l} style={{ background: "#ffffff08", borderRadius: 8, padding: "6px 12px", textAlign: "center" }}>
              <div style={{ fontSize: 10, color: "#64748b", fontFamily: "monospace" }}>{l}</div>
              <div style={{ fontFamily: "monospace", fontWeight: 700, fontSize: 13, color: v >= 0 ? "#00e5a0" : "#f87171" }}>{v > 0 ? "+" : ""}{fmt.pct(v)}</div>
            </div>
          ))}
        </div>
      )}

      {/* 3-col info */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginBottom: 16 }}>
        {data.top_holdings?.length > 0 && (
          <MiniInfoBox title="Top Holdings" color={color} items={data.top_holdings.slice(0, 6).map(h => ({ l: h.name, v: h.weight + "%" }))} />
        )}
        {data.countries?.length > 0 && (
          <MiniInfoBox title="Paesi" color="#3b9eff" items={data.countries.slice(0, 5).map(c => ({ l: c.name, v: c.weight + "%" }))} />
        )}
        {data.sectors?.length > 0 && (
          <MiniInfoBox title="Settori" color="#00e5a0" items={data.sectors.slice(0, 5).map(s => ({ l: s.name, v: s.weight + "%" }))} />
        )}
      </div>

      {/* Add row */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", borderTop: "1px solid #ffffff10", paddingTop: 14 }}>
        <span style={{ color: "#64748b", fontSize: 13 }}>Allocazione</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6, background: "#ffffff08", border: "1.5px solid #ffffff15", borderRadius: 8, padding: "6px 10px" }}>
          <input
            type="number" min="0.1" max="100" step="0.1" value={alloc}
            onChange={e => setAlloc(e.target.value)}
            style={{ width: 52, background: "none", border: "none", color: "white", fontFamily: "monospace", fontSize: 15, fontWeight: 700, outline: "none", textAlign: "center" }}
          />
          <span style={{ color: "#64748b", fontFamily: "monospace" }}>%</span>
        </div>
        <button
          onClick={() => onAdd({ ...data, allocation: parseFloat(alloc) || 10 })}
          style={{ marginLeft: "auto", background: color, border: "none", borderRadius: 8, padding: "9px 20px", color: "white", fontWeight: 700, cursor: "pointer", fontSize: 14, transition: "opacity .2s" }}
          onMouseEnter={e => e.currentTarget.style.opacity = "0.85"}
          onMouseLeave={e => e.currentTarget.style.opacity = "1"}
        >
          + Aggiungi al portafoglio
        </button>
      </div>
    </div>
  );
}

function MiniInfoBox({ title, color, items }) {
  return (
    <div style={{ background: "#ffffff06", borderRadius: 8, padding: "10px 12px", border: "1px solid #ffffff0e" }}>
      <div style={{ fontSize: 10, fontFamily: "monospace", color: "#64748b", letterSpacing: 1, marginBottom: 8, textTransform: "uppercase" }}>{title}</div>
      {items.map((item, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: color, flexShrink: 0 }} />
          <span style={{ flex: 1, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#cbd5e1" }}>{item.l}</span>
          <span style={{ fontFamily: "monospace", fontSize: 11, color: "#64748b" }}>{item.v}</span>
        </div>
      ))}
    </div>
  );
}

// ── Live Dashboard ────────────────────────────────────────────────────────
function LiveDashboard({ portfolio, liquidita }) {
  const total = portfolio.reduce((s, h) => s + h.allocation, 0) + parseFloat(liquidita || 0);
  if (total === 0) return null;

  // Category breakdown
  const catMap = {};
  portfolio.forEach(h => { catMap[h.category] = (catMap[h.category] || 0) + h.allocation; });
  if (parseFloat(liquidita) > 0) catMap["Liquidità"] = (catMap["Liquidità"] || 0) + parseFloat(liquidita);
  const catPct = Object.entries(catMap).map(([name, v]) => ({ name, value: parseFloat((v / total * 100).toFixed(1)) }));

  // Geo weighted
  const geoMap = {};
  portfolio.forEach(h => {
    const w = h.allocation / total;
    (h.countries || []).forEach(c => { geoMap[c.name] = (geoMap[c.name] || 0) + c.weight * w; });
  });
  const geoData = Object.entries(geoMap).map(([name, v]) => ({ name, value: parseFloat(v.toFixed(1)) })).sort((a, b) => b.value - a.value).filter(d => d.value > 0);

  // Sector weighted
  const secMap = {};
  portfolio.forEach(h => {
    const w = h.allocation / total;
    (h.sectors || []).forEach(s => { secMap[s.name] = (secMap[s.name] || 0) + s.weight * w; });
  });
  const secData = Object.entries(secMap).map(([name, v]) => ({ name, value: parseFloat(v.toFixed(1)) })).sort((a, b) => b.value - a.value).slice(0, 8);
  const maxSec = secData[0]?.value || 1;

  const maxAlloc = Math.max(...portfolio.map(h => h.allocation), 1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, animation: "fadeIn 0.4s ease" }}>

      {/* Row 1: Donut + Geo */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>

        {/* Donut */}
        <div style={{ background: "#0d1425", border: "1px solid #1e2a45", borderRadius: 14, padding: 18 }}>
          <div style={{ fontSize: 11, fontFamily: "monospace", color: "#64748b", letterSpacing: 1, marginBottom: 12, textTransform: "uppercase" }}>Asset Allocation</div>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <div style={{ width: 140, height: 140, position: "relative", flexShrink: 0 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={catPct} cx="50%" cy="50%" innerRadius={42} outerRadius={65} paddingAngle={3} dataKey="value" strokeWidth={0}>
                    {catPct.map(({ name }) => <Cell key={name} fill={C[name] || "#888"} />)}
                  </Pie>
                  <Tooltip formatter={v => `${v.toFixed(1)}%`} contentStyle={{ background: "#1a2440", border: "1px solid #2a3a60", borderRadius: 8, fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", pointerEvents: "none" }}>
                <span style={{ fontWeight: 800, fontSize: 16, lineHeight: 1 }}>{portfolio.length}</span>
                <span style={{ fontSize: 9, color: "#64748b" }}>asset</span>
              </div>
            </div>
            <div style={{ flex: 1 }}>
              {catPct.map(({ name, value }) => (
                <div key={name} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: C[name] || "#888", flexShrink: 0 }} />
                  <span style={{ flex: 1, fontSize: 12, color: "#cbd5e1" }}>{name}</span>
                  <span style={{ fontFamily: "monospace", fontWeight: 700, fontSize: 12, color: C[name] || "#888" }}>{value.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Geo */}
        <div style={{ background: "#0d1425", border: "1px solid #1e2a45", borderRadius: 14, padding: 18 }}>
          <div style={{ fontSize: 11, fontFamily: "monospace", color: "#64748b", letterSpacing: 1, marginBottom: 12, textTransform: "uppercase" }}>Esposizione Geografica</div>
          {geoData.length === 0 ? (
            <div style={{ color: "#374151", fontSize: 13, textAlign: "center", paddingTop: 40 }}>Aggiungi asset con dati geografici</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {geoData.map(({ name, value }) => (
                <div key={name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 80, fontSize: 11, color: "#94a3b8", flexShrink: 0 }}>{name}</span>
                  <Bar2 value={value} max={geoData[0]?.value || 1} color={C.geo[name] || "#64748b"} h={7} />
                  <span style={{ fontFamily: "monospace", fontSize: 11, width: 36, textAlign: "right", color: C.geo[name] || "#64748b", fontWeight: 700 }}>{value.toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Row 2: Holdings list */}
      <div style={{ background: "#0d1425", border: "1px solid #1e2a45", borderRadius: 14, padding: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontFamily: "monospace", color: "#64748b", letterSpacing: 1, textTransform: "uppercase" }}>Holdings</div>
          <div style={{ fontSize: 11, fontFamily: "monospace", color: "#64748b", letterSpacing: 1, textTransform: "uppercase" }}>Allocazione</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {portfolio.map((h, i) => {
            const color = C[h.category] || "#888";
            const pct = (h.allocation / total * 100).toFixed(1);
            return (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{ width: 34, height: 34, borderRadius: 8, background: color + "20", border: `1px solid ${color}40`, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "monospace", fontSize: 9, fontWeight: 800, color, flexShrink: 0 }}>
                  {h.ticker.slice(0, 5)}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.name}</div>
                  <div style={{ fontFamily: "monospace", fontSize: 10, color: "#818cf8" }}>{h.ticker}</div>
                </div>
                <Bar2 value={h.allocation} max={maxAlloc * 1.1} color={color} h={6} />
                <span style={{ fontFamily: "monospace", fontWeight: 700, fontSize: 13, width: 44, textAlign: "right", color }}>{pct}%</span>
              </div>
            );
          })}
          {parseFloat(liquidita) > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 34, height: 34, borderRadius: 8, background: "#ffb02020", border: "1px solid #ffb02040", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0 }}>💰</div>
              <div style={{ flex: 1 }}><div style={{ fontSize: 13, fontWeight: 600 }}>Liquidità</div></div>
              <Bar2 value={parseFloat(liquidita)} max={maxAlloc * 1.1} color="#ffb020" h={6} />
              <span style={{ fontFamily: "monospace", fontWeight: 700, fontSize: 13, width: 44, textAlign: "right", color: "#ffb020" }}>{(parseFloat(liquidita) / total * 100).toFixed(1)}%</span>
            </div>
          )}
        </div>
      </div>

      {/* Row 3: Sector + Class bar */}
      <div style={{ display: "grid", gridTemplateColumns: secData.length > 0 ? "1fr 1fr" : "1fr", gap: 12 }}>
        {/* Class exposure bar */}
        <div style={{ background: "#0d1425", border: "1px solid #1e2a45", borderRadius: 14, padding: 18 }}>
          <div style={{ fontSize: 11, fontFamily: "monospace", color: "#64748b", letterSpacing: 1, marginBottom: 12, textTransform: "uppercase" }}>Classe di Attivi</div>
          <div style={{ display: "flex", borderRadius: 8, overflow: "hidden", gap: 2, height: 52 }}>
            {catPct.map(({ name, value }) => (
              <div key={name} style={{ flex: value, background: C[name] || "#888", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minWidth: 0 }}>
                <span style={{ fontWeight: 800, fontSize: 14, color: "white" }}>{value.toFixed(0)}%</span>
                <span style={{ fontSize: 9, color: "rgba(255,255,255,0.7)" }}>{name}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Sectors */}
        {secData.length > 0 && (
          <div style={{ background: "#0d1425", border: "1px solid #1e2a45", borderRadius: 14, padding: 18 }}>
            <div style={{ fontSize: 11, fontFamily: "monospace", color: "#64748b", letterSpacing: 1, marginBottom: 12, textTransform: "uppercase" }}>Settori</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {secData.map(({ name, value }, i) => (
                <div key={name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 90, fontSize: 11, color: "#94a3b8", flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
                  <Bar2 value={value} max={maxSec} color={C.sector[i % C.sector.length]} h={6} />
                  <span style={{ fontFamily: "monospace", fontSize: 10, color: "#64748b", width: 32, textAlign: "right" }}>{value.toFixed(0)}%</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────
export default function App() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [portfolio, setPortfolio] = useState([]);
  const [liquidita, setLiquidita] = useState("0");
  const inputRef = useRef();

  const total = portfolio.reduce((s, h) => s + h.allocation, 0) + parseFloat(liquidita || 0);
  const totalOk = Math.abs(total - 100) < 0.5;

  const doSearch = useCallback(async () => {
    const q = query.trim().toUpperCase();
    if (!q) return;
    setLoading(true);
    setError("");
    setResult(null);

    // Try backend first, fall back to demo
    try {
      const res = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(q)}`);
      if (res.ok) {
        setResult(await res.json());
        setLoading(false);
        return;
      }
    } catch (_) {}

    // Demo fallback
    await new Promise(r => setTimeout(r, 600));
    const hit = DEMO_DB[q] || Object.values(DEMO_DB).find(d => d.ticker === q || d.isin === q);
    if (hit) { setResult(hit); }
    else { setError(`"${q}" non trovato. Prova: IE00B3RBWM25, MSFT, NVDA, ETH-USD`); }
    setLoading(false);
  }, [query]);

  const handleAdd = useCallback((asset) => {
    setPortfolio(prev => {
      const idx = prev.findIndex(h => h.ticker === asset.ticker);
      if (idx >= 0) { const n = [...prev]; n[idx].allocation = asset.allocation; return n; }
      return [...prev, asset];
    });
    setResult(null);
    setQuery("");
    inputRef.current?.focus();
  }, []);

  const removeAsset = (i) => setPortfolio(p => p.filter((_, idx) => idx !== i));

  return (
    <div style={{ background: "#060c1a", minHeight: "100vh", color: "white", fontFamily: "'DM Sans', system-ui, sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes slideDown { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        input:focus { outline: none; border-color: #7c6ff7 !important; }
        ::-webkit-scrollbar { width: 4px; } ::-webkit-scrollbar-track { background: #0d1425; } ::-webkit-scrollbar-thumb { background: #1e2a45; border-radius: 2px; }
      `}</style>

      {/* Navbar */}
      <div style={{ borderBottom: "1px solid #1e2a45", padding: "0 24px", height: 54, display: "flex", alignItems: "center", background: "rgba(6,12,26,0.9)", backdropFilter: "blur(12px)", position: "sticky", top: 0, zIndex: 10 }}>
        <span style={{ fontSize: 20 }}>📊</span>
        <span style={{ fontWeight: 800, fontSize: 16, marginLeft: 8 }}>Portfolio<span style={{ color: "#7c6ff7" }}>Lab</span></span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {portfolio.length > 0 && (
            <span style={{ background: "#7c6ff720", color: "#7c6ff7", border: "1px solid #7c6ff740", borderRadius: 20, padding: "3px 12px", fontSize: 13, fontWeight: 600 }}>
              {portfolio.length} asset · {total.toFixed(1)}%
            </span>
          )}
          <span style={{ background: "#00e5a015", color: "#00e5a0", border: "1px solid #00e5a030", borderRadius: 20, padding: "3px 12px", fontSize: 12, fontWeight: 600 }}>🆓 Free</span>
        </div>
      </div>

      {/* AD top */}
      <div style={{ background: "#0a1020", borderBottom: "1px solid #1e2a45", height: 60, display: "flex", alignItems: "center", justifyContent: "center", color: "#1e2a45", fontFamily: "monospace", fontSize: 12 }}>
        ADV — 728×90 Leaderboard
      </div>

      {/* Body */}
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 20px", display: "grid", gridTemplateColumns: "380px 1fr", gap: 20, alignItems: "start" }}>

        {/* LEFT PANEL */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

          {/* Search */}
          <div style={{ background: "#0d1425", border: "1px solid #1e2a45", borderRadius: 14, padding: 20 }}>
            <h2 style={{ fontWeight: 800, fontSize: 16, marginBottom: 4 }}>Aggiungi al portafoglio</h2>
            <p style={{ fontSize: 12, color: "#64748b", marginBottom: 14, lineHeight: 1.5 }}>
              ISIN europeo, ticker (MSFT, NVDA…) o crypto (ETH-USD, BTC-USD)
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                ref={inputRef}
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={e => e.key === "Enter" && doSearch()}
                placeholder="ES. IE00B3RBWM25 · MSFT · ETH-USD"
                style={{ flex: 1, background: "#060c1a", border: "1.5px solid #1e2a45", borderRadius: 8, padding: "10px 14px", color: "white", fontSize: 13, fontFamily: "monospace" }}
              />
              <button
                onClick={doSearch}
                disabled={loading || !query.trim()}
                style={{ background: loading || !query.trim() ? "#1e2a45" : "#7c6ff7", border: "none", borderRadius: 8, padding: "10px 16px", color: "white", fontWeight: 700, cursor: loading || !query.trim() ? "not-allowed" : "pointer", display: "flex", alignItems: "center", gap: 6, fontSize: 13, transition: "background .2s" }}
              >
                {loading ? <><Spinner /> …</> : "Cerca"}
              </button>
            </div>

            {error && (
              <div style={{ marginTop: 10, padding: 10, background: "#f8717115", border: "1px solid #f8717130", borderRadius: 8, fontSize: 12, color: "#f87171" }}>
                ❌ {error}
              </div>
            )}

            {/* Demo suggestions */}
            {!result && !loading && portfolio.length === 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 11, color: "#374151", marginBottom: 6, fontFamily: "monospace" }}>PROVA CON:</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {["IE00B3RBWM25", "IE00BKM4GZ66", "MSFT", "NVDA", "NVO", "ETH-USD"].map(s => (
                    <button key={s} onClick={() => { setQuery(s); }} style={{ background: "#ffffff08", border: "1px solid #ffffff12", borderRadius: 6, padding: "4px 10px", color: "#818cf8", fontFamily: "monospace", fontSize: 11, cursor: "pointer" }}>{s}</button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Result card */}
          {result && <ResultCard data={result} onAdd={handleAdd} />}

          {/* Portfolio list */}
          {portfolio.length > 0 && (
            <div style={{ background: "#0d1425", border: "1px solid #1e2a45", borderRadius: 14, padding: 16 }}>
              <div style={{ fontSize: 11, fontFamily: "monospace", color: "#64748b", letterSpacing: 1, marginBottom: 12, textTransform: "uppercase" }}>Nel portafoglio</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {portfolio.map((h, i) => {
                  const color = C[h.category] || "#888";
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", background: "#ffffff05", borderRadius: 8 }}>
                      <div style={{ width: 28, height: 28, borderRadius: 6, background: color + "20", border: `1px solid ${color}40`, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "monospace", fontSize: 8, fontWeight: 800, color, flexShrink: 0 }}>{h.ticker.slice(0, 5)}</div>
                      <span style={{ flex: 1, fontSize: 12, fontWeight: 600 }}>{h.name}</span>
                      <input
                        type="number" value={h.allocation} min="0.1" max="100" step="0.1"
                        onChange={e => setPortfolio(p => { const n = [...p]; n[i] = { ...n[i], allocation: parseFloat(e.target.value) || 0 }; return n; })}
                        style={{ width: 48, background: "none", border: "1px solid #1e2a45", borderRadius: 5, color: "white", fontFamily: "monospace", fontSize: 12, padding: "3px 6px", textAlign: "center" }}
                      />
                      <span style={{ color: "#64748b", fontSize: 12 }}>%</span>
                      <button onClick={() => removeAsset(i)} style={{ background: "none", border: "none", color: "#374151", cursor: "pointer", fontSize: 16, padding: "0 2px" }}
                        onMouseEnter={e => e.currentTarget.style.color = "#f87171"}
                        onMouseLeave={e => e.currentTarget.style.color = "#374151"}
                      >×</button>
                    </div>
                  );
                })}
                {/* Liquidità */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", background: "#ffb02008", border: "1px solid #ffb02020", borderRadius: 8 }}>
                  <span style={{ fontSize: 16 }}>💰</span>
                  <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: "#ffb020" }}>Liquidità</span>
                  <input type="number" value={liquidita} min="0" max="100" step="0.1"
                    onChange={e => setLiquidita(e.target.value)}
                    style={{ width: 48, background: "none", border: "1px solid #ffb02040", borderRadius: 5, color: "#ffb020", fontFamily: "monospace", fontSize: 12, padding: "3px 6px", textAlign: "center" }}
                  />
                  <span style={{ color: "#64748b", fontSize: 12 }}>%</span>
                  <div style={{ width: 20 }} />
                </div>
              </div>
              {/* Total indicator */}
              <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 12, color: "#64748b" }}>Totale:</span>
                <span style={{ fontFamily: "monospace", fontWeight: 700, fontSize: 13, color: totalOk ? "#00e5a0" : total > 0 ? "#ffb020" : "#64748b" }}>{total.toFixed(1)}%</span>
                {totalOk && <span style={{ fontSize: 14 }}>✅</span>}
              </div>
            </div>
          )}

          {/* Sidebar AD */}
          <div style={{ background: "#0a1020", border: "1px solid #1e2a45", borderRadius: 10, height: 280, display: "flex", alignItems: "center", justifyContent: "center", color: "#1e2a45", fontFamily: "monospace", fontSize: 12 }}>
            ADV — 300×250
          </div>
        </div>

        {/* RIGHT: Live Dashboard */}
        <div>
          {portfolio.length === 0 ? (
            <div style={{ background: "#0d1425", border: "1px solid #1e2a45", borderRadius: 14, padding: 60, textAlign: "center" }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>📊</div>
              <h2 style={{ fontWeight: 800, fontSize: 20, marginBottom: 8 }}>Il dashboard si compone in tempo reale</h2>
              <p style={{ color: "#64748b", fontSize: 14, lineHeight: 1.7, maxWidth: 420, margin: "0 auto" }}>
                Cerca un ISIN (ETF europei via JustETF), un ticker azionario o una crypto.<br />
                Aggiungendo asset i grafici si aggiornano istantaneamente.
              </p>
              <div style={{ marginTop: 20, display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
                {["ETF", "Azioni", "Crypto"].map(t => (
                  <span key={t} style={{ background: "#ffffff08", border: "1px solid #1e2a45", borderRadius: 20, padding: "5px 16px", fontSize: 13, color: "#64748b" }}>{t}</span>
                ))}
              </div>
            </div>
          ) : (
            <LiveDashboard portfolio={portfolio} liquidita={liquidita} />
          )}

          {/* Inline AD */}
          {portfolio.length > 0 && (
            <div style={{ background: "#0a1020", border: "1px solid #1e2a45", borderRadius: 10, height: 90, display: "flex", alignItems: "center", justifyContent: "center", color: "#1e2a45", fontFamily: "monospace", fontSize: 12, marginTop: 12 }}>
              ADV — 728×90 Rectangle
            </div>
          )}
        </div>
      </div>

      {/* Footer AD */}
      <div style={{ borderTop: "1px solid #1e2a45", padding: 20, textAlign: "center" }}>
        <div style={{ background: "#0a1020", border: "1px solid #1e2a45", borderRadius: 8, height: 60, display: "flex", alignItems: "center", justifyContent: "center", color: "#1e2a45", fontFamily: "monospace", fontSize: 12, maxWidth: 800, margin: "0 auto 16px" }}>
          ADV — Footer Leaderboard
        </div>
        <p style={{ color: "#1e2a45", fontSize: 12 }}>© 2025 PortfolioLab — Solo a scopo informativo. Non è consulenza finanziaria.</p>
      </div>
    </div>
  );
}
