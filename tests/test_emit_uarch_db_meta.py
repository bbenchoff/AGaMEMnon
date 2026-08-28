from agamemnon.engine.emit_uarch_db import _dev_meta_value


def test_dev_meta_value_preserves_flat_csv_and_token_boundaries():
    encoded = _dev_meta_value('14,12,0;profile="trace"\r\n')
    assert encoded == "14%2C12%2C0%3Bprofile=%22trace%22%0D%0A"
    assert not any(character in encoded for character in ',;"\r\n')
    assert _dev_meta_value("1") == "1"
