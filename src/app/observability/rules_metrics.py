from prometheus_client import Counter, Histogram

# Counts per tenant (label tenant_id)
rule_match_counter = Counter('rule_match_count', 'Number of rule matches', ['tenant_id'])
rule_miss_counter = Counter('rule_miss_count', 'Number of times rules did not match', ['tenant_id'])
# Tier hits
tier_hit_counter = Counter('tier_hit_count', 'Tier routing hits', ['tier'])
# Latency histogram for rule evaluation
rule_latency_hist = Histogram('rule_evaluation_latency_seconds', 'Latency of rule evaluation in seconds')
