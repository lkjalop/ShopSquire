"""Buyer-facing quantity/deadline alternatives; never mutates cart or sends RFQs."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class FulfillmentChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice_id: Literal[
        "enough_now", "split_delivery", "wait_preferred", "next_best_now",
        "supplier_enquiry", "alternative_architecture", "relax_constraint",
    ]
    label: str
    available_now: int = Field(ge=0)
    remaining: int = Field(ge=0)
    requires_buyer_confirmation: Literal[True] = True
    cart_mutation: Literal[False] = False
    supplier_send_authorized: Literal[False] = False


def reduce_fulfillment_choices(
    *, requested_quantity: int, available_now: int, known_lead_time_days: int | None,
    deadline_days: int | None, has_next_best: bool, has_architecture_alternative: bool,
) -> list[FulfillmentChoice]:
    requested = max(1, int(requested_quantity))
    now = max(0, min(int(available_now), requested))
    remaining = requested - now
    if remaining == 0:
        return [FulfillmentChoice(
            choice_id="enough_now", label=f"Take all {requested} now",
            available_now=now, remaining=0,
        )]
    choices = [FulfillmentChoice(
        choice_id="split_delivery", label=f"Take {now} now and source {remaining}",
        available_now=now, remaining=remaining,
    )]
    if known_lead_time_days is not None:
        label = f"Wait {known_lead_time_days} days for the preferred fit"
        if deadline_days is not None and known_lead_time_days > deadline_days:
            label += " (misses requested deadline)"
        choices.append(FulfillmentChoice(
            choice_id="wait_preferred", label=label, available_now=now, remaining=remaining,
        ))
    if has_next_best:
        choices.append(FulfillmentChoice(
            choice_id="next_best_now", label="Take the next-best verified option now",
            available_now=now, remaining=remaining,
        ))
    choices.append(FulfillmentChoice(
        choice_id="supplier_enquiry", label=f"Ask suppliers for {remaining} compatible units",
        available_now=now, remaining=remaining,
    ))
    if has_architecture_alternative:
        choices.append(FulfillmentChoice(
            choice_id="alternative_architecture", label="Compare another architecture class",
            available_now=now, remaining=remaining,
        ))
    choices.append(FulfillmentChoice(
        choice_id="relax_constraint", label="Change budget, deadline, quantity, or requirement",
        available_now=now, remaining=remaining,
    ))
    return choices


__all__ = ["FulfillmentChoice", "reduce_fulfillment_choices"]
