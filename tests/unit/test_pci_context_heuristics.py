from src.app.security.pci import contains_pci_data


def test_contains_pci_data_flags_card_with_context_even_if_luhn_fails():
    # Fake PAN that fails Luhn, but includes clear card context + expiry.
    assert contains_pci_data("do i just use card 5432 1234 8907 4567 09/28") is True


def test_contains_pci_data_does_not_flag_long_digits_without_context_if_luhn_fails():
    # Long digits alone should not trigger PCI unless Luhn passes or context hints exist.
    assert contains_pci_data("ref 5432 1234 8907 4567 please process") is False

