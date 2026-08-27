# Security policy

## Supported versions

Until the first stable release, security fixes are applied to the latest `0.1.x` development
version only. Production deployments should run the exact locked revision approved by their
operator.

## Reporting a vulnerability

Do not open a public issue containing vulnerability details, credentials, document contents, or
personal data. Send a private report to `security@sci-search.invalid` with the affected version,
impact, reproduction steps, and any suggested mitigation.

`security@sci-search.invalid` is an intentionally non-deliverable placeholder. A real monitored
institutional address must replace it before any public or production deployment. Once configured,
the project aims to acknowledge reports within three business days and provide an initial severity
assessment within ten business days.

Never include API keys, OIDC tokens, database passwords, raw private publications, model prompts,
or personal research data in reports unless an authorized maintainer provides a secure transfer
channel.

Scientific-validity disagreements—such as disputed interpretation, evidence quality, extraction
accuracy, or literature coverage—are handled through the evidence-review and validation process.
They are not software vulnerabilities unless they arise from an exploitable security failure.
