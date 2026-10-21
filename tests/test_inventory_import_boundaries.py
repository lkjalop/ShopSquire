from pathlib import Path

import pytest

from scripts.seed_inventory_from_txt import parse_inventory


def test_desktop_categories_do_not_inherit_previous_storage_section():
    rows = parse_inventory('Hard drive\n::::::\nExample Mini PC\nMini-form-factor workstation\nPrice: 1000\n::::::\nExample Desktop tower\nPrice: 2000\n::::::\nApple iMac 24-inch\nPrice: 3000')
    assert [row['category'] for row in rows] == ['mini_pc', 'desktop_tower', 'all_in_one']


@pytest.mark.parametrize('claim', ['Thunderbolt: none listed', 'No Thunderbolt 4', 'Thunderbolt 4: UNKNOWN', 'Thunderbolt 4 not supported'])
def test_negative_or_unknown_port_claim_cannot_create_docking_support(claim):
    row = parse_inventory(f'Example Laptop\nPrice: 1000\nPorts: {claim}')[0]
    assert 'docking' not in row['specs']


def test_port_generation_is_not_invented():
    row = parse_inventory('Example Laptop\nPrice: 1000\nPorts: 2x Thunderbolt 5')[0]
    assert row['specs']['docking'] == 'Thunderbolt 5'


def test_explicit_price_conflict_is_held_with_raw_evidence():
    row = parse_inventory('Example Laptop\nPrice: CONFLICT — $2899 and $4799\nnotes: Price 2899 observed earlier')[0]
    assert row['price_cents'] is None
    assert row['specs']['catalog_import']['status'] == 'held_price_conflict'
    assert '$4799' in row['specs']['catalog_import']['observations'][0]['raw_text']


def test_duplicate_title_prices_are_not_resolved_by_input_order():
    blocks = ['Example Laptop\nPrice: 1000', 'Example Laptop\nPrice: 1200']
    for text in ['\n::::::\n'.join(blocks), '\n::::::\n'.join(reversed(blocks))]:
        rows = parse_inventory(text)
        assert len(rows) == 1
        assert rows[0]['price_cents'] is None
        assert rows[0]['specs']['catalog_import']['status'] == 'held_price_conflict'
        assert len(rows[0]['specs']['catalog_import']['observations']) == 2


def test_document_metadata_is_not_a_product():
    text = 'Example Laptop\nPrice: 1000\n::::::\nINGESTION NOTES FOR THE PIPELINE\nPrice: 25\n::::::\nPENDING — 15 URLs NOT YET EXTRACTED'
    assert len(parse_inventory(text)) == 1


def test_actual_august_document_keeps_conflicts_and_desktop_types():
    rows = parse_inventory(Path('docs/2026-08-08 laptop-products-aug.txt').read_text(encoding='utf-8'))
    assert len(rows) == 105  # 106 product entries; repeated Dell title reconciled.
    assert next(r for r in rows if r['name'].startswith('HP Z2 Mini'))['category'] == 'mini_pc'
    assert next(r for r in rows if r['name'].startswith('GMR Zephyr'))['category'] == 'desktop_tower'
    assert next(r for r in rows if r['name'].startswith('HyperX OMEN'))['price_cents'] is None
