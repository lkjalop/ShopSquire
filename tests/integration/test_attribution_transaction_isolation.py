"""Attribution requests need independent database transactions."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.integration.test_attribution_capture import stack


def test_independent_sessions_cannot_read_uncommitted_attribution_catalogue_changes(stack):
    engine = stack.app.state.engine
    with Session(engine) as writer, Session(engine) as reader:
        writer.execute(text("UPDATE products SET price_cents=199999 WHERE sku='ATTR-1'"))
        try:
            price = reader.scalar(text("SELECT price_cents FROM products WHERE sku='ATTR-1'"))
            assert price == 119900, 'a separate transaction must not read or commit another session changes'
        finally:
            reader.rollback()
            writer.rollback()
