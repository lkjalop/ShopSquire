from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import get_db
from src.app.routers.demo import router
from src.app.services.electronics_shop_scenario import seed_scenario


def test_demo_is_explicitly_enabled_and_reads_seeded_tables(monkeypatch):
    engine = create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    with Session(engine) as db:
        seed_scenario(db,tenant_id='synthetic-electronics',sku='existing-sku',retail_cents=100000)
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            monkeypatch.setenv('ENABLE_DEMO_ROUTES','0')
            assert client.get('/api/v1/demo/electronics-shop').status_code == 404
            monkeypatch.setenv('ENABLE_DEMO_ROUTES','1')
            response = client.get('/api/v1/demo/electronics-shop?quantity=40')
            assert response.status_code == 200
            assert response.json()['assessment']['shortfall'] == 25
            history=response.json()['history']
            assert history['sku']==response.json()['assessment']['sku']
            assert sum(row['available'] for row in history['locations'])==response.json()['assessment']['available']
            assert len(history['events'])==7
            assert client.get('/api/v1/demo/electronics-shop?quantity=0').status_code == 422
    engine.dispose()
