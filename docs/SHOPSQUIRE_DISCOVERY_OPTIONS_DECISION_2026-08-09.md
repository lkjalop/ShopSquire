# Discovery — What The Options Actually Are

**Date:** 2026-08-09 · Decision memo, not an audit
**Context:** SearXNG CAPTCHA'd; canonical-first only covers enrolled sources

---

## What I got wrong

I proposed canonical-first as if it solved discovery. It doesn't. It solves the **enrolled** case
and does nothing for a term with no enrolled source — which is precisely the case external search
exists for. Your criticism is correct: pinning a URL for every new term is not discovery, it's a
manually-maintained lookup table wearing discovery's name, and it grows an edge case per term.

One distinction I do want to keep, because it isn't the same thing as brittleness:

- **Determinism about *where authority comes from*** — a curated publisher registry with
  per-source allowed/forbidden claim types. This is the product. An auditor cannot accept
  "we took the RAM floor from whatever the index returned that morning." Keep it.
- **Determinism about *what words mean*** — regex → persona → floor. This is the brittleness, and
  it's the thing you've been rightly killing all week.

Canonical-first is the first kind. But I presented a coverage retreat as an architecture win, and
it isn't one.

---

## Measured facts

```
SearXNG default mix   duckduckgo, startpage, brave, qwant  -> CAPTCHA / unresponsive
                      mojeek                                -> 10 results, healthy
                      bing                                  -> 10 results, healthy

site: operator        works on Google-class engines (blocked)
                      returns 0 on mojeek/bing              -> our query syntax is coupled
                                                               to the engines that block

plain query + domain filter, engines=mojeek,bing
  MITRE ATT&CK ICS matrix          20 results, 5 on-domain, canonical /matrices/ics/ FIRST
  Hyper-V host requirements        10 results, 0 on-domain
  Factory IO system requirements   10 results, 0 on-domain
  Omniverse Isaac Sim requirements 10 results, 0 on-domain
```

Two separate problems, and only one is fixable by configuration:

1. **Uptime** — the default engine mix is majority-blocked. Fixable: pin `mojeek,bing`, and drop
   the `site:` operator (it silently zeroes those engines). The MITRE result actually *improved*
   without it — plain semantic query ranked the canonical page first, where the earlier `site:`
   discovery had picked `/analytics/`.
2. **Coverage** — Mojeek and Bing-via-SearXNG simply don't surface Microsoft Learn or Factory I/O
   for these queries. Not blocked. Just thinner indexes. **No configuration fixes this.**

---

## The reframe that matters

"External search" is being treated as one capability. It's two jobs with different answers.

### Job 1 — resolve an ambiguous *concept* into workload families

*"PLC-controlled factory and cyberattacks against the OT network"* → virtualisation + ICS
adversary behaviour + factory simulation.

**This needs no web search, and you already do it.** Screenshot 59 produced three correct
hypotheses — Factory I/O host requirements, Hyper-V host capability, ICS adversary behaviour —
with `External calls: 0`. The model interpreted; the registry's `applicability.workloads` mapped
each hypothesis to a publisher. Discovery contributed nothing.

This is the ambiguity case you're worried about, and it is already solved without search.

### Job 2 — get authoritative *numbers* for a named thing

*"Siemens NX 2025 needs 32GB RAM."*

This needs a specific document — but note **you already know the vendor**. "Siemens NX" → Siemens.
You do not need a general web index to find a vendor's own documentation. You need
vendor-resolution, which is a much smaller and much more reliable problem than open-web search.

The whole week's failure has been using Job-2 machinery (find a URL on the open web) for a problem
that is mostly Job 1 (needs no search) plus a narrow Job 2 (needs a vendor lookup).

---

## Options, honestly ranked

### 1. Pay for one search API. It is about $5/month at demo volume.

The boring correct answer. An independent-index provider (Brave operates its own crawl, so it does
not CAPTCHA the way a Google proxy does) with a low monthly credit tier. At demo and pilot volume —
hundreds of queries — this is somewhere between free and a rounding error.

Say the quiet part: **you are spending engineering days to avoid roughly the price of a coffee per
month.** That is the actual waste in this thread, not the API spend. Verify current terms before
committing — the two prior analyses contradicted each other on Brave's attribution and Tavily's
latency, and I have not verified either.

Keep the tier ladder so it stays cheap: cache → enrolled canonical → paid discovery only for
unenrolled named things. Paid calls stay near zero *because* of the ladder, not because the
provider is free.

### 2. Vendor-resolution instead of web search, for named products

For Job 2 the target is deterministic in *where* and open in *what*:

```
named product  ->  official vendor domain  ->  fetch docs  ->  model reads  ->  typed claim
                   (Wikidata P856 "official website", free, no CAPTCHA)
```

Wikidata has official-website links for essentially every commercial software product, via a free
SPARQL endpoint that does not rate-limit like a search engine. This is not a lookup table you
hand-maintain — it's a public dataset doing the vendor resolution for you.

This is the genuinely good engineering answer for Job 2, and it's cheaper *and* more reliable than
search, because you skip the "which of these 20 URLs is authoritative" step entirely.

### 3. Fix the SearXNG config anyway — it's two lines and it helps

`engines: mojeek, bing` and drop `site:`. Coverage stays thin, but uptime stops being random and
you get a free tier-3 that sometimes hits. Keep it as a fallback below the paid provider, not as
the primary.

### 4. Grow the registry from real traffic

Every buyer utterance naming something unenrolled becomes a row in an enrollment backlog. After
fifty real queries you will know the twenty publishers that actually matter for your vertical.
The registry stops being hand-curated guesswork and becomes a measured artifact — which is also a
much better story than "we curated 13 sources we thought would be useful."

### 5. Accept best-effort on the tail, and make the UX honest about it

Not a consolation prize. Your differentiator was never "we can find anything on the web" — it's
"we never claim fit without provenance." A system that says *"I don't have an enrolled source for
Siemens NX. Upload the requirements, paste the vendor link, or I'll stay provisional and tell you
exactly what's unverified"* is **on thesis**, not off it.

---

## Is this a failed demo?

Only if the demo claims something it isn't.

- Demo that claims **"we search the web"** → fails, visibly, on stage, at the mercy of a CAPTCHA.
- Demo that claims **"we refuse to guess, and here is the governed path from ambiguity to
  certainty"** → the CAPTCHA becomes a *feature of the story*: an unavailable source is reported as
  unavailable, the shortlist stays provisional, nothing is fabricated, and the buyer is given three
  real ways forward.

You already have the second demo built. Screenshot 59 is it: purpose retained, three interpretations,
one high-information question, per-hypothesis shelves, `Fit: conditional`,
`External calls: 0 · Paid calls: 0`. That is a better demo than a lucky search result, and it is
the one thing in this product nobody else is doing.

The bug in that screenshot was never that search failed. It was that the system **blamed a healthy
container and offered a dead end** instead of saying what it knew and what it could do next.

---

## Recommendation

1. Config fix now (two lines, free) — `mojeek,bing`, drop `site:`.
2. Wikidata vendor-resolution for named products — highest engineering value, free, no CAPTCHA.
3. One paid provider behind the tier ladder — budget $5–20/month, revisit at pilot scale.
4. Enrollment backlog from real traffic.
5. Reframe the demo narrative around governed uncertainty, which is what you actually built.

And stop treating the 13-source registry as a limitation. Ten curated, claim-typed, freshness-bounded
publishers is a stronger procurement artifact than an unbounded web crawl. The gap is the *tail*,
and the tail is what buyer upload and vendor-resolution are for.
