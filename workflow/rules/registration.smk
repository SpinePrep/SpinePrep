"""
Registration rule for EPI→PAM50 with metrics and QC.

Implements SCT-based registration with:
- Doctor precheck for SCT/PAM50 availability
- Intensity-normalized SSIM/PSNR metrics
- Header sanity checks
- Before/after mosaics for QC
"""

import json
import os
import subprocess
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np

matplotlib.use("Agg")


rule registration_pam50:
    """
    Register EPI reference to PAM50 template with full QC metrics.

    Conservative SCT registration (rigid+affine) with SSIM/PSNR validation,
    header checks, and mosaic generation for QC.
    """
    input:
        epi_ref="{deriv}/sub-{sub}/func/sub-{sub}_task-{task}_run-{run}_desc-mean_bold.nii.gz",
        doctor_json=lambda wildcards: f"{CFG['paths']['logs_dir']}/doctor.json",
    output:
        # Transformation
        warp="{deriv}/sub-{sub}/xfm/sub-{sub}_task-{task}_run-{run}_from-epi_to-PAM50_desc-sct_xfm.nii.gz",
        # Registered reference
        registered="{deriv}/sub-{sub}/func/sub-{sub}_task-{task}_run-{run}_space-PAM50_desc-ref_bold.nii.gz",
        # Metrics
        metrics="{deriv}/sub-{sub}/qc/sub-{sub}_task-{task}_run-{run}_desc-registration_metrics.json",
        # Mosaics
        mosaic_before="{deriv}/sub-{sub}/qc/registration/sub-{sub}_task-{task}_run-{run}_desc-before_mosaic.png",
        mosaic_after="{deriv}/sub-{sub}/qc/registration/sub-{sub}_task-{task}_run-{run}_desc-after_mosaic.png",
    log:
        "{deriv}/logs/registration_pam50_{sub}_{task}_{run}.log",
    resources:
        mem_mb=2000,
    run:
        from spineprep.registration.sct import (
            check_doctor_status,
            create_output_paths,
            map_sct_error,
            run_sct_register,
        )
        from spineprep.registration.metrics import (
            compute_psnr,
            compute_ssim,
            normalize_intensity,
        )
        from spineprep.registration.header import validate_registration_output

        # Step 1: Check doctor status for SCT/PAM50
        try:
            check_doctor_status(input.doctor_json)
        except (FileNotFoundError, RuntimeError) as e:
            msg = f"Doctor precheck failed: {e}\nRun 'spineprep doctor' before registration."
            with open(log[0], "w") as f:
                f.write(msg)
            raise RuntimeError(msg)

            # Step 2: Get PAM50 template path
        pam50_dir = os.environ.get("SCT_DIR", "/opt/sct") + "/data/PAM50"
        fixed_image_key = CFG.get("registration", {}).get("fixed_image", "PAM50_t2")
        pam50_template = f"{pam50_dir}/{fixed_image_key}.nii.gz"

        if not Path(pam50_template).exists():
            msg = f"PAM50 template not found: {pam50_template}"
            with open(log[0], "w") as f:
                f.write(msg)
            raise FileNotFoundError(msg)

            # Step 3: Run SCT registration
        result = run_sct_register(
            src_image=input.epi_ref,
            dest_image=pam50_template,
            out_warp=output.warp,
            out_resampled=output.registered,
        )

        # Write registration log
        with open(log[0], "w") as f:
            f.write(f"Command: {result['command']}\n")
            f.write(f"SCT version: {result['sct_version']}\n")
            f.write(f"Return code: {result['return_code']}\n")
            f.write(f"\nSTDOUT:\n{result['stdout']}\n")
            f.write(f"\nSTDERR:\n{result['stderr']}\n")

            # Check registration success
        if not result["success"]:
            error_msg = map_sct_error(result["return_code"], result["stderr"])
            raise RuntimeError(f"Registration failed: {error_msg}")

            # Step 4: Load images for metrics
        epi_img = nib.load(input.epi_ref)
        registered_img = nib.load(output.registered)
        template_img = nib.load(pam50_template)

        # Step 5: Validate header
        # Get expected zooms from template
        expected_zooms = template_img.header.get_zooms()[:3]
        header_validation = validate_registration_output(
            registered_img,
            expected_zooms=expected_zooms,
        )

        # Step 6: Compute metrics (SSIM/PSNR)
        # Normalize images for fair comparison
        template_data = template_img.get_fdata()
        registered_data = registered_img.get_fdata()

        # Clip and normalize
        template_norm = normalize_intensity(template_data, clip_percentiles=(2, 98))
        registered_norm = normalize_intensity(registered_data, clip_percentiles=(2, 98))

        # Read thresholds from config
        qc_cfg = CFG.get("qc", {})
        reg_cfg = qc_cfg.get("registration", {})
        ssim_min = reg_cfg.get("ssim_min", 0.60)
        psnr_min = reg_cfg.get("psnr_min", 15.0)

        # Compute metrics
        ssim_val = compute_ssim(registered_norm, template_norm)
        psnr_val = compute_psnr(registered_norm, template_norm)

        # Step 7: Write metrics JSON
        metrics_data = {
            "ssim": float(ssim_val),
            "psnr": float(psnr_val),
            "thresholds": {
                "ssim_min": ssim_min,
                "psnr_min": psnr_min,
            },
            "header": header_validation,
            "sct_version": result["sct_version"],
            "template": pam50_template,
            "status": ("pass" if (ssim_val >= ssim_min and psnr_val >= psnr_min) else "warn"),
        }

        Path(output.metrics).parent.mkdir(parents=True, exist_ok=True)
        with open(output.metrics, "w") as f:
            json.dump(metrics_data, f, indent=2)

            # Step 8: Create mosaics (before/after)


        def create_mosaic(img_data, title, out_path):
            """Create simple orthogonal mosaic."""
            # Get mid-slices
            mid_x = img_data.shape[0] // 2
            mid_y = img_data.shape[1] // 2
            mid_z = img_data.shape[2] // 2

            fig, axes = plt.subplots(1, 3, figsize=(12, 4))

            # Sagittal
            axes[0].imshow(img_data[mid_x, :, :].T, cmap="gray", origin="lower")
            axes[0].set_title("Sagittal")
            axes[0].axis("off")

            # Coronal
            axes[1].imshow(img_data[:, mid_y, :].T, cmap="gray", origin="lower")
            axes[1].set_title("Coronal")
            axes[1].axis("off")

            # Axial
            axes[2].imshow(img_data[:, :, mid_z].T, cmap="gray", origin="lower")
            axes[2].set_title("Axial")
            axes[2].axis("off")

            fig.suptitle(title)
            fig.tight_layout()
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(out_path, dpi=100, bbox_inches="tight")
            plt.close(fig)

            # Before: EPI reference (original)


        epi_data = epi_img.get_fdata()
        create_mosaic(
            epi_data,
            f"Before Registration: {wildcards.sub} {wildcards.task}",
            output.mosaic_before,
        )

        # After: Registered EPI in PAM50 space
        create_mosaic(
            registered_data,
            f"After Registration: {wildcards.sub} {wildcards.task} (PAM50 space)",
            output.mosaic_after,
        )

        # Step 9: Write provenance
        prov_path = Path(output.warp).with_suffix(".prov.json")
        with open(prov_path, "w") as f:
            json.dump(
                {
                    "step": "registration_pam50",
                    "inputs": {
                        "epi_ref": input.epi_ref,
                        "template": pam50_template,
                        "doctor_json": input.doctor_json,
                    },
                    "outputs": {
                        "warp": output.warp,
                        "registered": output.registered,
                        "metrics": output.metrics,
                    },
                    "sct_version": result["sct_version"],
                    "command": result["command"],
                    "metrics": metrics_data,
                    "timestamp": subprocess.check_output(["date", "-Iseconds"], text=True).strip(),
                },
                f,
                indent=2,
            )

            # Log completion
        with open(log[0], "a") as f:
            f.write(f"\nRegistration completed successfully.\n")
            f.write(f"SSIM: {ssim_val:.4f} (threshold: {ssim_min})\n")
            f.write(f"PSNR: {psnr_val:.2f} dB (threshold: {psnr_min})\n")
            f.write(f"Status: {metrics_data['status']}\n")
