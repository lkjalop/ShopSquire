from __future__ import annotations

from typing import Any, Dict, List


def _confidence_band(value: float) -> str:
    if value >= 0.82:
        return "high"
    if value >= 0.58:
        return "medium"
    return "low"


def _clean_lines(values: List[Any], *, limit: int = 4) -> List[str]:
    out: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        out.append(text)
    return out[:limit]


def _build_lead(
    *,
    lead_id: str,
    finding_type: str,
    title: str,
    what_we_observed: List[str],
    why_it_matters: str,
    what_to_hunt_next: List[str],
    where_to_check: List[str],
    confirmation_signals: List[str],
    disproving_signals: List[str],
    push_downstream: List[str],
    likely_kill_chain_stage: str,
    confidence_score: float,
    llm_guidance: str | None = None,
    business_guidance: str | None = None,
    evidence_refs: List[str] | None = None,
) -> Dict[str, Any]:
    confidence = round(float(confidence_score), 4)
    row: Dict[str, Any] = {
        "lead_id": lead_id,
        "finding_type": finding_type,
        "title": title,
        "what_we_observed": _clean_lines(what_we_observed),
        "why_it_matters": why_it_matters,
        "what_to_hunt_next": _clean_lines(what_to_hunt_next),
        "where_to_check": _clean_lines(where_to_check),
        "confirmation_signals": _clean_lines(confirmation_signals),
        "disproving_signals": _clean_lines(disproving_signals),
        "push_downstream": _clean_lines(push_downstream),
        "likely_kill_chain_stage": likely_kill_chain_stage,
        "confidence_score": confidence,
        "confidence_band": _confidence_band(confidence),
        "business_guidance": business_guidance or why_it_matters,
        "analyst_guidance": llm_guidance or "",
        "evidence_refs": _clean_lines(evidence_refs or [], limit=6),
    }
    return row


def build_threat_hunter_leads(
    *,
    findings: List[Dict[str, Any]] | None,
    evidence_snapshot: Dict[str, Any] | None,
    llm_assist: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    finding_rows = [f for f in (findings or []) if isinstance(f, dict)]
    ev = evidence_snapshot if isinstance(evidence_snapshot, dict) else {}
    llm = llm_assist if isinstance(llm_assist, dict) else {}
    llm_summary = str(llm.get("summary") or llm.get("business_summary") or "").strip()
    by_type: Dict[str, Dict[str, Any]] = {}
    for finding in finding_rows:
        ftype = str(finding.get("finding_type") or "").strip()
        if not ftype:
            continue
        incumbent = by_type.get(ftype)
        if incumbent is None or float(finding.get("confidence_score") or 0.0) > float(incumbent.get("confidence_score") or 0.0):
            by_type[ftype] = finding

    infra = ev.get("sender_infrastructure") if isinstance(ev.get("sender_infrastructure"), dict) else {}
    geo = infra.get("originating_geo") if isinstance(infra.get("originating_geo"), dict) else {}
    rel = infra.get("related_incidents") if isinstance(infra.get("related_incidents"), dict) else {}
    rep = infra.get("reputation") if isinstance(infra.get("reputation"), dict) else {}

    leads: List[Dict[str, Any]] = []

    def evidence_for(finding: Dict[str, Any]) -> List[str]:
        items = [str(x) for x in (finding.get("evidence") or []) if str(x or "").strip()]
        art = str(((finding.get("artifact_ref") or {}).get("file_name") or "")).strip()
        if art:
            items.insert(0, f"Artifact: {art}")
        return items[:4]

    for ftype in (
        "c2_beacon_pattern",
        "lolbin_command_sequence",
        "data_exfiltration_instruction",
        "prompt_injection_hidden",
        "ssn_leakage_linked_qr",
    ):
        finding = by_type.get(ftype)
        if not finding:
            continue
        score = float(finding.get("confidence_score") or 0.0)
        evidence_lines = evidence_for(finding)
        if ftype == "c2_beacon_pattern":
            leads.append(
                _build_lead(
                    lead_id=f"lead_{ftype}",
                    finding_type=ftype,
                    title="Threat Hunter Lead: possible command-and-control follow-on",
                    what_we_observed=evidence_lines + [f"Reputation flags: {', '.join(rep.get('flags') or [])}" if rep.get("flags") else ""],
                    why_it_matters="If the hidden callback pattern was executed, an endpoint may now be checking in to attacker infrastructure.",
                    what_to_hunt_next=[
                        "Check for repeated low-volume callbacks, jitter, or periodic requests after the artifact was handled.",
                        "Look for DNS, proxy, CDN, SWG, or XDR telemetry tied to the same host, user, or destination.",
                    ],
                    where_to_check=["XDR network telemetry", "DNS / proxy / firewall logs", "CDN or secure-web-gateway logs", "eBPF socket/connect telemetry"],
                    confirmation_signals=[
                        "Repeated outbound connections to the same destination after user interaction.",
                        "Matching JA3, SNI, DNS, or browser network telemetry on the same host.",
                    ],
                    disproving_signals=[
                        "No follow-on network activity from the affected host or user.",
                        "The destination resolves to a known-benign business endpoint already approved in policy.",
                    ],
                    push_downstream=["SIEM / XDR now", "Network / proxy telemetry correlation", "NDR hunt if beacon overlap is seen"],
                    likely_kill_chain_stage=str(((finding.get("threat_context") or {}).get("pasta_stage") or "Command and Control")),
                    confidence_score=max(score, 0.71),
                    llm_guidance=f"{llm_summary} Hunt for the same callback pattern only on hosts that interacted with the artifact." if llm_summary else "",
                    business_guidance="Use this as a focused hunting lead, not proof of compromise.",
                    evidence_refs=[str(finding.get("finding_id") or "")],
                )
            )
        elif ftype == "lolbin_command_sequence":
            leads.append(
                _build_lead(
                    lead_id=f"lead_{ftype}",
                    finding_type=ftype,
                    title="Threat Hunter Lead: possible fileless or LOLBin execution",
                    what_we_observed=evidence_lines,
                    why_it_matters="Trusted operating-system tools may have been used to stage or execute payloads without dropping obvious malware first.",
                    what_to_hunt_next=[
                        "Review parent-child process chains from Office, Outlook, browser, or image-handling workflows into LOLBins.",
                        "Check for encoded PowerShell, certutil, mshta, rundll32, regsvr32, bitsadmin, wscript, or cscript activity.",
                    ],
                    where_to_check=["XDR / EDR process trees", "PowerShell / AMSI / ETW logs", "eBPF exec and file telemetry", "Proxy and DNS logs"],
                    confirmation_signals=[
                        "A document, mail client, or browser spawned a LOLBin or encoded script process.",
                        "The same host made payload-fetch requests or wrote new binaries immediately after execution.",
                    ],
                    disproving_signals=[
                        "No suspicious process tree or script activity exists on the affected host.",
                        "The file was never opened and no execution telemetry followed.",
                    ],
                    push_downstream=["XDR now", "SOAR / ticketing if execution overlap is confirmed"],
                    likely_kill_chain_stage=str(((finding.get("threat_context") or {}).get("pasta_stage") or "Execution")),
                    confidence_score=max(score, 0.73),
                    llm_guidance=f"{llm_summary} Focus on parent-child execution chains before broad containment." if llm_summary else "",
                    business_guidance="This lead is strongest when paired with endpoint process or network evidence.",
                    evidence_refs=[str(finding.get("finding_id") or "")],
                )
            )
        elif ftype == "data_exfiltration_instruction":
            leads.append(
                _build_lead(
                    lead_id=f"lead_{ftype}",
                    finding_type=ftype,
                    title="Threat Hunter Lead: possible data staging or exfiltration",
                    what_we_observed=evidence_lines,
                    why_it_matters="The artifact describes how data should be collected or moved out of the environment, so the next risk is theft rather than just deception.",
                    what_to_hunt_next=[
                        "Check for archive creation, staging directories, browser uploads, curl/wget/scp/rclone activity, or bulk cloud reads.",
                        "Look for unusual SaaS, storage, DLP, CASB, and identity activity tied to the same host or user.",
                    ],
                    where_to_check=["DLP / CASB / SaaS audit logs", "Cloud storage access logs", "Browser and proxy telemetry", "EDR / eBPF file and network telemetry"],
                    confirmation_signals=[
                        "Sensitive files were read and then uploaded, synced, or transferred shortly afterwards.",
                        "Cloud object listing, bulk-read, or download activity spiked for the same identity.",
                    ],
                    disproving_signals=[
                        "No unusual file movement, upload, or cloud-access activity occurred after interaction.",
                        "The user never opened the artifact or had no path to the targeted data sources.",
                    ],
                    push_downstream=["SIEM / XDR now", "DLP / CASB correlation", "Cloud audit review if sensitive stores were in scope"],
                    likely_kill_chain_stage=str(((finding.get("threat_context") or {}).get("pasta_stage") or "Actions on Objectives")),
                    confidence_score=max(score, 0.75),
                    llm_guidance=f"{llm_summary} Treat this as a targeted hunt for staging and transfer signals, not a confirmed breach." if llm_summary else "",
                    business_guidance="Use confirmation signals to decide whether this stays a lead or becomes a breach investigation.",
                    evidence_refs=[str(finding.get("finding_id") or "")],
                )
            )
        elif ftype == "prompt_injection_hidden":
            leads.append(
                _build_lead(
                    lead_id=f"lead_{ftype}",
                    finding_type=ftype,
                    title="Threat Hunter Lead: AI workflow manipulation attempt",
                    what_we_observed=evidence_lines,
                    why_it_matters="The artifact appears designed to steer model or agent behavior, so the main hunt surface is AI workflow safety rather than endpoint malware first.",
                    what_to_hunt_next=[
                        "Review model, agent, and connector audit logs for unsafe tool requests, prompt overrides, or context leakage.",
                        "Check whether the artifact entered any retrieval corpus, summarization path, or automated decision workflow before sanitization.",
                    ],
                    where_to_check=["Agent audit logs", "Connector action logs", "Prompt-injection review trail", "Model/tool invocation telemetry"],
                    confirmation_signals=[
                        "Unsafe tool requests, abnormal prompt content, or context leakage appeared after artifact ingestion.",
                        "The artifact bypassed sanitization and reached an agent or model-facing path.",
                    ],
                    disproving_signals=[
                        "The artifact was sanitized before ingestion and no unsafe tool requests occurred.",
                        "No model or agent workflow consumed the hidden content.",
                    ],
                    push_downstream=["Ticket / AI governance review", "SIEM if unsafe tool actions or leakage was observed"],
                    likely_kill_chain_stage=str(((finding.get("threat_context") or {}).get("pasta_stage") or "Initial Access")),
                    confidence_score=max(score, 0.68),
                    llm_guidance=f"{llm_summary} Keep the hunt limited to workflows that actually ingested the artifact." if llm_summary else "",
                    business_guidance="This is a lead for AI workflow review, not proof that a model was compromised.",
                    evidence_refs=[str(finding.get("finding_id") or "")],
                )
            )
        elif ftype == "ssn_leakage_linked_qr":
            leads.append(
                _build_lead(
                    lead_id=f"lead_{ftype}",
                    finding_type=ftype,
                    title="Threat Hunter Lead: QR-linked privacy or regulated-data exposure",
                    what_we_observed=evidence_lines + [f"Geo / ASN: {geo.get('country') or 'unknown'} {geo.get('asn_org') or ''}".strip()],
                    why_it_matters="The linked path may expose regulated identity data, so the next step is to confirm access path, scope, and audience rather than guess attacker origin.",
                    what_to_hunt_next=[
                        "Check public-link exposure, object permissions, RBAC or ABAC failures, and access logs for the linked artifact.",
                        "Review browser, SaaS, IAM, and object-store telemetry for unusual reads, downloads, or referrers.",
                    ],
                    where_to_check=["Privacy / DLP logs", "IAM and SaaS audit logs", "Object storage access logs", "Browser and proxy logs"],
                    confirmation_signals=[
                        "The linked artifact was publicly reachable or accessed by unexpected identities, countries, or hosting infrastructure.",
                        "Sensitive identity fields were visible in linked content and access logs show real viewers.",
                    ],
                    disproving_signals=[
                        "The linked document was never accessible outside approved controls.",
                        "No access logs, referrers, or object reads support actual exposure.",
                    ],
                    push_downstream=["Privacy / legal review", "SIEM if broad exposure or suspicious access was observed"],
                    likely_kill_chain_stage=str(((finding.get("threat_context") or {}).get("pasta_stage") or "Actions on Objectives")),
                    confidence_score=max(score, 0.77),
                    llm_guidance=f"{llm_summary} Treat this as a privacy-scoping lead first, then escalate to incident response if access is confirmed." if llm_summary else "",
                    business_guidance="This is strongest as a privacy and exposure-scoping lead, not a claim about attacker identity.",
                    evidence_refs=[str(finding.get("finding_id") or "")],
                )
            )

    if (int(rel.get("count") or 0) > 0 or (rep.get("flags") or []) or geo.get("asn_org")) and not any(
        str((row or {}).get("finding_type") or "") == "suspicious_sender_infrastructure" for row in leads
    ):
        lines = []
        if int(rel.get("count") or 0) > 0:
            lines.append(f"{int(rel.get('count') or 0)} related incidents matched the sender or supplier context.")
        if rep.get("flags"):
            lines.append(f"Infrastructure reputation flags: {', '.join(rep.get('flags') or [])}.")
        if geo.get("country") or geo.get("asn_org"):
            geo_line = f"Originating infrastructure resolved to {geo.get('country') or 'unknown country'}"
            if geo.get("asn_org"):
                geo_line += f" via {geo.get('asn_org')}"
            lines.append(geo_line + ".")
        leads.append(
            _build_lead(
                lead_id="lead_suspicious_sender_infrastructure",
                finding_type="suspicious_sender_infrastructure",
                title="Threat Hunter Lead: suspicious sender infrastructure overlap",
                what_we_observed=lines,
                why_it_matters="Prior incident overlap and infrastructure reputation increase the chance that this is part of a campaign rather than an isolated email.",
                what_to_hunt_next=[
                    "Search for the same sender domain, reply domain, URLs, bank details, or hosting footprint across mail, proxy, and endpoint telemetry.",
                    "Look for other users, queues, or suppliers touched by the same infrastructure during the same period.",
                ],
                where_to_check=["Mail gateway / secure email telemetry", "SIEM / XDR correlation", "Proxy / DNS logs", "Supplier incident history"],
                confirmation_signals=[
                    "The same domains, URLs, or bank details appear across multiple incidents or users.",
                    "Mail, proxy, or DNS logs show the same hosting or VPN footprint around related cases.",
                ],
                disproving_signals=[
                    "No related cases or telemetry overlap exists beyond this single message.",
                    "Infrastructure resolves to a known benign supplier path already approved in governance.",
                ],
                push_downstream=["SIEM / XDR now", "Email-security middleware if sender or reply indicators justify it"],
                likely_kill_chain_stage="Delivery",
                confidence_score=0.66 + (0.04 if int(rel.get("count") or 0) > 0 else 0.0),
                llm_guidance=f"{llm_summary} Focus the hunt on overlapping sender, reply, URL, and supplier signals." if llm_summary else "",
                business_guidance="Use this to decide whether to broaden the search to campaign scope.",
                evidence_refs=[str(m.get("incident_id") or "") for m in (rel.get("matches") or []) if isinstance(m, dict)],
            )
        )

    return leads[:6]
