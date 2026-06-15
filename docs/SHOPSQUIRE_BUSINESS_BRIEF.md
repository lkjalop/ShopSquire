# ShopSquire — Business Brief
**One page. Plain language. What it is, who it helps, why it's worth it.**

---

## The one-liner
**An AI shopping assistant that's safe enough to actually leave running on its own.**

## The problem (why this exists)
Every retailer is being told to "add an AI agent." The agents demo well and break in production: they **recommend products you don't stock**, get **tricked by manipulated image uploads / prompt injection**, **wave through fraudulent returns**, and **can't explain or be audited.** So businesses won't hand them real decisions. **The blocker to AI in commerce isn't intelligence — it's trust.**

## What it does (in outcomes, not features)
| Capability | Business outcome |
|---|---|
| Understands what the shopper means, recommends, asks the *right* clarifying question | **Higher conversion** — fewer shoppers bounce |
| Refuses to invent a product/brand it can't verify against your catalog | **Fewer wrong-item returns; no brand-damaging AI mistakes** |
| Acts autonomously by default; pulls in a human only at a real boundary | **Lower labor cost** — the few cases that need a person get one; the rest don't |
| Detects attacks in uploads, fraud in return claims, risky IPs/suppliers | **Loss prevention** — fraud and AI-era attacks caught before they cost money |
| Logs *every* decision as an auditable trace | **Deployability** — compliance/legal can actually approve it |

Net: **more revenue · less loss · lower cost · actually deployable.**

## Who it's for (ICP)
**Mid-market online retailers & marketplaces** — too big to do it by hand, too small to staff *both* a data-science team *and* a trust-&-safety team. Best fit = those with a real threat surface: **customer image uploads, returns/warranty, and suppliers.** (ANZ angle: AusPost/StarTrack-integrated marketplaces.)

## Why it's different
The market is split into **dumb-but-safe** (keyword search) and **smart-but-untrustworthy** (LLM bots that hallucinate and can't be audited). The **smart *and* trustworthy/auditable** quadrant is essentially empty. That's the position: *the trust layer that makes agentic commerce deployable.*

## Why now
The whole industry is racing to put autonomous agents into commerce. Capability is no longer the constraint — **trust is.** Whoever makes agentic commerce *safe to deploy* wins the adoption, not whoever makes it marginally smarter.

## The proof (this is what makes it credible, not hype)
- **Measured, not asserted:** an eval harness scores it — query understanding, anti-hallucination, and security detection all near-perfect on the test set, with a 0% false-alarm rate. (`python -m eval.run_eval`)
- **Auditable by design:** every decision opens into a trace showing which agents fired and why.
- **The thesis is runnable:** a bounded-autonomy demo shows it handling most cases solo and escalating only the genuine ones. (`python scripts/demo_bounded_autonomy.py`)

## Honest risks (so this isn't a pitch deck)
- **Breadth over depth.** Built wide and fast — three flawless things beat thirty half-built ones. Focus the demo.
- **Value is conditional on threat surface.** A tiny single-brand store doesn't need the security half; a marketplace with UGC + returns does. Choose the ICP accordingly.
- **It's a strong prototype proving a thesis, not a hardened product.** The next step is *validation* (a live demo to a real audience), not more building.

## The decision this brief supports
*Is this worth pursuing?* → **Yes, conditionally:** the thesis is real and the proof exists. The cheapest way to confirm it is a **focused live demo to a target buyer**, not more engineering. If the demo lands, invest in depth + the security-heavy ICP. If it doesn't, you've spent days, not months.
