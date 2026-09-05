from agamemnon.engine.routing_selectors import relative_edges


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
