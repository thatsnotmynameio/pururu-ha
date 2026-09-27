# Security policy

## Supported versions

Only the latest release gets fixes. Update through HACS before reporting.

## Reporting a vulnerability

Report it privately through GitHub: **Security → Report a vulnerability** on this repository, or
<https://github.com/thatsnotmynameio/pururu-ha/security/advisories/new>. Please don't open a public
issue.

Include the pururu and Home Assistant versions, the `pururu:` configuration that triggers it (with
anything private removed) and what an attacker could do with it.

## Scope

pururu runs inside Home Assistant and uses the libraries Home Assistant ships. A vulnerability in
Home Assistant itself or in one of its dependencies belongs to the
[Home Assistant project](https://www.home-assistant.io/security/). `uv.lock` pins those libraries
only for pururu's tests, at the versions of the Home Assistant release it's tested against.
