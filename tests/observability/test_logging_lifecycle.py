import logging

from src.app.observability import logging as app_logging


def test_repeated_application_logging_initialization_keeps_one_handler_and_one_log_line(tmp_path, monkeypatch):
    root, http = logging.Logger('isolated-root'), logging.Logger('shopsquire.http')
    http.parent = root
    monkeypatch.setenv('LOG_FILE', str(tmp_path / 'app.log'))
    monkeypatch.setattr(logging, 'basicConfig', lambda **kwargs: None)
    monkeypatch.setattr(logging, 'getLogger', lambda name=None: http if name == 'shopsquire.http' else root)
    try:
        for _ in range(20):
            app_logging.init_logging()
        assert len(root.handlers) == 1
        assert len(root.filters) == 2
        http.warning('ONE_DELIVERY_CANARY')
        root.handlers[0].flush()
        assert (tmp_path / 'app.log').read_text().count('ONE_DELIVERY_CANARY') == 1
    finally:
        for handler in {*root.handlers, *http.handlers}:
            handler.close()
