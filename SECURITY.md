# Security

## Supported versions

Only the current `world-class/v1` source line for **PlotProof 0.1.0a2** is considered for fixes. Older snapshots are unsupported. This is a best-effort project with no SLA, production support, or guarantee that every reported issue will receive a fix.

## Reporting a vulnerability

Do not include credentials, private data, proprietary inputs, personal paths, or unreduced production artifacts in public issues. Report vulnerabilities privately through [GitHub Security Advisories](https://github.com/gedouluhui/plotproof/security/advisories/new). Include the affected version or commit, operating system, runtime/dependency versions, a minimal sanitized reproduction, and the security impact you observed.

## Security boundaries

The checker executes a local figure module and an owned PDFium worker against bounded local files. It is not a hostile-code sandbox or a general PDF security checker.

Hashes and fingerprints identify bytes or normalized inputs; they are not signatures or proof of trust. Review generated reports before sharing because metadata, names, prompts, queries, or previews may still be sensitive.
