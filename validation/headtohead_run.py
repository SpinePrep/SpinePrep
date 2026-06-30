"""T4 driver: run the SCT-default arm across cervical scopes and compare to ours.

For N runs per scope, register funcref->anat with SCT defaults, Dice the warped
func cord region vs the anat cord seg, pair against our S6 cord_dice, and report
paired stats (Wilcoxon) + a figure. Uses S6 work-tree inputs.

Usage: poetry run python validation/headtohead_run.py [n_per_scope]
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "validation")
import headtohead_sct_default as hh  # noqa: E402

# cervical scopes where cord-Dice is the registration truth metric
SCOPES = ["dorsalhorn", "handgrasp", "cosmotor", "cospain"]


def run(n_per: int = 8) -> pd.DataFrame:
    rows = []
    for scope in SCOPES:
        ours = hh.our_cord_dice(scope)
        s6 = Path(f"work/done/{scope}/S6").resolve()
        dirs = sorted(glob.glob(str(s6 / "work" / "S6_func_to_anat_registration" / "*")))
        done = 0
        for d in dirs:
            if done >= n_per:
                break
            d = Path(d); run_id = d.name
            fr, anat = d / "funcref.nii.gz", d / "anat_in_bold.nii.gz"
            aseg, fseg = d / "anat_dseg_in_bold.nii.gz", d / "funccrop_mask.nii.gz"
            o = ours.get(run_id)
            if not (fr.exists() and anat.exists() and aseg.exists() and fseg.exists()) or o is None:
                continue
            sct = hh.run_sct_default(fr, anat, fseg, aseg, Path("/tmp/t4") / scope / run_id)
            if sct is None:
                continue
            rows.append({"scope": scope, "run_id": run_id, "ours": round(o, 4),
                         "sct_default": round(sct, 4)})
            done += 1
        print(f"  {scope}: {done} runs compared")
    df = pd.DataFrame(rows)
    out = Path("validation/results/headtohead_dice.tsv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, sep="\t", index=False)
    if not df.empty:
        from scipy.stats import wilcoxon
        o = df["ours"].to_numpy(); s = df["sct_default"].to_numpy()
        try:
            stat, p = wilcoxon(o, s)
        except Exception:
            stat, p = float("nan"), float("nan")
        print(f"\nPAIRED n={len(df)}: ours mean={o.mean():.3f} (sd {o.std():.3f}) | "
              f"SCT-default mean={s.mean():.3f} (sd {s.std():.3f}) | "
              f"delta=+{o.mean()-s.mean():.3f} | Wilcoxon p={p:.2e} | "
              f"ours>sct in {(o>s).sum()}/{len(df)}")
        _figure(df, Path("validation/results/figures/headtohead_dice.png"))
    return df


def _figure(df: pd.DataFrame, out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for _, r in df.iterrows():
        ax.plot([0, 1], [r["sct_default"], r["ours"]], "-", color="#bbb", lw=0.7, zorder=1)
    ax.scatter(np.zeros(len(df)), df["sct_default"], s=22, color="#cc6666", zorder=2, label="SCT-default")
    ax.scatter(np.ones(len(df)), df["ours"], s=22, color="#1f9d57", zorder=2, label="SpinalfMRIprep (S6 recipe)")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["SCT-default", "ours"])
    ax.set_ylabel("func→anat cord Dice"); ax.set_ylim(0, 1)
    ax.set_title(f"Head-to-head cord registration (paired, n={len(df)})", fontsize=10)
    ax.legend(fontsize=8, loc="lower center"); ax.grid(axis="y", alpha=0.25); ax.set_axisbelow(True)
    fig.tight_layout(); fig.savefig(out, dpi=130, bbox_inches="tight"); plt.close(fig)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    print(f"T4 head-to-head vs SCT-default — {n} runs/scope across {SCOPES}")
    run(n)
