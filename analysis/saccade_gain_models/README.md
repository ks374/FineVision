# First-saccade gain and latency analysis

This folder contains the complete reproducible pipeline for the 2026-08-06 and
both 2026-08-07 SaccadeMultiStim sessions. The interrupted first 2026-08-07 run
is included, but only its trials that individually pass all selection criteria
enter the models. Both 8/7 runs share one day indicator.

## Models

With 8/6 as the reference day:

```text
gain_pct = beta0 + betaC * contrast + beta7 * D_8/7
           + betaR * distance_deg + error

latency_ms = alpha0 + alphaC * contrast + alpha7 * D_8/7
             + alphaR * distance_deg + error
```

`contrast` is Weber contrast `(target luminance - background luminance) /
background luminance`. The configured background luminance is 5 cd/m².
Continuous predictors are mean-centered, which changes intercepts but not their
slopes.

## Main trial definition

- Status is `Success` and the trial is not a control trial.
- The fixation and target acceptance windows do not overlap: target distance
  must exceed `Fix_Window_Radius_deg + Stim_Window_Radius_deg`.
- EyeLink timing messages are complete.
- The first saccade after fixation offset and before the target-window end has
  EyeLink amplitude at least 1 degree.
- A gain value can be reconstructed in the correct session coordinate system.
- Main analysis: saccade onset is at least 80 ms after stimulus onset.
- Sensitivity analysis: the same first saccades without the 80-ms exclusion.

## Coordinate handling

- 8/6 used HREF samples. The script applies the final saved calibration
  immediately preceding the task session.
- Both 8/7 runs used EyeLink GAZE coordinates, transformed from top-left EyeLink
  pixels to centered FineVision pixels.
- EyeLink messages are read directly through the official EDF Access DLL because
  the installed EDF2ASC build truncates the final character of message lines.

## Run

From PowerShell:

```powershell
cd D:\Chenghang\FineVision\analysis\saccade_gain_models
.\run_analysis.ps1
```

Or directly:

```powershell
D:\Software\Psychopy\python.exe analyze_saccade_models.py
```

The first run converts the EDF files and creates an approximately 200 MB
`cache/` directory. Later runs reuse it. To reconvert the raw EDF files:

```powershell
.\run_analysis.ps1 -ForceConvert
```

Useful alternatives:

```powershell
.\run_analysis.ps1 -MinimumLatencyMs 0
.\run_analysis.ps1 -BackgroundLuminance 5.875
.\run_analysis.ps1 -BootstrapRepetitions 10000
```

The 5 versus 5.875 background choice rescales the linear contrast coefficient
but, because background is constant across these trials, does not change fitted
values or the test of whether the contrast slope is zero.

## Outputs

`outputs/` contains:

- `analysis_report.md`: human-readable model report.
- `model_coefficients.csv`: estimates, cluster-robust confidence intervals,
  p-values, and stratified cluster-bootstrap intervals.
- `model_fit_summary.csv`: sample size, R², RMSE, and cluster count.
- `trial_level_all.csv`: every logged trial plus inclusion/exclusion flags.
- `trial_level_main.csv`: exact rows and centered predictors used for the main
  models.
- `trial_level_sensitivity.csv`: rows used without the latency cutoff.
- `exclusion_flow.csv`, `session_counts.csv`, and `run_counts.csv`: audit trail
  of trial selection by pooled day and by original recording run.
- `pooled_run_diagnostic.csv`: adjusted comparison of the first versus second
  8/7 run, used to check whether pooling hides a large run intercept difference.
- `power_projection.csv` and `power_projection.md`: approximate cluster-aware
  sample-size projections for the contrast-to-gain slope.
- `figure_model_effects.png`: fitted effects at mean target distance.
- `figure_diagnostics.png`: residual and Q-Q plots.
- `figure_data_overview.png`: trial-level overview.
- `input_manifest.csv`: path, size, modification time, and SHA-256 for every
  source file.
- `analysis_metadata.json`: runtime versions and effective configuration.

## Statistical notes

The models are trial-level OLS. Confidence intervals use CR1 cluster-robust
standard errors with `recording session x relative target position` as the
cluster. Bootstrap intervals resample position clusters separately within each
recording session and use the fixed seed in `config.json`. The two 8/7 runs
share the same day coefficient but remain separate clustering strata.

This first model assumes a common contrast slope and common distance slope
across days, and simplifies target position to distance. Planned extensions can
add `contrast x session`, target direction, or exact relative-position effects.

The latency residuals are non-normal and the main latency distribution is
left-truncated at 80 ms by design. Treat that OLS model as an exploratory model
of the conditional mean. Cluster-robust and bootstrap intervals account for
dependence within repeated recording-session-position cells, but they do not eliminate
truncation.

## Approximate power projection

After the main analysis has run, calculate the default 80% and 90% power
scenarios with:

```powershell
D:\Software\Psychopy\python.exe power_projection.py
```

The projection uses the current cluster-robust standard error and scales
information by independent recording-session-by-position clusters. It is a
planning estimate, not a guarantee that future data will be significant.
