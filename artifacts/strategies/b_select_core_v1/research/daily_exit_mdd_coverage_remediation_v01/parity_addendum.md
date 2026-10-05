# Per-case transaction and terminal parity addendum

This additive audit uses the immutable sealed event/trade files and compares them with the valuation reconstruction boundary. No event or trade-ledger output was generated or replayed.

| Window | Scenario | event rows before=after | transaction signature | cash conservation failures | original valid-day value mismatch | cutoff cash before=after | support cash before=after | cutoff positions | terminal equity parity |
|---|---|---:|---|---:|---:|---|---|---:|---|
| P1 | CONTROL_MONTH_END | 918=918 | PASS | 0 | 0 | 33,095,595.37=33,095,595.37 | 33,095,595.37=33,095,595.37 | 81 | PASS |
| P1 | TEST_DAILY | 929=929 | PASS | 0 | 0 | 154,746,881.24=154,746,881.24 | 166,928,657.90=166,928,657.90 | 60 | PASS |
| P2-1 | CONTROL_MONTH_END | 391=391 | PASS | 0 | 0 | 134,622,177.71=134,622,177.71 | 134,622,177.71=134,622,177.71 | 37 | PASS |
| P2-1 | TEST_DAILY | 394=394 | PASS | 0 | 0 | 162,893,587.35=162,893,587.35 | 162,893,587.35=162,893,587.35 | 35 | PASS |
| P2-2 | CONTROL_MONTH_END | 590=590 | PASS | 0 | 0 | 34,319,698.69=34,319,698.69 | 34,319,698.69=34,319,698.69 | 56 | PASS |
| P2-2 | TEST_DAILY | 601=601 | PASS | 0 | 0 | 90,056,792.84=90,056,792.84 | 95,453,180.66=95,453,180.66 | 51 | PASS |
| P3-1 | CONTROL_MONTH_END | 320=320 | PASS | 0 | 0 | 123,178,769.49=123,178,769.49 | 123,178,769.49=123,178,769.49 | 34 | PASS |
| P3-1 | TEST_DAILY | 323=323 | PASS | 0 | 0 | 140,599,690.69=140,599,690.69 | 140,599,690.69=140,599,690.69 | 30 | PASS |
| P3-2 | CONTROL_MONTH_END | 517=517 | PASS | 0 | 0 | 34,482,772.74=34,482,772.74 | 34,482,772.74=34,482,772.74 | 52 | PASS |
| P3-2 | TEST_DAILY | 528=528 | PASS | 0 | 0 | 78,966,826.91=78,966,826.91 | 84,363,214.73=84,363,214.73 | 45 | PASS |

The CSV contains before/after SHA-256 and canonical signatures for the full event fields and transaction keys. The source files serve as both sides of the comparison because the postprocessor does not write transaction files. Daily cash, open-position count, cutoff/support equity and invested value on all previously valid days also match exactly or within the sealed engine's 1e-6 valuation tolerance.

Base remediation summary SHA-256: 1069e0b91f9668f68f69c554095102bdbed9c09494ebce09d1a562362a8aaa83.
