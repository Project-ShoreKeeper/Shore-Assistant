from app.services.cua.formats import evocua, gui_owl, ui_tars
from app.services.cua.formats.base import CuaFormat, ParsedStep

_REGISTRY: dict[str, CuaFormat] = {
    evocua.FORMAT.name: evocua.FORMAT,
    gui_owl.FORMAT.name: gui_owl.FORMAT,
    ui_tars.FORMAT.name: ui_tars.FORMAT,
}


def get_format(name: str) -> CuaFormat:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown CUA_MODEL_FORMAT {name!r}; "
            f"expected one of {sorted(_REGISTRY)}."
        ) from None


__all__ = ["CuaFormat", "ParsedStep", "get_format"]
