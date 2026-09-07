# Security Policy

## Supported Version

Security fixes are applied to the latest release and the current `main` branch.

## Reporting a Vulnerability

Do not open a public issue for vulnerabilities that could expose credentials, execute arbitrary commands, access local files, or permit server-side request forgery. Use GitHub's private vulnerability reporting feature for this repository instead.

Include the affected version, operating system, reproduction steps, impact, and any suggested mitigation. Do not include real cookies, tokens, downloaded private media, or other user data in a report.

## Security Boundaries

- ReClip accepts public HTTP and HTTPS media URLs. Agent interfaces reject local-network URLs and URLs containing credentials.
- The MCP server writes only to `RECLIP_MCP_DOWNLOAD_DIR`, which defaults to `~/Downloads/ReClip`.
- MCP download tools require an explicit authorization confirmation argument.
- ReClip does not provide DRM, authentication, subscription, or access-control bypasses.
- Cookies and authentication data must never be committed to the repository or sent to the hosted public instance.
