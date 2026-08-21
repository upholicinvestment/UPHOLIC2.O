# Frozen Breakout–Retest Scanner Validation

## Status

**Experimental forward watchlist only. No broker connection and no order placement.**

The scanner implements the frozen 1% extension, Call-IV-spike and quiet-retest hypothesis without threshold controls in the user interface. `LOCKED_RULE.json` is checked at startup; a changed parameter file stops the scanner.

## Automated checks

All four checks passed on 20 August 2026:

1. A valid 1% extension and retest at 20% of State 1 option volume creates exactly one signal, one hypothetical entry and the expected target exit.
2. A first retest at 40% of State 1 option volume is rejected.
3. An incomplete five-minute retest bucket cannot create a signal.
4. Changing the frozen 1% threshold to 2% makes the lock validation fail.

The scanner also compiled successfully on Python 3.13.

## Historical causal replay audit

A causal replay starting on 10 August generated five signals: PAYTM, MOTILALOFS, KEI, KAYNES and DRREDDY. GLENMARK from the exploratory six-event table was not generated because an earlier active state blocked it.

This difference is deliberate. The exploratory ranking applied the one-active rule after complete paths were known. The forward scanner chooses the earliest eligible State 1 in real time and cannot know which future candidate will eventually pass the quiet-retest filter. The causal scanner is therefore stricter and avoids using future knowledge.

## Current forward-test check

The supplied feature catalog ends on 19 August 2026. With the frozen forward start of 20 August 2026, the initial scan correctly generated zero forward signals and reported `STALE_DATA`.

New stock-option data must be exported into the source CSV before the scanner can produce a current watchlist. Raw source data is never changed.
