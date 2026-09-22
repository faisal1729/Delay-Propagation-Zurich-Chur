# -*- coding: utf-8 -*-
# Empirical delay propagation on the Zürich–Chur railway corridor

**Data source:** [opentransportdata.swiss](https://data.opentransportdata.swiss/en/dataset/ist-daten-v2),
Business Office SKI (CC-BY-4.0).
See `README.md` for context, methodology, and limitations.

**Notebook structure**

1. Data loading and initial inspection
2. Filtering to trains, real-time telemetry, and the Zürich–Chur corridor
3. Delay computation
4. Distribution overview
5. Per-segment propagation regressions (β and α)
6. Residual diagnostics

##1. Data loading and initial inspection
"""

# to get the file directly from transportdata
url = "https://data.opentransportdata.swiss/dataset/febff1f3-ee85-470a-9487-2d07f93457c1/resource/4ac5bcf3-8dbc-4b12-b700-a6dac7dd7397/download/2026-09-10_istdaten.csv"
!wget -q "$url" -O ist_daten_2026_09_10.csv
!ls -lh ist_daten_2026_09_10.csv

csv_path = "ist_daten_2026_09_10.csv"

# we take a look at few lines to confirm delimiter and encoding
with open(csv_path, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if i < 3:
            print(repr(line))
        else:
            break

!wc -l ist_daten_2026_09_10.csv

"""This tells us the file is complete and matches the web preview"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

# nicer default plot style
plt.rcParams['figure.dpi'] = 100
plt.rcParams['savefig.dpi'] = 200
plt.rcParams['figure.figsize'] = (10, 5)
pd.set_option('display.max_columns', 30)
pd.set_option('display.width', 200)

# columns we actually need for delay-propagation analysis
usecols = [
    'BETRIEBSTAG', 'FAHRT_BEZEICHNER',
    'PRODUKT_ID', 'LINIEN_TEXT', 'VERKEHRSMITTEL_TEXT',
    'FAELLT_AUS_TF', 'DURCHFAHRT_TF',
    'BPUIC', 'HALTESTELLEN_NAME',
    'ANKUNFTSZEIT', 'AN_PROGNOSE', 'AN_PROGNOSE_STATUS',
    'ABFAHRTSZEIT', 'AB_PROGNOSE', 'AB_PROGNOSE_STATUS',
]

# dtype hints save memory and speed up the read
dtypes = {
    'BETRIEBSTAG': 'string',
    'FAHRT_BEZEICHNER': 'string',
    'PRODUKT_ID': 'category',
    'LINIEN_TEXT': 'string',
    'VERKEHRSMITTEL_TEXT': 'category',
    'BPUIC': 'string',        # string, not int — some rows have long SLOID-style values
    'HALTESTELLEN_NAME': 'string',
    'AN_PROGNOSE_STATUS': 'category',
    'AB_PROGNOSE_STATUS': 'category',
}

df = pd.read_csv(
    csv_path,
    sep=';',
    encoding='utf-8',
    usecols=usecols,
    dtype=dtypes,
    low_memory=False,
)

print(f"Loaded: {len(df):,} rows")
print(f"Memory: {df.memory_usage(deep=True).sum() / 1e6:.1f} MB")
print(f"Columns: {list(df.columns)}")
df.head(3)

"""And some sanity checks:"""

print("=== Product distribution ===")
print(df['PRODUKT_ID'].value_counts(dropna=False))

print("\n=== Prognose status distribution (arrival) ===")
print(df['AN_PROGNOSE_STATUS'].value_counts(dropna=False))

print("\n=== Prognose status distribution (departure) ===")
print(df['AB_PROGNOSE_STATUS'].value_counts(dropna=False))

print("\n=== Cancelled trips ===")
print(df['FAELLT_AUS_TF'].value_counts(dropna=False))

print("\n=== Pass-through (no stop) ===")
print(df['DURCHFAHRT_TF'].value_counts(dropna=False))

print("\n=== Top 15 service categories ===")
print(df['VERKEHRSMITTEL_TEXT'].value_counts().head(15))

"""## 2. Filtering to trains, real-time telemetry, and the Zürich–Chur corridor

let's do the cheap filters that apply universally
"""

# Step 1: restrict to trains, non-cancelled, non-passthrough
trains = df[
    (df['PRODUKT_ID'] == 'Zug') &
    (df['FAELLT_AUS_TF'] == False) &
    (df['DURCHFAHRT_TF'] == False)
].copy()

print(f"After train + not-cancelled + not-passthrough: {len(trains):,} rows")

# Step 2: check what fraction of TRAIN rows have REAL telemetry
print("\nTrain arrival status:")
print(trains['AN_PROGNOSE_STATUS'].value_counts(dropna=False))
print("\nTrain departure status:")
print(trains['AB_PROGNOSE_STATUS'].value_counts(dropna=False))

# Step 3: check the service-category distribution among trains
print("\nTrain service categories (top 15):")
print(trains['VERKEHRSMITTEL_TEXT'].value_counts().head(15))

# Look up the actual BPUIC codes for these station names.
# We use flexible substring matching because names can have small variations.
corridor_names = [
    'Zürich HB', 'Thalwil', 'Pfäffikon SZ', 'Ziegelbrücke',
    'Sargans', 'Bad Ragaz', 'Maienfeld', 'Landquart', 'Chur',
]

# For each candidate name, show which BPUIC codes appear in the data
for name in corridor_names:
    matches = trains[trains['HALTESTELLEN_NAME'].str.contains(
        name, case=False, na=False, regex=False
    )][['HALTESTELLEN_NAME', 'BPUIC']].drop_duplicates()

    print(f"\n=== {name} ===")
    print(matches.head(5).to_string(index=False))

# The canonical corridor (in geographical order Zurich → Chur)
corridor_ids = [
    '8503000',  # Zürich HB
    '8503202',  # Thalwil
    '8503209',  # Pfäffikon SZ
    '8503225',  # Ziegelbrücke
    '8509411',  # Sargans
    '8509004',  # Bad Ragaz
    '8509003',  # Maienfeld
    '8509002',  # Landquart
    '8509000',  # Chur
]

# ordering for later
corridor_order = {bpuic: i for i, bpuic in enumerate(corridor_ids)}
corridor_names_ordered = [
    'Zürich HB', 'Thalwil', 'Pfäffikon SZ', 'Ziegelbrücke',
    'Sargans', 'Bad Ragaz', 'Maienfeld', 'Landquart', 'Chur'
]

# Step 1: restrict to corridor stops with REAL arrival telemetry
mask = (
    trains['BPUIC'].isin(corridor_ids) &
    (trains['AN_PROGNOSE_STATUS'] == 'REAL')
)
corr = trains.loc[mask].copy()
print(f"Corridor rows with REAL arrival: {len(corr):,}")

# Step 2: parse timestamps
corr['scheduled_arr'] = pd.to_datetime(
    corr['ANKUNFTSZEIT'], format='%d.%m.%Y %H:%M', errors='coerce'
)
corr['actual_arr'] = pd.to_datetime(
    corr['AN_PROGNOSE'], format='%d.%m.%Y %H:%M', errors='coerce'
)

# Step 3: compute arrival delay in minutes (positive = late)
corr['arr_delay_min'] = (
    corr['actual_arr'] - corr['scheduled_arr']
).dt.total_seconds() / 60.0

# Step 4: add the corridor position index for later ordering
corr['corridor_pos'] = corr['BPUIC'].map(corridor_order)

# how does the delay distribution look?
print("\n=== Arrival delay distribution (minutes) ===")
print(corr['arr_delay_min'].describe(percentiles=[.05, .25, .5, .75, .9, .95, .99]))

# quick station-level summary
print("\n=== Rows per corridor station ===")
station_counts = (
    corr.groupby(['corridor_pos', 'HALTESTELLEN_NAME'])
        .size()
        .reset_index(name='n_arrivals')
        .sort_values('corridor_pos')
)
print(station_counts.to_string(index=False))

"""perhaps a time format mismatch"""

# What do the timestamp columns actually look like in the corridor subset?
print("=== ANKUNFTSZEIT samples ===")
print(corr['ANKUNFTSZEIT'].dropna().head(10).tolist())

print("\n=== AN_PROGNOSE samples ===")
print(corr['AN_PROGNOSE'].dropna().head(10).tolist())

print("\n=== dtype check ===")
print(f"ANKUNFTSZEIT dtype: {corr['ANKUNFTSZEIT'].dtype}")
print(f"AN_PROGNOSE dtype: {corr['AN_PROGNOSE'].dtype}")

print("\n=== null counts ===")
print(f"ANKUNFTSZEIT nulls: {corr['ANKUNFTSZEIT'].isna().sum()} / {len(corr)}")
print(f"AN_PROGNOSE nulls: {corr['AN_PROGNOSE'].isna().sum()} / {len(corr)}")

"""So the scheduled and actual times use different precisions.

## 3. Delay computation
"""

# Re-parse with the correct format for each column
corr['scheduled_arr'] = pd.to_datetime(
    corr['ANKUNFTSZEIT'], format='%d.%m.%Y %H:%M', errors='coerce'
)
corr['actual_arr'] = pd.to_datetime(
    corr['AN_PROGNOSE'], format='%d.%m.%Y %H:%M:%S', errors='coerce'
)

# Recompute arrival delay in minutes (positive = late)
corr['arr_delay_min'] = (
    corr['actual_arr'] - corr['scheduled_arr']
).dt.total_seconds() / 60.0

# Sanity check: any parse failures now?
print(f"Scheduled arrival NaT: {corr['scheduled_arr'].isna().sum()} / {len(corr)}")
print(f"Actual arrival NaT:    {corr['actual_arr'].isna().sum()} / {len(corr)}")
print(f"Delay NaN:             {corr['arr_delay_min'].isna().sum()} / {len(corr)}")

print("\n=== Arrival delay distribution (minutes) ===")
print(corr['arr_delay_min'].describe(percentiles=[.05, .25, .5, .75, .9, .95, .99]).round(2))

# Build train × station pivot: rows = trains, columns = corridor stations, values = arr_delay_min
# Use FAHRT_BEZEICHNER as the train identifier
delay_matrix = (
    corr
    .pivot_table(
        index='FAHRT_BEZEICHNER',
        columns='corridor_pos',
        values='arr_delay_min',
        aggfunc='first',   # if any train arrives twice at same station, take first
    )
    .sort_index(axis=1)
)

# Rename columns from corridor_pos indices to station names
delay_matrix.columns = [corridor_names_ordered[i] for i in delay_matrix.columns]
print(f"Train × station delay matrix: {delay_matrix.shape}")
print(delay_matrix.head())

# For each adjacent segment, count how many trains visit BOTH endpoints
print("\n=== Trains visiting both endpoints of each segment ===")
segments = list(zip(corridor_names_ordered[:-1], corridor_names_ordered[1:]))
for a, b in segments:
    n_both = delay_matrix[[a, b]].dropna().shape[0]
    print(f"  {a:16s} → {b:16s}  n = {n_both}")

"""So 2,184 unique trains visit at least one corridor station"""

from scipy import stats

# Threshold for the "large delay" regime
LARGE_DELAY_THRESHOLD = 3.0  # minutes; ~90th percentile

def fit_segment(x, y):
    """OLS regression of y on x. Returns dict with slope, intercept, R^2, n, std_err."""
    if len(x) < 5:
        return None
    result = stats.linregress(x, y)
    return {
        'n': len(x),
        'beta': result.slope,
        'alpha': result.intercept,
        'r2': result.rvalue ** 2,
        'p': result.pvalue,
        'se_beta': result.stderr,
    }

rows = []
for k in range(len(corridor_names_ordered) - 1):
    a = corridor_names_ordered[k]
    b = corridor_names_ordered[k + 1]

    pair = delay_matrix[[a, b]].dropna()
    if len(pair) < 5:
        continue

    # All trains
    all_fit = fit_segment(pair[a].values, pair[b].values)
    # Trains with large incoming delay
    large = pair[pair[a] > LARGE_DELAY_THRESHOLD]
    large_fit = fit_segment(large[a].values, large[b].values) if len(large) >= 5 else None
    # Trains with small incoming delay (for the contrast plot)
    small = pair[pair[a] <= LARGE_DELAY_THRESHOLD]
    small_fit = fit_segment(small[a].values, small[b].values) if len(small) >= 5 else None

    rows.append({
        'segment': f"{a} → {b}",
        'k': k,
        'n_all':   all_fit['n'],
        'beta_all': all_fit['beta'],
        'alpha_all': all_fit['alpha'],
        'r2_all':  all_fit['r2'],
        'n_small':  small_fit['n'] if small_fit else 0,
        'beta_small': small_fit['beta'] if small_fit else np.nan,
        'n_large':  large_fit['n'] if large_fit else 0,
        'beta_large': large_fit['beta'] if large_fit else np.nan,
    })

results = pd.DataFrame(rows)
print(results.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

"""### What this cell does

For each segment $k \to k+1$ on the corridor, we fit a simple linear regression of the outgoing arrival delay on the incoming arrival delay:

$$y_i = \alpha + \beta \, x_i + \varepsilon_i, \qquad i = 1, \dots, n$$

where for train $i$:
- $x_i$ is its arrival delay at station $k$ (in minutes),
- $y_i$ is its arrival delay at station $k+1$ (in minutes),
- $\varepsilon_i$ captures segment-specific noise (dwell variability, minor incidents, driver behaviour).

**Interpretation of the coefficients:**

- $\beta$ (**propagation coefficient**): how much of the incoming delay carries forward.
  - $\beta = 1$: delay carries forward perfectly (pure carrier segment).
  - $\beta = 0$: delay is fully absorbed (buffer / slack in the schedule).
  - $\beta < 1$: partial absorption.
  - $\beta > 1$: delay is amplified on this segment.

- $\alpha$ (**baseline accretion**): how many minutes late even an on-time train ($x_i=0$) arrives at the next station.
  - $\alpha > 0$: the schedule itself is slightly tight — trains lose time even without incoming delay.
  - $\alpha < 0$: on-time trains catch up further (schedule contains conservative running times).

**Estimation.** We use ordinary least squares (OLS): $\hat\alpha$ and $\hat\beta$ minimise $\sum_i (y_i - \alpha - \beta x_i)^2$. The closed-form solution is

$$\hat\beta = \frac{\operatorname{Cov}(x,y)}{\operatorname{Var}(x)}, \qquad \hat\alpha = \bar y - \hat\beta \bar x.$$

**Other returned quantities:**

- `r2` = $R^2$: fraction of the variance in outgoing delay explained by incoming delay. High $R^2$ means propagation is the dominant story on this segment; low $R^2$ means outgoing delay is largely driven by segment-specific noise, uncorrelated with what came in.
- `p`: two-sided p-value for the null hypothesis $\beta = 0$. Small $p$ means the slope is statistically distinguishable from zero.
- `se_beta`: standard error of $\hat\beta$. An approximate 95% confidence interval is $\hat\beta \pm 1.96 \cdot \text{SE}$.

**Implicit assumptions.**

1. Linearity of the incoming/outgoing delay relationship.
2. Homoscedastic, independent Gaussian residuals (approximately; delay data has heavy tails but sample sizes here are large enough for coefficient estimates to be trustworthy).
3. Correlations between trains sharing the same track window are not modelled — a first-cut analysis; more sophisticated approaches (delay propagation networks, Markov models) would relax this.

**Regime split.** We fit the regression twice per segment:
- once on all trains (`beta_all`),
- once restricted to trains with incoming delay $\le 3$ minutes (`beta_small`, ≈ 90th percentile of the delay distribution),
- once restricted to trains with incoming delay $> 3$ minutes (`beta_large`).

The comparison of `beta_small` and `beta_large` tests whether propagation behaves differently for small jitter versus real delays — a signal directly relevant to robust timetabling.

##4. Distribution overview
"""

fig, ax = plt.subplots(figsize=(9, 4.5))

delays = corr['arr_delay_min']

# Full range, no clipping
xmin, xmax = -3, 36
ax.hist(
    delays,
    bins=np.arange(xmin, xmax + 0.5, 0.5),
    color='#4C72B0',
    edgecolor='white',
    linewidth=0.6,
    alpha=0.9,
)

median = delays.median()
p90 = delays.quantile(0.90)
p99 = delays.quantile(0.99)

ax.axvline(median, linestyle='--', color='#333', linewidth=1.5)
ax.axvline(p90, linestyle='--', color='#C44E52', linewidth=1.5)

ax.annotate(
    f'median = {median:.1f} min',
    xy=(median, ax.get_ylim()[1] * 0.92),
    xytext=(median + 3.5, ax.get_ylim()[1] * 0.92),
    fontsize=11, color='#333',
    arrowprops=dict(arrowstyle='->', color='#333', lw=0.8),
)
ax.annotate(
    f'90th percentile = {p90:.1f} min',
    xy=(p90, ax.get_ylim()[1] * 0.72),
    xytext=(p90 + 3.5, ax.get_ylim()[1] * 0.72),
    fontsize=11, color='#C44E52',
    arrowprops=dict(arrowstyle='->', color='#C44E52', lw=0.8),
)

# Mark the max as a small label, not a clipped bin
ax.annotate(
    f'max = {delays.max():.1f} min',
    xy=(delays.max(), 5),
    xytext=(delays.max() - 6, 60),
    fontsize=10, color='#555',
    arrowprops=dict(arrowstyle='->', color='#555', lw=0.6),
)

ax.set_xlim(xmin, xmax)
ax.set_xlabel('Arrival delay (minutes)')
ax.set_ylabel('Number of arrivals')
ax.set_title(f'Zürich HB ↔ Chur corridor, 10 Sept 2026 — {len(delays):,} arrival events',
             fontsize=13)

plt.tight_layout()
plt.savefig('plot1_delay_distribution.png', bbox_inches='tight', facecolor='white', dpi=200)
plt.show()

"""## 5. Per-segment propagation regressions ($\beta$ and $\alpha$)"""

# ---- Plot 2: propagation coefficient along the corridor ----

# Build a small display-friendly frame for the plot
plot_df = results.copy()
plot_df['segment_short'] = [
    'Zürich HB\n→ Thalwil',
    'Thalwil\n→ Pfäffikon SZ',
    'Pfäffikon SZ\n→ Ziegelbrücke',
    'Ziegelbrücke\n→ Sargans',
    'Sargans\n→ Bad Ragaz',
    'Bad Ragaz\n→ Maienfeld',
    'Maienfeld\n→ Landquart',
    'Landquart\n→ Chur',
]

# recompute SE_beta so we can plot 95% CI
# (we already have this in the results table from linregress, but let's make sure)
se_by_segment = []
for k in range(len(corridor_names_ordered) - 1):
    a, b = corridor_names_ordered[k], corridor_names_ordered[k+1]
    pair = delay_matrix[[a, b]].dropna()
    res = stats.linregress(pair[a].values, pair[b].values)
    se_by_segment.append(res.stderr)
plot_df['se_beta'] = se_by_segment
plot_df['ci95'] = 1.96 * plot_df['se_beta']

fig, ax = plt.subplots(figsize=(10, 5.5))

x = np.arange(len(plot_df))
y = plot_df['beta_all'].values
yerr = plot_df['ci95'].values

# Connect points with a thin light line, then overlay dots with errorbars
ax.plot(x, y, color='#888', linewidth=1, zorder=1)
ax.errorbar(
    x, y, yerr=yerr,
    fmt='o', markersize=10,
    color='#2E5A88',
    ecolor='#2E5A88', elinewidth=1.5, capsize=5,
    zorder=2,
)

# Reference lines
ax.axhline(1.0, linestyle='--', color='#C44E52', linewidth=1.2, alpha=0.8)
ax.text(len(plot_df) - 0.4, 1.03, 'β = 1  (delay carries forward)',
        color='#C44E52', fontsize=10, ha='right', va='bottom')

ax.axhline(0.0, linestyle=':', color='#999', linewidth=1)
ax.text(len(plot_df) - 0.4, -0.03, 'β = 0  (delay fully absorbed)',
        color='#666', fontsize=10, ha='right', va='top')

# n= labels under each point
ymin_pos = min(y - yerr) - 0.15
for i, n in enumerate(plot_df['n_all']):
    ax.text(i, ymin_pos, f'n = {n}', ha='center', va='top',
            fontsize=10, color='#555')

# Axes
ax.set_xticks(x)
ax.set_xticklabels(plot_df['segment_short'], fontsize=10)
ax.set_ylabel('Propagation coefficient  β')
ax.set_title('Delay propagation along the Zürich HB ↔ Chur corridor',fontsize=13)

ax.set_ylim(ymin_pos - 0.1, 1.25)

plt.tight_layout()
plt.savefig('plot2_propagation_beta.png', bbox_inches='tight', facecolor='white', dpi=200)
plt.show()

"""## 6. Residual diagnostics"""

# Two-segment version, sized for a 16:9 slide
fig, axes = plt.subplots(2, 2, figsize=(11, 8))

segments_to_show = [
    (0, 'Zürich HB → Thalwil'),         # absorbing, low R², high variability
    (5, 'Bad Ragaz → Maienfeld'),       # carrier, high R², tight residuals
]

for col, (k, label) in enumerate(segments_to_show):
    a = corridor_names_ordered[k]
    b = corridor_names_ordered[k + 1]

    pair = delay_matrix[[a, b]].dropna()
    x = pair[a].values
    y = pair[b].values

    result = stats.linregress(x, y)
    y_hat = result.intercept + result.slope * x
    residuals = y - y_hat

    # Top: residuals vs fitted
    ax_top = axes[0, col]
    ax_top.scatter(y_hat, residuals, s=25, alpha=0.55, color='#4C72B0')
    ax_top.axhline(0, color='#C44E52', linewidth=1.2, linestyle='--')
    ax_top.set_title(f"{label}\n(n = {len(x)}, β = {result.slope:.2f}, R² = {result.rvalue**2:.2f})",
                     fontsize=12)
    ax_top.set_ylabel("Residual (min)", fontsize=11)
    ax_top.set_xlabel("Fitted ŷ", fontsize=11)
    ax_top.grid(True, alpha=0.2)

    # Bottom: Q-Q vs normal
    ax_bot = axes[1, col]
    stats.probplot(residuals, dist='norm', plot=ax_bot)
    ax_bot.set_title("")
    ax_bot.get_lines()[0].set_markerfacecolor('#4C72B0')
    ax_bot.get_lines()[0].set_markeredgecolor('#4C72B0')
    ax_bot.get_lines()[0].set_markersize(5)
    ax_bot.get_lines()[1].set_color('#C44E52')
    ax_bot.set_ylabel("Ordered residuals", fontsize=11)
    ax_bot.set_xlabel("Theoretical quantile", fontsize=11)
    ax_bot.grid(True, alpha=0.2)

plt.tight_layout()
plt.savefig('residual_diagnostics_slide.png', bbox_inches='tight', facecolor='white', dpi=200)
plt.show()
