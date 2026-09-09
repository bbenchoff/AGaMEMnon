from agamemnon.engine.routing_selectors import relative_edges, nonportable_translation


def test_row_one_rmux27_boundary_observations_do_not_translate_to_interior():
    clean = {
        (13, 4, "RMUX", 20, "RMUX", 13, 1, 27): (2, 9),
        (21, 4, "RMUX", 20, "RMUX", 21, 1, 27): (2, 9),
        (18, 5, "RMUX", 20, "RMUX", 18, 1, 75): (2, 9),
    }
    relative, rejected = relative_edges(clean)
    assert ("RMUX", 20, "RMUX", 27, 0, 3) in rejected
    assert ("RMUX", 20, "RMUX", 27, 0, 3) not in relative
    assert nonportable_translation(clean, "X18Y2_RMUX27", "X18Y5_RMUX20")
    assert not nonportable_translation(clean, "X13Y1_RMUX27", "X13Y4_RMUX20")
    assert not nonportable_translation(clean, "X21Y1_RMUX27", "X21Y4_RMUX20")
    assert not nonportable_translation(clean, "X18Y1_RMUX75", "X18Y5_RMUX20")
    assert relative[("RMUX", 20, "RMUX", 75, 0, 4)] == (2, 9)


def test_boundary_only_rmux_turnback_is_not_exported_to_interior():
    clean = {(20, y, "RMUX", 69, "RMUX", 20, y, 15): (0, 8)
             for y in range(1, 11)}
    # A genuinely observed interior alternative remains coordinate-specific.
    clean[(14, 7, "RMUX", 69, "RMUX", 15, 7, 63)] = (5, 7)
    original = dict(clean)
    relative, rejected = relative_edges(clean)
    key = ("RMUX", 69, "RMUX", 15, 0, 0)
    assert key not in relative
    assert key in rejected
    assert relative[("RMUX", 69, "RMUX", 63, -1, 0)] == (5, 7)
    assert clean == original  # no loss of exact boundary or interior evidence
    # Same destination repaired both regbank reset and add/sub overflow readback.
    assert nonportable_translation(clean, "X14Y7_RMUX15", "X14Y7_RMUX69")
    assert not nonportable_translation(clean, "X15Y7_RMUX63", "X14Y7_RMUX69")
    assert not nonportable_translation(clean, "X20Y7_RMUX15", "X20Y7_RMUX69")


def test_row_three_rmux_feedback_observation_is_not_exported():
    clean = {(x, 3, "RMUX", 46, "RMUX", x, 2, 7): (2, 9)
             for x in (2, 3, 4, 10, 14, 20)}
    clean[(14, 12, "RMUX", 46, "RMUX", 14, 8, 55)] = (2, 9)
    original = dict(clean)
    relative, rejected = relative_edges(clean)
    key = ("RMUX", 46, "RMUX", 7, 0, 1)
    assert key not in relative
    assert key in rejected
    assert relative[("RMUX", 46, "RMUX", 55, 0, 4)] == (2, 9)
    assert clean == original


def test_supplemental_paths_cannot_restore_withdrawn_translations():
    clean = {(14, 3, "RMUX", 46, "RMUX", 14, 2, 7): (2, 9)}
    assert nonportable_translation(clean, "X14Y11_RMUX07", "X14Y12_RMUX46")
    assert not nonportable_translation(clean, "X14Y2_RMUX7", "X14Y3_RMUX46")
    assert not nonportable_translation(clean, "X14Y12_RMUX46", "X14Y12_IMUX00")
    assert not nonportable_translation(clean, "special", "X14Y12_IMUX00")


def test_relative_selector_promotion_is_unanimous_and_fail_closed():
    common = ("RMUX", 3, "OMUX", 7)
    clean = {
        (10, 5, common[0], common[1], common[2], 9, 5, common[3]): (1, 7),
        (11, 6, common[0], common[1], common[2], 10, 6, common[3]): (1, 7),
        (12, 7, common[0], common[1], common[2], 11, 7, common[3]): (2, 8),
        (20, 4, "IMUX", 1, "RMUX", 20, 4, 9): (0, 6),
    }
    relative, conflicts = relative_edges(clean)
    assert ("RMUX", 3, "OMUX", 7, 1, 0) not in relative
    assert ("RMUX", 3, "OMUX", 7, 1, 0) in conflicts
    assert relative[("IMUX", 1, "RMUX", 9, 0, 0)] == (0, 6)
