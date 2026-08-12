"""Continuous silicon audit of the amendment-promoted default routing surface.

The D0 default-promotion amendment enlarges the default "can build" set to the
witnessed, differentially-validated routing rows.  That promotion is paired with
this continuous audit: default rows are sampled on real silicon (SRAM-only,
register-bank / GPIO readback where the row is observable) and any silicon
disagreement DEMOTES the row from the default surface immediately, as a
first-class retained-negative finding.  Default promotion is therefore revocable
the instant the board disagrees.

Hardware is driven out-of-process (the user runs OpenOCD / the board), so this
module is a pure, fully-testable mechanism: the caller injects a ``sampler``
callable that returns a :class:`SiliconSample` for one admitted default row.
:func:`silicon_sram_sampler` is the not-yet-wired production entry point (TODO).
"""

from __future__ import annotations

from dataclasses import dataclass


RETAINED_NEGATIVE_SCHEMA = "agamemnon.hil-default-demotion.v1"


@dataclass(frozen=True)
class SiliconSample:
    """One SRAM-only silicon readback for a default-promoted routing row.

    ``observable`` is False when the row cannot be read back this pass (no
    register-bank / GPIO observation point available); an unobservable row is
    neither confirmed nor demoted.  ``agrees`` is only meaningful when the row is
    observable and records whether silicon matched the emitted routing selection.
    """

    row_identity: str
    edge_id: str
    observable: bool
    agrees: bool
    detail: str = ""


@dataclass(frozen=True)
class AuditOutcome:
    retained: tuple[dict, ...]
    demoted: tuple[dict, ...]
    retained_negatives: tuple[dict, ...]
    confirmed: tuple[str, ...]
    unobserved: tuple[str, ...]


def build_retained_negative(row, sample):
    """Record a silicon disagreement as a first-class retained negative."""
    return {
        "schema": RETAINED_NEGATIVE_SCHEMA,
        "kind": "silicon-disagreement-demotion",
        "finding": "first-class",
        "row_identity": row["row_identity"],
        "edge_id": row["edge_id"],
        "reason": "silicon-disagreement",
        "detail": sample.detail,
    }


def audit_default_rows(rows, sampler):
    """Sample each default row on silicon and demote-on-disagreement.

    ``sampler(row)`` returns a :class:`SiliconSample`.  A silicon disagreement on
    any default row demotes it from the default set immediately and appends a
    retained-negative finding; agreements confirm the row; rows that cannot be
    observed this pass are retained unchanged (absence of observation is not
    disagreement).
    """
    retained: list[dict] = []
    demoted: list[dict] = []
    negatives: list[dict] = []
    confirmed: list[str] = []
    unobserved: list[str] = []
    for row in rows:
        sample = sampler(row)
        if not isinstance(sample, SiliconSample):
            raise TypeError("sampler must return a SiliconSample")
        if sample.row_identity != row["row_identity"]:
            raise ValueError("sampler returned a sample for the wrong row")
        if not sample.observable:
            unobserved.append(row["row_identity"])
            retained.append(row)
            continue
        if sample.agrees:
            confirmed.append(row["row_identity"])
            retained.append(row)
        else:
            demoted.append(row)
            negatives.append(build_retained_negative(row, sample))
    return AuditOutcome(
        tuple(retained), tuple(demoted), tuple(negatives),
        tuple(confirmed), tuple(unobserved),
    )


def demote_on_disagreement(rows, disagreeing_identities):
    """Return the default set with any disagreeing row removed (demoted)."""
    blocked = set(disagreeing_identities)
    return tuple(row for row in rows if row["row_identity"] not in blocked)


def silicon_sram_sampler(row):  # pragma: no cover - hardware entry point
    """Production SRAM-only HIL sampler for one default-promoted routing row.

    TODO: wire this to the SRAM-only hardware-in-the-loop loop (load the row's
    minimal witness image over the DAP, read the row back through the register
    bank / GPIO observation point, and return a :class:`SiliconSample`).  The
    demote-on-disagreement mechanism above consumes its results; until the loop
    is wired this stays a loud, unmistakable stub rather than a silent pass.
    """
    raise NotImplementedError(
        "SRAM-only HIL sampler for default-promoted routing rows is not wired yet; "
        "inject a sampler into audit_default_rows() to drive the demote-on-"
        "disagreement mechanism"
    )
