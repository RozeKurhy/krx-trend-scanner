# Fear Index V01 final formula

Selected candidate: `downside_sensitive_v01`

The score is bounded to 0-100 and uses only V-KOSPI 200, KOSPI close, and KOSPI trading value. All rolling features use current and prior observations only.

Regime guards:

- `PANIC`: score >= 72 and KOSPI downside (`20D return <= -5%` or `60D drawdown <= -10%`).
- `OVERHEATED`: strong positive KOSPI trend with adequate participation and no downside guard.
- `APATHY`: low score, weak/flat KOSPI, and participation percentile <= 40%.
- `ANXIOUS`: elevated score or downside not meeting PANIC.
- `NORMAL`: remaining available observations.

The downside guard is intentional: elevated V-KOSPI during a strong bull move cannot become PANIC automatically.
