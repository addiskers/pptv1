"""Icon set coverage: every drawer renders, cache hits, tiles."""
import time

import pytest
from PIL import Image

from deckengine.core import icons
from deckengine.core.icons import ICON_NAMES, get_icon, get_icon_tile

ORIGINAL_12 = ("person", "people", "money", "growth", "chart", "leaf",
               "building", "target", "globe", "bulb", "shield", "clock")
NEW_18 = ("gear", "handshake", "truck", "factory", "document", "calendar",
          "warning", "check", "refresh", "scale", "award", "flag", "pin",
          "cart", "drop", "rocket", "network", "lock")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "CACHE_DIR", tmp_path)
    return tmp_path


def test_icon_names_has_30_entries_in_order():
    assert len(ICON_NAMES) == 30
    assert ICON_NAMES[:12] == ORIGINAL_12
    assert ICON_NAMES[12:] == NEW_18


def test_every_icon_renders_png_of_right_size(cache):
    for name in ICON_NAMES:
        p = get_icon(name, "1f3864", px=64)
        assert p.is_file()
        assert p.suffix == ".png"
        with Image.open(p) as im:
            assert im.size == (64, 64), name
            assert im.mode == "RGBA"


def test_every_icon_draws_visible_pixels(cache):
    for name in ICON_NAMES:
        p = get_icon(name, "000000", px=48)
        with Image.open(p) as im:
            assert im.getchannel("A").getextrema()[1] > 0, name


def test_second_call_is_cache_hit(cache):
    p1 = get_icon("gear", "aa0000", px=32)
    m1 = p1.stat().st_mtime_ns
    time.sleep(0.02)
    p2 = get_icon("gear", "aa0000", px=32)
    assert p2 == p1
    assert p2.stat().st_mtime_ns == m1


def test_tile_renders_and_respects_px(cache):
    p = get_icon_tile("lock", "ffffff", "1f3864", px=96)
    assert p.is_file()
    assert p.suffix == ".png"
    with Image.open(p) as im:
        assert im.size == (96, 96)
    p2 = get_icon_tile("lock", "ffffff", "1f3864", px=40)
    assert p2 != p
    with Image.open(p2) as im:
        assert im.size == (40, 40)


def test_tile_default_px_and_all_names(cache):
    for name in ICON_NAMES:
        p = get_icon_tile(name, "ffffff", "1f3864")
        with Image.open(p) as im:
            assert im.size == (128, 128), name


def test_tile_rounded_corners_and_opaque_body(cache):
    p = get_icon_tile("check", "ffffff", "000000", px=64)
    with Image.open(p) as im:
        assert im.getpixel((0, 0))[3] < 128     # corner clipped
        assert im.getpixel((4, 32))[3] > 200    # bg body opaque
        assert im.getpixel((32, 4))[3] > 200


def test_tile_radius_frac_gets_distinct_cache_entry(cache):
    p1 = get_icon_tile("gear", "ffffff", "1f3864", px=64)
    p2 = get_icon_tile("gear", "ffffff", "1f3864", px=64, radius_frac=0.5)
    assert p2 != p1
    with Image.open(p1) as a, Image.open(p2) as b:
        assert a.tobytes() != b.tobytes()


def test_tile_glyph_is_composited(cache):
    plain = get_icon_tile("check", "000000", "000000", px=64)
    inked = get_icon_tile("check", "ffffff", "000000", px=64)
    with Image.open(plain) as a, Image.open(inked) as b:
        assert a.tobytes() != b.tobytes()


def test_tile_second_call_is_cache_hit(cache):
    p1 = get_icon_tile("pin", "ffffff", "c00000", px=64)
    m1 = p1.stat().st_mtime_ns
    time.sleep(0.02)
    p2 = get_icon_tile("pin", "ffffff", "c00000", px=64)
    assert p2 == p1
    assert p2.stat().st_mtime_ns == m1


def test_unknown_name_raises_keyerror(cache):
    with pytest.raises(KeyError):
        get_icon("sparkles", "000000")
    with pytest.raises(KeyError):
        get_icon_tile("sparkles", "000000", "ffffff")
