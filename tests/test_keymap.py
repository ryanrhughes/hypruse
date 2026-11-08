import pytest

from hypruse import keymap

# ask the module itself, so a build that points it at the library by path
# (Nix, where find_library sees nothing) runs these tests instead of skipping
pytestmark = pytest.mark.skipif(keymap._lib() is None, reason="libxkbcommon not installed")


def test_us_layout():
    m = keymap.Keymap("us")
    assert m.chord("a") == ("", "a")
    assert m.chord("A") == ("SHIFT", "a")
    assert m.chord("1") == ("", "1")
    assert m.chord("!") == ("SHIFT", "1")
    assert m.chord(" ") == ("", "space")


def test_french_azerty():
    m = keymap.Keymap("fr")
    assert m.chord("1") == ("SHIFT", "ampersand")  # digits are shifted on AZERTY
    assert m.chord("&") == ("", "ampersand")
    assert m.chord("@") == ("MOD5", "agrave")  # AltGr
    assert m.chord("é") == ("", "eacute")


def test_a_character_the_layout_cannot_type_is_none():
    assert keymap.Keymap("us").chord("上") is None


def test_control_characters_map_to_their_keys():
    m = keymap.Keymap("us")
    assert m.chord("\n") == ("", "Return")
    assert m.chord("\t") == ("", "Tab")


def test_a_keypad_name_is_not_turned_into_a_main_row_key():
    # KP_1 is not "1": on AZERTY that would be Shift and ampersand
    assert keymap.for_layout("fr").chord_for_key("KP_1") is None


def test_real_keys_sit_at_their_evdev_codes():
    # a generated keymap put every combo's first key on evdev 1 (KEY_ESC), so
    # Hyprland read SUPER plus any key as SUPER+Escape (Omarchy's System menu)
    real = keymap.RealKeys("us")
    assert real.text.startswith(b"xkb_keymap")
    assert real.code("Super_L") == 125
    assert real.code("Control_L") == 29
    assert real.code("k") == 37
    assert real.code("space") == 57
    assert real.code("Escape") == 1
    assert real.code("/") == 53  # a literal character goes through its keysym
    assert real.code("K") is None  # shifted: not where any key sits unshifted


def test_real_keys_follow_the_layout():
    assert keymap.RealKeys("fr").code("a") == keymap.RealKeys("us").code("q")
