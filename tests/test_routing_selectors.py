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


def test_row_three_rmux87_alu_target_translation_is_not_exported():
    # VP-AGM-001: RMUX87 -> RMUX59 (dy 1) is a row-3 boundary observation. At
    # X14Y12 pair 2/9 has exact evidence for a DIFFERENT driver, X14Y8_RMUX39,
    # so translating the row-3 relative key into the interior silently selects
    # the wrong source -- the original ALU target branch fails DC capture while
    # siblings work. The key was restored to NONPORTABLE_RELATIVE_KEYS on
    # 2026-09-11 (04e789a6, ratified in session) after 96c73ca never merged;
    # this pins its withdrawal so the just-ratified P0 fix has explicit coverage
    # alongside the other three keys.
    clean = {(x, 3, "RMUX", 59, "RMUX", x, 2, 87): (2, 9)
             for x in (2, 3, 4, 10, 14, 20)}
    clean[(14, 12, "RMUX", 59, "RMUX", 14, 8, 39)] = (2, 9)
    original = dict(clean)
    relative, rejected = relative_edges(clean)
    key = ("RMUX", 59, "RMUX", 87, 0, 1)
    assert key not in relative
    assert key in rejected
    assert relative[("RMUX", 59, "RMUX", 39, 0, 4)] == (2, 9)
    assert clean == original
    # The withdrawn interior instance is refused; the exact row-3 observation
    # and the legitimate different-driver edge both remain authoritative.
    assert nonportable_translation(clean, "X14Y11_RMUX87", "X14Y12_RMUX59")
    assert not nonportable_translation(clean, "X14Y2_RMUX87", "X14Y3_RMUX59")
    assert not nonportable_translation(clean, "X14Y8_RMUX39", "X14Y12_RMUX59")


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


def test_column_sixteen_rmux03_turnback_does_not_translate_east():
    clean = {(16, y, "RMUX", 14, "RMUX", 15, y, 3): (5, 8)
             for y in (5, 6, 7, 8, 9, 10, 11, 12)}
    # At column 20 the same word selects a different, four-tile-away source.
    clean[(20, 12, "RMUX", 14, "RMUX", 16, 12, 51)] = (5, 8)
    clean[(20, 12, "RMUX", 14, "RMUX", 18, 12, 51)] = (3, 8)
    original = dict(clean)
    relative, rejected = relative_edges(clean)
    key = ("RMUX", 14, "RMUX", 3, 1, 0)
    assert key in rejected
    assert key not in relative
    assert clean == original
    assert nonportable_translation(clean, "X19Y12_RMUX03", "X20Y12_RMUX14")
    assert not nonportable_translation(clean, "X15Y12_RMUX03", "X16Y12_RMUX14")
    assert not nonportable_translation(clean, "X18Y12_RMUX51", "X20Y12_RMUX14")
