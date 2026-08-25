"""Fail-closed registry for exact images with retained silicon failures.

These records fence only the byte-exact canonical images named here.  They do
not imply that a different placement, route, or configuration for the same
logical design is safe.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class SiliconNegative:
    defect: str
    scope: str


# SHA-256 is over the canonical uncompressed image (header plus CRC-finalized
# payload), which is the same representation written by ``agamemnon to-bin``.
KNOWN_SILICON_NEGATIVE_IMAGES = {
    # VP-AGM-001: initial, entry-corridor diagnostic, and two route-restricted
    # images all failed the retained MCU ALU handshake contract.
    "89ab69b5e78b8a4ba5624a8acbc248fff9c49226575ebf4f2a2ec5519ee821fe":
        SiliconNegative("VP-AGM-001", "MCU ALU handshake"),
    "5f12964f70ae7ab2e7bdcd842bdcbc48b27cf6e801cb3b301de6b1930909f185":
        SiliconNegative("VP-AGM-001", "MCU ALU handshake entry diagnostic"),
    "1ecd07d0be49d4daf488c956408bafb89c9ba070e907b5e93ccde6a36636d545":
        SiliconNegative("VP-AGM-001", "MCU ALU handshake route diagnostic"),
    "93248ab06e9864eb7de7aff19a810863cfb4d7f7a41bf1e3bd99a099624963a8":
        SiliconNegative("VP-AGM-003", "clock-enable FSM"),
    "5d31d39de66ba611859ce244537a68d5c022d885e481e409a1279b65201f7ad5":
        SiliconNegative("VP-AGM-004", "rotate composition"),
    "99a5a6e08abfd2d14fde05f5b86dad60502c68fb69ec785a14cdc410b915d28f":
        SiliconNegative("VP-AGM-005", "one-bit add/subtract reset composition"),
    "cebec70f82da2e5f43da880bd70d464b9e81d227f69441326167a33e9c869ea6":
        SiliconNegative("VP-AGM-006", "initialized BRAM x1 Port-A read"),
    "d8712e1dfcc67f8099b5f4f188c140c3673ed8ea138ca6ec110635f0edf0160a":
        SiliconNegative("VP-AGM-006", "initialized BRAM x18 Port-A read"),
    "f627c9741f2bd8a2c8565c9bc678863a87fb0cd25287f4dd67e2af278c5e8fc1":
        SiliconNegative("VP-AGM-007", "PLL-fed five-site registered state"),
    "66e5a5da50bac8becf9e1e79b74fad92eb3d918c93a9b37257338a398716bb96":
        SiliconNegative("VP-AGM-008", "PIN_12 held-input composition"),
    "66b22a0b204eda79e5d68b74445e90d88936c0d9b34ef957e89fb742d7dc035c":
        SiliconNegative("VP-AGM-008", "PIN_10 held-input composition"),
    "ac659575e33e7e31160283a00d913e9b5883b933edeecebdf22c18686e1bd109":
        SiliconNegative("VP-AGM-008", "PIN_10 pad-state diagnostic"),
    "f895ff5eb01b5aa34a8d975d8174ea4118d7ca91bc5d73c9b5f5be03d915cee8":
        SiliconNegative("VP-AGM-008", "SPI0 MISO initial composition"),
    "b883504de4b28f3175c641d944d63899a262a8a880ba506c0071195193ef7ea6":
        SiliconNegative("VP-AGM-008", "SPI0 MISO isolated composition"),
    "e6e1cf153eb519368a91c45737a16c25aeb6bc75462710734d1663f9b3c09fca":
        SiliconNegative("VP-AGM-008", "SPI1 MISO initial composition"),
    "15da95aa610f581c352060fcc6bb70e99f989b38214b43bc1b256d390ca431a6":
        SiliconNegative("VP-AGM-008", "SPI1 MISO isolated composition"),
    "2c95736439961f66638bd9e98dc141ca7fad0373fe802356d779311b64cd8955":
        SiliconNegative("VP-AGM-009", "20-percent utilization composition"),
}


def refuse_known_silicon_negative_digest(digest):
    """Refuse a canonical image digest if retained evidence says it is wrong."""
    negative = KNOWN_SILICON_NEGATIVE_IMAGES.get(str(digest).lower())
    if negative is None:
        return
    raise SystemExit(
        "known silicon-negative image for %s (%s), SHA-256 %s; "
        "refusing exact image" % (negative.defect, negative.scope, digest)
    )


def refuse_known_silicon_negative_image(header, image):
    """Hash and check a CRC-finalized canonical uncompressed image."""
    digest = hashlib.sha256(bytes(header) + bytes(image)).hexdigest()
    refuse_known_silicon_negative_digest(digest)
