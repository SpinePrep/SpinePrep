# Retired analysis scripts

Kept for provenance, not for use. Do not run these or quote their numbers.

## t25_ranking.py — retired 2026-07-27
The original integrative figure. Two reasons it was retired rather than updated:

1. **It hardcoded every value**, including `("smoothing 4 mm FWHM", [30.0], 'choice')`
   — a +30% bar that was never measured and was later invalidated. N4 measured the
   kernel arms properly and found no arm changes the effect at all (every paired test
   p > 0.18).
2. **Its framing is superseded.** It sorted choices into "imported from brain —
   harmful" against "cord-derived alternative — helps". F4 showed only the censored
   FRACTION matters, not the threshold's provenance, and N4 showed cord-shaped
   smoothing does not beat isotropic. The dichotomy the figure was built on does not
   survive its own project's measurements.

Replaced by `../fig_integrative.py`, which reads every value from a result CSV.
