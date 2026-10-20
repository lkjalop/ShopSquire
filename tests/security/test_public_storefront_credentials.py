"""Public catalog pages must not publish operator credentials or test UI state."""
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.app.routers import ui_storefront


@pytest.fixture
def public_pages(monkeypatch):
    product = dict(sku='owned-test-product', name='Synthetic product', price=100,
                   currency='AUD', image_url='', features=[], specs={}, stock=5)
    monkeypatch.setattr(ui_storefront, '_get_products', lambda: [product])
    monkeypatch.setattr(ui_storefront, '_find_product_by_sku', lambda sku: product)
    monkeypatch.setenv('MERCHANT_API_KEY', 'private-merchant-credential-sentinel')
    app = FastAPI()
    app.include_router(ui_storefront.router)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize('path', ['/ui/storefront', '/ui/product/owned-test-product'])
def test_public_html_does_not_expose_an_operator_credential(public_pages, path):
    response = public_pages.get(path)
    assert response.status_code == 200
    assert 'private-merchant-credential-sentinel' not in response.text


def test_fast_health_setting_does_not_open_a_product_dialog(public_pages, monkeypatch):
    monkeypatch.setenv('TEST_FAST_HEALTH', '1')
    response = public_pages.get('/ui/product/owned-test-product')
    assert response.status_code == 200
    dialog = re.search(r'<div id="decision-modal"[^>]*>', response.text)
    assert dialog is not None
    assert 'display:none' in dialog.group()
