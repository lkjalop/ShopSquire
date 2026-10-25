# Screenshots 038 / 039 — verification

**Date:** 2026-09-12 · **HEAD:** `a0218c26` + **31 uncommitted files**
**Question asked:** are the unit-cost bug (038) and the broken dollar figure (039) fixed?

**Short answer: yes in practice, no in principle.** The root cause is fixed and verified live. The
two *downstream* string defects the screenshots exposed are still in the code, unguarded — I
reproduced both byte-for-byte by calling the functions with the inputs the screenshots show.

---

## 1. What the screenshots showed

| | Screenshot 038 | Screenshot 039 |
|---|---|---|
| Buyer said | *"need help with a **2000** laptop for digital twin?"* | *"i mean a **$2000** laptop?"* → *"per item?"* |
| System read | **2000 units** | still 2000 units |
| Result | *"per-unit floor is $629 — about **$1,258,000** total"*, role `PROCURE_SUBJECT`, bulk fulfilment plan ("6 of 2000 available", "Transfer 49…") | *"a practical budget band is $629-**$2,000.0**"* and *"2000 units **for general fit your $4,000,000**"* |

Three distinct defects: **(A)** a singular article-led price read as a quantity; **(B)** malformed
currency `$2,000.0`; **(C)** the ungrammatical phrase *"for general fit your"*.

---

## 2. Defect A — the unit-cost misread: **FIXED**

### Parser level

```
'need help with a 2000 laptop for digital twin?'  →  qty=None   budget=(None, 2000, 'around')
'a 2000 laptop'                                   →  qty=None   budget=(None, 2000, 'around')
'i mean a $2000 laptop?'                          →  qty=None   budget=(None, 2000, 'around')
'2000 laptops'                                    →  qty=2000   budget=None            ← correctly still a count
```

The singular-article discriminator now works: *a* 2000 laptop is a $2,000 laptop; *2000 laptops*
is a count. The team's own note confirms the mechanism — the budget grammar now recognises the
article-led price construction "without a fixed list of preceding verbs/prepositions", i.e. no
keyword table was added.

### Live, on the running stack — the exact three-turn sequence

| Turn | Budget | Quantity | Transition |
|---|---|---|---|
| *"need help with a 2000 laptop for digital twin?"* | `None..2000 (around)` | **None** (`requested_qty=1`) | NEW_CATEGORY |
| *"i mean a $2000 laptop?"* | `None..2000` | None | COMMERCIAL_AMENDMENT |
| *"per item?"* | `None..2000` | None, `budget_scope=per_unit` | COMMERCIAL_AMENDMENT |

No "2000 units", no $1,258,000, no `PROCURE_SUBJECT` role, no bulk fulfilment plan, and no
*"Is that budget per item, or the total for all 2000?"* question. **The running API has the fix**
(they restarted it: PID 36108 → 45028).

Note this fix is in the **31 uncommitted files**, not in any commit. It is one `git stash` or one
bad merge away from disappearing.

---

## 3. Defects B and C — **not fixed, only unreachable on that input**

Both reproduce exactly when the functions are called with the inputs the screenshots show.

### C · `core.py:2082` + `:2089` — *"for general fit your"*

```python
uc = (list(getattr(decision, "use_cases", None) or ["your use case"]))[0].replace("_", " ")
...
return (f"Good news — {q} units for {uc} fit your ${total / 100:,.0f}: ...")
```

Executed with `use_cases=["general"]`:

```
Good news — 2000 units for general fit your $4,000,000: about $1,258,000 total at $629 each.
```

**Byte-for-byte the screenshot-039 sentence.** With an *empty* `use_cases` the same function
produces the readable *"for your use case"* — so the code already knows the right fallback, it just
does not recognise `"general"` as the generic bucket.

**This is a live risk, not a hypothetical.** `turn_router.py:1207` produces the literal string:

```python
use_cases = ",".join(prior.get("use_cases") or []) or "general"
```

**Fix:** treat `"general"` (and any generic placeholder) exactly as the empty case at `core.py:2082`.

### B · `answer_quality.py:255` — `$2,000.0`

```python
return f"{direct} a practical budget band is ${lo_band:,}-${hi_band:,}. {base_message}".strip()
```

Executed with `canonical_budget = {"budget_max": 2000.0}`:

```
For your case, a practical budget band is $629-$2,000.0. Base.
```

**Byte-for-byte the screenshot-039 figure.** `BudgetParse` types `budget_max` as `Optional[int]`
and coerces with `int(...)`, so the *typed* path is safe — but line 224 reads
`canonical_budget.get("budget_max")` from a **plain dict**, which carries no such guarantee, and
the screenshot proves a float reached it at least once.

**Fix:** `:,.0f` instead of `:,` on both bands — the same format the adjacent `_bulk_message`
already uses correctly.

### Do they still ship today?

On a genuine bulk turn, no — both render correctly, because neither bad input occurred:

> *"For your case, a practical budget band is $629-$1,200. Good news — 50 units for **your use
> case** fit your $60,000: about $31,450 total at $629 each."*

Clean integers, readable prose. So the defects are **latent**: the screenshots' path no longer
reaches them, and nothing prevents another path from doing so.

---

## 4. Summary

| Defect | Status | Location | Fix |
|---|---|---|---|
| **A** Singular price read as quantity | ✅ **Fixed**, verified live | budget grammar + core | done (uncommitted) |
| **B** `$2,000.0` malformed currency | ⚠️ **Latent** | `answer_quality.py:255` | `:,.0f` |
| **C** *"for general fit your"* | ⚠️ **Latent, producible** | `core.py:2082` ← `turn_router.py:1207` | treat `"general"` as the empty case |

**Recommended:** two one-line hardening fixes, plus a regression asserting that no buyer-facing
message contains a currency figure with a decimal, and none contains a raw slug where a use-case
phrase belongs. Both are cheap and belong to the invariant family (I2 Budget) rather than to
example tests — they guard a *rendering property*, not a particular sentence.

**And commit the tree.** 31 files, including this fix, are uncommitted.

---

## Method

Offline execution of `parse_commercial_terms`, `parse_budget`, `core._bulk_message` and
`answer_quality._render_budget_decision`; the exact three-turn screenshot sequence plus two bulk
turns run live against the running stack. No cart, supplier, approval or payment action was taken.
