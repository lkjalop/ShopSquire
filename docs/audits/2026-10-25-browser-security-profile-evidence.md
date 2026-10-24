# Owned security corpus and staff test profiles

25 October 2026. Independently assembled on `bf8d54ef`, using the new exact lean API/test environment and matching Chromium. No application authorization or detection threshold changed.

The required hosted UI profile now generates five owned inert LSB image carriers plus a clean control through the existing fixture generator. Previously it attempted manifest/coverage assertions against absent local dump files. Carrier extraction is checked by the generator. Manifest labels are expectations; actual detector/HTTP assertions remain separate and unchanged. These tests do not establish attack-family recall or live malware capability.

**63 tests pass**, zero failures/errors/skips, in 90.735 seconds: the actual steg/CV detector and HTTP contracts, clean-image control, and incident token revocation/expiry case. HTTP revocation is exercised against the owned server; expiry additionally uses the existing local token-record unit check. Native QR/OCR bindings come from the explicit test profile and host libraries.

The two-browser buyer/staff message exchange and one route-mocked admin rendering case then both pass, with no skips, in 55.985 seconds. The first exchanges real incident messages/receipts; the second qualifies rendering, not a real incident transition. Public local-demo incident creation is explicitly enabled only inside the two test scopes that require it. Default and production admission are unchanged; the separate publication-security controls remain passing.

The workflow passes Actionlint 1.7.12 syntax/context validation. This is not hosted execution or ShellCheck/Pyflakes verification. The earlier hosted failures remain retained, and broader security, provider/model and frontend gates remain separately required.
