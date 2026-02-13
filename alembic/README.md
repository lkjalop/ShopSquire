# Alembic Migrations

This directory contains Alembic migration scaffolding for ShopSquire.

- Configure DATABASE_URL in your environment, or rely on app settings.
- Generate a revision: alembic revision -m "init".
- Autogenerate from models: alembic revision --autogenerate -m "update".
- Apply migrations: alembic upgrade head.

Target metadata is loaded from src.app.models.orm.Base.metadata when available.
