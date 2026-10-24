# Retired storefront dependency tree

The obsolete `src/frontend/storefront-react` was already deprecated, script-locked and excluded from the supported build/CI paths. A read-only 25 October npm lock audit reports nine affected packages: six high, two moderate and one low, with zero critical findings. This is separate from the two active frontend locks, both re-audited with zero findings on the same date.

The repair removes only the deprecated package/install manifests and updates ownership/setup notes. Historical source remains available so old file references still resolve; the prior manifests remain in Git history at `f83c072d`. No vulnerable package was renamed, ignored or marked safe. The unsupported dependency surface was retired rather than upgraded into another supported frontend.

The [structured receipt](2026-10-25-deprecated-storefront-retirement-evidence.json) records before-manifest hashes, native npm exit status, affected packages and unchanged active-manifest hashes. Repository search found no active script, CI, test or compose installation of the obsolete package. This does not establish zero vulnerabilities for the complete repository, operating-system images or archived source. Earlier C22 test results retain their original source identity; this later change alters no active application or frontend code.
