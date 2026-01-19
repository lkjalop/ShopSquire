from src.app.security.firewall import TransactionFirewall


def test_firewall_caps_and_thresholds():
    fw = TransactionFirewall({})
    # Over cap discount
    d = fw.check_pricing(20000, 50)
    assert not d.allowed and d.approval_required
    # Auto-approve threshold
    d2 = fw.check_pricing(10000, 10)
    assert d2.allowed and not d2.approval_required
    d3 = fw.check_pricing(30000, 5)
    assert d3.allowed and d3.approval_required
    d4 = fw.check_pricing(20000, 31)
    assert not d4.allowed and d4.approval_required
