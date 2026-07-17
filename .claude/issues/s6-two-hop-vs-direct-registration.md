---
status: candidate
title: "S6: quantify whether the two-hop func->anat->template design adds registration error vs registering func->template directly"
repo: SpinePrep/SpinePrep
url:
drafted: 2026-07-16
evidence: .claude/specs/s6-algorithm-audit-v2.md
---

## Summary

SpinePrep registers the functional cord EPI to the subject's own anatomy in S6,
then registers that anatomy to the PAM50 template in S7 -- a two-hop chain
(func -> anat -> template). Two other approaches register the template to the
functional mean directly, initialised by the anatomy-to-template warp (Kaptan et
al. 2023; SCT's own fMRI tutorial). Both designs are defensible, and there is no
evidence the extra hop adds error -- but there is also no measurement either way.
This issue is to make that measurement, later.

## Why it matters

Each registration hop introduces some resampling and interpolation error. A
two-hop composition can accumulate error the direct path avoids, or it can be
more robust because each hop solves an easier sub-problem. Which one wins for
cord fMRI is an empirical question we have not answered. The current choice is
defensible by precedent (CoSpine and Eippert 2017 also compose two hops), not by
our own data.

## What the field does

- Kaptan et al. 2023 (verified from their code): registers the PAM50 template to
  the functional mean directly, initialised by the anatomy-to-template inverse
  warp. No independent func->own-anat registration.
- SCT fMRI tutorial: template -> func directly, single intensity SyN step,
  reusing the anat<->template warp.
- CoSpine / Wei 2025: two-hop (func -> structural -> template), like SpinePrep.
- Eippert 2017: func -> subject structural -> study template (two-hop, FSL).

So the two-hop design has precedent, but the direct path is what the closest
methodological reference (Kaptan/Eippert lab) actually runs.

## The experiment

The CoSpine datasets (ds005883, ds005884) are the natural test set. For each run,
warp the PAM50 cord (and a set of vertebral-level landmarks) into functional
space by (a) the current two-hop chain and (b) a direct template->func
registration initialised by the anat->template warp, then compare against a
manual or reference cord/level position in functional space. Report the residual
displacement of the cord centerline and the level boundaries under each path. The
metric must be independent of the registration objective (see the cord-Dice
circularity note in the S6 audit): centerline displacement in mm and
vertebral-level agreement, not cord Dice.

## Decision this informs

If the direct path is measurably better, switch S6/S7 to register
template<->func directly and drop the independent func->own-anat hop. If they are
within noise, keep the two-hop design and state in the paper that it was compared
against the direct path and found equivalent -- which is a stronger claim than
"defensible by precedent".

## Status

Deferred. Not blocking v1. Recorded so the choice is revisited with data rather
than left as an untested default.
