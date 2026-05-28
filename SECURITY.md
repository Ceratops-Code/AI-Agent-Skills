# Security Policy

## Reporting A Vulnerability

Use GitHub private vulnerability reporting for this repository. Do not open a
public issue for vulnerabilities, leaked credentials, or bypass techniques.

When reporting, include:

- affected skill or file path
- the unsafe instruction or behavior
- impact and reproduction steps
- suggested fix, if known

The maintainer will triage reports through GitHub security advisories.

## Scope

In scope:

- instructions that could cause credential exposure
- unsafe GitHub, registry, or local filesystem workflows
- prompt-injection risks in bundled skill resources
- accidental private endpoint, token, or local path leakage

Out of scope:

- requests for new features
- disagreements about workflow preferences
- vulnerabilities in third-party services that these skills mention but do not
  ship
