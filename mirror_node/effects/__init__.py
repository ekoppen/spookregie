from .xray import xray
from .thermal import thermal
from .contour import contour
from .posterize import posterize

EFFECTS = {
    "xray": xray,
    "thermal": thermal,
    "contour": contour,
    "posterize": posterize,
}


def get_effect(name):
    try:
        return EFFECTS[name]
    except KeyError:
        raise ValueError(f"Onbekend effect: {name}") from None
