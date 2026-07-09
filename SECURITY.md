# Security Policy

## Scope

SpinePrep is a research preprocessing pipeline. The most relevant "security"
concerns are: code that could damage or exfiltrate a user's data, unsafe handling
of file paths, or a dependency with a known vulnerability. SpinePrep does not run
a network service and is normally executed on trusted local or HPC systems.

## Supported versions

Security fixes are applied to the latest released version. There is no long-term
support branch yet.

| Version | Supported |
| ------- | --------- |
| 1.0.x   | ✅        |
| < 1.0   | ❌        |

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

- Preferred: use GitHub's private
  [**"Report a vulnerability"**](https://github.com/SpinePrep/SpinePrep/security/advisories/new)
  advisory form.
- Or email **sharifikiomars@gmail.com** with the subject line
  `SpinePrep security`.

Please include a description, the affected version/commit, and a minimal
reproduction if possible. You will get an acknowledgement within a few working
days. Once a fix is available we will credit you (unless you prefer to remain
anonymous) in the release notes.
