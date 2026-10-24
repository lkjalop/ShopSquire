# Lean browser-test dependency profile

25 October 2026. Hosted UI tests exposed missing `psutil` and QR/OCR Python bindings after the installation command succeeded. They were already locked in the main closure; the lean exported test profile omitted them. They are now explicit test dependencies and roots. No locked package version changed and no model framework was added to the test profile.

Two Windows/Linux export controls first failed unchanged on the preceding profile. The independent export suite now passes **12 tests, zero failures/errors/skips**. All eight exports were regenerated and validated. Lock SHA-256: `5a13f34581ad8603c7fa1d28c63861ba79ceea758f5f3b8ce43cbb88ca17147b`.

A new Python 3.11 Windows environment installed committed bootstrap/API/test profiles in **151.625 seconds**. `pip check`, profile check and compilation passed. Actual imports of process monitoring and native QR bindings succeeded, and the OCR binary returned its version. Installed package names/versions exactly matched the union of those three exports, with no missing, extra or mismatched package.

That fresh environment then passed **17 tests, zero failures/errors/skips**, including five real API/browser vision-performance controls and the export suite, in 23.578 seconds. The scope is basic CV and bounded fixture processing, not vision-model accuracy or the whole security suite. Matching Node dependencies and Python Chromium were supplied explicitly. Process RSS/handle/headroom limits were unchanged; no violation occurred.

A new lock-wide PyPI advisory query covered all **217 distinct locked versions** with zero matches, errors or skips. This is not an operating-system/native-library audit. Linux QR system libraries and required corpus/actor profiles still need their own hosted evidence. Other hosted UI/security failures remain open; importing dependencies alone does not certify their behaviour.
