/* agrv2k.cc — nextpnr-generic Viaduct microarchitecture for the AGM AGRV2K eFPGA.
 *
 * Overlay component of Project AGaMEMnon. This file is OWNED by AGaMEMnon
 * (engine/uarch/agrv2k/) and copied into a PINNED nextpnr submodule at
 * generic/viaduct/agrv2k/ by build.sh (never a hand-maintained fork). See ../README.md.
 *
 * The device is DATA, not code: init() loads the flat dev_*.csv produced by
 * engine/emit_uarch_db.py (which runs the proven arch.py graph generator against a
 * recording fake-ctx) and replays it 1:1 into nextpnr. No fabric topology is hard-coded here.
 *
 * Names are FLAT single-element IdStringLists ("X14Y8_RMUX21", pip "src.dst"), so the routed
 * --write JSON matches bitgen_seq.py's X{x}Y{y}_{res} / {src}.{dst} parsing unchanged.
 */

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <set>
#include <memory>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "cells.h"
#include "design_utils.h"
#include "log.h"
#include "nextpnr.h"
#include "util.h"
#include "viaduct_api.h"
#include "viaduct_helpers.h"

NEXTPNR_NAMESPACE_BEGIN

namespace {

// ---- tiny CSV reader. dev_*.csv are simple: no quoting, no embedded commas, '\n' rows. ----
struct Csv
{
    std::ifstream in;
    std::vector<std::string> fields;
    explicit Csv(const std::string &path) : in(path)
    {
        if (!in)
            log_error("agrv2k: cannot open chipdb file '%s'\n", path.c_str());
    }
    bool next()
    {
        std::string line;
        if (!std::getline(in, line))
            return false;
        if (!line.empty() && line.back() == '\r')
            line.pop_back();
        fields.clear();
        std::string cur;
        std::istringstream ss(line);
        while (std::getline(ss, cur, ','))
            fields.push_back(cur);
        return true;
    }
    const std::string &at(size_t i) const
    {
        static const std::string empty;
        return i < fields.size() ? fields[i] : empty;
    }
};

static int to_int(const std::string &s, int dflt = 0)
{
    return s.empty() ? dflt : int(std::strtol(s.c_str(), nullptr, 10));
}
static double to_double(const std::string &s, double dflt = 0.0)
{
    return s.empty() ? dflt : std::strtod(s.c_str(), nullptr);
}

// ---- Packing: LUT/DFF/const/IO fusing into GENERIC_SLICE + GENERIC_IOB. ----
// These four functions are ported VERBATIM from nextpnr's generic/pack.cc `Arch::pack()` else-branch
// (the built-in generic packer the old `nextpnr-generic --pre-pack arch.py` flow used). When a Viaduct
// uarch is active nextpnr calls `uarch->pack()` INSTEAD of that built-in path, so we replicate it here
// to get byte-identical GENERIC_SLICE cells (INIT + FF_USED) that bitgen_seq.py consumes unchanged.
// Helpers (create_generic_cell/lut_to_lc/dff_to_lc/nxio_to_iob/is_lut/is_ff/is_lc/net_only_drives) are
// the generic arch's own (cells.h / design_utils.h) and link in since we compile into nextpnr-generic.

static void pack_lut_lutffs(Context *ctx)
{
    log_info("Packing LUT-FFs..\n");

    pool<IdString> packed_cells;
    std::vector<std::unique_ptr<CellInfo>> new_cells;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ctx->verbose)
            log_info("cell '%s' is of type '%s'\n", ci->name.c_str(ctx), ci->type.c_str(ctx));
        if (is_lut(ctx, ci)) {
            std::unique_ptr<CellInfo> packed =
                    create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), ci->name.str(ctx) + "_LC");
            for (auto &attr : ci->attrs)
                packed->attrs[attr.first] = attr.second;
            packed_cells.insert(ci->name);
            if (ctx->verbose)
                log_info("packed cell %s into %s\n", ci->name.c_str(ctx), packed->name.c_str(ctx));
            // See if we can pack into a DFF
            // TODO: LUT cascade
            NetInfo *o = ci->ports.at(ctx->id("Q")).net;
            CellInfo *dff = net_only_drives(ctx, o, is_ff, ctx->id("D"), true);
            auto lut_bel = ci->attrs.find(ctx->id("BEL"));
            bool packed_dff = false;
            if (dff) {
                if (ctx->verbose)
                    log_info("found attached dff %s\n", dff->name.c_str(ctx));
                auto dff_bel = dff->attrs.find(ctx->id("BEL"));
                if (lut_bel != ci->attrs.end() && dff_bel != dff->attrs.end() && lut_bel->second != dff_bel->second) {
                    // Locations don't match, can't pack
                } else {
                    lut_to_lc(ctx, ci, packed.get(), false);
                    dff_to_lc(ctx, dff, packed.get(), false);
                    ctx->nets.erase(o->name);
                    if (dff_bel != dff->attrs.end())
                        packed->attrs[ctx->id("BEL")] = dff_bel->second;
                    packed_cells.insert(dff->name);
                    if (ctx->verbose)
                        log_info("packed cell %s into %s\n", dff->name.c_str(ctx), packed->name.c_str(ctx));
                    packed_dff = true;
                }
            }
            if (!packed_dff) {
                lut_to_lc(ctx, ci, packed.get(), true);
            }
            new_cells.push_back(std::move(packed));
        }
    }
    for (auto pcell : packed_cells) {
        ctx->cells.erase(pcell);
    }
    for (auto &ncell : new_cells) {
        ctx->cells[ncell->name] = std::move(ncell);
    }
}

static void pack_nonlut_ffs(Context *ctx)
{
    log_info("Packing non-LUT FFs..\n");

    pool<IdString> packed_cells;
    std::vector<std::unique_ptr<CellInfo>> new_cells;

    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (is_ff(ctx, ci)) {
            std::unique_ptr<CellInfo> packed =
                    create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), ci->name.str(ctx) + "_DFFLC");
            for (auto &attr : ci->attrs)
                packed->attrs[attr.first] = attr.second;
            if (ctx->verbose)
                log_info("packed cell %s into %s\n", ci->name.c_str(ctx), packed->name.c_str(ctx));
            packed_cells.insert(ci->name);
            dff_to_lc(ctx, ci, packed.get(), true);
            new_cells.push_back(std::move(packed));
        }
    }
    for (auto pcell : packed_cells) {
        ctx->cells.erase(pcell);
    }
    for (auto &ncell : new_cells) {
        ctx->cells[ncell->name] = std::move(ncell);
    }
}

static void set_net_constant(const Context *ctx, NetInfo *orig, NetInfo *constnet, bool constval)
{
    orig->driver.cell = nullptr;
    for (auto user : orig->users) {
        if (user.cell != nullptr) {
            CellInfo *uc = user.cell;
            if (ctx->verbose)
                log_info("%s user %s\n", orig->name.c_str(ctx), uc->name.c_str(ctx));
            if ((is_lut(ctx, uc) || is_lc(ctx, uc)) && (user.port.str(ctx).at(0) == 'I') && !constval) {
                uc->ports[user.port].net = nullptr;
                uc->ports[user.port].user_idx = {};
            } else {
                uc->ports[user.port].net = constnet;
                uc->ports[user.port].user_idx = constnet->users.add(user);
            }
        }
    }
    orig->users.clear();
}

static void pack_constants(Context *ctx)
{
    log_info("Packing constants..\n");

    std::unique_ptr<CellInfo> gnd_cell = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), "$PACKER_GND");
    gnd_cell->params[ctx->id("INIT")] = Property(0, 1 << ctx->args.K);
    std::unique_ptr<NetInfo> gnd_net = std::make_unique<NetInfo>(ctx->id("$PACKER_GND_NET"));
    gnd_net->driver.cell = gnd_cell.get();
    gnd_net->driver.port = ctx->id("F");
    gnd_cell->ports.at(ctx->id("F")).net = gnd_net.get();

    std::unique_ptr<CellInfo> vcc_cell = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), "$PACKER_VCC");
    // Fill with 1s
    vcc_cell->params[ctx->id("INIT")] = Property(Property::S1).extract(0, (1 << ctx->args.K), Property::S1);
    std::unique_ptr<NetInfo> vcc_net = std::make_unique<NetInfo>(ctx->id("$PACKER_VCC_NET"));
    vcc_net->driver.cell = vcc_cell.get();
    vcc_net->driver.port = ctx->id("F");
    vcc_cell->ports.at(ctx->id("F")).net = vcc_net.get();

    std::vector<IdString> dead_nets;

    bool gnd_used = false, vcc_used = false;

    for (auto &net : ctx->nets) {
        NetInfo *ni = net.second.get();
        if (ni->driver.cell != nullptr && ni->driver.cell->type == ctx->id("GND")) {
            IdString drv_cell = ni->driver.cell->name;
            set_net_constant(ctx, ni, gnd_net.get(), false);
            gnd_used = true;
            dead_nets.push_back(net.first);
            ctx->cells.erase(drv_cell);
        } else if (ni->driver.cell != nullptr && ni->driver.cell->type == ctx->id("VCC")) {
            IdString drv_cell = ni->driver.cell->name;
            set_net_constant(ctx, ni, vcc_net.get(), true);
            vcc_used = true;
            dead_nets.push_back(net.first);
            ctx->cells.erase(drv_cell);
        }
    }

    if (gnd_used) {
        ctx->cells[gnd_cell->name] = std::move(gnd_cell);
        ctx->nets[gnd_net->name] = std::move(gnd_net);
    }

    if (vcc_used) {
        ctx->cells[vcc_cell->name] = std::move(vcc_cell);
        ctx->nets[vcc_net->name] = std::move(vcc_net);
    }

    for (auto dn : dead_nets) {
        ctx->nets.erase(dn);
    }
}

static bool is_nextpnr_iob(Context *ctx, CellInfo *cell)
{
    return cell->type == ctx->id("$nextpnr_ibuf") || cell->type == ctx->id("$nextpnr_obuf") ||
           cell->type == ctx->id("$nextpnr_iobuf");
}

static bool is_generic_iob(const Context *ctx, const CellInfo *cell) { return cell->type == ctx->id("GENERIC_IOB"); }

static void pack_io(Context *ctx)
{
    pool<IdString> packed_cells;
    pool<IdString> delete_nets;

    std::vector<std::unique_ptr<CellInfo>> new_cells;
    log_info("Packing IOs..\n");

    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (is_nextpnr_iob(ctx, ci)) {
            CellInfo *iob = nullptr;
            if (ci->type == ctx->id("$nextpnr_ibuf") || ci->type == ctx->id("$nextpnr_iobuf")) {
                iob = net_only_drives(ctx, ci->ports.at(ctx->id("O")).net, is_generic_iob, ctx->id("PAD"), true, ci);

            } else if (ci->type == ctx->id("$nextpnr_obuf")) {
                NetInfo *net = ci->ports.at(ctx->id("I")).net;
                iob = net_only_drives(ctx, net, is_generic_iob, ctx->id("PAD"), true, ci);
            }
            if (iob != nullptr) {
                // Trivial case, GENERIC_IOB used. Just destroy the net and the
                // iobuf
                log_info("%s feeds GENERIC_IOB %s, removing %s %s.\n", ci->name.c_str(ctx), iob->name.c_str(ctx),
                         ci->type.c_str(ctx), ci->name.c_str(ctx));
                NetInfo *net = iob->ports.at(ctx->id("PAD")).net;
                if (((ci->type == ctx->id("$nextpnr_ibuf") || ci->type == ctx->id("$nextpnr_iobuf")) &&
                     net->users.entries() > 1) ||
                    (ci->type == ctx->id("$nextpnr_obuf") && (net->users.entries() > 2 || net->driver.cell != nullptr)))
                    log_error("PAD of %s '%s' connected to more than a single top level IO.\n", iob->type.c_str(ctx),
                              iob->name.c_str(ctx));

                if (net != nullptr) {
                    delete_nets.insert(net->name);
                    iob->ports.at(ctx->id("PAD")).net = nullptr;
                }
                if (ci->type == ctx->id("$nextpnr_iobuf")) {
                    NetInfo *net2 = ci->ports.at(ctx->id("I")).net;
                    if (net2 != nullptr) {
                        delete_nets.insert(net2->name);
                    }
                }
            } else if (bool_or_default(ctx->settings, ctx->id("disable_iobs"))) {
                // No IO buffer insertion; just remove nextpnr_[io]buf
                for (auto &p : ci->ports)
                    ci->disconnectPort(p.first);
            } else {
                // Create a GENERIC_IOB buffer
                std::unique_ptr<CellInfo> ice_cell =
                        create_generic_cell(ctx, ctx->id("GENERIC_IOB"), ci->name.str(ctx) + "$iob");
                nxio_to_iob(ctx, ci, ice_cell.get(), packed_cells);
                new_cells.push_back(std::move(ice_cell));
                iob = new_cells.back().get();
            }
            packed_cells.insert(ci->name);
            if (iob != nullptr)
                for (auto &attr : ci->attrs)
                    iob->attrs[attr.first] = attr.second;
        }
    }
    for (auto pcell : packed_cells) {
        ctx->cells.erase(pcell);
    }
    for (auto dnet : delete_nets) {
        ctx->nets.erase(dnet);
    }
    for (auto &ncell : new_cells) {
        ctx->cells[ncell->name] = std::move(ncell);
    }
}

// ---- pack: dedicated hardware carry. The carry techmap (synth/ag32_carry_map.v) lowers yosys `$alu`
// to a chain of AG32_FA cells (ports A,B,CIN,SUM,COUT, chained COUT[i]->CIN[i+1]). Fuse each AG32_FA
// (+ the DFF it drives, if any) into ONE GENERIC_SLICE that KEEPS the CIN/COUT ports, so nextpnr routes
// the carry over the arch's dedicated COUT<z>->CIN<z+1> pips (arch.py sec 2b, AGAMEMNON_HW_CARRY) and
// bitgen's carry_sets emits CFG_LUTCMUX[2z+1]=1 (modeMux=1 -> pinC=Cin). The stock pack_lut_lutffs would
// DROP CIN/COUT (it only maps I/Q/F/CLK) -- that's why this dedicated pass exists. See ag32-dense-carry-
// mechanism: ripple slice INIT=0x96E8 (LutOut(D=1)=A^B^Cin ; Cout=maj(A,B,Cin) from the low mask byte);
// D=I[3] must be 1, so tie it to a shared VCC slice; I[2] is unused (pinC comes from the Cin hardware).
static void pack_carries(Context *ctx)
{
    IdString fa_type = ctx->id("AG32_FA");
    bool any = false;
    for (auto &cell : ctx->cells)
        if (cell.second->type == fa_type) { any = true; break; }
    if (!any)
        return;
    log_info("Packing carry chains..\n");

    // one shared VCC slice fans out to every carry cell's D input (I[3]=1)
    std::unique_ptr<CellInfo> vcc_cell = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), "$CARRY_VCC");
    vcc_cell->params[ctx->id("INIT")] = Property(Property::S1).extract(0, (1 << ctx->args.K), Property::S1);
    vcc_cell->params[ctx->id("FF_USED")] = 0;
    auto vcc_net_uptr = std::make_unique<NetInfo>(ctx->id("$CARRY_VCC_NET"));
    NetInfo *vcc_net = vcc_net_uptr.get();
    vcc_cell->connectPort(ctx->id("F"), vcc_net);

    pool<IdString> packed_cells;
    std::vector<std::unique_ptr<CellInfo>> new_cells;
    long n_fa = 0, n_ffused = 0;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != fa_type)
            continue;
        std::unique_ptr<CellInfo> lc =
                create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), ci->name.str(ctx) + "_CARRY");
        lc->addInput(ctx->id("CIN"));   // create_generic_cell doesn't add the carry ports
        lc->addOutput(ctx->id("COUT"));
        // CONSTANT FOLD: a full adder whose A/B input is a constant (e.g. the counter's "+1" addend, GND on
        // the high bits) bakes that value into the LUT mask so we DON'T route GND/VCC to every dense slice
        // (that ingress is what makes a dense carry tile unroutable -- and it's why the vendor uses per-bit
        // masks 0x96E8/0x69D4/..). The unfolded mask is 0x96E8: LutOut(D=1)=A^B^Cin, Cout=maj(A,B,Cin).
        auto const_of = [&](NetInfo *n) -> int {          // -1 = routed signal; 0/1 = folded constant
            if (n == nullptr)
                return 0;
            const std::string nm = n->name.str(ctx);
            if (nm.find("PACKER_GND") != std::string::npos)
                return 0;
            if (nm.find("PACKER_VCC") != std::string::npos || nm.find("CARRY_VCC") != std::string::npos)
                return 1;
            return -1;
        };
        int ac = const_of(ci->getPort(ctx->id("A")));
        int bc = const_of(ci->getPort(ctx->id("B")));
        int mask = 0;
        for (int i = 0; i < 16; i++) {
            int pA = i & 1, pB = (i >> 1) & 1, pC = (i >> 2) & 1, D = (i >> 3) & 1;
            int a = (ac >= 0) ? ac : pA, b = (bc >= 0) ? bc : pB;
            int bit = D ? (a ^ b ^ pC) : ((a + b + pC) >= 2 ? 1 : 0); // hi byte=sum, lo byte=Cout(maj)
            if (bit)
                mask |= (1 << i);
        }
        lc->params[ctx->id("INIT")] = Property(mask, 1 << ctx->args.K);
        if (ac < 0)
            ci->movePortTo(ctx->id("A"), lc.get(), ctx->id("I[0]"));
        else
            ci->disconnectPort(ctx->id("A"));   // folded -> don't route the constant
        if (bc < 0)
            ci->movePortTo(ctx->id("B"), lc.get(), ctx->id("I[1]"));
        else
            ci->disconnectPort(ctx->id("B"));
        // CIN: only route a real carry net; a constant carry-in (the head/seed, Cin=0) must NOT be wired
        // to the synthetic carry wire (a constant can't reach it) -- leave it unconnected (pinC=Cin=0).
        if (const_of(ci->getPort(ctx->id("CIN"))) < 0)
            ci->movePortTo(ctx->id("CIN"), lc.get(), ctx->id("CIN"));
        else
            ci->disconnectPort(ctx->id("CIN"));
        ci->movePortTo(ctx->id("COUT"), lc.get(), ctx->id("COUT"));
        lc->connectPort(ctx->id("I[3]"), vcc_net); // D=1 (selects the sum half; inherent, must be routed)

        // fuse the DFF the SUM drives (reset-free counter: SUM -> DFF.D directly), else comb F=SUM
        NetInfo *sum = ci->ports.at(ctx->id("SUM")).net;
        CellInfo *dff = sum ? net_only_drives(ctx, sum, is_ff, ctx->id("D"), true) : nullptr;
        if (dff != nullptr) {
            lc->params[ctx->id("FF_USED")] = 1;
            dff->movePortTo(ctx->id("CLK"), lc.get(), ctx->id("CLK"));
            dff->movePortTo(ctx->id("Q"), lc.get(), ctx->id("Q"));
            ctx->nets.erase(sum->name); // internal LUT->FF net; F stays unconnected
            packed_cells.insert(dff->name);
            ++n_ffused;
        } else {
            lc->params[ctx->id("FF_USED")] = 0;
            ci->movePortTo(ctx->id("SUM"), lc.get(), ctx->id("F"));
        }
        packed_cells.insert(ci->name);
        new_cells.push_back(std::move(lc));
        ++n_fa;
    }
    ctx->cells[vcc_cell->name] = std::move(vcc_cell);
    ctx->nets[vcc_net_uptr->name] = std::move(vcc_net_uptr);
    for (auto pc : packed_cells)
        ctx->cells.erase(pc);
    for (auto &nc : new_cells)
        ctx->cells[nc->name] = std::move(nc);
    log_info("  fused %ld AG32_FA carry slices (%ld registered) + 1 shared VCC\n", n_fa, n_ffused);

    // ---- constructive placement: keep each carry chain CONTIGUOUS. The COUT<z>->CIN<z+1> pip only links
    // adjacent slices, and nextpnr's SA placer won't keep a bare carry net contiguous (it scattered the
    // chain -> carry[k] unroutable). So bind the chain to fixed consecutive slots on one tile (LOCKED),
    // which is exactly what the dense placer will do. Tile via AGRV2K_CARRY_TILE (default 14,8). Trace the
    // order by following COUT->CIN. (Single chain / <=16 for now; multi-chain + >16 spill = dense placer.)
    std::vector<CellInfo *> carry;
    for (auto &cell : ctx->cells)
        if (cell.second->type == ctx->id("GENERIC_SLICE") && cell.second->ports.count(ctx->id("COUT")))
            carry.push_back(cell.second.get());
    if (!carry.empty()) {
        dict<IdString, CellInfo *> cin_reader;
        pool<IdString> cout_nets;
        for (auto c : carry) {
            NetInfo *cn = c->getPort(ctx->id("CIN"));
            if (cn)
                cin_reader[cn->name] = c;
            NetInfo *co = c->getPort(ctx->id("COUT"));
            if (co)
                cout_nets.insert(co->name);
        }
        CellInfo *head = carry[0];
        for (auto c : carry) {
            NetInfo *cn = c->getPort(ctx->id("CIN"));
            if (cn == nullptr || !cout_nets.count(cn->name)) { head = c; break; }
        }
        std::vector<CellInfo *> ordered;
        pool<IdString> seen;
        for (CellInfo *cur = head; cur != nullptr && !seen.count(cur->name);) {
            ordered.push_back(cur);
            seen.insert(cur->name);
            NetInfo *co = cur->getPort(ctx->id("COUT"));
            cur = (co && cin_reader.count(co->name)) ? cin_reader.at(co->name) : nullptr;
        }
        int tx = 14, ty = 8;
        if (const char *e = std::getenv("AGRV2K_CARRY_TILE")) {
            std::string s(e);
            auto comma = s.find(',');
            if (comma != std::string::npos) {
                tx = std::atoi(s.substr(0, comma).c_str());
                ty = std::atoi(s.substr(comma + 1).c_str());
            }
        }
        int bound = 0;
        for (size_t i = 0; i < ordered.size() && i < 16; i++) {
            std::string bn = "X" + std::to_string(tx) + "Y" + std::to_string(ty) + "_SLICE" + std::to_string(i);
            BelId b = ctx->getBelByName(IdStringList(ctx->id(bn)));
            if (b != BelId()) {
                ctx->bindBel(b, ordered[i], STRENGTH_LOCKED);
                ++bound;
            }
        }
        log_info("  carry chain: bound %d/%d cells to (%d,%d) SLICE0..%d (contiguous)\n", bound,
                 int(ordered.size()), tx, ty, bound - 1);
    }
}

// first 'h' followed by digits in a cell name -> that number (mcu_h3 -> 3); -1 if none. Mirrors the old
// pin_ahb_condplace regex h(\d+) so AHB bit k == the design's mcu_h<k> == hrdata[k] (no read-bit scramble).
static int parse_hk(const std::string &s)
{
    for (size_t i = 0; i + 1 < s.size(); i++)
        if (s[i] == 'h' && std::isdigit((unsigned char)s[i + 1]))
            return std::atoi(s.c_str() + i + 1);
    return -1;
}

// ---- pack: bind MCU_DOUT exit cells to their fixed hrdata bels BY NAME. The fabric->MCU readout lanes are
// fixed bels (X10Y5_MCU_DOUT10..19); a cell named mcu_h<k> reads out on hrdata[k] (0x60000000 bit k), so we
// must bind by name -- nextpnr's arbitrary placement would scramble the read bits. Lanes 10-15 are the
// proven distinct-feeder lanes (see ag32-counter-freeze-solved). MCU_DIN entry could be handled the same way.
static void pack_mcu_edge(Context *ctx)
{
    long n = 0;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != ctx->id("MCU_DOUT"))
            continue;
        int k = parse_hk(ci->name.str(ctx));
        if (k < 0)
            continue;
        std::string bn = "X10Y5_MCU_DOUT" + std::to_string(10 + k);
        BelId b = ctx->getBelByName(IdStringList(ctx->id(bn)));
        if (b != BelId() && ctx->checkBelAvail(b)) {
            ctx->bindBel(b, ci, STRENGTH_LOCKED);
            ++n;
        }
    }
    if (n)
        log_info("agrv2k: bound %ld MCU_DOUT exit cell(s) to hrdata lanes by name\n", n);
}

// ---- pack: crude constructive DENSE placer (AGRV2K_DENSE_TILE="x,y"). Binds every still-unplaced data
// GENERIC_SLICE to an EVEN slot (0,2,..,14) of the tile, spilling up in y. Every intra-tile link is then
// even->even = guaranteed-conducting (the even-slot invariant), so a dense sequential design (shift/LFSR/
// FSM -- SERV's actual need) packs tight AND conducts, without the wide-carry own-Q conflict. Skips
// constants + the carry VCC (let the placer float them). Stepping-stone to a general conduction-aware placer.
static void pack_dense(Context *ctx)
{
    const char *e = std::getenv("AGRV2K_DENSE_TILE");
    if (e == nullptr)
        return;
    int tx = 14, ty = 8;
    {
        std::string s(e);
        auto c = s.find(',');
        if (c != std::string::npos) {
            tx = std::atoi(s.substr(0, c).c_str());
            ty = std::atoi(s.substr(c + 1).c_str());
        }
    }
    int slot = 0, y = ty, bound = 0;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != ctx->id("GENERIC_SLICE") || ci->bel != BelId())
            continue; // only unplaced slices (carry/MCU already bound)
        const std::string nm = ci->name.str(ctx);
        if (nm.find("PACKER") != std::string::npos || nm.find("CARRY_VCC") != std::string::npos)
            continue; // let constants float
        int z = slot * 2;
        if (z > 14) { y++; slot = 0; z = 0; }
        std::string bn = "X" + std::to_string(tx) + "Y" + std::to_string(y) + "_SLICE" + std::to_string(z);
        BelId b = ctx->getBelByName(IdStringList(ctx->id(bn)));
        if (b != BelId() && ctx->checkBelAvail(b)) {
            ctx->bindBel(b, ci, STRENGTH_LOCKED);
            ++bound;
            ++slot;
        }
    }
    if (bound)
        log_info("agrv2k: DENSE-placed %d data slices on even slots from (%d,%d)\n", bound, tx, ty);
}

// ---- pack: CONDUCTION-AWARE placer (AGRV2K_CONDPLACE). Backtracking-embed the post-pack cell graph onto
// the silicon-conducting tile graph so EVERY driver->consumer edge is same-tile or a proven inter-tile
// RMUX->RMUX hop (tile_adj from master_conduction). This is the OTHER half of the solve: with the
// conduction-GATED devdb the router has no dead pip to fall back on, so a conducting PATH must exist by
// construction -- which naive even-slot placement (pack_dense) doesn't guarantee. Ports the proven
// engine_work/pin_ahb_condplace.py embedder (1 cell/tile default; the approach ahb_count2 computes with).
// Exit-driver FFs (feeding a bound MCU_DOUT) are anchored on tiles that conductingly reach EXIT_TILE(14,12).
static void pack_condplace(Context *ctx, const std::unordered_map<int, std::unordered_set<int>> &tile_adj)
{
    if (std::getenv("AGRV2K_CONDPLACE") == nullptr || tile_adj.empty())
        return;
    auto tkey = [](int x, int y) { return (x << 8) | (y & 0xff); };
    const int EXIT = tkey(14, 12);
    auto conduct = [&](int a, int b) -> bool {
        if (a == b)
            return true;
        auto it = tile_adj.find(a);
        if (it != tile_adj.end() && it->second.count(b))
            return true;
        auto jt = tile_adj.find(b);
        return jt != tile_adj.end() && jt->second.count(a);
    };
    auto reaches_exit = [&](int t) { return conduct(t, EXIT); };
    std::set<int> tileset;
    for (auto &kv : tile_adj) {
        tileset.insert(kv.first);
        for (int t : kv.second)
            tileset.insert(t);
    }
    std::vector<int> cand(tileset.begin(), tileset.end()); // sorted (from std::set)

    std::vector<CellInfo *> cells;
    for (auto &c : ctx->cells) {
        CellInfo *ci = c.second.get();
        if (ci->type != ctx->id("GENERIC_SLICE") || ci->bel != BelId())
            continue;
        const std::string nm = ci->name.str(ctx);
        if (nm.find("PACKER") != std::string::npos || nm.find("CARRY_VCC") != std::string::npos)
            continue;
        cells.push_back(ci);
    }
    std::set<CellInfo *> cellset(cells.begin(), cells.end());
    std::unordered_map<CellInfo *, std::set<CellInfo *>> deps, indeps;
    std::set<CellInfo *> exitdrv;
    for (auto ci : cells) {
        NetInfo *o = ci->getPort(ctx->id("Q"));
        if (o == nullptr)
            o = ci->getPort(ctx->id("F"));
        if (o == nullptr)
            continue;
        for (auto &u : o->users) {
            if (u.cell == nullptr)
                continue;
            if (u.cell->type == ctx->id("MCU_DOUT"))
                exitdrv.insert(ci);
            if (cellset.count(u.cell) && u.cell != ci) {
                deps[ci].insert(u.cell);
                indeps[u.cell].insert(ci);
            }
        }
    }
    // most-constrained first: exit-drivers, then high fan-in/out
    std::stable_sort(cells.begin(), cells.end(), [&](CellInfo *a, CellInfo *b) {
        int ea = exitdrv.count(a) ? 0 : 1, eb = exitdrv.count(b) ? 0 : 1;
        if (ea != eb)
            return ea < eb;
        return (deps[a].size() + indeps[a].size()) > (deps[b].size() + indeps[b].size());
    });
    int CAP = 1;
    if (const char *e = std::getenv("AGRV2K_CONDPLACE_CAP"))
        CAP = std::max(1, std::atoi(e));

    std::unordered_map<CellInfo *, int> assign;
    std::unordered_map<int, int> occ;
    auto feasible = [&](CellInfo *ci, int t) -> bool {
        if (occ[t] >= CAP)
            return false;
        if (exitdrv.count(ci) && !reaches_exit(t))
            return false;
        for (auto d : deps[ci])
            if (assign.count(d) && !conduct(t, assign[d]))
                return false;
        for (auto dr : indeps[ci])
            if (assign.count(dr) && !conduct(assign[dr], t))
                return false;
        return true;
    };
    // GREEDY placement (NOT exhaustive backtracking, which is exponential and hangs past ~a dozen cells).
    // Place each cell (most-constrained first) on the first feasible tile, PREFERRING tiles adjacent to its
    // already-placed neighbours (keeps a net's endpoints close -> conducting + low fanout spread). Linear.
    int failed = 0;
    for (auto ci : cells) {
        // candidate order: placed-neighbour tiles + their conducting neighbours first, then all tiles
        std::vector<int> pref;
        std::set<int> seen;
        auto addpref = [&](int t) { if (t >= 0 && !seen.count(t)) { seen.insert(t); pref.push_back(t); } };
        for (auto d : deps[ci])
            if (assign.count(d)) { addpref(assign[d]); auto it = tile_adj.find(assign[d]); if (it != tile_adj.end()) for (int n : it->second) addpref(n); }
        for (auto dr : indeps[ci])
            if (assign.count(dr)) { addpref(assign[dr]); auto it = tile_adj.find(assign[dr]); if (it != tile_adj.end()) for (int n : it->second) addpref(n); }
        for (int t : cand)
            addpref(t);
        int best = -1;
        for (int t : pref)
            if (feasible(ci, t)) { best = t; break; }
        if (best < 0) { ++failed; continue; }
        assign[ci] = best;
        occ[best]++;
    }
    if (failed) {
        log_error("agrv2k: CONDPLACE greedy failed to place %d/%d cells (raise AGRV2K_CONDPLACE_CAP or "
                  "densify the conducting graph)\n", failed, int(cells.size()));
        return;
    }
    std::unordered_map<int, int> slot;
    for (auto ci : cells) {
        int t = assign[ci], z = slot[t] * 2; // even slots
        slot[t]++;
        std::string bn = "X" + std::to_string(t >> 8) + "Y" + std::to_string(t & 0xff) + "_SLICE" +
                         std::to_string(z);
        BelId b = ctx->getBelByName(IdStringList(ctx->id(bn)));
        if (b != BelId())
            ctx->bindBel(b, ci, STRENGTH_LOCKED);
    }
    log_info("agrv2k: CONDPLACE embedded %d cells on conducting tiles (cap %d, %d exit-drivers)\n",
             int(cells.size()), CAP, int(exitdrv.size()));
}

struct AgrvImpl : ViaductAPI
{
    std::string chipdb;
    ViaductHelpers h;
    dict<IdString, WireId> wire_by_name;
    dict<IdString, BelId> bel_by_name;

    // Conducting inter-tile tile-graph (RMUX->RMUX, silicon-verified), for isBelLocationValid's
    // conducting-pair check. Loaded from master_conduction.csv in the chipdb dir (if present).
    std::unordered_map<int, std::unordered_set<int>> tile_adj;
    static int tkey(int x, int y) { return (x << 8) | (y & 0xff); }
    bool tiles_conduct(int ax, int ay, int bx, int by) const
    {
        if (ax == bx && ay == by)
            return true; // same tile: intra-tile crossbar (even-slot invariant guarantees the pair conducts)
        int ka = tkey(ax, ay), kb = tkey(bx, by);
        auto it = tile_adj.find(ka);
        if (it != tile_adj.end() && it->second.count(kb))
            return true;
        auto jt = tile_adj.find(kb);
        if (jt != tile_adj.end() && jt->second.count(ka))
            return true;
        return false;
    }

    explicit AgrvImpl(const dict<std::string, std::string> &args)
    {
        for (auto &a : args) {
            if (a.first == "chipdb")
                chipdb = a.second;
            else
                log_error("agrv2k: unrecognised option '%s' (expected chipdb=<dir>)\n", a.first.c_str());
        }
        if (chipdb.empty())
            log_error("agrv2k: missing required option -o chipdb=<dir> (the dev_*.csv directory)\n");
    }

    std::string path(const std::string &f) const
    {
        if (!chipdb.empty() && (chipdb.back() == '/' || chipdb.back() == '\\'))
            return chipdb + f;
        return chipdb + "/" + f;
    }

    void init(Context *ctx) override
    {
        ViaductAPI::init(ctx);
        h.init(ctx);
        load_db();
        load_conduction();
    }

    // Conducting inter-tile tile-graph for the placement-legality check. master_conduction.csv
    // (columns src_res,src_x,src_y,dst_res,dst_x,dst_y,source) is copied into the chipdb dir by the
    // emit step; if absent the conducting-pair check is disabled (permissive).
    void load_conduction()
    {
        std::ifstream f(path("master_conduction.csv"));
        if (!f) {
            log_info("agrv2k: no master_conduction.csv in chipdb dir — conducting-pair check DISABLED\n");
            return;
        }
        std::string line;
        std::getline(f, line); // header
        long n = 0;
        while (std::getline(f, line)) {
            if (!line.empty() && line.back() == '\r')
                line.pop_back();
            std::vector<std::string> fs;
            std::string cur;
            std::istringstream ss(line);
            while (std::getline(ss, cur, ','))
                fs.push_back(cur);
            if (fs.size() < 6)
                continue;
            if (fs[0].rfind("RMUX", 0) != 0 || fs[3].rfind("RMUX", 0) != 0)
                continue; // only inter-tile RMUX->RMUX mesh hops define tile adjacency
            int sx = to_int(fs[1]), sy = to_int(fs[2]), dx = to_int(fs[4]), dy = to_int(fs[5]);
            if (sx == dx && sy == dy)
                continue;
            tile_adj[tkey(sx, sy)].insert(tkey(dx, dy));
            ++n;
        }
        log_info("agrv2k: loaded %ld conducting inter-tile RMUX->RMUX edges (master_conduction.csv)\n", n);
    }

    void load_db()
    {
        int lutk = 4;
        {
            Csv c(path("dev_meta.csv"));
            c.next(); // header
            while (c.next())
                if (c.at(0) == "lutk")
                    lutk = to_int(c.at(1), 4);
        }
        ctx->setLutK(lutk);

        long nw = 0, nb = 0, npin = 0, np = 0;
        {
            Csv c(path("dev_wires.csv"));
            c.next();
            while (c.next()) {
                if (c.at(0).empty())
                    continue;
                IdString id = ctx->id(c.at(0));
                wire_by_name[id] =
                        ctx->addWire(IdStringList(id), ctx->id(c.at(1)), to_int(c.at(2)), to_int(c.at(3)));
                ++nw;
            }
        }
        {
            Csv c(path("dev_bels.csv"));
            c.next();
            while (c.next()) {
                if (c.at(0).empty())
                    continue;
                IdString id = ctx->id(c.at(0));
                Loc loc(to_int(c.at(2)), to_int(c.at(3)), to_int(c.at(4)));
                bel_by_name[id] = ctx->addBel(IdStringList(id), ctx->id(c.at(1)), loc, false, false);
                ++nb;
            }
        }
        {
            Csv c(path("dev_belpins.csv"));
            c.next();
            while (c.next()) {
                if (c.at(0).empty())
                    continue;
                auto bi = bel_by_name.find(ctx->id(c.at(0)));
                if (bi == bel_by_name.end())
                    log_error("agrv2k: belpin references unknown bel '%s'\n", c.at(0).c_str());
                auto wi = wire_by_name.find(ctx->id(c.at(2)));
                if (wi == wire_by_name.end())
                    log_error("agrv2k: belpin '%s.%s' -> unknown wire '%s'\n", c.at(0).c_str(),
                              c.at(1).c_str(), c.at(2).c_str());
                IdString pin = ctx->id(c.at(1));
                const std::string &dir = c.at(3);
                if (dir == "out")
                    ctx->addBelOutput(bi->second, pin, wi->second);
                else if (dir == "inout")
                    ctx->addBelInout(bi->second, pin, wi->second);
                else
                    ctx->addBelInput(bi->second, pin, wi->second);
                ++npin;
            }
        }
        {
            Csv c(path("dev_pips.csv"));
            c.next();
            while (c.next()) {
                if (c.at(0).empty())
                    continue;
                auto si = wire_by_name.find(ctx->id(c.at(2)));
                auto di = wire_by_name.find(ctx->id(c.at(3)));
                if (si == wire_by_name.end() || di == wire_by_name.end())
                    log_error("agrv2k: pip '%s' references unknown endpoint\n", c.at(0).c_str());
                Loc loc(to_int(c.at(5)), to_int(c.at(6)), to_int(c.at(7)));
                ctx->addPip(IdStringList(ctx->id(c.at(0))), ctx->id(c.at(1)), si->second, di->second,
                            ctx->getDelayFromNS(to_double(c.at(4), 0.05)), loc);
                ++np;
                // Build the placer's conducting tile-graph FROM THE DEVDB PIPS themselves, so pack_condplace
                // agrees EXACTLY with what the router can route (the devdb is conduction-gated). Any
                // inter-tile RMUX->RMUX pip = a conducting tile edge. (Sparser master_conduction alone made
                // the placer reject placements the gated router could actually route -> embed failures.)
                if (c.at(2).find("_RMUX") != std::string::npos && c.at(3).find("_RMUX") != std::string::npos) {
                    int sx, sy, dx2, dy2;
                    if (std::sscanf(c.at(2).c_str(), "X%dY%d", &sx, &sy) == 2 &&
                        std::sscanf(c.at(3).c_str(), "X%dY%d", &dx2, &dy2) == 2 && (sx != dx2 || sy != dy2))
                        tile_adj[tkey(sx, sy)].insert(tkey(dx2, dy2));
                }
            }
        }
        log_info("agrv2k: loaded chipdb '%s' — lutk=%d wires=%ld bels=%ld belpins=%ld pips=%ld\n",
                 chipdb.c_str(), lutk, nw, nb, npin, np);
    }

    // ---- pack: our slices arrive PRE-FUSED (GENERIC_SLICE carries INIT + FF_USED), so there is no
    //      LUT+FF pairing to do (unlike the example uarch). Minimal for now; bring-up against a real
    //      synth JSON will tell us whether constant/IOB handling is needed here. ----
    void pack() override
    {
        // Replicate the generic arch's built-in pack (pack.cc), which the Viaduct path bypasses. Order
        // matters: constants first (may create GENERIC_SLICE), then IO trimming (GENERIC_IOB already in
        // the synth netlist via iopadmap -> the $nextpnr_[io]buf are trimmed), then LUT(+DFF) fusing and
        // finally standalone FFs. Output: GENERIC_SLICE cells (INIT + FF_USED) + GENERIC_IOB, 1:1 with
        // our bels, and byte-compatible with bitgen_seq.py.
        pack_constants(ctx);
        pack_io(ctx);
        pack_carries(ctx);   // dedicated HW carry: fuse AG32_FA(+DFF) -> GENERIC_SLICE keeping CIN/COUT
        pack_lut_lutffs(ctx);
        pack_nonlut_ffs(ctx);
        pack_mcu_edge(ctx);  // bind MCU_DOUT exit cells AFTER fusion (binding before corrupts a readout net
                             // shared with a fusing LUT -> stale port). Names survive; bels still free.
        pack_condplace(ctx, tile_adj); // AGRV2K_CONDPLACE: embed cells on conducting tile-pairs (the placer half)
        pack_dense(ctx);     // AGRV2K_DENSE_TILE: bind remaining data slices to even slots (dense, conducting)
    }

    // parse "X14Y8_OMUX02" -> tile "X14Y8", res "OMUX", idx 2
    static bool parse_wire(const std::string &w, std::string &tile, std::string &res, int &idx)
    {
        auto u = w.rfind('_');
        if (u == std::string::npos)
            return false;
        tile = w.substr(0, u);
        std::string r = w.substr(u + 1);
        size_t i = 0;
        while (i < r.size() && !std::isdigit((unsigned char)r[i]))
            i++;
        if (i == r.size())
            return false;
        res = r.substr(0, i);
        idx = std::atoi(r.c_str() + i);
        return true;
    }

    // ---- routing gate (own-Q conduction side-quest). AGRV2K_NO_FBBRIDGE rejects the self-feedback bridge
    // OMUX[3z+2]->OMUX[3z+1] (same slice), whose downstream OMUX[3z+1]->IMUX[4z+1] crossbar hop is a DEAD
    // (non-vendor-used) feedback pair on silicon (the counter-freeze). Rejecting it forces a registered
    // cell's own-Q feedback onto the CONDUCTING RMUX mesh (OMUX->RMUX->..->IMUX, out-and-back) instead --
    // the fix a dense hardware-carry cell needs, since it can't use the Qin internal path (pinC=Cin).
    bool checkPipAvail(PipId pip) const override
    {
        if (std::getenv("AGRV2K_NO_FBBRIDGE") == nullptr)
            return true;
        std::string s = ctx->getWireName(ctx->getPipSrcWire(pip)).str(ctx);
        std::string d = ctx->getWireName(ctx->getPipDstWire(pip)).str(ctx);
        std::string st, sr, dt, dr;
        int si, di;
        if (parse_wire(s, st, sr, si) && parse_wire(d, dt, dr, di) && st == dt && sr == "OMUX" &&
            dr == "OMUX" && (si % 3) == 2 && (di % 3) == 1 && (si / 3) == (di / 3))
            return false; // dead self-feedback bridge -> force feedback via the mesh
        return true;
    }

    // ---- legality: STAGE-GATED.
    //   Stage 0/1 = permissive (prove build + graph load + end-to-end pipeline on a trivial design).
    //   Stage 2   = even-slot + conducting-pair (port engine_work/pin_densepack.py).
    //   Stage 3   = exit-lane reachability (port engine_work/pin_ahb_condplace.py) — the pivotal test.
    bool isBelLocationValid(BelId bel, bool explain_invalid) const override
    {
        (void)explain_invalid;
        CellInfo *ci = ctx->getBoundBelCell(bel);
        if (ci == nullptr || ci->type != ctx->id("GENERIC_SLICE"))
            return true; // only fabric slices are conduction-constrained; IO/MCU/BRAM bels are fixed

        Loc loc = ctx->getBelLocation(bel);
        // CARRY-CHAIN EXEMPTION: a dedicated hardware-carry slice (has CIN/COUT ports) chains to its
        // neighbour over the internal COUT<z>->CIN<z+1> pip, NOT the OMUX->IMUX crossbar, and the vendor
        // places carry chains on CONSECUTIVE slices (LCCELL N always even => N=2*slice => z,z+1,z+2...;
        // dense_oracle confirms). So carry slices are exempt from the even-slot rule below; the carry net
        // (routable only between adjacent bels) forces them onto a contiguous run.
        bool is_carry = ci->ports.count(ctx->id("CIN")) || ci->ports.count(ctx->id("COUT"));
        // EVEN-SLOT INVARIANT: the intra-tile OMUX->IMUX crossbar's only dead (zs,zd) pairs all involve
        // an ODD endpoint (chipdb/xbar_conduction.csv), so restricting NON-carry slices to even z
        // {0,2,..,14} makes every intra-tile crossbar link even->even => guaranteed to conduct.
        if (!is_carry && (loc.z & 1) != 0)
            return false;

        // CONDUCTING-PAIR: every already-placed DATA neighbour must sit on a tile that conducts to/from
        // this one (same tile via crossbar, or one proven inter-tile RMUX hop). Skip the clock (global
        // tree, not the mesh), constants, and high-fanout nets.
        // NOTE: as a HARD reject this is too tight for nextpnr's SA placer to satisfy on the sparse
        // conducting tile-graph (large chains fail to find a legal placement). Gated behind
        // AGRV2K_CONDPAIR=1 while we evaluate router-side conduction gating + clustering as the
        // convergent path; even-slot alone (above) is the always-on intra-tile guarantee.
        if (tile_adj.empty() || std::getenv("AGRV2K_CONDPAIR") == nullptr)
            return true;
        auto reaches = [&](CellInfo *oc) -> bool {
            if (oc == nullptr || oc == ci || oc->type != ctx->id("GENERIC_SLICE"))
                return true;
            if (oc->bel == BelId())
                return true; // neighbour not placed yet
            Loc ol = ctx->getBelLocation(oc->bel);
            return tiles_conduct(loc.x, loc.y, ol.x, ol.y);
        };
        for (auto &pe : ci->ports) {
            if (pe.first == ctx->id("CLK"))
                continue; // clock rides the global tree, not the RMUX mesh
            NetInfo *net = pe.second.net;
            if (net == nullptr)
                continue;
            if (net->users.entries() > 24)
                continue; // global/high-fanout (reset, enable, const); not a point-to-point data hop
            if (net->driver.cell != nullptr && !reaches(net->driver.cell))
                return false;
            for (auto &u : net->users)
                if (!reaches(u.cell))
                    return false;
        }
        return true;
    }
};

struct AgrvArch : ViaductArch
{
    AgrvArch() : ViaductArch("agrv2k") {}
    std::unique_ptr<ViaductAPI> create(const dict<std::string, std::string> &args) override
    {
        return std::make_unique<AgrvImpl>(args);
    }
} agrvArch;

} // namespace

NEXTPNR_NAMESPACE_END
