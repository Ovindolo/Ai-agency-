# Rezumat complet — botul de trading (sesiunea 22–29 octombrie 2026)

Tot ce am discutat, tot ce mi-ai dat, ce am testat și ce a ieșit. Fișierul stă în repo ca să nu se mai
piardă nimic între sesiuni (Claude nu are memorie de la o conversație la alta).

## 1. Concluzia în 5 rânduri

1. **Pe 15 minute, pe futures, nimic din ce am testat nu bate costurile** (~0,14% pe o intrare+ieșire).
2. Cel mai bun lucru găsit, modelul nostru cu toți indicatorii, chiar „vede” ceva (52–54% direcție corectă,
   +3…+10 bp înainte de taxe), dar taxa e ~14 bp: câștigul e cam o treime din cost.
3. Singurul rezultat pozitiv a fost **modelul săptămânal pe 20 de monede** (+382% din 2023, cădere max 26%),
   dar **pe ultimele 12 luni a pierdut** și testul statistic dă 90% (pragul e 95%): promițător, nedovedit.
4. Recomandarea pentru cei 800$: **BTC (sau BTC+ETH) cumpărat și ținut / DCA**; restul doar pe hârtie.
5. Ce a rămas netestat și ar putea schimba rezultatul: **execuție doar cu ordine limită** (taxe ~4 bp).

## 2. Ce mi-ai dat (link-uri, fișiere, idei)

### Link-uri trimise de tine
| Link | Ce era | Verdict |
|---|---|---|
| https://github.com/shiyu-coder/Kronos | Model AI pentru lumânări (AAAI 2026) | Testat pe BTC real: nu se tranzacționează (vezi §3) |
| https://identidadsoberana.org/mac/ | „TradingView pentru Mac” | **VIRUS** (comandă ascunsă care descarcă de pe `undisruptedai.com` și cere parola de Mac) |
| Postarea „TradingView Premium crack + KeyGen” (text, fără link) | Program „crăcuit” | **Momeală pentru virus care fură parole și crypto** — nu instala |
| https://github.com/TauricResearch/TradingAgents | Agenți AI care dezbat tranzacții | Pe acțiuni; doar idee pentru analiza de seară |
| https://github.com/openbq-org/OpenBB | „OpenBB” | **Copie falsă** (nume care imită originalul) — nu folosi |
| https://github.com/OpenBB-finance/OpenBB | OpenBB original | Date financiare, nu tranzacționare |
| https://github.com/virattt/ai-hedge-fund | Agenți care imită investitori | Educativ, acțiuni, fără tranzacții reale |
| https://github.com/freqtrade/freqtrade | Bot crypto | Folosit: 17 strategii ale comunității testate, 0 trec |
| https://github.com/microsoft/qlib | Platformă cantitativă (acțiuni) | Baza lui Kronos; nimic nou pentru noi |
| https://github.com/nautechsystems/nautilus_trader | Motor profesionist backtest/live | Idee preluată (paritate test–live); prea greu pentru 800$ |
| https://github.com/microsoft/RD-Agent | AI care inventează factori | Ce am făcut noi manual; scump, risc de tipare din noroc |
| https://arxiv.org/abs/2609.05663 | Studiul DXRG despre agenți AI în producție | Verificat la sursă; regulile valide sunt deja în bot; 3 cifre din tweet NU apar în studiu |

### Fișiere și materiale
- **Grafice CriptoPedia** (NEAR dublu fund 1h, ENA canal, USDT.D cap-umeri) — analizate.
- **Analiza TraderBrain** (AI local, „8 din 8”) — short BTC 27.10: intrarea atinsă, stopul nu, TP1 neatins
  la ultima verificare; 8 tranzacții nu dovedesc nimic statistic, iar postarea acoperă ambele direcții.
- **Arhiva chat Cryptopedia.ro** (265.059 mesaje, iul. 2019 – ian. 2022) — auditate apelurile admin-ului
  (doar local, nu în git: conține mesajele altor oameni).
- **Arhiva cu 9 cărți** + PDF-urile separate:
  Matov *The Ultimate Price Action Trading Guide*; Bulkowski *Encyclopedia of Chart Patterns*;
  Al Brooks *Trading Price Action: Trading Ranges*; *Big Book of Chart Patterns*; Wade FX *Market Structure
  and Powerful Setups*; *Supply and Demand Ebook*; *5 Supply and Demand Rules*; *Top 12 Candlesticks*;
  Swing Trader Society *Risk Management* și *Psychology*; *Blockchain Secrets* (Tarruella 2019);
  @coinchase: *Realizare portofoliu*, *Introducere în Trading – canale de trend*, *Change și Revolut*;
  *Analiza cripto 22-05* (2018).
- **Imagini didactice**: structură de trend (HH/HL), steaguri și fanioane, canal descendent.
- **Lista ta de monede**: NEAR, SUI, SEI, ETH, ENA, INJ, XMR, TIA, LINK, SOL, UNI, ASTER, QNT, VVV
  (+ adăugate de mine: BTC, BNB, XRP, DOGE, AVAX, AAVE).
- **Ideile tale**: bot pe 15 minute care decide long/short din tot ce vede pe grafic; să aleagă singur cea
  mai bună strategie; să conteze volumele; un bot legat de TradingView.

### Din sesiunile de dinainte (salvate în repo)
Interviul (`context/Trading_Context.md`: futures, 15m, ținere câteva ore, LuxAlgo/Fibonacci/Ichimoku,
1k → 5k neconfirmat), strategiile Ichimoku/Fibonacci/Supertrend, Jev, auditul grupurilor de semnale,
guard-ul de futures, screenerul de insideri. **Semnalele grupurilor plătite nu s-au salvat**
(`context/semnale.csv` e gol) — dacă le mai ai, trimite-le din nou.

## 3. Ce am testat și ce a ieșit (date reale Binance, cu taxe)

| Test | Comandă | Rezultat |
|---|---|---|
| Strategiile botului (trend pullback, Ichimoku, Fibonacci, Supertrend) pe 15m, BTC/ETH/SOL, 6 ani | `make research` | **Toate pierd** (−6% … −12%), în orice regim; trendul zilnic face bani dar nu bate buy & hold și nu trece testul statistic |
| Strategiile comunității freqtrade | `make tournament` | 23 testate, **0 trec** (cea mai bună: +12$ în 2 ani) |
| Kronos, BTC 15m, sep. 2025 → oct. 2026, 5.037 prognoze | `make kronos` | Direcție 51,3% vs 50,6% „mereu sus”; **pierde la toate pragurile**; volatilitatea o estimează mai prost decât un calcul simplu |
| Setup-urile din cărți (pin bar, engulfing, inside bar, zone S/D, „5 reguli”), 20 monede, futures 1h/4h, 2022 → 2026 | `make pa` | **Toate pierd**. Zonele păreau +0,2–0,3R — era o eroare a simulatorului, corectată; după corectură pierd |
| Selector lunar „alege cea mai bună strategie” (20 variante) | `make pa-select` | 19 pierd, una +0,13R pe 97 tranzacții = noroc (test statistic 0%) |
| Apelurile admin-ului Cryptopedia (157, 111 executate) | `make audit-calls` | 84% ating ținta 1, dar mediana după 90 de zile −5%; **aceleași monede cumpărate la întâmplare 1–10 zile mai târziu: la fel sau mai bine** |
| Model propriu săptămânal, 20 monede, funding, OI, stablecoin-uri | `make model` | +382% (vs BTC +241%), cădere 26%; **ultimele 12 luni −5%**; nedovedit |
| Model 15m cu TOȚI indicatorii, pattern-urile și volumele (delta, VWAP, OBV), lista ta de 20 monede, 2024 → 2026 | `make m15` | +3…+10 bp înainte de taxe, **−4…−11 bp după**; ultimele 6 luni mai rău |
| Analiza 2018 din PDF, verificată pe prețuri | — | Prognozele de scădere au ieșit, cele de creștere nu (ETH „830–957” → a ajuns la 82) |

Detalii: `docs/RESEARCH_SOURCES.md`, `docs/BOOKS.md`; rapoartele în `reports/` (doar local).

## 4. Ce am verificat pe GitHub pentru tine

| Repo | Ce e | Verdict |
|---|---|---|
| https://github.com/milesdeutscher/garchmethod (Storm Gauge) | Indicator de volatilitate + GARCH | Curat; nu dă intrări, doar mărimea poziției |
| https://github.com/Boom-Vitt/anglerfish-fable5 | Bot spot cu AI (Claude Fable 5) | Cel mai sigur construit (hârtie implicit, limite); dar AI-ul ghicește direcția, netestat |
| https://github.com/beydah/TradingView-Webhook-Bot | Alertă TradingView → Binance Futures | **Periculos implicit**: 100% din sold la 2x, stop-loss neapelat |
| https://github.com/CryptoGnome/Tradingview-Webhook-Bot | Alertă → Bybit/Binance | Parolă implicită „12345”, abandonat din 2023 |
| https://github.com/51bitquant/binance-tradingview-webhook-bot | Alertă → Binance | Vechi, fără management de risc |
| https://github.com/LuxAlgo/PineTS | Rulează Pine Script fără TradingView | Gratuit (AGPL), Pine v6 incomplet |
| https://pypi.org/project/pynesys-pynecore/ | Pine Script în Python | Motor gratuit; conversia .pine cere cheie plătită |
| https://github.com/dylanpersonguy/OpenCharts | Alternativă open-source la TradingView | Gratuit, proiect mic |
| „Claude Fable 5.1 indicator” | — | **Nu există oficial**; e un model AI, nu un indicator; atenție la momeli |

## 5. Siguranță (important)
- **Nu instala niciodată** TradingView „crăcuit”, KeyGen-uri, arhive cu parolă sau comenzi `curl … | zsh`.
- Un indicator TradingView real e **doar text Pine** lipit în Pine Editor, niciodată un .exe/.dmg.
- Dacă ai rulat ceva suspect: de pe telefon schimbă parolele (Binance, email, Telegram), **șterge cheile
  API Binance**, mută crypto-ul într-un portofel nou, reinstalează calculatorul.
- Folosește doar organizațiile originale pe GitHub (ex. `OpenBB-finance`, nu `openbq-org`).

## 6. Ce urmează (variante)
1. **Bot cu alerte live, fără TradingView plătit**: urmărește monedele tale de la Binance, calculează
   indicatorii aleși de tine, trimite alertă pe Telegram, tranzacționează **pe hârtie** cu stop mereu,
   1% risc, levier după volatilitate, și ține jurnal pe fiecare semnal.
2. **Paper trading cu ordine limită** pe modelul de 15 minute (singura cale netestată care ar putea trece
   de costuri).
3. **Jurnal pentru TraderBrain / mentor**: fiecare postare urmărită automat până la stop sau țintă;
   verdict după 30–40.
4. **Bani reali**: doar BTC/ETH ținut sau DCA, până când ceva trece pe hârtie.

## 7. Comenzi (din folderul `trading-bot/`)
`make research` · `make tournament` · `make kronos-setup && make kronos` · `make model-data && make model` ·
`make pa && make pa-select` · `make m15` · `make audit-calls EXPORT=<folder export> AUTHOR=<nume>`
