"""Fail-closed registries for retained silicon failures.

The image registry fences byte-exact canonical images.  The logical-design
registry additionally fences an exact synthesized cell graph while ignoring
placement and routing annotations, so rerouting a demonstrated-bad design does
not silently bypass its retained negative.  Neither registry implies that a
different logical composition is safe.
"""

from __future__ import annotations

import hashlib
import sys
import re
import os
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class SiliconNegative:
    defect: str
    scope: str


LOGICAL_DESIGN_DIGEST_SCHEMA = 1


# SHA-256 is over the canonical uncompressed image (header plus CRC-finalized
# payload), which is the same representation written by ``agamemnon to-bin``.
KNOWN_SILICON_NEGATIVE_IMAGES = {
    # Work-branch qualification, 2026-09-04: original-RTL waitstate16 emits
    # after dedicated-CIN admission is corrected, but fails 3/3 with a passing
    # control. All 312 observations finish; first mismatch is 13 (byte write),
    # signature 128a86c4 rather than 62190c8e. The LUT-carry implementation of
    # the SAME RTL passes 3/3: do not fence its logical graph or attribute the
    # failure to carry arithmetic without localization. Exact image only.
    "73c9826375b7c3261e52e766f9793e457350402d143406dc8de1e66d78b3bf2c":
        SiliconNegative("VP-GPT6-001", "waitstate16 dedicated-carry routed image"),
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
    # VP-AGM-012: designs the shared-control lowering newly let EMIT (previously
    # ROUTABILITY_GAP refusals) whose release-strict-clean image is wrong on
    # silicon -- the fabric-wide constant fan-in is funneled through the single
    # MCU-boundary $PACKER_GND at X14Y11 and mis-routes.  Each fails the retained
    # handshake 3/3 (logic8 hangs the hart).  The companion designs
    # compare_1_2_4/shift8/util10 emit and are silicon-correct, so they are
    # deliberately NOT fenced.  This is interim containment; the general fix is
    # per-tile-local constant generation.
    "818ff992fea304d11fd02ca9ec09d6c1f1edb6550fc75354003bb663a40e4999":
        SiliconNegative("VP-AGM-012", "4-bit add/subtract shared-constant emit"),
    "9ba3847c9e2170483eefaf71f287d0671a6e40ffe7ca8fea7d430c6bb7e2d02d":
        SiliconNegative("VP-AGM-012", "8-bit add/subtract shared-constant emit"),
    "fbd0362495b0b1589171ee8774f2e1cb6da05867c37f719767a36a3bcda57f92":
        SiliconNegative("VP-AGM-012", "8-bit priority shared-constant emit"),
    "f82dda520a9b57b3164f61a2b1fc996c3a480d147f78ee962f0ac2112ae7ffd0":
        SiliconNegative("VP-AGM-012", "5-percent utilization shared-constant emit"),
    "b8ab756dba05ff4f678cf70a15ce033164144ab7266407bf380d2ff3d725226a":
        SiliconNegative("VP-AGM-012", "8-bit logic shared-constant emit (hangs hart)"),
    # VP-AGM-013: a release-strict-clean 5-percent utilization structural image
    # that is wrong on silicon.  Two independent campaigns emitted this exact
    # image, it reproduces byte-for-byte on the current engine, and it passes the
    # routed model for all 1,024 steps -- and silicon still diverges from the
    # third step onward.  A traced run shows the request handshake, the phase
    # counter and the completion count all correct while only the folded state
    # digest differs, so the design is not hanging; it computes a different
    # function.  No single-fault model (output inversion, step slip, one- or
    # two-bit state divergence, a stuck or inverted command bit, an inverted lane
    # feedback, or a swapped lane tap) reproduces the observed trajectory.
    "72ce36fc78be7569a689d217968598f7320c3e2d5dcccfd5c35e26edc296acb1":
        SiliconNegative("VP-AGM-013", "5-percent utilization structural state digest"),
    # VP-AGM-014: three designs the campaign ledger records as ROUTABILITY_GAP
    # -- the release-strict router previously emitted no image for any of them
    # after 40-80 attempts -- now route and emit release-strict clean, with zero
    # unmapped selectors and no tier-2 confidence manifest.  Each retained image
    # fails its retained contract on silicon 3/3 deterministically.
    #
    # The oracle is not in doubt: for every one of the three, vendor-built images
    # of the same design in the same form pass that same oracle 4/4 on silicon,
    # and the campaign's own runners bind the structural forms to the user-form
    # oracle exactly as the witness session did.  Two independently configured,
    # probe-clean nextpnr binaries produce these images byte-for-byte, so this is
    # the engine's own behaviour and not a local toolchain artifact.
    #
    # This is a fail-open regression: a refusal became a wrong answer.  Until the
    # cause is found, the exact images are refused.
    "1e7098f2fc326c7611223a975271c771446c3e41abfc62682ed5a7d8641f8be0":
        SiliconNegative("VP-AGM-014", "8-bit add/subtract structural newly-routable emit"),
    "e8b31fba4859937ab2993b9045cae113da4042e0d65c76d1c33fcb593b57a8bb":
        SiliconNegative("VP-AGM-014", "8-bit compare structural newly-routable emit"),
    "a339ad6fd90dc4f3eefc5c432cc4a1bb3255d6f0ad24e176479188743295ac27":
        SiliconNegative("VP-AGM-014", "8-bit logic newly-routable emit"),
    # VP-AGM-015: six more designs the ledger records as ROUTABILITY_GAP that
    # emit release-strict clean when rebuilt unchanged at current main, and fail
    # their retained contract on silicon 3/3 with byte-identical mailboxes across
    # runs.  Same session, same harness and same known-good control as the three
    # VP-AGM-014 rows -- and in that same session three OTHER rebuilt gap rows
    # passed 3/3, so the harness demonstrably distinguishes right from wrong.
    #
    # Their failures do not resemble each other: two never reach ready at all,
    # one fails its first sample with every read lane reading 1, and three run
    # 2, 11 and 21 correct samples before diverging.  That is not one defect, so
    # the exact images and their reroute-invariant logical compositions are
    # refused rather than patched around.
    "48d2d5eabf1ac247259b8f805fa051c6f808cc80ed98ee9a6e8e04b564a0728c":
        SiliconNegative("VP-AGM-015", "16-bit add/subtract structural rebuilt gap emit"),
    "b9ed8c4b9e7517d41be4618b502bc8dd365d389ecef4f1a37491b097293ff826":
        SiliconNegative("VP-AGM-015", "paired 1/2/4-bit compare structural rebuilt gap emit"),
    "f82e5533be457e4b918ede13ab834690ebbc7e8fdf302a1f45271cb4a0d1118e":
        SiliconNegative("VP-AGM-015", "dual 4-bit LFSR structural rebuilt gap emit"),
    "1f54814ad0ff4f24180b8b3cb695d3194564efc2fa22b5fb0ada72ea4b1f829e":
        SiliconNegative("VP-AGM-015", "clock-enable FSM structural rebuilt gap emit"),
    "6d5e46d8c135c8f9ab1c266585e339c3afb8f33c48c4f83b77e32379bbfffcc4":
        SiliconNegative("VP-AGM-015", "2-bit shift structural rebuilt gap emit"),
    "0486b52e41edeb31ff6ebeaef361244bb01301a79be238dbb559deb46e4e02ae":
        SiliconNegative("VP-AGM-015", "4-bit right shift structural rebuilt gap emit"),
    # VP-AGM-016 covered four rows; area_a_addsub4_user has since been REMOVED
    # from it. That row passes its own contract 3/3 -- it had been compared to a
    # different design's expected mailbox by a harness defect, so the fence was
    # placed on a design that was never wrong.
    # VP-AGM-016: the last four rebuilt gap rows witnessed wrong in the same
    # sweep.  Same shape as VP-AGM-014 and VP-AGM-015 -- the ledger recorded a
    # routing refusal, the current engine emits release-strict clean, and the
    # image fails its retained contract on silicon 3/3.  Two designs that passed
    # 3/3 ran in the same batch behind the same control, so the batch
    # distinguishes right from wrong.
    "a0e6226f3e9e0bf5190e672799c495918c42dadb20b9676157411271ab5c9c82":
        SiliconNegative("VP-AGM-016", "4-bit add/subtract structural rebuilt gap emit"),
    "4bf17468b9d29a1efdc5f258192925339579fb68e36b34b6fc7f3a7f25457f1f":
        SiliconNegative("VP-AGM-016", "8-bit priority rebuilt gap emit"),
    "6cb7fb208f4c1dc8c520b7186cbb048d9aa3db7832c70bf6b297a2978c6fa0e6":
        SiliconNegative("VP-AGM-016", "4-bit rotate structural rebuilt gap emit"),
    # VP-AGM-017: two further rebuilt gap rows witnessed wrong.  Same session
    # shape as VP-AGM-014/015/016 -- ledger says ROUTABILITY_GAP, current main
    # emits release-strict clean, silicon fails 3/3 -- and the same batch
    # returned PASS 3/3 for util10_structural and util20_structural, so the
    # batch separates right from wrong.  util5_user is the user-facing sibling
    # of the VP-AGM-013 structural row, which was already fenced.
    "60743d5fd59c9bfd034cb51d3cea8b337e84ff0c67fc4a623d139a21c07468c1":
        SiliconNegative("VP-AGM-017", "4-bit multiply structural rebuilt gap emit"),
    "649dcc2f42008749f0cf107f66e2c7ec6cdee8c7edb03df95d1ce3389578f9ad":
        SiliconNegative("VP-AGM-017", "5-percent utilization rebuilt gap emit"),
    # VP-AGM-018: a rebuilt PIN_10 held-input row, judged on the Pico pad rig
    # against its own 512-step pad contract rather than a mailbox.  It emits
    # release-strict clean and diverges at pad observation 3.  The same batch
    # returned PASS 3/3 for the PIN_12 input row and for both pad-output rows
    # behind the same known-good control, so the rig separates right from wrong
    # and this is specific to PIN_10.
    # VP-AGM-019: the three rows that stayed wrong after the tied-zero LUT-input
    # cofactor fix.  That fix took fifteen of eighteen rebuilt rows to PASS 3/3,
    # so these are NOT the zero-cofactor mechanism -- the netlist audit finds no
    # LUT in any of the three whose INIT reads an undriven pin.  Their cause is
    # unnamed, which is why they are fenced rather than explained.  addsub16 did
    # move from "never reaches ready" to diverging at sample 5, so part of its
    # failure was the cofactor defect and part is something else.
    "05cdaacfe1d438be9b7d24e820e5c60942b42437bf823242df0aec37e03427fc":
        SiliconNegative("VP-AGM-019", "16-bit add/subtract structural, post-cofactor"),
    "29793569a57a3ab04f7762daa17dcac6b3d41787f8e4bd0386ebad0ec5aca2c8":
        SiliconNegative("VP-AGM-019", "4-bit multiply structural, post-cofactor"),
    "a30e319eb4e9395b8e2cdfb5be686dc7806eeed962b7901a23d46dfcb546e1a0":
        SiliconNegative("VP-AGM-019", "5-percent utilization structural, post-cofactor"),
    "5032942cdfc30aee330b600a75eb44d41c85b1a9b7ab1af89de9814c04a36619":
        SiliconNegative("VP-AGM-018", "PIN_10 held-input rebuilt gap emit"),
}


# SHA-256 is over ``logical_design_digest``'s canonical JSON projection.  The
# projection retains ports, cell names/types/parameters/connections, memories,
# and net identities, but removes nextpnr's module settings plus module/cell/net
# attributes.  Those excluded fields hold the route seed, placer/router knobs,
# BEL placement, route strings, and other physical annotations.  This makes the
# fence invariant to a reroute of the same synthesized composition without
# broadening it to every use of a feature or primitive.
KNOWN_SILICON_NEGATIVE_DESIGNS = {
    # These hashes bind the retained routed modules after removing every
    # module/cell/net attribute.  They therefore cover changed BEL placement,
    # route strings, and nextpnr's physical annotations for the same exact
    # synthesized graph.  The private artifacts and silicon results remain in
    # the workbench; only their one-way logical-design fingerprints live here.
    "cfbe0b417c5c1e284f6e2f580bffb20ffbe9180d0e52831286e1f485de0b745f":
        SiliconNegative("VP-AGM-001", "MCU ALU handshake logical composition"),
    "2a74d54a443eaf573a7097aee474bf011f3e8b256831e2a13e221fb1a7cd8c2e":
        SiliconNegative("VP-AGM-003", "clock-enable FSM logical composition"),
    "3601986a419af8810c87442d9b573ae2418c7a94e227ccc49ca71a7ca38a4c18":
        SiliconNegative("VP-AGM-004", "rotate logical composition"),
    "18f2a6ecf2f90da5ad8101ccff1f1a15f6ce414f9168e64ee618c99bdda3d9eb":
        SiliconNegative("VP-AGM-005", "one-bit add/subtract logical composition"),
    "60c4598e7ad4bd5ab2ee10cb683c4a2ec6c1535b25d16a4c5801e19fb4d78bd8":
        SiliconNegative("VP-AGM-008", "PIN_12 held-input logical composition"),
    "e551b97f97e43ecd91e6a08cbfdc04d8539162023cd71698cfeccf53d6a0aa8a":
        SiliconNegative("VP-AGM-008", "PIN_10 held-input logical composition"),
    "e03cb683f11999ccdede468b1ccfaf95aa62b0e027a097b714242c82b40e07b5":
        SiliconNegative("VP-AGM-009", "20-percent utilization logical composition"),
    # VP-AGM-012 (see the image registry above): reroute-invariant fence for the
    # five shared-control-lowered designs whose emit is silicon-wrong.
    "091d55a8274b135088e4ce4013ed2a43d670ac0e303acb331ed9bcadae7a3301":
        SiliconNegative("VP-AGM-012", "4-bit add/subtract shared-constant logical composition"),
    "feb8618c8d8a0aaee93d2f0ae7d753cd7a6f89ce5895037b693105e418dae6ca":
        SiliconNegative("VP-AGM-012", "8-bit add/subtract shared-constant logical composition"),
    "536d9d0c265b577b9515b56e97bc5c50738d87238f4d56cb2107e6d999b81c8c":
        SiliconNegative("VP-AGM-012", "8-bit priority shared-constant logical composition"),
    "0bdc08a1dd69ef0c6a06943714918db58ed60179d35a3ccb92d91552dcc900be":
        SiliconNegative("VP-AGM-012", "5-percent utilization shared-constant logical composition"),
    "1bddb34fd0711a1f07c0ed88670e1c5fef12f42e0e2553d43cc81f929140ba64":
        SiliconNegative("VP-AGM-012", "8-bit logic shared-constant logical composition"),
    # VP-AGM-013 (see the image registry above): reroute-invariant fence, so a
    # replaced placement or route of the same synthesized graph cannot silently
    # reintroduce the demonstrated-bad composition.
    "cd9f9d9e4551f68f994e3c0fc85a2f3037262b3aa595eee7e79f52b680e254eb":
        SiliconNegative("VP-AGM-013", "5-percent utilization structural logical composition"),
    # VP-AGM-014 (see the image registry above): reroute-invariant fence.  These
    # three designs became routable through a route change, so an image-only
    # fence would be bypassed by the next reroute of the same graph.
    "27dc3bcba2db80b18c04ed28a9bde721a332326f6a1df0a3d38bb04cf7aacd64":
        SiliconNegative("VP-AGM-014", "8-bit add/subtract structural logical composition"),
    "31039d2cc78458800352464082efcbf6a3529e586e6c07bd29d0b1cc9e48c5d0":
        SiliconNegative("VP-AGM-014", "8-bit compare structural logical composition"),
    "e5577bd862ccde73e854f2e13db109405bcdee767e433d19071757529dfe6a73":
        SiliconNegative("VP-AGM-014", "8-bit logic logical composition"),
    # VP-AGM-015 (see the image registry above): reroute-invariant fence.  These
    # rows became emittable through engine changes made after their gap verdicts
    # were recorded, so an image-only fence would be bypassed by the next reroute.
    "93b745d53b437110c5ba476870c2ff55625832ae8838df6e219e98a28f000d50":
        SiliconNegative("VP-AGM-015", "16-bit add/subtract structural rebuilt gap emit logical composition"),
    "deb24066916574538432c3d8e95d99a4f08e15d0eea382750067302957fd2ebb":
        SiliconNegative("VP-AGM-015", "paired 1/2/4-bit compare structural rebuilt gap emit logical composition"),
    "5c16a4db1af95a7b8958e8816b7fd9956762b95c954f6a7c94f2e4103ecc8ef5":
        SiliconNegative("VP-AGM-015", "dual 4-bit LFSR structural rebuilt gap emit logical composition"),
    "c7098e8e052b700ba185e99273d86c69337b55dbe265f2bcf7c136913921c67c":
        SiliconNegative("VP-AGM-015", "clock-enable FSM structural rebuilt gap emit logical composition"),
    "68bb2537c44e2cac039fa2e5d104ba95cd890177741406b3de5ca1d94822a6ad":
        SiliconNegative("VP-AGM-015", "2-bit shift structural rebuilt gap emit logical composition"),
    "492f7d863175c0630ef88ab89900fac0ddc887c390e18a9f7be2a4fef49fa30e":
        SiliconNegative("VP-AGM-015", "4-bit right shift structural rebuilt gap emit logical composition"),
    # VP-AGM-016 (see the image registry above): reroute-invariant fence.
    "6bf9b40d4afdac031a90ba6f751c810e4094dbecb11f6354ea655bfa799c88f3":
        SiliconNegative("VP-AGM-016", "4-bit add/subtract structural rebuilt gap emit logical composition"),
    "307f9eaf9a083ab940eaf8cecace23c597ba5422876cb29b2ed005a0a27bde2b":
        SiliconNegative("VP-AGM-016", "8-bit priority rebuilt gap emit logical composition"),
    "1fa3671f4a5e9dd1f7b18a4fefcbe28bfee3d76d83cc2d0f2b59ad2c17dc4bf6":
        SiliconNegative("VP-AGM-016", "4-bit rotate structural rebuilt gap emit logical composition"),
    # VP-AGM-017 (see the image registry above): reroute-invariant fence.
    "4d8ebb927e4089e0e26826832087acd0359582815544324b98b4712cc5646920":
        SiliconNegative("VP-AGM-017", "4-bit multiply structural rebuilt gap emit logical composition"),
    "a2ed91c29868a4757af518a7036f393ca2108745ad12e696c38901f543150f7c":
        SiliconNegative("VP-AGM-017", "5-percent utilization rebuilt gap emit logical composition"),
    # VP-AGM-018 (see the image registry above): reroute-invariant fence.
    "237c0ae935ee109c91e8478ef047384a17bb9f67db9de08b896475f892c6ee01":
        SiliconNegative("VP-AGM-018", "PIN_10 held-input rebuilt gap emit logical composition"),
    # VP-AGM-019 (see the image registry above): reroute-invariant fence.
    "2ee070547e17d44e1c59b4e359ff3cb7b792b48849d599f30f52d9e868a69e50":
        SiliconNegative("VP-AGM-019", "16-bit add/subtract structural post-cofactor logical composition"),
    "5d7437c251a6f43b17cc74febc322e7c76e4cec7f6568a377f3933213454b484":
        SiliconNegative("VP-AGM-019", "4-bit multiply structural post-cofactor logical composition"),
    "bf57c57162ca0c6014f1cc7f6e349d8913af26f7c4b384ed3ed74c6fbce9852f":
        SiliconNegative("VP-AGM-019", "5-percent utilization structural post-cofactor logical composition"),
}


def _logical_design_projection(module):
    """Return the route/placement-independent part of a routed top module."""
    projection = {}
    for key, value in module.items():
        if key in {"attributes", "settings"}:
            continue
        if key in {"cells", "netnames"}:
            projection[key] = {
                name: {
                    item_key: item_value
                    for item_key, item_value in item.items()
                    if item_key != "attributes"
                }
                for name, item in value.items()
            }
        else:
            projection[key] = value
    return projection


def logical_design_digest(module):
    """Hash a synthesized module without placement or routing annotations."""
    canonical = json.dumps(
        {
            "schema": LOGICAL_DESIGN_DIGEST_SCHEMA,
            "module": _logical_design_projection(module),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


_BEL = re.compile(r"^X(\d+)Y(\d+)_SLICE(\d+)$")
_HOP = re.compile(r"X(\d+)Y(\d+)_OMUX(\d+)\.X\d+Y\d+_OMUX(\d+)")


def combinational_copresentations(module):
    """Nets where a COMBINATIONAL slice presents on two OMUX wires at once.

    af.exe never emits one: across 60 vendor oracle trees and 3,740
    driver-slice nets, all 514 multi-wire presentations have a registered
    driver. On silicon the pattern reads stuck-low at 13 of 14 measured sites.
    X14Y4 is the one measured exception and is not counted.
    """
    registered = {}
    for cell in module.get("cells", {}).values():
        match = _BEL.match(cell.get("attributes", {}).get("NEXTPNR_BEL", "") or "")
        if match:
            used = str(cell.get("parameters", {}).get("FF_USED", "0"))
            registered[tuple(int(g) for g in match.groups())] = bool(int(used, 2))
    found = []
    for name, net in module.get("netnames", {}).items():
        route = net.get("attributes", {}).get("ROUTING", "") or ""
        for x, y, src, dst in _HOP.findall(route):
            src, dst = int(src), int(dst)
            if src % 3 != 2 or dst != src - 1:
                continue
            if (int(x), int(y)) == (14, 4):
                continue
            if not registered.get((int(x), int(y), src // 3)):
                found.append("%s @ X%sY%s_SLICE%d" % (name, x, y, src // 3))
    return found


def _shout(text):
    """Write to stdout AND stderr, unbuffered, so a build log cannot lose it."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.write(text)
            stream.flush()
        except Exception:  # noqa: BLE001, S110
            pass


def refuse_known_silicon_negative_design(module):
    """Refuse a routed module whose exact logical cell graph is retained bad."""
    digest = logical_design_digest(module)
    negative = KNOWN_SILICON_NEGATIVE_DESIGNS.get(digest)
    if negative is None:
        return

    # NARROW REQUALIFICATION PATH -- workbench only, opt-in, and loud.
    #
    # The design fence is deliberately reroute-invariant: it exists so that a
    # design demonstrated wrong on silicon cannot be laundered by rerouting it
    # until it happens to pass. That is the right default and it stays.
    #
    # But a root cause changes what a reroute means. Combinational
    # co-presentation is a STRUCTURAL property of a route that can be checked
    # exactly, and it explains six of the seven correctness escapes. A rebuild
    # that provably contains none is not "another spin of the lottery", it is a
    # different and specifically-defensible configuration -- so it is worth
    # putting in front of the board to find out.
    #
    # This is NOT an admission of parity. Nothing here may be quoted as a pass:
    # it exists to MAKE an image the board can judge. The fence is only lifted
    # again, permanently, by a witnessed silicon result.
    if os.environ.get("AGAMEMNON_COPRESENT_REQUALIFY") == "1":
        offenders = combinational_copresentations(module)
        if not offenders:
            sys.stderr.write(
                "\n*** REQUALIFICATION BUILD -- NOT A RELEASE IMAGE ***\n"
                "%s (%s) is fenced silicon-negative, SHA-256 %s.\n"
                "This route contains zero combinational co-presentations, so "
                "the fence is bypassed to produce an image for the board.\n"
                "The result is UNWITNESSED. Do not score it, do not ship it, "
                "and do not lift the fence without a silicon result.\n\n"
                % (negative.defect, negative.scope, digest))
            return
        _shout(
            "AGAMEMNON_COPRESENT_REQUALIFY set but this route still has %d "
            "combinational co-presentation(s), e.g. %s; refusing as usual.\n"
            % (len(offenders), offenders[0]))

    raise SystemExit(
        "known silicon-negative logical design for %s (%s), SHA-256 %s; "
        "refusing rerouted variants of the retained composition" %
        (negative.defect, negative.scope, digest)
    )


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
