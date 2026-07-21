# Runtime benchmark

How long SpinePrep takes, measured and reported so the number means something.

Not a pipeline step. These modules read the timing records that each step now
writes into its `qc.json`, in the same read-only way `validation/` reads QC.

## The two numbers, and why one is not enough

**Latency** is one run start to finish on an idle machine: what someone
processing a single subject waits. It is the only figure comparable across
papers and hardware.

**Throughput** is runs per hour at N workers on a saturated machine: what a lab
planning a 40-subject study needs.

They differ by roughly the worker count. Quoting one when the reader wants the
other is the most common way a pipeline benchmark misleads, so `analyze.py`
partitions records on worker count and refuses to pool them.

## Measuring

Throughput is free. Every step records its own timing, so any normal cohort run
produces it:

```bash
python3 benchmark/analyze.py /path/to/out
```

Latency needs dedicated compute, because the reference cohort runs 12-way
parallel under `batch` on a shared box:

```bash
python3 benchmark/latency.py --out /tmp/bench --auto /path/to/cohort
```

It picks three runs spanning the real cost drivers — a short and a long run
from the majority `none` distortion mode, plus a topup run, which does strictly
more work — and runs each three times serially. It refuses to start above a
1-minute load average of 4.0: latency measured on a busy machine is not latency,
and a number produced that way will be quoted as single-run time later.

## Reporting

Always alongside the number:

- **hardware** — cores, RAM, GPU, storage;
- **parallelism** — worker count and GPU slot cap;
- **tool versions** — from the existing reproducibility receipt;
- **whether the machine was contended** — `load_avg_start` is recorded per run.

Report **median and range**, not mean ± SD. Wall-clock is right-skewed; SD
implies a symmetry the distribution does not have.

Report **per dataset, not pooled**. Acquisition differences are the point, the
same way they are for quality (design invariant 8).

Report the **first repeat separately** rather than discarding it. SCT loads
segmentation model weights on first call, and for someone running a single
subject that cold cost is their actual experience.

### Steps scale differently

S4, S5, S8 and S9 grow with the number of volumes. S2, S6 and S7 work on a 3D
reference and are roughly flat in run length. A single "minutes per volume"
figure across all steps would be wrong, so `analyze.py` marks which steps scale
and reports raw per-step minutes.

### What `tool%` means

Nearly all of SpinePrep's cost is SCT, FSL and ANTs subprocesses. `tool_s` is
time inside those calls; the remainder is SpinePrep's own overhead. Reporting
only wall-clock would take credit, or blame, for SCT's runtime. The honest
framing of the whole benchmark is **what the automation costs on top of the
tools it integrates**.

## What is excluded, and why

- **Resumed runs** — served from cache in milliseconds; they would deflate every
  average they entered. Marked at the source, not guessed at.
- **Failed runs** — a run that died in its first minute is not a measurement of
  how long the step takes.

Both are counted and printed, never silently dropped.

## What we do not claim

**No head-to-head against fMRIPrep or SCT.** SpinePrep is mostly a wrapper
around SCT, FSL and ANTs, so "SpinePrep vs SCT" would partly measure SCT against
itself. If a comparison is ever wanted, it means something only on the same data
and the same machine.

Timing is also not a property of the software alone. Unlike the QC metrics it
does not reproduce across machines, so no summary here should be quoted without
the hardware it was measured on.
