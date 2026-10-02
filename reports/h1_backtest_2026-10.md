# H1 historical test -- second-ring lag after reports

Generated 2026-10-02T07:36:14+00:00. Seed 20261002, 200 placebo baskets per event.
Pre-registered in hypotheses-and-evaluation-2026-10-01.md; event source per Amendment 1 (SEC EDGAR results filings, acceptance timestamp). Numbers only.

## Verdict

H1 (sessions 2-21): FAIL -- paired difference -0.09% (week-clustered t = -0.23, 1124 events, 306 weeks); bar: > 0, t >= 3.0, >= +0.50 pp, positive in 2019-21, 2022-23, 2024-26 (2019-21 -0.26%, 2022-23 -0.16%, 2024-26 +0.17%)

Checks: paired_gt_0 no, t_ge_3 no, effect_ge_0.50pp no, positive_all_subperiods no

## Sample

- Events: 1124 (one per reporter-quarter, 2019-01-01 to 2026-06-30)
- Independent weeks (2-21): 306
- Events with a missing acceptance timestamp (assumed after the US close): 0
- Events skipped for a missing reaction price: 0

## Per horizon (2-21 is the test; 2-6, 2-11, 2-41 are diagnostics)

| horizon | events | weeks | linked mean | placebo mean | paired (week mean) | t (week-clustered) | hit rate |
|---|---|---|---|---|---|---|---|
| 2-6 | 1124 | 306 | -0.11% | -0.01% | -0.12% | -0.58 | 49.6% |
| 2-11 | 1124 | 306 | -0.08% | -0.01% | +0.01% | 0.04 | 49.6% |
| 2-21 | 1124 | 306 | +0.25% | -0.03% | -0.09% | -0.23 | 52.0% |
| 2-41 | 1124 | 306 | +0.37% | -0.02% | -0.76% | -0.75 | 50.4% |

### 2019-21

| horizon | events | weeks | linked mean | placebo mean | paired (week mean) | t (week-clustered) | hit rate |
|---|---|---|---|---|---|---|---|
| 2-6 | 414 | 116 | -0.20% | -0.03% | -0.16% | -0.50 | 49.3% |
| 2-11 | 414 | 116 | -0.20% | -0.02% | +0.02% | 0.05 | 48.1% |
| 2-21 | 414 | 116 | -0.07% | -0.05% | -0.26% | -0.67 | 49.8% |
| 2-41 | 414 | 116 | -1.15% | -0.04% | -1.90% | -1.50 | 47.6% |

### 2022-23

| horizon | events | weeks | linked mean | placebo mean | paired (week mean) | t (week-clustered) | hit rate |
|---|---|---|---|---|---|---|---|
| 2-6 | 303 | 86 | +0.57% | +0.01% | +0.41% | 0.88 | 51.8% |
| 2-11 | 303 | 86 | +0.37% | -0.01% | +0.20% | 0.39 | 51.2% |
| 2-21 | 303 | 86 | -0.11% | -0.02% | -0.16% | -0.22 | 52.5% |
| 2-41 | 303 | 86 | +2.44% | -0.01% | +0.42% | 0.19 | 49.8% |

### 2024-26

| horizon | events | weeks | linked mean | placebo mean | paired (week mean) | t (week-clustered) | hit rate |
|---|---|---|---|---|---|---|---|
| 2-6 | 407 | 104 | -0.53% | +0.00% | -0.53% | -1.54 | 48.2% |
| 2-11 | 407 | 104 | -0.28% | +0.00% | -0.15% | -0.34 | 49.9% |
| 2-21 | 407 | 104 | +0.83% | -0.01% | +0.17% | 0.20 | 54.1% |
| 2-41 | 407 | 104 | +0.37% | -0.00% | -0.47% | -0.25 | 53.8% |

## Coverage (EDGAR results filings found per reporter; 30 expected)

| reporter | US ticker | form | found | coverage |
|---|---|---|---|---|
| amd | AMD | 8-K | 30/30 | 100% |
| amkr | AMKR | 8-K | 30/30 | 100% |
| amzn | AMZN | 8-K | 30/30 | 100% |
| anet | ANET | 8-K | 30/30 | 100% |
| ase | ASX | 6-K | 30/30 | 100% |
| avgo | AVGO | 8-K | 30/30 | 100% |
| axti | AXTI | 8-K | 30/30 | 100% |
| cdns | CDNS | 8-K | 30/30 | 100% |
| clf | CLF | 8-K | 30/30 | 100% |
| cohr | COHR | 8-K | 30/30 | 100% |
| corning_fiber | GLW | 8-K | 30/30 | 100% |
| entegris | ENTG | 8-K | 30/30 | 100% |
| etn | ETN | 8-K | 30/30 | 100% |
| fn | FN | 8-K | 30/30 | 100% |
| googl | GOOGL | 8-K | 30/30 | 100% |
| hwm | HWM | 8-K | 30/30 | 100% |
| intc | INTC | 8-K | 30/30 | 100% |
| klac | KLAC | 8-K | 30/30 | 100% |
| lite | LITE | 8-K | 30/30 | 100% |
| lrcx | LRCX | 8-K | 30/30 | 100% |
| meta | META | 8-K | 30/30 | 100% |
| mpwr | MPWR | 8-K | 30/30 | 100% |
| msft | MSFT | 8-K | 30/30 | 100% |
| nvda | NVDA | 8-K | 30/30 | 100% |
| orcl | ORCL | 8-K | 30/30 | 100% |
| smci | SMCI | 8-K | 30/30 | 100% |
| snps | SNPS | 8-K | 30/30 | 100% |
| teck | TECK | 6-K | 30/30 | 100% |
| ter | TER | 8-K | 30/30 | 100% |
| tower | TSEM | 6-K | 30/30 | 100% |
| tsmc | TSM | 6-K | 30/30 | 100% |
| amat | AMAT | 8-K | 29/30 | 97% |
| mu | MU | 8-K | 29/30 | 97% |
| vrt | VRT | 8-K | 25/30 | 83% |
| asml | ASML | 6-K | 23/30 | 77% |
| mrvl | MRVL | 8-K | 21/30 | 70% |
| ceg | CEG | 8-K | 17/30 | 57% |
| crdo | CRDO | 8-K | 17/30 | 57% |
| arm | ARM | 6-K | 11/30 | 37% |
| alab | ALAB | 8-K | 9/30 | 30% |
| gev | GEV | 8-K | 8/30 | 27% |
| crwv | CRWV | 8-K | 5/30 | 17% |

Below 50% coverage: alab, arm, crwv, gev

## Excluded reporters (Amendment 1: no EDGAR results filings)

- Advantest (6857.T): EDGAR filer with no results filings (8-K 2.02 / results 6-K) in the window
- AGC Inc. (5201.T): no US listing
- Ajinomoto (2802.T): no EDGAR filer for its listing
- ASMPT (0522.HK): no EDGAR filer for its listing
- Hon Hai Precision (Foxconn) (2317.TW): no US listing
- GlobalWafers (6488.TWO): no US listing
- Hanmi Semiconductor (042700.KS): no US listing
- HOYA (7741.T): no EDGAR filer for its listing
- Ibiden (4062.T): no EDGAR filer for its listing
- IQE (IQE.L): no US listing
- Lasertec (6920.T): no EDGAR filer for its listing
- Nitto Boseki (Nittobo) (3110.T): no US listing
- Samsung Electronics (005930.KS): no US listing
- Shin-Etsu Chemical (4063.T): no EDGAR filer for its listing
- Siemens Energy (ENR.DE): no US listing
- Siltronic (WAF.DE): no US listing
- SKC (Absolics) (011790.KS): no US listing
- SK hynix (000660.KS): no US listing
- SUMCO (3436.T): no EDGAR filer for its listing
- Tokyo Electron (8035.T): no US listing
- Tokyo Ohka Kogyo (4186.T): no US listing
- Unimicron Technology (3037.TW): no US listing
- Wacker Chemie (WCH.DE): no US listing

## Declared weaknesses (restated from the pre-flight)

- Edge look-ahead: the map's edges are as known in 2026, not as they were at the time of each event. This biases toward finding an effect.
- Survivorship: only currently listed nodes are included.
- Event-date and time-zone mapping: EDGAR acceptance time is read as UTC (checked against three known releases); a results 6-K is identified by keywords in its cover or Exhibit 99 documents.
- Earnings seasons cluster events, so there are few independent weeks.
- Horizons examined: 2-6, 2-11, 2-21, 2-41 (four); only 2-21 is the test.
