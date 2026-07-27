# Every analysis, ranked

All work across the three rounds, sorted by what it can carry in a paper. Compiled
2026-07-27.

**Scoring, applied consistently.**

- **Novelty** — ✔✔ verified novel against a specific literature search
  (`NOVELTY_REVIEW.md`); ✔ novel with a close neighbour to cite; ~ partially scooped;
  — known, replication, or not a novelty claim.
- **Impact** — does it change what the field does, invalidate a published claim, or
  supply a number the field lacks?
- **Evidence** — n, p, independent verification, controls, and whether the design is
  within-run (unarguable) or across-run (contestable).

Sources: `COMPENDIUM.md` (Round 1), `ROUND2_RESULTS.md` (Rounds 2–3),
`FLAGSHIP_FINDINGS.md` (the distilled core), `NOVELTY_REVIEW.md` (verdicts).

---

## TIER 1 — carries the paper

| # | analysis | novelty | impact | evidence |
|---|---|---|---|---|
| **1** | **Image-based distortion correction harms cord geometry** (F1, + A2a mechanism, + A2b premise) | ✔✔ | Inverts a default shipped in fMRIPrep (`--use-syn-sdc`) and recommended by Wang 2017. ~82% of cord runs are exposed | 80 runs, p=8×10⁻¹⁵, **two independently computed metrics agree**, plus the only **physical referee** in the project. Premise now measured (cord distortion **2.60×** brain, same shot, p=1.9×10⁻⁷) and mechanism measured (SyN **under-corrects 6×**, \|r\|=0.47) |
| **2** | **Analytic variability — the pipeline chooses the answer** (R10 multiverse) | ✔✔ *(ZERO prior results)* | Indicts every single-pipeline cord result: the conclusion is positive in only **15–30%** of 54 defensible pipelines and **the sign flips in all four datasets**. Also ranks the axes, confirming summary measure as the largest | 216 pipelines, all on fixed runs (the only comparison the estimator caveat permits). Explicitly a **lower bound** — distortion could not enter |
| **3** | **Individual-level inference fails on every estimator** (F4: effect ICC, peak ICC, pattern, profile, behaviour, responder call, ceiling arithmetic) | ✔✔ for the ceiling arithmetic | Rules out cord task fMRI as an individual or biomarker measure, with the cost stated: max clinical correlation **0.21**, N=**172**, or **57 sessions**. Redirects the field to connectivity (ICC 0.49, 3 sessions) | **Seven independent estimators converging** is the strongest form of evidence here. Includes the external behavioural referee (grip force at 100 Hz) that no earlier analysis had |

---

## TIER 2 — strong, distinct contributions

| # | analysis | novelty | impact | evidence |
|---|---|---|---|---|
| **4** | **The cord peak is not a measurement of the subject** (N5, tightened by B4) | ✔✔ | Invalidates a class of published level-specific claims. Stronger than the old F3 because **registration is exonerated**: within-subject repeats share it | ICC(2,1) = +0.16, +0.03, +0.05, −0.04 across 4 datasets; between-run SD ≥ between-subject SD. Our own frame audited clean (0.95–1.13×). Per-dataset CIs all ≤1; RFT null **quantitatively excluded** (predicts 0.5–2.5 mm vs 11–25 mm measured) |
| **5** | **The cord is better behaved than the brain for inference** (paired-organ A) | ✔✔ | Inverts the standing intuition that the cord is the statistically hard organ | **Within-run**, so no confound remains to name. FWE 10.4% vs 28.7% at a third the tSNR; paired p=3.3×10⁻¹⁸, 107 runs |
| **6** | **Non-rigid cord deformation is 3.85× the rigid motion the pipeline corrects** (A8) | ✔✔ | Names a missing pipeline capability. Cord-specific with no brain analogue. Candidate mechanism for the S2 heterogeneity | **416/416 runs (100%)**, all nine datasets, ratios 2.78–4.84. The cleanest universal result in the project |
| **7** | **aCompCor slice-wise settles Kaptan vs Hemmerling** (A1) | — *(not a novelty claim)* | Resolves a live disagreement between two published readings, and gives an actionable fix worth **38 dof/run** | Clean dissociation on the same runs: connectivity −35% (p=2.3×10⁻³⁵) while task detection unchanged (p=0.58). Redoes a retracted analysis correctly |
| **8** | **The confound model spends most of the run** (R7) | ✔✔ | Concrete pipeline defect: CSF is **78%** of the budget, **85.8%** of runs spend >half their frames, **7.8%** have no residual dof (one dataset at **−54**). 12–37× the literature's component counts | 450 runs from metrics the pipeline already writes. Cost is **analytic** (t ∝ √dof), not simulated, and A1 confirmed it empirically |

---

## TIER 3 — solid supporting results

| # | analysis | novelty | impact | evidence |
|---|---|---|---|---|
| **9** | **Cord inference is valid** (N1) + **the null effect-size floor** | ✔✔ | A reusable benchmark: \|d\| p95 = **0.31**. Retires a worry (inference is fine, prewhitening should not be applied) and shows uncorrected p<0.001 declares activation in **53%** of task-free runs | 126 resting runs × 200 designs. Refuted three of my own predictions, which is why it is trustworthy |
| **10** | **No QC metric predicts scientific outcome** (R2) + **the estimator caveat it caught** | ✔✔ | The caveat matters more than the null: it qualifies **every** split-half magnitude in the project and defines exactly which comparisons remain safe | All 7 families have negative leave-one-dataset-out R². The caveat is calibrated against a **task-free null** (ρ = −0.30, −0.48), not argued |
| **11** | **QC metrics measure the site, not the person** (A6) | not searched | Explains R2's null mechanically, and states the multi-site case: harmonise before pooling | 48% dataset / 19% subject / 33% run over 33 metrics; dataset dominates in 27/33 |
| **12** | **Scoped replication** (F5) | — | Establishes the pipeline's authority to criticise. The **1/4 non-replication under unbiased CV** is itself important and agrees with P1 independently | Laterality 92% (now tested: p=1.8×10⁻⁵ to 6.2×10⁻⁸, CI excludes 50%), ICC 0.05 vs Dabbagh 0.03, V–V 0.49 vs Kaptan 0.63 |
| **13** | **Model-free detection by ISC** (R9) | ✔✔ | Shows shared stimulus-driven signal exists without any HRF or design model — but at 1–3%, one to two orders below brain sensory cortex | Circular-shift null, validity of shared timing checked rather than assumed. **Serious caveat**: cannot separate neural response from task-locked artifact, and whole-cord > horn argues for artifact |
| **14** | **Multivariate detection** (N3) | — *(MVPA established in cord)* | One clean positive where the univariate mean sits at exactly 0.500 (ds005883 whole cord **0.639**, p=0.0001) — but it does not generalise | Third design; the first two were invalid and discarded. Permutation null now at 0.492–0.505 as it must be |
| **15** | **Spatial reproducibility ordering** (R3/R4) | ~ **partially scooped** by Ricchi 2026 | Survives as a caveat on their paper (anatomy/tSNR alone identify at 0.56–0.60) plus the ordering peak < pattern < profile, and the session-gap boundary | Anatomy control was essential and is what makes it publishable. **No "first" language** |
| **16** | **Biomarker ceiling arithmetic** (R6, folded into F4) | ✔✔ | Clinical reach for near-zero cost; the one place the reliability results have a direct consequence | Arithmetic over measured ICCs, no new data |

---

## TIER 4 — nulls and negatives worth keeping

| # | analysis | why it stays |
|---|---|---|
| 17 | **Cord-shaped smoothing failed** (N4) | The prediction was wrong (isotropic won), but two side observations are worth more: **no arm changes the effect** (every paired test p>0.18 — the group-d spread is between-subject SD shrinking), and **the field's "isotropic" kernel is not isotropic** at 4 mm slices |
| 18 | **Global signal, preprocessed and raw** (R5, A4) | Two attempts to explain the ds005884 anomaly, both failed. 1–2% of variance either way, not task-locked. No basis for global signal regression |
| 19 | **Responder consistency** (R8) | Coarsening to yes/no buys nothing (kappa +0.18, −0.05). Feeds F4 |
| 20 | **High-pass filtering** (Round 1) | Null; justifies the inherited 100 s cutoff. One of the four axes pruned from the multiverse |
| 21 | **Physiological noise by cord zone** (Round 1) | Null; not edge-concentrated. Pruned axis |
| 22 | **Confound families on task detection** (Round 1) | No family improves sensitivity — the other half of R7's ledger |
| 23 | **Motion correction ablation** (Round 1, v2) | tSNR +0% to +121%, no consistent transfer. A8 is the candidate mechanism |
| 24 | **Smoothing sweep, FD censoring, design degeneracy, biological robustness, motion regression cost** (Round 1) | Absorbed into F2's axis ranking and R7; individually superseded |

---

## TIER 5 — infrastructure that makes the rest usable

| analysis | value |
|---|---|
| **Novelty review** (B1) | Cleared 8 claims, caught the Ricchi scoop. Unblocked by using WebFetch against PubMed when WebSearch was exhausted |
| **F3 tightening** (B4) | Per-dataset CIs, the binomial test, and the RFT null excluded rather than ignored |
| **Integrative figure rebuilt** (B7) | Reads every value from a result CSV; the retired version hardcoded an invented +30% bar |
| **FD traceability, Morrison removal** (B5, B6) | Two documentation defects that would have become prose errors |
| **The retractions** (8 of them) | Nine self-caught Round 1 errors and seven failed Round 2–3 predictions. This is the record that makes the survivors credible |

---

## The four that would most change the ranking if done

| | what | effect |
|---|---|---|
| A3 | add the distortion axis to the multiverse | raises **#2** above its current lower bound |
| — | reconcile F1's tension (both metrics, same voxels, same run) | closes the one open hole in **#1** |
| — | explain the ds005884 anomaly | removes the project's last unexplained observation |
| B8 | re-run P1's harness on `preproc-v1` | unblocks the second paper, not this one |

---

## Summary counts

- **40 distinct analyses** across three rounds.
- **9 verified novel**, 1 novel with a neighbour, 1 partially scooped.
- **3 in Tier 1** — F1 distortion, the multiverse, individual-level failure.
- **16 failures kept in the record**: 9 self-caught Round 1 errors, 7 refuted Round 2–3
  predictions, plus 8 retractions and 3 discarded designs.
- **1 observation still unexplained** (the ds005884 whole-cord anomaly) and **1 open
  tension** (F1's under-correction versus its worsening).
