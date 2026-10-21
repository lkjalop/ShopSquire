"""Keep startup, background work and shutdown under one application owner."""
from contextlib import asynccontextmanager
import logging
import sys

from src.app.models.database_ownership import database_owner


@asynccontextmanager
async def application_lifespan(app, lifespan, shutdown):
    with database_owner(getattr(app.state, 'engine', None)):
        try:
            async with lifespan(app):
                yield
        finally:
            # A custom ASGI lifespan does not invoke legacy shutdown handlers.
            # Preserve a required-startup/request error if cleanup also fails.
            primary_error = sys.exc_info()[1]
            try:
                await shutdown()
            except BaseException:
                if primary_error is None:
                    raise
                logging.getLogger(__name__).exception('Resource cleanup failed; preserving the application error')
