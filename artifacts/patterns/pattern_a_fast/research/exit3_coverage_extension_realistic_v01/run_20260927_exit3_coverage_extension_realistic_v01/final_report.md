# Exit3 coverage extension realistic portfolio backtest V01

Run: run_20260927_exit3_coverage_extension_realistic_v01

## Verdict

MIXED_NO_CLEAR_WINNER

Only holding-lifecycle C1 trades gain a first PROGRESSED departure Exit3. The certified T15 entries, Exit4 15pt, Loss Guard, PIT filter, execution, cost, capital, and universe contracts remain frozen. No production promotion is made.

## Account performance

| Window | Strategy | Final Asset | Cumulative Return | CAGR | MDD | Realized Net P/L | Turnover | Utilization | Avg Idle Cash | Cash Skips | Filled / Realized / Open |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P2-1 | CONTROL | 230,372,653.50 KRW | 15.19% | 3.27% | -30.19% | -8,809,401.75 KRW | 1,768,957,441.37 KRW | 86.37% | 25,130,467.14 KRW | 156 | 199/161/38 |
| P2-1 | TEST | 242,156,047.07 KRW | 21.08% | 4.44% | -28.49% | -5,719,613.22 KRW | 1,986,201,750.97 KRW | 83.30% | 31,041,761.68 KRW | 136 | 219/184/35 |
| P2-2 | CONTROL | 369,288,642.98 KRW | 84.64% | 11.46% | -30.80% | 139,733,515.22 KRW | 2,416,285,709.66 KRW | 87.72% | 28,030,007.08 KRW | 243 | 242/218/27 |
| P2-2 | TEST | 355,330,012.44 KRW | 77.67% | 10.70% | -31.15% | 127,260,212.66 KRW | 2,566,658,848.50 KRW | 86.80% | 30,027,162.88 KRW | 229 | 256/237/22 |
| P3-2 | CONTROL | 371,154,513.82 KRW | 85.58% | 14.20% | -15.14% | 149,026,076.54 KRW | 2,301,623,428.78 KRW | 77.81% | 50,479,566.01 KRW | 177 | 228/207/24 |
| P3-2 | TEST | 383,745,334.36 KRW | 91.87% | 15.02% | -15.52% | 148,635,255.61 KRW | 2,373,786,358.97 KRW | 77.41% | 52,285,369.40 KRW | 171 | 234/216/21 |

Account deltas are TEST minus CONTROL; see portfolio_summary_delta.csv.

## Win/Loss statistics

- P2-1 CONTROL: win rate 22.98%; wins/losses/flat 37/124/0; average/median win 49.93%/26.72%; average/median loss -16.46%/-16.23%; payoff 3.03; profit factor 0.91; expectancy -1.20% and -54,716.78 KRW per trade.
- P2-1 TEST: win rate 25.00%; wins/losses/flat 46/138/0; average/median win 46.83%/26.94%; average/median loss -16.54%/-16.32%; payoff 2.83; profit factor 0.95; expectancy -0.70% and -31,084.85 KRW per trade.
- P2-2 CONTROL: win rate 30.28%; wins/losses/flat 66/152/0; average/median win 80.99%/64.07%; average/median loss -16.80%/-16.19%; payoff 4.82; profit factor 2.11; expectancy 12.81% and 640,979.43 KRW per trade.
- P2-2 TEST: win rate 29.54%; wins/losses/flat 70/167/0; average/median win 76.29%/55.10%; average/median loss -16.73%/-16.30%; payoff 4.56; profit factor 1.92; expectancy 10.74% and 536,962.92 KRW per trade.
- P3-2 CONTROL: win rate 30.43%; wins/losses/flat 63/144/0; average/median win 85.53%/77.14%; average/median loss -16.68%/-16.32%; payoff 5.13; profit factor 2.26; expectancy 14.43% and 719,932.74 KRW per trade.
- P3-2 TEST: win rate 31.02%; wins/losses/flat 67/149/0; average/median win 81.25%/70.46%; average/median loss -16.52%/-16.27%; payoff 4.92; profit factor 2.22; expectancy 13.81% and 688,126.18 KRW per trade.

## Return distribution

- P2-1 CONTROL STRATEGY_PATH_GROSS_ALL_ELIGIBLE: n=355; mean/median/P25/P75=4.49%/-14.90%/-16.36%/17.04%; >=+20/+30/+50/+100/+200=84/59/38/11/1; <=-15/-30/-40/-50/-60=174/8/2/0/0.
- P2-1 CONTROL PORTFOLIO_NET_REALIZED_CLOSED: n=161; mean/median/P25/P75=-1.20%/-15.69%/-16.87%/-11.66%; >=+20/+30/+50/+100/+200=25/17/11/7/1; <=-15/-30/-40/-50/-60=107/2/0/0/0.
- P2-1 TEST STRATEGY_PATH_GROSS_ALL_ELIGIBLE: n=355; mean/median/P25/P75=3.98%/-14.87%/-16.29%/15.68%; >=+20/+30/+50/+100/+200=80/55/35/10/1; <=-15/-30/-40/-50/-60=172/4/0/0/0.
- P2-1 TEST PORTFOLIO_NET_REALIZED_CLOSED: n=184; mean/median/P25/P75=-0.70%/-15.69%/-16.88%/-0.08%; >=+20/+30/+50/+100/+200=32/20/13/7/1; <=-15/-30/-40/-50/-60=118/3/0/0/0.
- P2-2 CONTROL STRATEGY_PATH_GROSS_ALL_ELIGIBLE: n=485; mean/median/P25/P75=15.36%/-14.63%/-16.16%/28.65%; >=+20/+30/+50/+100/+200=137/117/99/42/5; <=-15/-30/-40/-50/-60=226/8/4/3/1.
- P2-2 CONTROL PORTFOLIO_NET_REALIZED_CLOSED: n=218; mean/median/P25/P75=12.81%/-15.52%/-16.68%/17.94%; >=+20/+30/+50/+100/+200=53/44/37/21/3; <=-15/-30/-40/-50/-60=125/5/2/1/0.
- P2-2 TEST STRATEGY_PATH_GROSS_ALL_ELIGIBLE: n=485; mean/median/P25/P75=15.46%/-14.56%/-16.14%/26.40%; >=+20/+30/+50/+100/+200=134/115/98/42/5; <=-15/-30/-40/-50/-60=223/6/2/1/0.
- P2-2 TEST PORTFOLIO_NET_REALIZED_CLOSED: n=237; mean/median/P25/P75=10.74%/-15.59%/-16.87%/16.32%; >=+20/+30/+50/+100/+200=53/43/37/21/3; <=-15/-30/-40/-50/-60=135/5/2/1/0.
- P3-2 CONTROL STRATEGY_PATH_GROSS_ALL_ELIGIBLE: n=405; mean/median/P25/P75=17.40%/-14.54%/-16.16%/40.84%; >=+20/+30/+50/+100/+200=121/109/95/38/3; <=-15/-30/-40/-50/-60=186/4/2/0/0.
- P3-2 CONTROL PORTFOLIO_NET_REALIZED_CLOSED: n=207; mean/median/P25/P75=14.43%/-15.59%/-16.93%/20.01%; >=+20/+30/+50/+100/+200=52/48/43/21/2; <=-15/-30/-40/-50/-60=119/2/1/0/0.
- P3-2 TEST STRATEGY_PATH_GROSS_ALL_ELIGIBLE: n=405; mean/median/P25/P75=17.33%/-14.53%/-16.13%/32.50%; >=+20/+30/+50/+100/+200=119/107/94/38/3; <=-15/-30/-40/-50/-60=184/3/1/0/0.
- P3-2 TEST PORTFOLIO_NET_REALIZED_CLOSED: n=216; mean/median/P25/P75=13.81%/-15.54%/-16.86%/17.36%; >=+20/+30/+50/+100/+200=53/48/43/21/2; <=-15/-30/-40/-50/-60=121/2/1/0/0.

## MFE / MAE / giveback

MFE/MAE are price-path returns. Realized giveback and capture ratio use net realized return after the certified costs; +50 and +100 winner capture are included in mfe_mae_comparison.csv.

- P2-1 CONTROL MFE_PCT_FILLED: n=199, mean/median/P25/P75=30.34/15.63/4.85/38.62.
- P2-1 CONTROL MAE_PCT_FILLED: n=199, mean/median/P25/P75=-15.31/-16.17/-17.59/-11.10.
- P2-1 CONTROL REALIZED_NET_GIVEBACK_PP: n=161, mean/median/P25/P75=29.99/22.60/18.32/35.30.
- P2-1 CONTROL REALIZED_NET_PROFIT_CAPTURE_RATIO: n=157, mean/median/P25/P75=-3.85/-1.32/-3.95/-0.05.
- P2-1 CONTROL GE_POS_50_WINNER_CAPTURE: n=11, mean/median/P25/P75=0.79/0.73/0.71/0.90.
- P2-1 CONTROL GE_POS_100_WINNER_CAPTURE: n=7, mean/median/P25/P75=0.84/0.87/0.74/0.93.
- P2-1 TEST MFE_PCT_FILLED: n=219, mean/median/P25/P75=30.53/15.63/4.93/41.33.
- P2-1 TEST MAE_PCT_FILLED: n=219, mean/median/P25/P75=-14.63/-16.12/-17.31/-10.81.
- P2-1 TEST REALIZED_NET_GIVEBACK_PP: n=184, mean/median/P25/P75=29.91/22.76/18.30/35.63.
- P2-1 TEST REALIZED_NET_PROFIT_CAPTURE_RATIO: n=180, mean/median/P25/P75=-3.58/-1.21/-3.76/0.04.
- P2-1 TEST GE_POS_50_WINNER_CAPTURE: n=13, mean/median/P25/P75=0.82/0.77/0.72/0.94.
- P2-1 TEST GE_POS_100_WINNER_CAPTURE: n=7, mean/median/P25/P75=0.84/0.87/0.74/0.93.
- P2-2 CONTROL MFE_PCT_FILLED: n=242, mean/median/P25/P75=49.49/21.20/5.47/62.31.
- P2-2 CONTROL MAE_PCT_FILLED: n=242, mean/median/P25/P75=-15.99/-16.36/-17.79/-11.65.
- P2-2 CONTROL REALIZED_NET_GIVEBACK_PP: n=218, mean/median/P25/P75=33.00/24.55/18.63/39.28.
- P2-2 CONTROL REALIZED_NET_PROFIT_CAPTURE_RATIO: n=213, mean/median/P25/P75=-3.21/-0.93/-2.86/0.34.
- P2-2 CONTROL GE_POS_50_WINNER_CAPTURE: n=37, mean/median/P25/P75=0.79/0.80/0.70/0.89.
- P2-2 CONTROL GE_POS_100_WINNER_CAPTURE: n=21, mean/median/P25/P75=0.82/0.87/0.73/0.91.
- P2-2 TEST MFE_PCT_FILLED: n=256, mean/median/P25/P75=46.51/19.88/5.41/51.86.
- P2-2 TEST MAE_PCT_FILLED: n=256, mean/median/P25/P75=-16.08/-16.46/-17.97/-11.72.
- P2-2 TEST REALIZED_NET_GIVEBACK_PP: n=237, mean/median/P25/P75=32.63/24.27/18.37/40.48.
- P2-2 TEST REALIZED_NET_PROFIT_CAPTURE_RATIO: n=232, mean/median/P25/P75=-4.15/-0.90/-2.89/0.32.
- P2-2 TEST GE_POS_50_WINNER_CAPTURE: n=37, mean/median/P25/P75=0.80/0.83/0.72/0.90.
- P2-2 TEST GE_POS_100_WINNER_CAPTURE: n=21, mean/median/P25/P75=0.83/0.88/0.75/0.93.
- P3-2 CONTROL MFE_PCT_FILLED: n=228, mean/median/P25/P75=49.27/19.66/4.99/67.60.
- P3-2 CONTROL MAE_PCT_FILLED: n=228, mean/median/P25/P75=-15.33/-16.32/-17.90/-11.61.
- P3-2 CONTROL REALIZED_NET_GIVEBACK_PP: n=207, mean/median/P25/P75=33.38/24.41/18.54/43.18.
- P3-2 CONTROL REALIZED_NET_PROFIT_CAPTURE_RATIO: n=202, mean/median/P25/P75=-5.14/-0.90/-3.34/0.42.
- P3-2 CONTROL GE_POS_50_WINNER_CAPTURE: n=43, mean/median/P25/P75=0.78/0.80/0.67/0.89.
- P3-2 CONTROL GE_POS_100_WINNER_CAPTURE: n=21, mean/median/P25/P75=0.81/0.87/0.72/0.91.
- P3-2 TEST MFE_PCT_FILLED: n=234, mean/median/P25/P75=50.23/19.66/4.97/66.95.
- P3-2 TEST MAE_PCT_FILLED: n=234, mean/median/P25/P75=-15.06/-16.30/-17.85/-11.48.
- P3-2 TEST REALIZED_NET_GIVEBACK_PP: n=216, mean/median/P25/P75=33.63/24.55/18.69/43.28.
- P3-2 TEST REALIZED_NET_PROFIT_CAPTURE_RATIO: n=211, mean/median/P25/P75=-5.20/-0.86/-3.34/0.38.
- P3-2 TEST GE_POS_50_WINNER_CAPTURE: n=43, mean/median/P25/P75=0.78/0.80/0.67/0.89.
- P3-2 TEST GE_POS_100_WINNER_CAPTURE: n=21, mean/median/P25/P75=0.81/0.87/0.72/0.91.

## Holding & capital rotation

- P2-1 CONTROL: mean/median/P25/P75 holding sessions=170.81/78.00/32.00/183.50.
- P2-1 TEST: mean/median/P25/P75 holding sessions=149.14/86.00/34.50/192.00.
- P2-2 CONTROL: mean/median/P25/P75 holding sessions=196.81/90.50/35.00/215.25.
- P2-2 TEST: mean/median/P25/P75 holding sessions=180.39/80.50/32.75/197.25.
- P3-2 CONTROL: mean/median/P25/P75 holding sessions=155.58/79.00/32.75/205.00.
- P3-2 TEST: mean/median/P25/P75 holding sessions=149.97/79.00/33.00/205.00.

Sale proceeds become available on the next certified local trading session, never the same day. Test-only cash-shortage fills and their realized P/L are in capital_rotation_analysis.csv; detailed Exit3 releases are in early_exit3_cash_release.csv.

## Exit structure

- P2-1 CONTROL Exit4: strategy paths 86; closed portfolio fills 40; new C1 Exit3 0; open at cutoff 0.
- P2-1 CONTROL Exit3: strategy paths 8; closed portfolio fills 4; new C1 Exit3 0; open at cutoff 0.
- P2-1 CONTROL Loss Guard: strategy paths 197; closed portfolio fills 117; new C1 Exit3 0; open at cutoff 0.
- P2-1 CONTROL No Exit / cutoff: strategy paths 64; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 64.
- P2-1 CONTROL Other: strategy paths 0; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 0.
- P2-1 TEST Exit4: strategy paths 86; closed portfolio fills 47; new C1 Exit3 0; open at cutoff 0.
- P2-1 TEST Exit3: strategy paths 27; closed portfolio fills 13; new C1 Exit3 19; open at cutoff 0.
- P2-1 TEST Loss Guard: strategy paths 197; closed portfolio fills 124; new C1 Exit3 0; open at cutoff 0.
- P2-1 TEST No Exit / cutoff: strategy paths 45; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 45.
- P2-1 TEST Other: strategy paths 0; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 0.
- P2-2 CONTROL Exit4: strategy paths 162; closed portfolio fills 73; new C1 Exit3 0; open at cutoff 0.
- P2-2 CONTROL Exit3: strategy paths 16; closed portfolio fills 8; new C1 Exit3 0; open at cutoff 0.
- P2-2 CONTROL Loss Guard: strategy paths 268; closed portfolio fills 137; new C1 Exit3 0; open at cutoff 0.
- P2-2 CONTROL No Exit / cutoff: strategy paths 39; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 39.
- P2-2 CONTROL Other: strategy paths 0; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 0.
- P2-2 TEST Exit4: strategy paths 162; closed portfolio fills 75; new C1 Exit3 0; open at cutoff 0.
- P2-2 TEST Exit3: strategy paths 27; closed portfolio fills 14; new C1 Exit3 11; open at cutoff 0.
- P2-2 TEST Loss Guard: strategy paths 268; closed portfolio fills 148; new C1 Exit3 0; open at cutoff 0.
- P2-2 TEST No Exit / cutoff: strategy paths 28; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 28.
- P2-2 TEST Other: strategy paths 0; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 0.
- P3-2 CONTROL Exit4: strategy paths 126; closed portfolio fills 65; new C1 Exit3 0; open at cutoff 0.
- P3-2 CONTROL Exit3: strategy paths 12; closed portfolio fills 9; new C1 Exit3 0; open at cutoff 0.
- P3-2 CONTROL Loss Guard: strategy paths 231; closed portfolio fills 133; new C1 Exit3 0; open at cutoff 0.
- P3-2 CONTROL No Exit / cutoff: strategy paths 36; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 36.
- P3-2 CONTROL Other: strategy paths 0; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 0.
- P3-2 TEST Exit4: strategy paths 126; closed portfolio fills 66; new C1 Exit3 0; open at cutoff 0.
- P3-2 TEST Exit3: strategy paths 20; closed portfolio fills 14; new C1 Exit3 8; open at cutoff 0.
- P3-2 TEST Loss Guard: strategy paths 231; closed portfolio fills 136; new C1 Exit3 0; open at cutoff 0.
- P3-2 TEST No Exit / cutoff: strategy paths 28; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 28.
- P3-2 TEST Other: strategy paths 0; closed portfolio fills 0; new C1 Exit3 0; open at cutoff 0.

## Coverage/C1 subset

- P2-1 CONTROL: n=42, filled/realized=17/8, path mean/median=20.58%/21.65%, net realized win rate=62.50%, <=-30/-50/-60=6/0/0, median MFE/MAE=48.84%/-15.02%, median holding=294.50 sessions.
- P2-1 TEST: n=42, filled/realized=22/21, path mean/median=16.22%/12.56%, net realized win rate=52.38%, <=-30/-50/-60=2/0/0, median MFE/MAE=42.23%/-10.10%, median holding=223.00 sessions.
- P2-2 CONTROL: n=43, filled/realized=17/10, path mean/median=35.67%/28.93%, net realized win rate=60.00%, <=-30/-50/-60=3/2/1, median MFE/MAE=63.28%/-12.46%, median holding=279.00 sessions.
- P2-2 TEST: n=43, filled/realized=19/17, path mean/median=36.80%/25.49%, net realized win rate=58.82%, <=-30/-50/-60=1/0/0, median MFE/MAE=53.85%/-10.35%, median holding=258.00 sessions.
- P3-2 CONTROL: n=37, filled/realized=18/11, path mean/median=44.32%/32.50%, net realized win rate=72.73%, <=-30/-50/-60=2/0/0, median MFE/MAE=75.42%/-10.33%, median holding=271.00 sessions.
- P3-2 TEST: n=37, filled/realized=18/16, path mean/median=43.57%/30.62%, net realized win rate=68.75%, <=-30/-50/-60=1/0/0, median MFE/MAE=61.36%/-10.29%, median holding=263.00 sessions.

## Deep-loss rescue

- P2-1 C1 <= -30%: CONTROL deep-loss 6; rescued above threshold 4; saved path return sum 138.00 pp; both-filled rescues 3; end-position P/L delta 3,523,700.15 KRW.
- P2-1 C1 <= -40%: CONTROL deep-loss 2; rescued above threshold 2; saved path return sum 90.19 pp; both-filled rescues 1; end-position P/L delta 1,182,664.79 KRW.
- P2-1 C1 <= -50%: CONTROL deep-loss 0; rescued above threshold 0; saved path return sum 0.00 pp; both-filled rescues 0; end-position P/L delta 0.00 KRW.
- P2-1 C1 <= -60%: CONTROL deep-loss 0; rescued above threshold 0; saved path return sum 0.00 pp; both-filled rescues 0; end-position P/L delta 0.00 KRW.
- P2-2 C1 <= -30%: CONTROL deep-loss 3; rescued above threshold 2; saved path return sum 111.33 pp; both-filled rescues 1; end-position P/L delta 1,658,664.79 KRW.
- P2-2 C1 <= -40%: CONTROL deep-loss 2; rescued above threshold 2; saved path return sum 111.33 pp; both-filled rescues 1; end-position P/L delta 1,658,664.79 KRW.
- P2-2 C1 <= -50%: CONTROL deep-loss 2; rescued above threshold 2; saved path return sum 111.33 pp; both-filled rescues 1; end-position P/L delta 1,658,664.79 KRW.
- P2-2 C1 <= -60%: CONTROL deep-loss 1; rescued above threshold 1; saved path return sum 76.82 pp; both-filled rescues 0; end-position P/L delta 0.00 KRW.
- P3-2 C1 <= -30%: CONTROL deep-loss 2; rescued above threshold 1; saved path return sum 37.98 pp; both-filled rescues 1; end-position P/L delta 1,880,539.24 KRW.
- P3-2 C1 <= -40%: CONTROL deep-loss 1; rescued above threshold 1; saved path return sum 37.98 pp; both-filled rescues 1; end-position P/L delta 1,880,539.24 KRW.
- P3-2 C1 <= -50%: CONTROL deep-loss 0; rescued above threshold 0; saved path return sum 0.00 pp; both-filled rescues 0; end-position P/L delta 0.00 KRW.
- P3-2 C1 <= -60%: CONTROL deep-loss 0; rescued above threshold 0; saved path return sum 0.00 pp; both-filled rescues 0; end-position P/L delta 0.00 KRW.

## Winner damage

- P2-1 prior CONTROL >=+50.00% winners reduced below threshold: 3.00; both-filled 1.00; end-position contribution delta -6,342,338.54 KRW.
- P2-1 prior CONTROL >=+100.00% winners reduced below threshold: 1.00; both-filled 1.00; end-position contribution delta -6,342,338.54 KRW.
- P2-1 prior CONTROL >=+200.00% winners reduced below threshold: 0.00; both-filled 0.00; end-position contribution delta 0.00 KRW.
- P2-2 prior CONTROL >=+50.00% winners reduced below threshold: 1.00; both-filled 0.00; end-position contribution delta 0.00 KRW.
- P2-2 prior CONTROL >=+100.00% winners reduced below threshold: 0.00; both-filled 0.00; end-position contribution delta 0.00 KRW.
- P2-2 prior CONTROL >=+200.00% winners reduced below threshold: 0.00; both-filled 0.00; end-position contribution delta 0.00 KRW.
- P3-2 prior CONTROL >=+50.00% winners reduced below threshold: 1.00; both-filled 0.00; end-position contribution delta 0.00 KRW.
- P3-2 prior CONTROL >=+100.00% winners reduced below threshold: 0.00; both-filled 0.00; end-position contribution delta 0.00 KRW.
- P3-2 prior CONTROL >=+200.00% winners reduced below threshold: 0.00; both-filled 0.00; end-position contribution delta 0.00 KRW.

Top ten most harmed extended C1 trades per window are listed as TOP rows in winner_damage.csv, with CONTROL/TEST returns and portfolio contribution deltas.

## Paired Trade comparison

paired_trade_comparison.csv contains every frozen entry identity, exit reason/date, holding delta, path return, MFE/MAE, holding-lifecycle class, first PROGRESSED/departure dates and stage, portfolio fill status, net realized outcomes, and end-position P/L contribution.

## Window consistency

TEST final asset is higher in 2/3 windows; C1 mean path return is higher in 1/3 windows. The windows overlap and are not independent replications.

## Final interpretation

1. Final Asset and CAGR are reported for all three windows; account-level results take priority.
2. Win rate is net realized return greater than zero and excludes open positions.
3. Deep-loss counts use CONTROL/TEST trade-path returns; saved portfolio P/L is separately limited to pairs filled in both accounts.
4. Winner loss counts compare the prior CONTROL return with the TEST return at +50, +100, and +200.
5. Giveback, profit capture, and +50/+100 winner capture are listed in the MFE/MAE table.
6. Holding days and T+1 capital release use the realistic portfolio replay.
7. C1 subset and whole-account effects are separate.
8. Direction across windows is reported, with the overlap limitation.
9. Exit4 remains 15pt; this research does not promote a production strategy.

## Validation

- P2-1: source_status=P2_1_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED; source_control_rows=355; source_control_portfolio_replay_parity=PASS; entry_identity_parity=PASS; exit_only_parity=PASS; C1_holding_count=42; held_first_departure_count=19; applied_Exit3_extension_count=19; archived_C1_identity_and_event_parity=True; PIT_entry_audit=PASS; source_execution_contract=PASS; sparse_fallback_control_test={'control': {'status': 'PASS', 'fallback_tickers': [], 'executed_fallback_entries': 0, 'cash_skip_entries': 0}, 'test': {'status': 'PASS', 'fallback_tickers': [], 'executed_fallback_entries': 0, 'cash_skip_entries': 0}}; test_unresolved_count=0; test_cash_conservation_pass=True; stage_cache_sha256=ac670c372cca9a3029308f41923072a8214461b4971ba85295982ce4a853f817; stage_leakage_sample_size=20; stage_leakage_mismatch_count=0; stage_effective_dates_within_control_holding_end=True; network_calls=0.
- P2-2: source_status=P2_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED; source_control_rows=485; source_control_portfolio_replay_parity=PASS; entry_identity_parity=PASS; exit_only_parity=PASS; C1_holding_count=43; held_first_departure_count=11; applied_Exit3_extension_count=11; archived_C1_identity_and_event_parity=True; PIT_entry_audit=PASS; source_execution_contract=PASS; sparse_fallback_control_test={'control': {'status': 'PASS', 'fallback_tickers': ['336570'], 'executed_fallback_entries': 0, 'cash_skip_entries': 1, 'entry_statuses': ['SKIPPED_CASH_UNAVAILABLE']}, 'test': {'status': 'PASS', 'fallback_tickers': ['336570'], 'executed_fallback_entries': 0, 'cash_skip_entries': 1, 'entry_statuses': ['SKIPPED_CASH_UNAVAILABLE']}}; test_unresolved_count=0; test_cash_conservation_pass=True; stage_cache_sha256=ac670c372cca9a3029308f41923072a8214461b4971ba85295982ce4a853f817; stage_leakage_sample_size=20; stage_leakage_mismatch_count=0; stage_effective_dates_within_control_holding_end=True; network_calls=0.
- P3-2: source_status=P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED; source_control_rows=405; source_control_portfolio_replay_parity=PASS; entry_identity_parity=PASS; exit_only_parity=PASS; C1_holding_count=37; held_first_departure_count=8; applied_Exit3_extension_count=8; archived_C1_identity_and_event_parity=True; PIT_entry_audit=PASS; source_execution_contract=PASS; sparse_fallback_control_test={'control': {'status': 'PASS', 'fallback_tickers': ['336570'], 'executed_fallback_entries': 0, 'cash_skip_entries': 1, 'entry_statuses': ['SKIPPED_CASH_UNAVAILABLE']}, 'test': {'status': 'PASS', 'fallback_tickers': ['336570'], 'executed_fallback_entries': 0, 'cash_skip_entries': 1, 'entry_statuses': ['SKIPPED_CASH_UNAVAILABLE']}}; test_unresolved_count=0; test_cash_conservation_pass=True; stage_cache_sha256=ac670c372cca9a3029308f41923072a8214461b4971ba85295982ce4a853f817; stage_leakage_sample_size=20; stage_leakage_mismatch_count=0; stage_effective_dates_within_control_holding_end=True; network_calls=0.

Holding-stage observations were clipped at the CONTROL holding end. No post-exit stage was used. The first PROGRESSED departure uses the existing V2 outcome calculator and next local session open. No API/network call was made.

## Git

- Start HEAD: e69df4583cc0bac129f01bf6ba1bbc03189551e3
- End HEAD: this research output commit on main
- Commit: research: add Exit3 coverage extension realistic backtest
- Push: origin/main
- HEAD == origin/main: verify after push
