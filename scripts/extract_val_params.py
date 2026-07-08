
import nibabel as nib
import json
import csv
import sys
import statistics
from pathlib import Path
import os

datasets = [
    {
        "id": "ds005884",
        "nii_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds005884_cospine_motor/sub-01/func/sub-01_task-motorL_bold.nii.gz",
        "json_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds005884_cospine_motor/sub-01/func/sub-01_task-motorL_bold.json",
        "events_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds005884_cospine_motor/sub-01/func/sub-01_task-motorL_events.tsv"
    },
    {
        "id": "ds005883",
        "nii_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds005883_cospine_pain/sub-01/func/sub-01_task-pain_bold.nii.gz",
        "json_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds005883_cospine_pain/sub-01/func/sub-01_task-pain_bold.json",
        "events_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds005883_cospine_pain/sub-01/func/sub-01_task-pain_events.tsv"
    },
    {
        "id": "ds004386",
        "nii_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds004386_spinalcord_rest_testretest/sub-ZS001/func/sub-ZS001_task-rest_acq-autozshim_bold.nii.gz",
        "json_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds004386_spinalcord_rest_testretest/sub-ZS001/func/sub-ZS001_task-rest_acq-autozshim_bold.json",
        "events_path": None 
    },
    {
        "id": "ds004616",
        "nii_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds004616_spinalcord_handgrasp_task/sub-01/ses-01/func/sub-01_ses-01_task-handgrasp_bold.nii.gz",
        "json_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds004616_spinalcord_handgrasp_task/sub-01/ses-01/func/sub-01_ses-01_task-handgrasp_bold.json",
        "events_path": "/mnt/ssd1/SpinePrep/datasets/openneuro_ds004616_spinalcord_handgrasp_task/sub-01/ses-01/func/sub-01_ses-01_task-handgrasp_events.tsv"
    },
    {
        "id": "Balgrist_11",
        "nii_path": "/mnt/ssd1/SpinePrep/datasets/internal_balgrist_motor_11/sub-01/func/sub-01_task-motor_acq-KombiShimZSpine_run-01_bold.nii.gz",
        "json_path": "/mnt/ssd1/SpinePrep/datasets/internal_balgrist_motor_11/sub-01/func/sub-01_task-motor_acq-KombiShimZSpine_run-01_bold.json",
        "events_path": None
    }
]

results = {}

def safe_float(v):
    try:
        return float(v)
    except:
        return v

def parse_events(path):
    try:
        if not path or not os.path.exists(path):
            return {"Error": "File not found or None"}
        
        onsets = []
        durations = []
        
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                if 'onset' in row and 'duration' in row:
                    try:
                        onsets.append(float(row['onset']))
                        durations.append(float(row['duration']))
                    except ValueError:
                        continue
        
        if not durations:
            return {"Error": "No valid duration/onset columns"}
            
        block_dur_mean = statistics.mean(durations)
        block_dur_unique = sorted(list(set(durations)))
        
        # Calculate ISIs
        isis = []
        if len(onsets) > 1:
            sorted_pairs = sorted(zip(onsets, durations), key=lambda x: x[0])
            sorted_onsets = [p[0] for p in sorted_pairs]
            sorted_durs = [p[1] for p in sorted_pairs]
            
            for i in range(len(sorted_onsets) - 1):
                # End of current block = onset + duration
                end_current = sorted_onsets[i] + sorted_durs[i]
                start_next = sorted_onsets[i+1]
                isi = start_next - end_current
                # Filter out very small ISIs (e.g. 0) that might be simultaneous events if any
                if isi > 0.1: 
                    isis.append(isi)
        
        stats = {
            "BlockDur_Mean": block_dur_mean,
            "BlockDur_Unique": block_dur_unique,
            "ISI_Mean": statistics.mean(isis) if isis else None,
            "ISI_Min": min(isis) if isis else None,
            "ISI_Max": max(isis) if isis else None
        }
        return stats

    except Exception as e:
        return {"Error": str(e)}

for ds in datasets:
    res = {}
    
    # NIfTI
    try:
        img = nib.load(ds["nii_path"])
        hdr = img.header
        zooms = hdr.get_zooms()
        shape = img.shape
        
        res["TR_header"] = safe_float(zooms[3])
        res["VoxelSize"] = [safe_float(x) for x in zooms[0:3]]
        res["Matrix"] = [int(x) for x in shape[0:3]]
        res["Volumes"] = int(shape[3])
        res["TotalDuration_Calc"] = res["Volumes"] * res["TR_header"]
    except Exception as e:
        res["Error_Nifti"] = str(e)
        
    # JSON
    try:
        if ds["json_path"] and os.path.exists(ds["json_path"]):
            with open(ds["json_path"]) as f:
                js = json.load(f)
                res["TR_json"] = js.get("RepetitionTime")
                res["TE"] = js.get("EchoTime")
                res["Multiband"] = js.get("MultibandAccelerationFactor")
                res["PE_Dir"] = js.get("PhaseEncodingDirection")
                res["TaskName"] = js.get("TaskName")
    except Exception as e:
        res["Error_JSON"] = str(e)

    # Events
    if ds["events_path"]:
        res["TaskTiming"] = parse_events(ds["events_path"])

    results[ds["id"]] = res

print(json.dumps(results, indent=2))
