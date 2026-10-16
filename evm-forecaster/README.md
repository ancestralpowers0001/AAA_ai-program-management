# EVM Forecaster

**The problem.** A monthly EVM report usually shows CPI, SPI and a single EAC. Leadership nods, and the program keeps reporting to a budget it stopped tracking to months ago. The data to see that coming is already in the report. It just isn't turned into a decision.

**What this does.** Give it cumulative PV, EV and AC by period. It returns:

1. A bottom line written for a program leader: where cost and schedule will land, and what to decide
2. Three EAC methods side by side, with when to trust each one
3. A TCPI recovery check that calls out a recovery plan that won't happen
4. An **Earned Schedule** finish date forecast, which stays accurate late in a program when classic SPI stops being useful
5. An S-curve chart

## Sample output

From [the synthetic sample program](data/sample_program.csv), an 18-month job at month 9:

> **Bottom line:** the program is over budget and behind schedule. At current performance it finishes +5% to +23% against budget and about 2.2 periods late.
>
> **Recovery check:** finishing on the original budget needs a TCPI of 1.10 against a CPI to date of 0.89. That is not credible.
>
> **Ask:** stop reporting to the original budget. Approve a revised EAC in the range above and decide now whether to recover scope, schedule, or funding.

![EVM S-curve](examples/sample_chart.svg)

Full report: [examples/sample_report.md](examples/sample_report.md)

## Run it

Python 3.9 or newer, no packages to install.

```bash
python evm_forecaster.py data/sample_program.csv
python evm_forecaster.py data/sample_program.csv --status-period 6 --out report.md --svg chart.svg
python -m unittest discover -s tests
```

Input is a CSV with cumulative values per period. Future periods carry PV only:

```csv
period,pv,ev,ac
1,120,110,118
2,280,250,270
3,480,,
```

## The method, and why it matters

| Measure | Formula | What a PM does with it |
|---|---|---|
| CPI | EV / AC | Value earned per dollar spent. Past about 20% complete it rarely moves much, so it is a reliable early warning. |
| EAC (budget rate) | AC + (BAC - EV) | Best case. Only defensible if the overrun had a one-time cause. |
| EAC (CPI) | BAC / CPI | The most common realistic forecast. |
| EAC (CPI x SPI) | AC + (BAC - EV) / (CPI x SPI) | Worst case, for when leadership is pushing to recover the schedule. |
| TCPI | (BAC - EV) / (BAC - AC) | The efficiency the rest of the work must hit to finish on budget. More than about 0.10 above the CPI to date is a red flag. |
| Earned Schedule | Time at which today's EV was planned | Where the program really is in time, not in dollars. |
| SPI(t) | ES / actual time | Schedule efficiency that does not drift to 1.00 near the end like classic SPI does. |
| Forecast duration | Planned duration / SPI(t) | A finish date forecast built on performance, not optimism. |

## What I would add next

- An AI-written narrative on top of the deterministic numbers, with the calculations kept as a guardrail so the language can't drift from the math
- Control-account level input, so it points to which part of the work is driving the overrun
- Management reserve and an EAC confidence range

All data here is synthetic. See the [repository note](../README.md#about-the-data).
