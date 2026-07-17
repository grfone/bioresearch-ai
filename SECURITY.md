# SECURITY

# Security Policy

## Supported Versions

Security updates are provided for the latest stable release.

Older versions may not receive security fixes.

| Version            | Supported |
| ------------------ | --------- |
| Latest Release     | ✅         |
| Development Branch | ✅         |
| Older Releases     | ❌         |

---

# Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly.

Please include:

* Description of the issue
* Steps to reproduce
* Potential impact
* Suggested mitigation (if available)

Avoid publicly disclosing vulnerabilities before they have been investigated and addressed.

---

# Security Principles

BioResearch AI follows several core security principles.

## Least Privilege

Components should only receive the permissions required to perform their tasks.

---

## Secure Defaults

The project should work securely without requiring extensive configuration.

---

## Secrets Management

Never commit:

* API keys
* Tokens
* Passwords
* Credentials
* Private certificates

Use environment variables or secret-management solutions instead.

---

## Dependency Management

Dependencies should be updated regularly to receive security fixes.

Recommended practices include:

* Version pinning
* Automated dependency scanning
* Vulnerability monitoring

---

## AI Safety

Language model outputs should never be treated as verified scientific evidence.

Generated reports should always:

* Include citations
* Distinguish evidence from inference
* Encourage expert review

---

## Data Privacy

BioResearch AI is designed primarily for public biomedical literature.

If processing sensitive or proprietary data:

* Follow applicable privacy regulations
* Protect confidential information
* Avoid transmitting sensitive data to third-party services unless authorized

---

## Responsible AI

The project aims to support scientific research—not replace scientific judgment.

Users remain responsible for:

* Verifying citations
* Validating conclusions
* Confirming biological interpretations

---

# Best Practices

When deploying BioResearch AI:

* Keep dependencies updated
* Protect API credentials
* Enable HTTPS
* Restrict production access
* Monitor logs
* Apply the principle of least privilege

---

# Disclosure Policy

Reported vulnerabilities will be reviewed promptly.

Where appropriate:

1. Confirm the issue
2. Develop a fix
3. Release a patched version
4. Publicly disclose the vulnerability after remediation

Responsible disclosure helps protect the entire community.

Thank you for helping improve the security of BioResearch AI.
