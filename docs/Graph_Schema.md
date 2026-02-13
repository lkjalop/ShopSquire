# Graph Schema (MVP)

Nodes
- Customer(id, email)
- Order(id, status, total_cents, created_at)
- Complaint(id, intent, severity)
- DecisionLog(id, agent_name, created_at)
- SecurityEvent(id, severity, created_at)
- Email(id, from_domain)
- Incident(id, severity, status)

Edges
- (Customer)-[:PLACED]->(Order)
- (Order)-[:HAS_DECISION]->(DecisionLog)
- (Complaint)-[:ABOUT]->(Order)
- (Complaint)-[:HAS_DECISION]->(DecisionLog)
- (SecurityEvent)-[:TRIGGERED]->(Incident)
- (SecurityEvent)-[:ASSOCIATED_WITH]->(Order)
- (Email)-[:LINKS_TO]->(Complaint)
- (DecisionLog)-[:LINKS_TO]->(SecurityEvent)

Query Examples
- Find complaints leading to incidents across orders: Complaint→Order→SecurityEvent→Incident.
- Shortest path from a customer to a security incident via any connected order/decision.
- Community detection on customers affected by a recall or fraud campaign.
