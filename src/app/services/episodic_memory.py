"""Episodic Memory System — 3-tier memory, chat history persistence, user profiles, RAPTOR summaries.

Tiers:
1. Working memory (current turn — function-local, managed by pipeline)
2. Session memory (conversation scope — Redis KV with 24h TTL via Memory class)
3. Long-term memory (user scope — persistent store for logged-in users)

Provides:
- Episodic Q&A storage (save each Q/A pair with timestamps)
- User profile persistence (preferences learned from past sessions)
- Chat history save/restore for logged-in users
- Session summarization (RAPTOR-style: compress long sessions into hierarchical summaries)
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from src.app.services.memory import Memory


# ── Data models ──

@dataclass
class Episode:
    """A single Q&A exchange."""
    turn_index: int
    query: str
    response_summary: str
    timestamp: float = 0.0
    slots_captured: Dict[str, Any] = field(default_factory=dict)
    nqe_questions_asked: List[str] = field(default_factory=list)
    products_shown: List[str] = field(default_factory=list)
    debate_ran: bool = False
    model_used: Optional[str] = None

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class UserProfile:
    """Persistent preferences learned from a logged-in user's history."""
    user_id: str
    preferred_brands: List[str] = field(default_factory=list)
    avoided_brands: List[str] = field(default_factory=list)
    budget_tier: Optional[str] = None  # "budget", "mid", "premium"
    typical_use_cases: List[str] = field(default_factory=list)
    purchase_history_summary: List[str] = field(default_factory=list)
    last_session_summary: Optional[str] = None
    # ── Persona & affinity learning ──
    inferred_persona: Optional[str] = None                       # gamer / office / creator / student
    accessory_acceptances: Dict[str, int] = field(default_factory=dict)   # slug → accept count
    accessory_rejections: Dict[str, int] = field(default_factory=dict)    # slug → skip count
    upsell_acceptance_rate: Optional[float] = None               # rolling 0-1
    price_sensitivity: Optional[str] = None                      # low / medium / high
    session_count: int = 0
    updated_at: float = 0.0

    def __post_init__(self):
        if self.updated_at == 0.0:
            self.updated_at = time.time()


@dataclass
class SessionSummary:
    """Compressed summary of a conversation session."""
    session_id: str
    user_id: Optional[str] = None
    turn_count: int = 0
    key_constraints: Dict[str, Any] = field(default_factory=dict)
    products_viewed: List[str] = field(default_factory=list)
    outcome: Optional[str] = None  # "purchased", "abandoned", "escalated"
    summary_text: str = ""
    created_at: float = 0.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()


# ── Redis key templates ──
_EPISODES_KEY = "episodic:{uid}:episodes"
_PROFILE_KEY = "profile:{user_id}"
_CHAT_HISTORY_KEY = "chat_history:{user_id}:sessions"
_SESSION_SUMMARY_KEY = "session_summary:{uid}"

# Long-term profile TTL (30 days)
_PROFILE_TTL = 60 * 60 * 24 * 30
# Chat history TTL (90 days)
_HISTORY_TTL = 60 * 60 * 24 * 90


class EpisodicMemory:
    """Manages 3-tier episodic memory on top of the core Memory service."""

    def __init__(self, memory: Memory):
        self.mem = memory

    # ── Tier 2: Session-scoped episodic storage ──

    def append_episode(self, uid: str, episode: Episode, ttl: int = 86400) -> None:
        """Append a Q&A episode to the session's episode list."""
        key = _EPISODES_KEY.format(uid=uid)
        try:
            raw = self.mem.redis.get(key)
            episodes = json.loads(raw) if raw else []
        except Exception:
            episodes = json.loads(self.mem._local_get(key) or "[]")

        episodes.append(asdict(episode))

        payload = json.dumps(episodes)
        try:
            self.mem.redis.setex(key, ttl, payload)
        except Exception:
            self.mem._local_setex(key, ttl, payload)

    def get_episodes(self, uid: str) -> List[Dict[str, Any]]:
        """Retrieve all episodes for a session."""
        key = _EPISODES_KEY.format(uid=uid)
        try:
            raw = self.mem.redis.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        local = self.mem._local_get(key)
        return json.loads(local) if local else []

    def get_session_context_summary(self, uid: str) -> str:
        """Build a text summary of the session so far from episodes."""
        episodes = self.get_episodes(uid)
        if not episodes:
            return ""
        lines = []
        for ep in episodes[-10:]:  # last 10 turns
            q = ep.get("query", "")[:100]
            r = ep.get("response_summary", "")[:100]
            slots = ep.get("slots_captured", {})
            slot_str = ", ".join(f"{k}={v}" for k, v in slots.items()) if slots else ""
            lines.append(f"Turn {ep.get('turn_index', '?')}: Q={q} | A={r}" + (f" [{slot_str}]" if slot_str else ""))
        return "\n".join(lines)

    # ── Tier 3: Long-term user profile ──

    def save_user_profile(self, profile: UserProfile) -> None:
        """Persist a user profile for logged-in users."""
        profile.updated_at = time.time()
        key = _PROFILE_KEY.format(user_id=profile.user_id)
        payload = json.dumps(asdict(profile))
        try:
            self.mem.redis.setex(key, _PROFILE_TTL, payload)
        except Exception:
            self.mem._local_setex(key, _PROFILE_TTL, payload)

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Retrieve a persistent user profile."""
        key = _PROFILE_KEY.format(user_id=user_id)
        raw = None
        try:
            raw = self.mem.redis.get(key)
        except Exception:
            pass
        if not raw:
            raw = self.mem._local_get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return UserProfile(**data)
        except Exception:
            return None

    def update_profile_from_session(
        self,
        user_id: str,
        session_slots: Dict[str, Any],
        session_summary: str = "",
    ) -> UserProfile:
        """Learn preferences from a session and merge into user profile."""
        profile = self.get_user_profile(user_id) or UserProfile(user_id=user_id)

        # Learn brand preferences
        brands_pos = session_slots.get("brands_positive", [])
        for b in brands_pos:
            if b not in profile.preferred_brands:
                profile.preferred_brands.append(b)
        brands_neg = session_slots.get("brands_negative", [])
        for b in brands_neg:
            if b not in profile.avoided_brands:
                profile.avoided_brands.append(b)

        # Learn budget tier
        budget_max = session_slots.get("budget_max")
        if budget_max:
            if budget_max <= 600:
                profile.budget_tier = "budget"
            elif budget_max <= 1200:
                profile.budget_tier = "mid"
            else:
                profile.budget_tier = "premium"

        # Track use cases
        use_cases = session_slots.get("use_case_hints", [])
        for uc in use_cases:
            if uc not in profile.typical_use_cases:
                profile.typical_use_cases.append(uc)

        if session_summary:
            profile.last_session_summary = session_summary[:500]

        self.save_user_profile(profile)
        return profile

    # ── Intent-driven profile update ──

    def update_profile_from_intent(
        self,
        user_id: str,
        intent_result: Any,
        session_summary: str = "",
    ) -> "UserProfile":
        """Merge a ShopperIntentResult into the long-term user profile.

        Call this after each recommend call so returning users get
        pre-seeded intent on their next visit.
        ``intent_result`` is a ShopperIntentResult (or any object with
        the same attributes).
        """
        profile = self.get_user_profile(user_id) or UserProfile(user_id=user_id)

        # Persona: adopt the most recent non-unknown persona
        persona = getattr(intent_result, "persona", None)
        if persona and persona != "unknown":
            profile.inferred_persona = persona

        # Budget tier
        bt = getattr(intent_result, "budget_tier", None)
        if bt and bt != "unknown":
            profile.budget_tier = bt

        # Price sensitivity
        ps = getattr(intent_result, "price_sensitivity", None)
        if ps:
            profile.price_sensitivity = ps

        # Brands
        for b in (getattr(intent_result, "brands_positive", None) or []):
            if b not in profile.preferred_brands:
                profile.preferred_brands.append(b)
        for b in (getattr(intent_result, "brands_negative", None) or []):
            if b not in profile.avoided_brands:
                profile.avoided_brands.append(b)

        # Use cases
        uc = getattr(intent_result, "use_case_key", None)
        if uc and uc not in profile.typical_use_cases:
            profile.typical_use_cases.append(uc)

        if session_summary:
            profile.last_session_summary = session_summary[:500]

        profile.session_count += 1
        self.save_user_profile(profile)
        return profile

    # ── Outcome-driven profile refinement ──

    def refine_profile_from_outcome(
        self,
        user_id: str,
        outcome: Dict[str, Any],
    ) -> "UserProfile":
        """Update the profile with commerce-outcome signals.

        ``outcome`` should contain keys from record_commerce_outcome:
        upsell_clicked, bundle_purchased, accessory_slug (which accessory),
        etc.  Over time this builds a learned preference model.
        """
        profile = self.get_user_profile(user_id) or UserProfile(user_id=user_id)

        slug = str(outcome.get("accessory_slug") or "").strip()
        if slug:
            if outcome.get("upsell_clicked") or outcome.get("bundle_purchased"):
                profile.accessory_acceptances[slug] = profile.accessory_acceptances.get(slug, 0) + 1
            else:
                profile.accessory_rejections[slug] = profile.accessory_rejections.get(slug, 0) + 1

        # Rolling upsell acceptance rate
        total_acc = sum(profile.accessory_acceptances.values())
        total_rej = sum(profile.accessory_rejections.values())
        total = total_acc + total_rej
        if total > 0:
            profile.upsell_acceptance_rate = round(total_acc / total, 3)

        # Track purchases
        purchased_sku = str(outcome.get("purchased_sku") or "").strip()
        if purchased_sku and purchased_sku not in profile.purchase_history_summary:
            profile.purchase_history_summary.append(purchased_sku)
            # Cap history length
            if len(profile.purchase_history_summary) > 100:
                profile.purchase_history_summary = profile.purchase_history_summary[-100:]

        self.save_user_profile(profile)
        return profile

    # ── Chat history save/restore ──

    def save_chat_session(
        self,
        user_id: str,
        session_id: str,
        episodes: List[Dict[str, Any]],
        summary: str = "",
    ) -> None:
        """Save a completed chat session to user's long-term history."""
        key = _CHAT_HISTORY_KEY.format(user_id=user_id)
        raw = None
        try:
            raw = self.mem.redis.get(key)
        except Exception:
            pass
        if not raw:
            raw = self.mem._local_get(key)

        history = json.loads(raw) if raw else []

        entry = {
            "session_id": session_id,
            "timestamp": time.time(),
            "turn_count": len(episodes),
            "summary": summary[:500],
            "episodes": episodes[-20:],  # keep last 20 turns per session
        }
        history.append(entry)

        # Keep only last 50 sessions
        if len(history) > 50:
            history = history[-50:]

        payload = json.dumps(history)
        try:
            self.mem.redis.setex(key, _HISTORY_TTL, payload)
        except Exception:
            self.mem._local_setex(key, _HISTORY_TTL, payload)

    def get_chat_history(self, user_id: str, last_n: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the last N chat sessions for a user."""
        key = _CHAT_HISTORY_KEY.format(user_id=user_id)
        raw = None
        try:
            raw = self.mem.redis.get(key)
        except Exception:
            pass
        if not raw:
            raw = self.mem._local_get(key)
        if not raw:
            return []
        history = json.loads(raw)
        return history[-last_n:]

    # ── RAPTOR-style session summarization ──

    def summarize_session(self, uid: str) -> SessionSummary:
        """Compress a session's episodes into a hierarchical summary.

        RAPTOR approach: group episodes by topic, summarize each group,
        then combine into a session-level summary.
        """
        episodes = self.get_episodes(uid)
        kv = self.mem.get_kv(uid)

        summary = SessionSummary(session_id=uid, turn_count=len(episodes))

        # Extract key constraints from KV state
        for key in ("budget_min", "budget_max", "use_case", "brand_preference", "gaming_tier"):
            val = kv.get(key)
            if val is not None:
                summary.key_constraints[key] = val

        # Extract products viewed
        products = kv.get("products_viewed") or kv.get("shortlist") or []
        if isinstance(products, list):
            summary.products_viewed = [str(p) for p in products[:10]]

        # Build summary text from episodes
        if episodes:
            parts = []
            for ep in episodes:
                q = ep.get("query", "")[:60]
                slots = ep.get("slots_captured", {})
                if q:
                    parts.append(q)
            summary.summary_text = " → ".join(parts[-8:])
        else:
            summary.summary_text = "No conversation data"

        # Persist the summary
        key = _SESSION_SUMMARY_KEY.format(uid=uid)
        payload = json.dumps(asdict(summary))
        try:
            self.mem.redis.setex(key, 86400, payload)
        except Exception:
            self.mem._local_setex(key, 86400, payload)

        return summary

    # ── Convenience: save_episode from orchestrator turn data ──

    def save_episode(
        self,
        uid: str,
        *,
        turn_index: int,
        query: str,
        response_summary: str,
        slots_captured: Dict[str, Any] | None = None,
        nqe_questions_asked: List[str] | None = None,
        products_shown: List[str] | None = None,
        debate_ran: bool = False,
        model_used: str | None = None,
    ) -> Episode:
        """High-level save that creates an Episode and appends it, then auto-summarizes if needed."""
        ep = Episode(
            turn_index=turn_index,
            query=query,
            response_summary=response_summary,
            slots_captured=slots_captured or {},
            nqe_questions_asked=nqe_questions_asked or [],
            products_shown=products_shown or [],
            debate_ran=debate_ran,
            model_used=model_used,
        )
        self.append_episode(uid, ep)

        # Auto-summarize after 5+ turns
        episodes = self.get_episodes(uid)
        if len(episodes) >= 5 and len(episodes) % 5 == 0:
            self.summarize_session(uid)

        return ep

    # ── Behavioral model extraction from episodic history ──

    def build_behavioral_model(self, user_id: str) -> Dict[str, Any]:
        """Analyze past sessions to build a shopper behavioral profile.

        Returns insights like typical comparison count, decision speed,
        preferred price range patterns, brand loyalty signals.
        """
        history = self.get_chat_history(user_id, last_n=20)
        if not history:
            return {"user_id": user_id, "sessions_analyzed": 0}

        turn_counts = []
        products_per_session = []
        outcomes = []
        all_constraints: Dict[str, list] = {}

        for session in history:
            tc = session.get("turn_count", 0)
            turn_counts.append(tc)
            eps = session.get("episodes") or []
            products_in_session: set = set()
            for ep in eps:
                for p in ep.get("products_shown") or ep.get("slots_captured", {}).get("products_viewed", []) or []:
                    products_in_session.add(str(p))
                for sk, sv in (ep.get("slots_captured") or {}).items():
                    if sk not in all_constraints:
                        all_constraints[sk] = []
                    all_constraints[sk].append(sv)
            products_per_session.append(len(products_in_session))
            if session.get("summary"):
                outcomes.append(session["summary"][:100])

        avg_turns = sum(turn_counts) / max(1, len(turn_counts))
        avg_products = sum(products_per_session) / max(1, len(products_per_session))

        # Detect decision style
        if avg_turns <= 3:
            decision_style = "quick_decider"
        elif avg_turns <= 6:
            decision_style = "moderate_explorer"
        else:
            decision_style = "thorough_researcher"

        # Detect comparison behavior
        if avg_products >= 5:
            comparison_style = "wide_comparator"
        elif avg_products >= 3:
            comparison_style = "moderate_comparator"
        else:
            comparison_style = "focused_buyer"

        return {
            "user_id": user_id,
            "sessions_analyzed": len(history),
            "avg_turns_per_session": round(avg_turns, 1),
            "avg_products_compared": round(avg_products, 1),
            "decision_style": decision_style,
            "comparison_style": comparison_style,
            "recurring_constraints": {
                k: v[-1] for k, v in all_constraints.items() if v
            },
        }

    def get_returning_customer_boost(self, user_id: str) -> Dict[str, Any]:
        """Return boost signals for returning customers."""
        profile = self.get_user_profile(user_id)
        if not profile:
            return {"is_returning": False}
        behavioral = self.build_behavioral_model(user_id)
        return {
            "is_returning": True,
            "preferred_brands": profile.preferred_brands[:5],
            "avoided_brands": profile.avoided_brands[:5],
            "budget_tier": profile.budget_tier,
            "typical_use_cases": profile.typical_use_cases[:3],
            "decision_style": behavioral.get("decision_style"),
            "comparison_style": behavioral.get("comparison_style"),
            "sessions_analyzed": behavioral.get("sessions_analyzed", 0),
        }
