# First-saccade gain and latency model report

Generated: 2026-08-24T05:17:18.769139+00:00

## Pre-specified models

Reference day: 8/6. Both 8/7 recording sessions were pooled under one day indicator. Continuous predictors were centered at their main-analysis means.

```text
gain_pct = beta0 + betaC * contrast_weber + beta7 * D_8/7
           + betaR * distance_deg + error

latency_ms = alpha0 + alphaC * contrast_weber + alpha7 * D_8/7
             + alphaR * distance_deg + error
```

Weber contrast was `(target luminance - 5) / 5`.

## Trial inclusion

- Main analysis: n=691 trials; first saccade latency >= 80 ms.
- Sensitivity analysis: n=873 trials; no minimum visual-latency exclusion.
- Both analyses used successful non-control trials, excluded overlapping fixation/target acceptance windows, and required a valid first saccade >= 1 deg after fixation offset.

| Session | Main n | Sensitivity n | Main position clusters |
|---|---:|---:|---:|
| 8/6 | 380 | 455 | 38 |
| 8/7 | 311 | 418 | 84 |

## Main result in one paragraph

For gain, the estimated contrast coefficient was 0.02799 percentage points per Weber-contrast unit (cluster-robust 95% CI -0.008609 to 0.06458, p=0.133). For latency, the estimated contrast coefficient was 0.01042 ms per Weber-contrast unit (cluster-robust 95% CI -0.1069 to 0.1277, p=0.861). These are conditional linear associations after adjusting for the day intercept and target distance; a confidence interval crossing zero is not proof of exactly zero effect.

## Main-analysis coefficients

| Outcome | Term | Estimate | Cluster 95% CI | p | Bootstrap 95% CI |
|---|---|---:|---:|---:|---:|
| gain_pct | Intercept | 98.29 | [96.73, 99.85] | 1.14e-129 | [96.78, 99.84] |
| gain_pct | contrast_weber_centered | 0.02799 | [-0.008609, 0.06458] | 0.133 | [-0.00655, 0.06325] |
| gain_pct | day_8_7 | -6.168 | [-7.891, -4.446] | 9.7e-11 | [-7.881, -4.457] |
| gain_pct | distance_deg_centered | -0.1927 | [-0.4674, 0.08196] | 0.167 | [-0.4707, 0.07006] |
| latency_ms | Intercept | 99.91 | [97.53, 102.3] | 1.03e-108 | [97.54, 102.2] |
| latency_ms | contrast_weber_centered | 0.01042 | [-0.1069, 0.1277] | 0.861 | [-0.1044, 0.1217] |
| latency_ms | day_8_7 | -0.4212 | [-3.548, 2.706] | 0.79 | [-3.562, 2.685] |
| latency_ms | distance_deg_centered | -1.315 | [-1.75, -0.8805] | 2.24e-08 | [-1.744, -0.8925] |

## Sensitivity-analysis coefficients

| Outcome | Term | Estimate | Cluster 95% CI | p | Bootstrap 95% CI |
|---|---|---:|---:|---:|---:|
| gain_pct | Intercept | 98.5 | [97.09, 99.91] | 2.42e-140 | [97.14, 99.92] |
| gain_pct | contrast_weber_centered | 0.02963 | [-0.00247, 0.06174] | 0.0701 | [-0.001268, 0.06065] |
| gain_pct | day_8_7 | -5.787 | [-7.353, -4.22] | 2.67e-11 | [-7.328, -4.291] |
| gain_pct | distance_deg_centered | -0.2202 | [-0.4627, 0.02239] | 0.0749 | [-0.4605, 0.01548] |
| latency_ms | Intercept | 95.94 | [93.27, 98.61] | 4.34e-104 | [93.28, 98.65] |
| latency_ms | contrast_weber_centered | -0.09806 | [-0.1956, -0.0004797] | 0.0489 | [-0.1926, -0.0001139] |
| latency_ms | day_8_7 | -2.254 | [-5.854, 1.345] | 0.218 | [-5.96, 1.277] |
| latency_ms | distance_deg_centered | -1.253 | [-1.718, -0.7892] | 4.09e-07 | [-1.701, -0.799] |

## Model fit

- Gain: R²=0.176, adjusted R²=0.172, RMSE=7.334, clusters=122.
- Latency: R²=0.057, adjusted R²=0.053, RMSE=18.555, clusters=122.

## Check of pooling the two 8/7 runs

- gain_pct: first minus second 8/7 run = -0.8941, cluster-robust 95% CI [-3.468, 1.68], p=0.493.
- latency_ms: first minus second 8/7 run = 3.537, cluster-robust 95% CI [-2.049, 9.123], p=0.212.

These comparisons adjust for contrast and distance. Failure to reject a run difference is not an equivalence test, but there was no large, statistically clear run offset that would by itself argue against the requested pooling.

## Coordinate reconstruction

- 8/6: EDF HREF samples transformed with `eyelink_calibration_20260806_142607.json`.
- Both 8/7 sessions (14:12 and 14:45) used EDF GAZE coordinates converted from EyeLink top-left coordinates to FineVision centered pixels.
- The interrupted 8/7 14:12 run was included only through trials that individually passed all pre-specified selection criteria.

## Interpretation limits

The simple model assumes one common contrast slope and one common distance slope across days, and approximates position by distance alone. Day-by-contrast interactions, target direction, or exact relative position should be examined as planned extensions if residual diagnostics or later data suggest violations. The 8/7 coefficient estimates the pooled day offset relative to 8/6; it does not estimate a separate offset for each 8/7 recording run.

The latency residuals are non-normal and the main latency outcome is left-truncated by design at 80 ms. Its OLS coefficient should therefore be read as an exploratory conditional mean association. The cluster-robust and cluster-bootstrap intervals reduce reliance on independent, homoscedastic trial errors, but they do not remove truncation.
