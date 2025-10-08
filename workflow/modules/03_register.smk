# Registration module for SpinePrep
# Minimal SCT-based registration to PAM50 template


rule register_epi_to_pam50:
    """
    Register EPI reference to PAM50 template using SCT.
    
    Conservative defaults: rigid + affine only (no deformable).
    """
    input:
        epi_ref="{deriv}/sub-{sub}/func/sub-{sub}_task-{task}_run-{run}_desc-mean_bold.nii.gz",
        pam50_t2=lambda wildcards: os.environ.get("PAM50_DIR", "/opt/sct/data/PAM50")
        + "/PAM50_t2.nii.gz",
    output:
        warp="{deriv}/sub-{sub}/xfm/from-epi_to-pam50_warp.nii.gz",
        resampled="{deriv}/sub-{sub}/func/sub-{sub}_task-{task}_run-{run}_space-PAM50_desc-ref_bold.nii.gz",
    log:
        "{deriv}/logs/register_{sub}_{task}_{run}.log",
    resources:
        mem_mb=2000,
    run:
        from spineprep.register.sct import run_register
        import json

        # Run registration
        result = run_register(
            src=input.epi_ref,
            dest=input.pam50_t2,
            out_warp=output.warp,
            out_resampled=output.resampled,
        )

        # Write log
        with open(log[0], "w") as f:
            f.write(f"Command: {result['command']}\\n")
            f.write(f"SCT version: {result['sct_version']}\\n")
            f.write(f"Return code: {result['return_code']}\\n")
            f.write(f"\\nSTDOUT:\\n{result['stdout']}\\n")
            f.write(f"\\nSTDERR:\\n{result['stderr']}\\n")

            # Write provenance
        prov_path = Path(output.warp).with_suffix(".prov.json")
        with open(prov_path, "w") as f:
            json.dump(
                {
                    "step": "register_epi_to_pam50",
                    "inputs": {"epi_ref": input.epi_ref, "pam50_t2": input.pam50_t2},
                    "sct_version": result["sct_version"],
                    "command": result["command"],
                    "timestamp": subprocess.check_output(
                        ["date", "-Iseconds"], text=True
                    ).strip(),
                },
                f,
                indent=2,
            )

        if not result["success"]:
            raise RuntimeError(f"Registration failed with code {result['return_code']}")
