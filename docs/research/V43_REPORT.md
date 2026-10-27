# v43: v39's best book replayed on one-minute bars, and a large minute grid

115,200 of 115,200 replays computed (1,382,400 books); 4000 one-year bootstrap paths from $5,000; ruin = at or under $1,250 at any time.

## Q1. Does the book survive the minute replay?

**True** (central case `next_open / 10% / next_vwap / auction`, base costs: median >= $15,000 and ruin <= 2%).

| case | base median | base ruin | HOT 5% median | HOT 5% ruin | high median | high ruin |
|---|---|---|---|---|---|---|
| next_vwap / 10% / threshold / auction | $22,053 | 0.1% | $16,157 | 0.5% | $10,247 | 2.6% |
| next_vwap / 10% / next_vwap / auction | $22,053 | 0.1% | $16,157 | 0.5% | $10,247 | 2.6% |
| next_vwap / 10% / next_high / auction | $22,053 | 0.1% | $16,157 | 0.5% | $10,247 | 2.6% |
| next_vwap / 5% / threshold / auction | $22,053 | 0.1% | $16,157 | 0.5% | $10,247 | 2.6% |
| next_vwap / 5% / next_vwap / auction | $22,053 | 0.1% | $16,157 | 0.5% | $10,247 | 2.6% |
| next_vwap / 5% / next_high / auction | $22,053 | 0.1% | $16,157 | 0.5% | $10,247 | 2.6% |
| next_vwap / no cap / threshold / auction | $22,039 | 0.1% | $16,154 | 0.5% | $10,247 | 2.6% |
| next_vwap / no cap / next_vwap / auction | $22,039 | 0.1% | $16,154 | 0.5% | $10,247 | 2.6% |
| next_vwap / no cap / next_high / auction | $22,039 | 0.1% | $16,154 | 0.5% | $10,247 | 2.6% |
| next_vwap / 20% / threshold / auction | $22,039 | 0.1% | $16,154 | 0.5% | $10,247 | 2.6% |
| next_vwap / 20% / next_vwap / auction | $22,039 | 0.1% | $16,154 | 0.5% | $10,247 | 2.6% |
| next_vwap / 20% / next_high / auction | $22,039 | 0.1% | $16,154 | 0.5% | $10,247 | 2.6% |
| next_open / 10% / threshold / auction | $22,006 | 0.1% | $16,153 | 0.5% | $10,252 | 2.5% |
| next_open / 10% / next_vwap / auction **(central)** | $22,006 | 0.1% | $16,153 | 0.5% | $10,252 | 2.5% |
| next_open / 10% / next_high / auction | $22,006 | 0.1% | $16,153 | 0.5% | $10,252 | 2.5% |
| next_open / 5% / threshold / auction | $22,006 | 0.1% | $16,155 | 0.5% | $10,252 | 2.5% |
| next_open / 5% / next_vwap / auction | $22,006 | 0.1% | $16,155 | 0.5% | $10,252 | 2.5% |
| next_open / 5% / next_high / auction | $22,006 | 0.1% | $16,155 | 0.5% | $10,252 | 2.5% |
| next_open / 20% / threshold / auction | $22,006 | 0.1% | $16,152 | 0.5% | $10,252 | 2.5% |
| next_open / 20% / next_vwap / auction | $22,006 | 0.1% | $16,152 | 0.5% | $10,252 | 2.5% |
| next_open / 20% / next_high / auction | $22,006 | 0.1% | $16,152 | 0.5% | $10,252 | 2.5% |
| next_open / no cap / threshold / auction | $21,997 | 0.1% | $16,152 | 0.5% | $10,252 | 2.5% |
| next_open / no cap / next_vwap / auction | $21,997 | 0.1% | $16,152 | 0.5% | $10,252 | 2.5% |
| next_open / no cap / next_high / auction | $21,997 | 0.1% | $16,152 | 0.5% | $10,252 | 2.5% |
| slip / 5% / threshold / auction | $21,964 | 0.1% | $16,080 | 0.5% | $10,235 | 2.5% |
| slip / 5% / next_vwap / auction | $21,964 | 0.1% | $16,080 | 0.5% | $10,235 | 2.5% |
| slip / 5% / next_high / auction | $21,964 | 0.1% | $16,080 | 0.5% | $10,235 | 2.5% |
| slip / 10% / threshold / auction | $21,963 | 0.1% | $16,080 | 0.5% | $10,226 | 2.5% |
| slip / 10% / next_vwap / auction | $21,963 | 0.1% | $16,080 | 0.5% | $10,226 | 2.5% |
| slip / 10% / next_high / auction | $21,963 | 0.1% | $16,080 | 0.5% | $10,226 | 2.5% |
| next_vwap / 5% / threshold / vwap | $21,955 | 0.1% | $16,124 | 0.5% | $10,258 | 2.6% |
| next_vwap / 5% / next_vwap / vwap | $21,955 | 0.1% | $16,124 | 0.5% | $10,258 | 2.6% |
| next_vwap / 5% / next_high / vwap | $21,955 | 0.1% | $16,124 | 0.5% | $10,258 | 2.6% |
| next_open / 5% / threshold / vwap | $21,951 | 0.1% | $16,100 | 0.5% | $10,259 | 2.6% |
| next_open / 5% / next_vwap / vwap | $21,951 | 0.1% | $16,100 | 0.5% | $10,259 | 2.6% |
| next_open / 5% / next_high / vwap | $21,951 | 0.1% | $16,100 | 0.5% | $10,259 | 2.6% |
| next_vwap / 10% / threshold / vwap | $21,949 | 0.1% | $16,121 | 0.5% | $10,258 | 2.6% |
| next_vwap / 10% / next_vwap / vwap | $21,949 | 0.1% | $16,121 | 0.5% | $10,258 | 2.6% |
| next_vwap / 10% / next_high / vwap | $21,949 | 0.1% | $16,121 | 0.5% | $10,258 | 2.6% |
| next_open / 10% / threshold / vwap | $21,946 | 0.1% | $16,101 | 0.5% | $10,259 | 2.6% |
| next_open / 10% / next_vwap / vwap | $21,946 | 0.1% | $16,101 | 0.5% | $10,259 | 2.6% |
| next_open / 10% / next_high / vwap | $21,946 | 0.1% | $16,101 | 0.5% | $10,259 | 2.6% |
| slip / 20% / threshold / auction | $21,946 | 0.1% | $16,080 | 0.5% | $10,225 | 2.5% |
| slip / 20% / next_vwap / auction | $21,946 | 0.1% | $16,080 | 0.5% | $10,225 | 2.5% |
| slip / 20% / next_high / auction | $21,946 | 0.1% | $16,080 | 0.5% | $10,225 | 2.5% |
| next_vwap / no cap / threshold / vwap | $21,945 | 0.1% | $16,124 | 0.5% | $10,258 | 2.6% |
| next_vwap / no cap / next_vwap / vwap | $21,945 | 0.1% | $16,124 | 0.5% | $10,258 | 2.6% |
| next_vwap / no cap / next_high / vwap | $21,945 | 0.1% | $16,124 | 0.5% | $10,258 | 2.6% |
| next_vwap / 20% / threshold / vwap | $21,945 | 0.1% | $16,122 | 0.5% | $10,258 | 2.6% |
| next_vwap / 20% / next_vwap / vwap | $21,945 | 0.1% | $16,122 | 0.5% | $10,258 | 2.6% |
| next_vwap / 20% / next_high / vwap | $21,945 | 0.1% | $16,122 | 0.5% | $10,258 | 2.6% |
| slip / no cap / threshold / auction *(daily-like)* | $21,944 | 0.1% | $16,080 | 0.5% | $10,225 | 2.5% |
| slip / no cap / next_vwap / auction | $21,944 | 0.1% | $16,080 | 0.5% | $10,225 | 2.5% |
| slip / no cap / next_high / auction | $21,944 | 0.1% | $16,080 | 0.5% | $10,225 | 2.5% |
| slip / 10% / threshold / vwap | $21,943 | 0.1% | $16,044 | 0.5% | $10,217 | 2.5% |
| slip / 10% / next_vwap / vwap | $21,943 | 0.1% | $16,044 | 0.5% | $10,217 | 2.5% |
| slip / 10% / next_high / vwap | $21,943 | 0.1% | $16,044 | 0.5% | $10,217 | 2.5% |
| slip / 5% / threshold / vwap | $21,943 | 0.1% | $16,039 | 0.5% | $10,217 | 2.5% |
| slip / 5% / next_vwap / vwap | $21,943 | 0.1% | $16,039 | 0.5% | $10,217 | 2.5% |
| slip / 5% / next_high / vwap | $21,943 | 0.1% | $16,039 | 0.5% | $10,217 | 2.5% |
| slip / no cap / threshold / vwap | $21,941 | 0.1% | $16,048 | 0.5% | $10,217 | 2.5% |
| slip / no cap / next_vwap / vwap | $21,941 | 0.1% | $16,048 | 0.5% | $10,217 | 2.5% |
| slip / no cap / next_high / vwap | $21,941 | 0.1% | $16,048 | 0.5% | $10,217 | 2.5% |
| slip / 20% / threshold / vwap | $21,941 | 0.1% | $16,047 | 0.5% | $10,217 | 2.5% |
| slip / 20% / next_vwap / vwap | $21,941 | 0.1% | $16,047 | 0.5% | $10,217 | 2.5% |
| slip / 20% / next_high / vwap | $21,941 | 0.1% | $16,047 | 0.5% | $10,217 | 2.5% |
| next_open / 20% / threshold / vwap | $21,941 | 0.1% | $16,102 | 0.5% | $10,259 | 2.6% |
| next_open / 20% / next_vwap / vwap | $21,941 | 0.1% | $16,102 | 0.5% | $10,259 | 2.6% |
| next_open / 20% / next_high / vwap | $21,941 | 0.1% | $16,102 | 0.5% | $10,259 | 2.6% |
| next_open / no cap / threshold / vwap | $21,941 | 0.1% | $16,104 | 0.5% | $10,259 | 2.6% |
| next_open / no cap / next_vwap / vwap | $21,941 | 0.1% | $16,104 | 0.5% | $10,259 | 2.6% |
| next_open / no cap / next_high / vwap | $21,941 | 0.1% | $16,104 | 0.5% | $10,259 | 2.6% |
| next_high / 5% / threshold / auction | $21,911 | 0.1% | $16,074 | 0.5% | $10,196 | 2.6% |
| next_high / 5% / next_vwap / auction | $21,911 | 0.1% | $16,074 | 0.5% | $10,196 | 2.6% |
| next_high / 5% / next_high / auction | $21,911 | 0.1% | $16,074 | 0.5% | $10,196 | 2.6% |
| next_high / 10% / threshold / auction | $21,899 | 0.1% | $16,072 | 0.5% | $10,196 | 2.6% |
| next_high / 10% / next_vwap / auction | $21,899 | 0.1% | $16,072 | 0.5% | $10,196 | 2.6% |
| next_high / 10% / next_high / auction | $21,899 | 0.1% | $16,072 | 0.5% | $10,196 | 2.6% |
| next_high / 20% / threshold / auction | $21,898 | 0.1% | $16,066 | 0.5% | $10,196 | 2.6% |
| next_high / 20% / next_vwap / auction | $21,898 | 0.1% | $16,066 | 0.5% | $10,196 | 2.6% |
| next_high / 20% / next_high / auction | $21,898 | 0.1% | $16,066 | 0.5% | $10,196 | 2.6% |
| next_high / no cap / threshold / auction | $21,897 | 0.1% | $16,066 | 0.5% | $10,196 | 2.6% |
| next_high / no cap / next_vwap / auction | $21,897 | 0.1% | $16,066 | 0.5% | $10,196 | 2.6% |
| next_high / no cap / next_high / auction | $21,897 | 0.1% | $16,066 | 0.5% | $10,196 | 2.6% |
| next_high / 5% / threshold / vwap | $21,875 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / 5% / next_vwap / vwap | $21,875 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / 5% / next_high / vwap | $21,875 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / no cap / threshold / vwap | $21,869 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / no cap / next_vwap / vwap | $21,869 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / no cap / next_high / vwap | $21,869 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / 20% / threshold / vwap | $21,869 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / 20% / next_vwap / vwap | $21,869 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / 20% / next_high / vwap | $21,869 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / 10% / threshold / vwap | $21,869 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / 10% / next_vwap / vwap | $21,869 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |
| next_high / 10% / next_high / vwap | $21,869 | 0.1% | $16,023 | 0.6% | $10,175 | 2.7% |

v39's daily book for reference: median $23,143, ruin 0.1%.

## Q2. Do minute rules improve the book?

**False** (central case: walk-forward median >= 1.15 x the shield's rule's, ruin <= 2.5% at base and HOT 5%, high-cost median >= the shield's rule's).

| case | book | costs | all median | all ruin | p10 | 2018-22 median | 2023+ median |
|---|---|---|---|---|---|---|---|
| next_open / 10% / next_vwap / auction | shield rule | base | $22,006 | 0.1% | $8,295 | $21,891 | $20,999 |
| next_open / 10% / next_vwap / auction | shield rule | hot5 | $16,153 | 0.5% | $6,084 | - | - |
| next_open / 10% / next_vwap / auction | shield rule | spread2 | $18,162 | 0.4% | $6,861 | - | - |
| next_open / 10% / next_vwap / auction | shield rule | high | $10,252 | 2.5% | $3,650 | - | - |
| next_open / 10% / next_vwap / auction | walk-forward | base | $21,697 | 10.3% | $0 | $19,969 | $20,999 |
| next_open / 10% / next_vwap / auction | walk-forward | hot5 | $15,292 | 10.9% | $0 | - | - |
| next_open / 10% / next_vwap / auction | walk-forward | spread2 | $17,471 | 10.6% | $0 | - | - |
| next_open / 10% / next_vwap / auction | walk-forward | high | $9,262 | 13.0% | $0 | - | - |
| slip / no cap / threshold / auction | shield rule | base | $21,944 | 0.1% | $8,269 | $21,764 | $20,994 |
| slip / no cap / threshold / auction | shield rule | hot5 | $16,080 | 0.5% | $6,069 | - | - |
| slip / no cap / threshold / auction | shield rule | spread2 | $18,090 | 0.4% | $6,843 | - | - |
| slip / no cap / threshold / auction | shield rule | high | $10,225 | 2.5% | $3,636 | - | - |
| slip / no cap / threshold / auction | walk-forward | base | $21,631 | 5.2% | $5,683 | $19,987 | $20,994 |
| slip / no cap / threshold / auction | walk-forward | hot5 | $15,276 | 6.5% | $3,938 | - | - |
| slip / no cap / threshold / auction | walk-forward | spread2 | $17,410 | 5.8% | $4,553 | - | - |
| slip / no cap / threshold / auction | walk-forward | high | $9,230 | 9.9% | $2,205 | - | - |

In 0 of 96 realism cases the walk-forward choice beats the shield's rule on the historical path ($10,000 level, base costs, summed log growth).

Central-case picks:

- 2018: delay 0, stop x1.0, flat hold, cover none, trail none, size x1.0
- 2019: delay 15, stop x1.0, flat hold, cover none, trail none, size x1.25
- 2020: delay 15, stop x1.0, flat hold, cover none, trail none, size x1.25
- 2021: delay 15, stop x1.5, flat hold, cover none, trail none, size x1.25
- 2022: delay 15, stop x1.5, flat hold, cover none, trail none, size x1.25
- 2023: delay 0, stop x1.5, flat hold, cover none, trail none, size x1.0
- 2024: delay 0, stop x1.5, flat hold, cover none, trail none, size x1.0
- 2025: delay 0, stop x1.5, flat hold, cover none, trail none, size x1.0
- 2026: delay 0, stop x1.5, flat hold, cover none, trail none, size x1.0

Top fixed rules in the central case (in-sample, all years, chosen after the fact):

| rule | log growth | worst yearly drawdown |
|---|---|---|
| shield rule | 12.79 | -70.3% |
| delay 0, stop x1.5, flat hold, cover none, trail none, size x1.0 | 12.93 | -70.3% |
| delay 0, stop x1.25, flat hold, cover none, trail none, size x1.0 | 12.90 | -70.3% |
| delay 0, stop x0.75, flat hold, cover none, trail none, size x1.0 | 12.82 | -70.3% |
| delay 0, stop x1.0, flat hold, cover none, trail none, size x1.0 | 12.79 | -70.3% |
| delay 0, stop none, flat hold, cover none, trail none, size x1.0 | 12.57 | -70.3% |
| delay 15, stop x1.5, flat hold, cover none, trail none, size x1.0 | 12.11 | -69.8% |
| delay 15, stop x1.25, flat hold, cover none, trail none, size x1.0 | 12.09 | -69.8% |
| delay 15, stop x0.75, flat hold, cover none, trail none, size x1.0 | 12.01 | -69.8% |
| delay 15, stop x1.0, flat hold, cover none, trail none, size x1.0 | 11.98 | -69.8% |
| delay 15, stop none, flat hold, cover none, trail none, size x1.0 | 11.76 | -69.8% |

## Q3. From $2,000 (central case, base costs; ruin = at or under $500)

| book | median | ruin | p10 | -50% |
|---|---|---|---|---|
| shield rule | $8,296 | 0.3% | $2,967 | 5.4% |
| walk-forward | $8,348 | 10.5% | $0 | 15.7% |

## Counts (all final replays)

{}
