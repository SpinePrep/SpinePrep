# Security Policy

## Supported Versions

We provide security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

### How to Report

Send an email to **sharifikiomars@gmail.com** with:

- **Subject**: `[SECURITY] SpinePrep vulnerability report`
- **Description**: Detailed description of the vulnerability
- **Impact**: Potential impact and affected components
- **Steps to reproduce**: If applicable
- **Suggested fix**: If you have one

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Assessment**: Within 7 days
- **Fix timeline**: Depends on severity
  - **Critical**: Patch within 7 days
  - **High**: Patch within 30 days
  - **Medium/Low**: Next minor release

### Disclosure Policy

- We will coordinate disclosure with you
- Public disclosure after patch is released
- Credit given to reporter (unless anonymity requested)

## Security Considerations

### Data Privacy

SpinePrep processes medical imaging data. Please ensure:

- **No PHI in issues**: Redact patient identifiers from bug reports
- **Local processing**: SpinePrep does not send data externally
- **No telemetry**: No usage statistics or analytics collected

### Configuration

- **No secrets in configs**: Use environment variables for sensitive paths
- **File permissions**: Ensure output directories have appropriate permissions
- **Container isolation**: Use containers for additional isolation if needed

### Known Limitations

- **No authentication**: SpinePrep assumes trusted local environment
- **File overwrites**: Processing may overwrite files in output directory
- **Resource limits**: No built-in memory/CPU limits (use container constraints)

## Best Practices

1. **Keep SCT updated**: Security fixes in Spinal Cord Toolbox
2. **Pin versions**: Use specific version tags for reproducibility
3. **Validate inputs**: Use `spineprep doctor` before processing
4. **Review outputs**: Check QC reports for unexpected results
5. **Restrict access**: Limit who can modify configuration and run pipeline

## Acknowledgments

We appreciate the security research community and will acknowledge responsible disclosures.

