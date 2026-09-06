from agamemnon.engine.routing_selectors import relative_edges, nonportable_translation


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


def test_alu_row_three_turnback_is_not_exported_to_interior():
    from pathlib import Path
    from agamemnon.engine.routing_selectors import load_clean_edges
    clean = load_clean_edges(str(Path(__file__).resolve().parents[1] / "agamemnon/chipdb"))
    observations = {k: v for k, v in clean.items()
                    if (k[2], k[3], k[4], k[7], k[0]-k[5], k[1]-k[6]) ==
                    ("RMUX", 59, "RMUX", 87, 0, 1)}
    assert observations and {k[1] for k in observations} == {3}
    assert (14, 12, "RMUX", 59, "RMUX", 14, 11, 87) not in clean
    assert tuple(clean[14, 12, "RMUX", 59, "RMUX", 14, 8, 39]) == (2, 9)
    relative, rejected = relative_edges(clean)
    assert ("RMUX", 59, "RMUX", 87, 0, 1) in rejected
    assert ("RMUX", 59, "RMUX", 87, 0, 1) not in relative
    assert nonportable_translation(clean, "X14Y11_RMUX87", "X14Y12_RMUX59")
    for k in observations:
        assert not nonportable_translation(clean, f"X{k[5]}Y{k[6]}_RMUX87", f"X{k[0]}Y{k[1]}_RMUX59")
