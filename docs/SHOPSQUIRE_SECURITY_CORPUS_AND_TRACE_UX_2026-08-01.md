# ShopSquire — Upload Security Corpus + Decision Trace Security Tab UX (2026-08-01)

*A generated, benign test corpus across 12 attack classes, and the Security-tab redesign needed to
make its results legible.*

---

## 1. The corpus

**Generator:** `scripts/gen_security_upload_corpus.py` · **Output:** `dump/test-sec/generated/`
**46 artifacts · 19 categories · 735 KB** — 10 critical, 23 high, 9 medium, 4 low.

Everything is inert by design: detection markers, not working exploits. SSRF targets are RFC 5737
TEST-NET / RFC 3927 link-local. All PII is synthetic. SVG scripts set a DOM attribute and exfiltrate
nothing. Decompression artifacts are bounded by `BOMB_BUDGET`.

### Verified behaviour (not just generated)
| Artifact | Proof |
|---|---|
| `polyglot_png_zip.png` | Opens as **PNG 640×480** *and* unzips to `payload/instructions.txt` |
| `png_bytes_declared_as.pdf` | Magic bytes `\x89PNG`, extension `.pdf` |
| `pixel_bomb_8000x8000.png` | **197 KB on disk → 192 MB decoded (64 MP, ~975× amplification)** |
| `exif_description_injection.jpg` | `ImageDescription` round-trips the injection string |
| `gps_and_serial_privacy.jpg` | GPS IFD present, `BodySerialNumber = SN-TEST-000000000` |

### Coverage map

| # | Directory | Artifacts | Key technique |
|---|---|---:|---|
| 01 | `01_mime_polyglot` | 6 | extension/content mismatch · PNG+ZIP and PDF+ZIP polyglots · SVG with script + `xlink` external fetch + `foreignObject` injection · bounded XML entity expansion |
| 02 | `02_metadata_injection` | 3 | EXIF `ImageDescription`/`Artist`/`Software` injection · XMP packet in a PNG `iTXt` chunk with external ref · GPS + serial + contact (privacy/retention path) |
| 03 | `03_resource_bombs` | 3 | 64 MP pixel bomb · 240-frame animated GIF · 4-level nested archive |
| 04 | `04_parser_differentials` | 4 | RIFF size overflow · truncated WebP · AVIF `ftyp` brand with no payload · PNG bad IHDR CRC |
| 05 | `05_qr_payloads` | 9 | cloud-metadata SSRF · loopback model port · punycode homoglyph · shortener · injection · synthetic PCI/SSN · `javascript:` · `data:text/html` · **two QRs in one image** |
| 06 | `06_visible_text_injection` | 5 | 6px sub-legible · low contrast (ΔL≈4) · rotated 37° · edge-cropped partial · mirrored |
| 07 | `07_adversarial_neardupe` | 4 | high-frequency patch · LSB-perturbed near-dupe · recompressed/resized near-dupe |
| 08 | `08_batch_replay_binding` | 7 | 3 clean + 1 poisoned batch · byte-identical replay · cross-tenant binding probe · stale-evidence probe |
| 10 | `10_supplier_documents` | 4 | PDF white-on-white injection · PDF external links · **CSV formula injection** · Unicode bidi/ZWSP/homoglyph |
| 12 | `12_runtime_probes` | 1 | concurrency storm · model timeout · oversize · storage isolation |

### The five that matter most

1. **`batch_poisoned_member.png`** (with its 3 clean siblings) — *one bad file must neither void the
   batch nor poison it.* This is the hardest correctness property in the whole corpus and the one
   most systems get wrong in both directions.
2. **`supplier_quote_indirect_injection.pdf`** — white-on-white instructions in a supplier quote.
   **The realistic B2B vector**: your agent reads a supplier document and the document tells it to
   skip the human gate. This is the one to demo.
3. **`polyglot_png_zip.png`** — valid image *and* valid archive. Tests whether validation looks past
   the header.
4. **`supplier_pricelist_formula_injection.csv`** — `=cmd|'/c calc'!A1`. Must be neutralised on
   ingest **and on export** (the export path is the one people forget).
5. **`qr_multi_code_chain.png`** — a decoder that stops at the first QR misses the second.

### Known-gap artifacts (documenting failure is the point)
`injection_mirrored.png` and `injection_edge_cropped.png` may not be caught. **Record that as a known
gap rather than fixing the test.** A corpus where everything passes is a corpus that isn't trying.

### Run it
```bash
python scripts/gen_security_upload_corpus.py --out dump/test-sec/generated
```
`SECURITY_CORPUS_MANIFEST.json` carries per-artifact `sha256`, `expected_detections`, OWASP mapping
and severity — so it can drive an automated assertion suite, not just manual upload.

**Next step:** wire the manifest into a pytest battery that asserts each artifact's
`expected_detections` fired. That converts the corpus from a demo prop into a regression gate.

---

## 2. Security tab — what's good and what's missing

The current tab is already analyst-shaped: **Decision · Business Impact · What Triggered It · What
Agents Found · What To Do Now · Push Recommendation · Threat Hunter Leads.** That structure is right
and should be kept.

**What it can't express for this corpus:**

| Gap | Why it matters |
|---|---|
| No **file identity** panel | Can't show declared-vs-sniffed MIME, which *is* the finding for half of category 01 |
| No **coverage matrix** | You see what fired; you can't see what ran, what passed, or **what was skipped and why** |
| No **batch view** | The single most important property (isolation) is invisible |
| No **containment ledger** | What the platform *did* — stripped, downscaled, wiped, renamed — isn't shown |
| No **untrusted-content chain** | Can't show that extracted text was treated as data, never instruction |
| No **replay/duplicate** signal | Same-hash resubmission is silent |

---

## 3. Proposed wireframes

### 3.1 Header — verdict + file identity (new)

```
┌─ Decision Trace · Security ─────────────────────────── trace 8f3a…c21 ─┐
│                                                                         │
│  ⛔ BLOCKED   severity CRITICAL   confidence 0.94   as_of 12:04:18Z     │
│  Prompt injection in supplier document — content quarantined            │
│                                                                         │
│─ FILE IDENTITY ────────────────────────────────────────────────────────│
│  uploaded as   supplier_quote_indirect_injection.pdf                    │
│  stored as     up_01J9K2…d4.bin   (generated name · outside webroot)    │
│  declared MIME application/pdf     sniffed  application/pdf     ✅ match │
│  size 41.2 KB    pages 1    sha256 9c2f…7ab1                            │
│  ⚠ seen before  no        parser  pdfminer 20240706                     │
└─────────────────────────────────────────────────────────────────────────┘
```

For a mismatch case the identity block is the finding:

```
│  declared MIME application/pdf     sniffed  image/png       ⛔ MISMATCH  │
│  → extension ignored; content type is authoritative; upload rejected    │
```

### 3.2 Coverage matrix — ran / passed / failed / **skipped** (new)

This is the honesty panel, and it is the direct analogue of the WHY-NOT idea: *what did you not
check, and why.*

```
┌─ CHECK COVERAGE  14 run · 9 pass · 3 fail · 2 skipped ─────────────────┐
│                                                                        │
│  ✅ magic-byte sniff        matched declared type            2 ms      │
│  ✅ size ceiling            41 KB / 12 MB                    0 ms      │
│  ✅ decoded-pixel ceiling   n/a (not an image)               —         │
│  ⛔ hidden-text scan        white-on-white run, 2 spans     18 ms      │
│  ⛔ injection patterns      2 matches (tool_abuse, authority) 6 ms     │
│  ⛔ external references     1 link → 192.0.2.10 (TEST-NET)   3 ms      │
│  ✅ archive trailer         no data after %%EOF              1 ms      │
│  ✅ entity expansion        no DTD                           1 ms      │
│  ⚪ steganography           SKIPPED — not a raster image               │
│  ⚪ QR decode               SKIPPED — not a raster image               │
│                                                                        │
│  ⚠ NOT COVERED for this file type: embedded-font shellcode,           │
│    JavaScript actions in /OpenAction. Documented gap, not a pass.      │
└────────────────────────────────────────────────────────────────────────┘
```

**The `⚪ SKIPPED` rows and the NOT-COVERED footer are the differentiator.** Every other security UI
shows findings. Showing what you *didn't* look at — and saying a skip is not a pass — is the same
discipline as `gates_pass: false`, applied to a screen.

### 3.3 Containment ledger — what was actually done (new)

```
┌─ CONTAINMENT APPLIED ──────────────────────────────────────────────────┐
│  ✔ stored under generated name, outside webroot, no execute bit        │
│  ✔ EXIF/XMP stripped before any model call        (3 fields removed)   │
│  ✔ extracted text marked untrusted:data           (never instruction)  │
│  ✔ external links NOT followed                    (1 blocked)          │
│  ✔ downscaled 4096→1280 for VLM; full-res kept for steg/QR only        │
│  ✔ quarantined to case CASE-2026-0801-A4 · retention 90d · deletable   │
│                                                                        │
│  ✘ NOT auto-deleted — operator decision required                       │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.4 Batch isolation — the key property, made visible (new)

```
┌─ BATCH  upload_batch_7c21   4 files · 1 quarantined · 3 usable ────────┐
│                                                                        │
│  file                      verdict      findings   evidence            │
│  ─────────────────────────────────────────────────────────────────────│
│  batch_clean_1.png         ✅ clean      —          RETAINED           │
│  batch_clean_2.png         ✅ clean      —          RETAINED           │
│  batch_clean_3.png         ✅ clean      —          RETAINED           │
│  batch_poisoned_member.png ⛔ blocked    2          QUARANTINED        │
│                                                                        │
│  ISOLATION PROOF                                                       │
│   ✔ poisoned file's extracted text never entered the shared context    │
│   ✔ 3 clean files still produced usable product evidence               │
│   ✔ no batch-wide wipe — one bad file did not void the other three     │
│                                                                        │
│  [ Show why batch_poisoned_member.png was blocked ]                    │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.5 Untrusted-content chain — provenance of every extracted string (new)

```
┌─ EXTRACTED CONTENT · PROVENANCE ───────────────────────────────────────┐
│                                                                        │
│  "…skip the human gate…"                                               │
│    origin    supplier_quote…pdf ▸ page 1 ▸ hidden text run 2           │
│    class     untrusted:document_text                                   │
│    reached   pattern scanner ✓   ·   model context ✗ BLOCKED           │
│    action    quarantined · surfaced to operator · not narrated         │
│                                                                        │
│  "Item: Laptop 15in  Qty: 25  Unit: AUD 1,410.00"                      │
│    origin    supplier_quote…pdf ▸ page 1 ▸ visible body                │
│    class     untrusted:document_text                                   │
│    reached   pattern scanner ✓   ·   model context ✓ AS DATA           │
│    action    parsed into quote fields · requires human confirmation    │
└────────────────────────────────────────────────────────────────────────┘
```

**This panel is the strongest thing you could build here.** It shows, per string, that content from
an untrusted document was carried as *data* and never as *instruction* — which is the entire LLM01
claim, made visual. Nobody else demos this.

### 3.6 QR / multi-artefact detail

```
┌─ EMBEDDED CODES  2 found ──────────────────────────────────────────────┐
│  #1  position 60,140   type QR                                         │
│      decoded  https://xn--shpsquire-8db.example/pay                    │
│      ⛔ punycode homoglyph · unicode-normalised: shopsquire (spoof)     │
│      action  quarantined · not followed · not shown to model           │
│                                                                        │
│  #2  position 480,140  type QR                                         │
│      decoded  http://127.0.0.1:6379/                                   │
│      ⛔ loopback service · egress allowlist deny                        │
│      action  quarantined · not followed                                │
│                                                                        │
│  ✔ ALL codes decoded — scan did not stop at the first                  │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.7 Layout — where these live

Keep the existing incident brief as the top section. Add the new panels beneath it, collapsed by
default, in this order:

```
Security tab
├── ⛔ Verdict + File Identity          (always open — 3.1)
├── ▸ Incident Brief                    (existing — keep as-is)
├── ▸ Check Coverage                    (collapsed — 3.2)   ← the honesty panel
├── ▸ Containment Applied               (collapsed — 3.3)
├── ▸ Extracted Content Provenance      (collapsed — 3.5)   ← the LLM01 proof
├── ▸ Embedded Codes                    (only if codes found — 3.6)
└── ▸ Batch Isolation                   (only if batch > 1 — 3.4)
```

The existing `leafIsVisible` / `showEmptyPanels` progressive-disclosure machinery already does the
"hide empty specialist panels" job — reuse it rather than adding a new pattern.

---

## 4. Build order

| # | Item | Effort | Why |
|---|---|---|---|
| 1 | **Manifest-driven pytest battery** — assert each artifact's `expected_detections` | **M** | Turns the corpus into a regression gate. Do this before any UI |
| 2 | **File identity panel** (3.1) | **S** | The finding for a whole attack class; data already exists at intake |
| 3 | **Check coverage matrix** (3.2) | **M** | Needs checks to emit ran/passed/skipped + reason. The differentiator |
| 4 | **Containment ledger** (3.3) | **S** | Actions are already taken; they just aren't surfaced |
| 5 | **Extracted content provenance** (3.5) | **M** | The strongest demo artifact on this page |
| 6 | **Batch isolation** (3.4) | **M** | Needs per-file verdicts in one batch envelope |
| 7 | Embedded codes detail (3.6) | **S** | Mostly a render of existing QR data |

**Do #1 first.** 46 artifacts with declared expectations is a test suite pretending to be a folder;
a UI built before the assertions would be showing results nobody has verified.

---

## 5. What this does for the David problem

His two hard questions were *"how do you know competitor prices are accurate?"* and *"what happens if
inventory data is stale or the RFQ email is wrong?"* — both fundamentally about **trusting external
input**.

Panel 3.5 answers a third, sharper version he didn't ask: **what happens when a supplier's own
document tries to instruct your agent?** Showing a real supplier PDF, the hidden instruction inside
it, and the trace proving it was carried as data and never reached the model as instruction — that is
a 60-second segment that reframes the platform from *"agentic commerce demo"* to *"someone who has
thought about the supply chain as an attack surface."*

---

*Corpus generated and verified. Security tab changes are proposed, not implemented.*
