from fastapi import APIRouter, FastAPI

from src.app.bootstrap.router_registration import RequiredRouter, register_required_routers


def test_required_router_group_registers_every_route_in_order():
    first = APIRouter()
    second = APIRouter()

    @first.get("/registration-first")
    def registration_first():
        return {"ok": True}

    @second.get("/registration-second")
    def registration_second():
        return {"ok": True}

    app = FastAPI()
    names = register_required_routers(app, (
        RequiredRouter("first", first),
        RequiredRouter("second", second),
    ))

    assert names == ("first", "second")
    paths = [route.path for route in app.routes]
    assert paths.index("/registration-first") < paths.index("/registration-second")


def test_required_router_group_does_not_hide_registration_failures():
    class BrokenApp:
        def include_router(self, _router):
            raise RuntimeError("registration_failed")

    try:
        register_required_routers(BrokenApp(), (RequiredRouter("broken", APIRouter()),))  # type: ignore[arg-type]
    except RuntimeError as exc:
        assert str(exc) == "registration_failed"
    else:
        raise AssertionError("required registration failure was hidden")
