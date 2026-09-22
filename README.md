# Empirical delay propagation on the Zürich–Chur railway corridor

A short empirical analysis of how arrival delays propagate along one Swiss main-line
corridor, using SBB's public operational data.

## Motivation

Railway timetables are designed for a nominal day where everything runs to plan.
In practice, small delays occur constantly and larger delays occasionally, and a
central question in transport research is whether a schedule that is optimal
on paper is also robust in operation — i.e., whether it absorbs incoming delay
or lets it propagate downstream. This analysis takes one main-line corridor
(Zürich HB ↔ Chur) and asks: how much of the delay observed at one station
carries forward to the next, and does the pattern vary along the corridor?

The finding is that the propagation coefficient varies substantially between
segments — some segments absorb delay strongly, others carry it almost
untouched — and that the absorbing segments cluster near the major stations
where being on time matters most for passenger connections.

## Data

The analysis uses [`ist-daten-v2`](https://data.opentransportdata.swiss/en/dataset/ist-daten-v2),
the actual-arrivals dataset published by the Business Office SKI on behalf of the
Swiss Federal Office of Transport (FOT). One CSV per operating day, one row per
train-stop event, with both scheduled and measured (`REAL`-status) times where
telemetry is available.

The dataset for 10 September 2026 contains 2,528,136 rows across all Swiss public
transport. After filtering to railway operations, valid non-cancelled trips,
`REAL`-status telemetry, and the nine corridor stations, 3,327 arrival events
remain across roughly 2,184 unique trains.

Corridor stations (in geographic order, Zürich → Chur):
Zürich HB, Thalwil, Pfäffikon SZ, Ziegelbrücke, Sargans, Bad Ragaz, Maienfeld,
Landquart, Chur.

Data attribution: *Data source: opentransportdata.swiss, published by SKI+ on
behalf of the Swiss Federal Office of Transport, licensed under CC-BY-4.0.*

## Method

For each of the eight adjacent-station segments along the corridor, the arrival
delay at the earlier station (`x`, in minutes) is regressed on the arrival
delay at the later station (`y`, in minutes) via ordinary least squares:
$y_i = α + β · x_i + ε_i$

The slope β is the **propagation coefficient**: $$\beta = 1$$ means delay carries
forward untouched; β = 0 means the segment fully absorbs incoming delay;
β < 1 indicates partial absorption. The intercept α measures the baseline
delay accretion for a punctual train — how many minutes late even an
on-time train tends to arrive at the next station.

Both travel directions (Zürich → Chur and Chur → Zürich) are pooled; the sample
size per segment ranges from 59 to 272 trains.

## Findings

Propagation is highly non-uniform along the corridor:

![Propagation coefficient along the corridor](plots/propagation_beta.png)

- Segments approaching the major terminals — Zürich HB and Chur — absorb roughly
  half of incoming delay (β ≈ 0.46).
- Segments in the middle of the corridor (Sargans → Bad Ragaz → Maienfeld) carry
  delay almost perfectly (β ∈ [0.90, 0.96]), with very little slack.
- One segment stands out: Pfäffikon SZ → Ziegelbrücke, with β ≈ 0.14 — an
  unusually strong absorber, possibly reflecting a generous scheduled running
  time or operational catch-up on that stretch.

The underlying delay distribution is heavily right-skewed:

![Distribution of arrival delays](plots/delay_distribution.png)

Median delay is 0.5 minutes; the 90th percentile is 2.5 minutes; the maximum
observed delay is 34.3 minutes. On-average metrics look excellent, but the
tail is where operational impact lives.

## Limitations

This is a first-cut exploratory analysis on a single day and should be read as
such.

- **One day.** Any day-specific idiosyncrasies (weather, incidents, service
  patterns) are baked into the point estimates. A multi-day analysis would
  separate stable structure from day-to-day noise.
- **Both directions pooled.** Buffer placement in real timetables is often
  asymmetric — slack tends to sit before major terminals in the direction of
  travel — but pooling averages this away.
- **Small-vs-large delay comparison not possible on this day.** Only ~10% of
  arrivals exceeded 3 minutes of delay; after requiring both-endpoint segment
  coverage, per-segment large-delay counts dropped to 0–22. Comparing
  propagation in the small-delay and large-delay regimes would require a day
  with more disruption.
- **Service categories pooled.** IC/ICE, IR, RE, and S services all contribute
  to the same per-segment regressions. Stratifying by service type would show
  whether the observed β reflects segment structure or train mix.
- **Standard errors are approximate.** Residuals are approximately mean-zero
  but have heavier right tails than Gaussian (see residual diagnostics in the
  notebook); the OLS-formula CIs are asymptotically valid but slightly
  optimistic.

Natural extensions are (1) a bad-day comparison to characterise the large-delay
regime, (2) a direction split with time-of-day stratification, and (3) using
the empirical β profile as input to a robust-timetabling optimisation, in the
tradition of Leutwiler & Corman's Benders-decomposition work.

## Reproducing the analysis

Requirements:

Or, from the included `requirements.txt`:

```bash
pip install -r requirements.txt
```

The CSV is ~614 MB and is not included in the repository. Download it directly
from opentransportdata.swiss:

```bash
wget https://opentransportdata.swiss/wp-content/uploads/ist-daten-archive/2026-09-10_IstDaten.csv
```

Then open `notebook.ipynb` and run the cells top to bottom.

## References

1. Büchel, B., Spanninger, T., & Corman, F. (2020). *Empirical dynamics of
   railway delay propagation identified during the large-scale Rastatt
   disruption.* Scientific Reports, 10, 18584.
   [DOI: 10.1038/s41598-020-75538-z](https://doi.org/10.1038/s41598-020-75538-z)

2. Leutwiler, F., & Corman, F. (2023). *Set-covering-based Benders
   decomposition heuristic for railway timetabling.*

## License

MIT — see `LICENSE`.

Analysis and code © 2026 Faisal Hussain Shah.
Data © opentransportdata.swiss (CC-BY-4.0).
