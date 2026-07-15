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

// ---- First conservative slice timing model. ----
// Provenance: decoded vendor library
//   AG32-Docs/tools/archdec/rodinia_p1000lp0_alta_lib.ar.txt
//   SHA256 8974d47eb279091a60b2ab2ed9b532c3577b806a6a7bcbbb135bdabb4945e815
// Each number below is the maximum of the four VALUE: WORST entries for the corresponding alta_slice
// arc.  Setup values are also maximised across every applicable ClkMux/BypassEn configuration.  The
// vendor data-input HOLD values are all negative; using a zero minimum-delay requirement is a
// conservative clamp until min-delay routing and silicon hold characterisation exist.  These are cell
// delays only: routing, clock skew, IO, BRAM, PLL, PVT/speed-grade selection and
// measurement margin are deliberately not claimed by this first model.
static constexpr double SLICE_LUT_TO_F_NS[4] = {0.608, 0.565, 0.474, 0.149}; // A/B/C/D -> LutOut
static constexpr double SLICE_SETUP_NS[4] = {1.040, 0.998, 0.904, 0.582};    // A/B/C/D -> rising Clk
static constexpr double SLICE_HOLD_NS = 0.000;                                // clamp negative vendor data
static constexpr double SLICE_CLK_TO_Q_NS = 0.312;
static constexpr double SLICE_CIN_TO_F_NS = 0.631;
static constexpr double SLICE_CARRY_TO_COUT_NS[3] = {0.635, 0.551, 0.153}; // A/B/Cin -> Cout
static constexpr double SLICE_CIN_SETUP_NS = 1.063;

static void add_slice_timing(Context *ctx)
{
    const IdString slice_type = ctx->id("GENERIC_SLICE");
    const IdString ff_used = ctx->id("FF_USED");
    const IdString clk = ctx->id("CLK");
    const IdString f = ctx->id("F");
    const IdString q = ctx->id("Q");
    const IdString cin = ctx->id("CIN");
    const IdString cout = ctx->id("COUT");
    long slices = 0, registered = 0, carries = 0;

    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != slice_type)
            continue;
        ++slices;

        // The four generic inputs map directly to alta_slice A/B/C/D.
        for (int i = 0; i < 4; ++i) {
            IdString input = ctx->id("I[" + std::to_string(i) + "]");
            ctx->addCellTimingDelay(ci->name, input, f, ctx->getDelayFromNS(SLICE_LUT_TO_F_NS[i]));
        }

        const bool is_carry = ci->ports.count(cout) != 0;
        if (is_carry) {
            ++carries;
            // In carry mode I[0]/I[1]/CIN are alta_slice A/B/Cin. I[2] is bypassed and I[3] selects
            // the sum half of the LUT mask, so neither is a physical dependency of Cout.
            ctx->addCellTimingDelay(ci->name, ctx->id("I[0]"), cout,
                                    ctx->getDelayFromNS(SLICE_CARRY_TO_COUT_NS[0]));
            ctx->addCellTimingDelay(ci->name, ctx->id("I[1]"), cout,
                                    ctx->getDelayFromNS(SLICE_CARRY_TO_COUT_NS[1]));
            ctx->addCellTimingDelay(ci->name, cin, cout,
                                    ctx->getDelayFromNS(SLICE_CARRY_TO_COUT_NS[2]));
            ctx->addCellTimingDelay(ci->name, cin, f, ctx->getDelayFromNS(SLICE_CIN_TO_F_NS));
        }

        if (int_or_default(ci->params, ff_used, 0) == 0)
            continue;
        ++registered;
        ctx->addCellTimingClock(ci->name, clk);
        for (int i = 0; i < 4; ++i) {
            IdString input = ctx->id("I[" + std::to_string(i) + "]");
            ctx->addCellTimingSetupHold(ci->name, input, clk, ctx->getDelayFromNS(SLICE_SETUP_NS[i]),
                                        ctx->getDelayFromNS(SLICE_HOLD_NS));
        }
        if (is_carry)
            ctx->addCellTimingSetupHold(ci->name, cin, clk, ctx->getDelayFromNS(SLICE_CIN_SETUP_NS),
                                        ctx->getDelayFromNS(SLICE_HOLD_NS));
        ctx->addCellTimingClockToOut(ci->name, q, clk, ctx->getDelayFromNS(SLICE_CLK_TO_Q_NS));
    }
    log_info("agrv2k: registered conservative cell timing for %ld slices (%ld FF, %ld carry)\n", slices,
             registered, carries);
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

    // The physical chain has no defined external Cin at slice 0.  The vendor
    // therefore places a combinational seed slice ahead of every arithmetic
    // bit and drives the first real Cin from that slice's Cout.  Leaving the
    // head Cin disconnected configures cleanly, but silicon only advances the
    // first bit. Find every AG32_FA chain head before cells are rewritten,
    // then insert one explicit seed per independent chain below.
    pool<IdString> fa_cout_nets;
    std::vector<CellInfo *> fa_heads;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != fa_type)
            continue;
        NetInfo *co = ci->getPort(ctx->id("COUT"));
        if (co != nullptr)
            fa_cout_nets.insert(co->name);
    }
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != fa_type)
            continue;
        NetInfo *cin_net = ci->getPort(ctx->id("CIN"));
        if (cin_net == nullptr || !fa_cout_nets.count(cin_net->name))
            fa_heads.push_back(ci);
    }
    if (fa_heads.empty())
        log_error("agrv2k: dedicated carry contains no chain head (cycle or malformed netlist)\n");
    std::sort(fa_heads.begin(), fa_heads.end(), [&](CellInfo *a, CellInfo *b) {
        return a->name.str(ctx) < b->name.str(ctx);
    });

    auto const_of = [&](NetInfo *n) -> int { // -1 = routed signal; 0/1 = folded constant
        if (n == nullptr)
            return 0;
        const std::string nm = n->name.str(ctx);
        if (nm.find("PACKER_GND") != std::string::npos)
            return 0;
        if (nm.find("PACKER_VCC") != std::string::npos || nm.find("CARRY_VCC") != std::string::npos)
            return 1;
        return -1;
    };
    struct CarrySeed {
        CellInfo *head;
        int input_const;
        std::unique_ptr<CellInfo> cell;
        std::unique_ptr<NetInfo> net;
    };
    std::vector<CarrySeed> seeds;
    std::unordered_map<CellInfo *, size_t> head_seed;
    for (size_t index = 0; index < fa_heads.size(); ++index) {
        CellInfo *head = fa_heads[index];
        const int input_const = const_of(head->getPort(ctx->id("CIN")));
        // Keep the original names for the single-chain case so its routed
        // evidence remains byte-for-byte reproducible.
        const std::string suffix = fa_heads.size() == 1 ? "" : "_" + std::to_string(index);
        auto seed = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), "$CARRY_SEED" + suffix);
        seed->addOutput(ctx->id("COUT"));
        // Cout uses mask[7:0]. A constant seed directly emits 0/1; a dynamic
        // chain input is buffered through physical input A (0xAA => Cout=A).
        const int seed_mask = input_const == 0 ? 0x0000 : (input_const == 1 ? 0x00ff : 0x00aa);
        seed->params[ctx->id("INIT")] = Property(seed_mask, 1 << ctx->args.K);
        seed->params[ctx->id("FF_USED")] = 0;
        if (input_const < 0)
            seed->addInput(ctx->id("I[0]"));
        auto seed_net = std::make_unique<NetInfo>(ctx->id("$CARRY_SEED_NET" + suffix));
        seed->connectPort(ctx->id("COUT"), seed_net.get());
        head_seed[head] = seeds.size();
        seeds.push_back({head, input_const, std::move(seed), std::move(seed_net)});
    }

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
        // The head always receives the explicit seed Cout.  For a dynamic CI,
        // move that original signal to the seed's A input; for a constant CI,
        // its value is already folded into the seed mask.  Interior cells keep
        // their normal dedicated carry nets.
        auto hs = head_seed.find(ci);
        if (hs != head_seed.end()) {
            CarrySeed &seed = seeds.at(hs->second);
            if (seed.input_const < 0)
                ci->movePortTo(ctx->id("CIN"), seed.cell.get(), ctx->id("I[0]"));
            else
                ci->disconnectPort(ctx->id("CIN"));
            lc->connectPort(ctx->id("CIN"), seed.net.get());
        } else if (const_of(ci->getPort(ctx->id("CIN"))) < 0) {
            ci->movePortTo(ctx->id("CIN"), lc.get(), ctx->id("CIN"));
        } else {
            ci->disconnectPort(ctx->id("CIN"));
        }
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
    for (auto &seed : seeds) {
        ctx->cells[seed.cell->name] = std::move(seed.cell);
        ctx->nets[seed.net->name] = std::move(seed.net);
    }
    ctx->cells[vcc_cell->name] = std::move(vcc_cell);
    ctx->nets[vcc_net_uptr->name] = std::move(vcc_net_uptr);
    for (auto pc : packed_cells)
        ctx->cells.erase(pc);
    for (auto &nc : new_cells)
        ctx->cells[nc->name] = std::move(nc);
    log_info("  fused %ld AG32_FA carry slices (%ld registered) + %ld seed(s) + shared VCC\n",
             n_fa, n_ffused, long(seeds.size()));

    // ---- constructive placement: keep each carry chain CONTIGUOUS in one tile.  Only the
    // intra-tile COUT<z> -> CIN<z+1> continuation at (15,1) is silicon-qualified in the open flow.
    // The vendor emits an apparent COUT15 -> tile-below CIN0 continuation, but an isolated open image
    // did not compute at that placement.  Fail safely above one tile instead of routing a wrong image.
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
        std::vector<CellInfo *> heads;
        for (auto c : carry) {
            NetInfo *cn = c->getPort(ctx->id("CIN"));
            if (cn == nullptr || !cout_nets.count(cn->name))
                heads.push_back(c);
        }
        std::sort(heads.begin(), heads.end(), [&](CellInfo *a, CellInfo *b) {
            return a->name.str(ctx) < b->name.str(ctx);
        });
        std::vector<std::vector<CellInfo *>> chains;
        pool<IdString> seen;
        size_t total = 0;
        for (CellInfo *head : heads) {
            std::vector<CellInfo *> chain;
            for (CellInfo *cur = head; cur != nullptr && !seen.count(cur->name);) {
                chain.push_back(cur);
                seen.insert(cur->name);
                NetInfo *co = cur->getPort(ctx->id("COUT"));
                cur = (co && cin_reader.count(co->name)) ? cin_reader.at(co->name) : nullptr;
            }
            if (!chain.empty()) {
                total += chain.size();
                chains.push_back(std::move(chain));
            }
        }
        if (seen.size() != carry.size())
            log_error("agrv2k: malformed or branched carry graph: traced %ld/%ld cells\n",
                      long(seen.size()), long(carry.size()));
        // (15,1) slots 0..8 are silicon-qualified for one eight-stage chain
        // (plus its seed), and two independent three-stage chains have also
        // passed in slots 0..7. Other tiles, starting slots, and larger total
        // footprints must not be emitted as working images.
        int tx = 15;
        int ty = 1;
        int start_slot = 0;
        if (total + size_t(start_slot) > 9)
            log_error("agrv2k: dedicated carry requires %ld slices from slot %d, but only nine "
                      "same-tile slots total (including one seed per chain) are silicon-qualified\n",
                      long(total), start_slot);
        int bound = 0, slot = start_slot;
        for (auto &chain : chains) {
            const int first = slot;
            for (CellInfo *ci : chain) {
                std::string bn = "X" + std::to_string(tx) + "Y" + std::to_string(ty) +
                                 "_SLICE" + std::to_string(slot);
                BelId b = ctx->getBelByName(IdStringList(ctx->id(bn)));
                if (b == BelId())
                    log_error("agrv2k: carry placement BEL '%s' is unavailable\n", bn.c_str());
                ctx->bindBel(b, ci, STRENGTH_LOCKED);
                ++bound;
                ++slot;
            }
            log_info("  carry chain: bound %ld cells at (%d,%d) SLICE%d..%d (contiguous)\n",
                     long(chain.size()), tx, ty, first, slot - 1);
        }
        log_info("  carry placement: %ld chain(s), %d/%ld cells bound from start tile (%d,%d)\n",
                 long(chains.size()), bound, long(total), tx, ty);
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

// ---- pack: bind MCU edge cells to their fixed bus lanes BY NAME. The fabric->MCU readout lanes are
// fixed bels (X10Y5_MCU_DOUT10..19); a cell named mcu_h<k> reads out on hrdata[k] (0x60000000 bit k), so we
// must bind by name -- nextpnr's arbitrary placement would scramble the read bits.  The three qualified
// MCU_DIN bels are likewise not interchangeable: DIN20=hwdata[0], DIN21=hwrite, DIN22=htrans[1].  Binding
// the conventional instance names used by the public AHB examples prevents a store-data/control scramble.
// Lanes 10-15 are the proven distinct-feeder read lanes (see ag32-counter-freeze-solved).
static void pack_mcu_edge(Context *ctx)
{
    long nout = 0, nin = 0;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        std::string name = ci->name.str(ctx);
        std::string bn;
        if (ci->type == ctx->id("MCU_DOUT")) {
            int k = parse_hk(name);
            if (k < 0)
                continue;
            bn = "X10Y5_MCU_DOUT" + std::to_string(10 + k);
        } else if (ci->type == ctx->id("MCU_DIN")) {
            int lane = -1;
            if (name.find("hwdata0") != std::string::npos)
                lane = 20;
            else if (name.find("hwrite") != std::string::npos)
                lane = 21;
            else if (name.find("htrans1") != std::string::npos)
                lane = 22;
            if (lane < 0)
                continue;
            bn = "X10Y5_MCU_DIN" + std::to_string(lane);
        } else {
            continue;
        }
        BelId b = ctx->getBelByName(IdStringList(ctx->id(bn)));
        if (b != BelId() && ctx->checkBelAvail(b)) {
            ctx->bindBel(b, ci, STRENGTH_LOCKED);
            if (ci->type == ctx->id("MCU_DOUT"))
                ++nout;
            else
                ++nin;
        } else {
            log_error("agrv2k: fixed MCU bus bel '%s' is unavailable for cell '%s'\n",
                      bn.c_str(), name.c_str());
        }
    }
    if (nout)
        log_info("agrv2k: bound %ld MCU_DOUT exit cell(s) to hrdata lanes by name\n", nout);
    if (nin)
        log_info("agrv2k: bound %ld MCU_DIN entry cell(s) to AHB lanes by name\n", nin);
}

// ---- pack: bind the design's CLOCK input pad to the dedicated CLKIN bel. The clock arrives as a
// GENERIC_IOB whose 'O' drives a clock net (a GENERIC_SLICE 'CLK' or an ALTA_BRAM9K 'Clk0'/'Clk1'). Such
// an INPUT iob needs a bel with an 'O' pin (CLKIN); nextpnr's placer, left free, may drop it on an
// output-only OPAD ("bel X..OPAD0 has no pin O" at route time). The counter got CLKIN by luck; a BRAM
// design (heavier clock fanout) did not. Binding it explicitly makes the clock deterministic + correct.
static void pack_clk(Context *ctx)
{
    if (std::getenv("AGRV2K_NO_PACKCLK") != nullptr)
        return; // isolation switch: let the placer choose the clock IOB bel (old, luck-based behaviour)
    // collect clock nets (driven onto CLK / Clk0 / Clk1 sinks)
    std::set<IdString> clk_nets;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        for (const char *pn : {"CLK", "Clk0", "Clk1"}) {
            NetInfo *ni = ci->getPort(ctx->id(pn));
            if (ni != nullptr)
                clk_nets.insert(ni->name);
        }
    }
    if (clk_nets.empty())
        return;
    BelId clkin = ctx->getBelByName(IdStringList(ctx->id("CLKIN")));
    if (clkin == BelId() || !ctx->checkBelAvail(clkin))
        return;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != ctx->id("GENERIC_IOB") || ci->bel != BelId())
            continue;
        NetInfo *o = ci->getPort(ctx->id("O")); // input pad: 'O' drives the fabric net
        if (o == nullptr || !clk_nets.count(o->name))
            continue;
        ctx->bindBel(clkin, ci, STRENGTH_LOCKED);
        log_info("agrv2k: bound clock input '%s' to CLKIN\n", ci->name.c_str(ctx));
        return; // one dedicated clock input
    }
}

// ---- pack: trim a read-only BRAM port's don't-care write inputs. An inferred ROM port still carries
// DataIn[17:0] tied to the constant 0 net; pack_constants then drives all 18 from one $PACKER_GND, and that
// 18-sink net can't fan out to the fixed BRAM bel through the conducting graph ("no route for arc N of
// $PACKER_GND_NET"). Since WeA=0 the write data is a hardware don't-care -- the proven old flow left DataInA
// as undriven dangling nets (never routed). Match that: DISCONNECT DataInA on a read-only BRAM so nextpnr
// doesn't route it. Runs AFTER pack_constants (so WeA is resolved to the GND net for the read-only test).
static void pack_bram_trim(Context *ctx)
{
    IdString gnd_net;
    for (auto &c : ctx->cells)
        if (c.second->name.str(ctx).find("PACKER_GND") != std::string::npos) {
            NetInfo *o = c.second->getPort(ctx->id("F"));
            if (o == nullptr)
                o = c.second->getPort(ctx->id("Q"));
            if (o != nullptr)
                gnd_net = o->name;
        }
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != ctx->id("ALTA_BRAM9K"))
            continue;
        std::vector<IdString> drop;
        for (const char port : {'A', 'B'}) {
            NetInfo *we = ci->getPort(ctx->id(std::string("We") + port));
            bool read_only = (we == nullptr) || (gnd_net != IdString() && we->name == gnd_net);
            if (!read_only)
                continue;
            std::string prefix = std::string("DataIn") + port;
            for (auto &p : ci->ports)
                if (p.first.str(ctx).rfind(prefix, 0) == 0)
                    drop.push_back(p.first);
        }
        for (auto pn : drop)
            ci->disconnectPort(pn);
        if (!drop.empty())
            log_info("agrv2k: read-only BRAM port(s) -> disconnected %d don't-care DataIn pin(s)\n",
                     int(drop.size()));
    }
}

// ---- pack: give the BRAM's constant CONTROL pins (both ports) DEDICATED LOCAL constant
// drivers instead of the shared global GND/VCC net. That global net also drives unused LUT inputs all over
// the design, so it can't be near the fixed BRAM AND near the logic at once -> "no route for arc N of
// $PACKER_GND_NET". The proven old flow drives each BRAM control pin from its OWN GENERIC_SLICE constant
// (placed next to the BRAM). Match that: create one 0/1-INIT GENERIC_SLICE per BRAM control pin and rewire
// the pin to it. These become ordinary bram-adjacent cells that pack_condplace biases onto the approach.
static void pack_bram_localize_const(Context *ctx)
{
    bool hardconst = std::getenv("AGRV2K_BRAM_HARDCONST") != nullptr;
    NetInfo *gnd = nullptr, *vcc = nullptr;
    for (auto &n : ctx->nets) {
        if (n.first == ctx->id("$PACKER_GND_NET"))
            gnd = n.second.get();
        else if (n.first == ctx->id("$PACKER_VCC_NET"))
            vcc = n.second.get();
    }
    if (gnd == nullptr && vcc == nullptr)
        return;
    int idx = 0;
    long n = 0, hard_n = 0, local_n = 0, routed_gnd_n = 0;
    std::vector<std::unique_ptr<CellInfo>> new_cells;
    std::vector<std::unique_ptr<NetInfo>> new_nets;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != ctx->id("ALTA_BRAM9K"))
            continue;
        std::vector<std::pair<IdString, bool>> pins; // (port, wants 1)
        std::vector<IdString> unused_data;
        auto active_width = [&](const char port) {
            IdString key = ctx->id(std::string("PORT") + port + "_WIDTH");
            int dwsel = ci->params.count(key) ? int(ci->params.at(key).as_int64()) : 0;
            return dwsel == 0 ? 18 : (dwsel == 8 ? 9 : (dwsel == 12 ? 4 : (dwsel == 14 ? 2 : 1)));
        };
        int active_a = active_width('A'), active_b = active_width('B');
        auto suffix_bits = [](int width) {
            return width == 18 ? 4 : (width == 9 ? 3 : (width == 4 ? 2 : (width == 2 ? 1 : 0)));
        };
        for (auto &p : ci->ports) {
            if (p.second.type != PORT_IN || p.second.net == nullptr)
                continue;
            int dbit = -1;
            bool padded_a = std::sscanf(p.first.str(ctx).c_str(), "DataInA[%d]", &dbit) == 1 && dbit >= active_a;
            dbit = -1;
            bool padded_b = std::sscanf(p.first.str(ctx).c_str(), "DataInB[%d]", &dbit) == 1 && dbit >= active_b;
            if (padded_a || padded_b) {
                // Narrow BRAM modes physically ignore the padded upper data pins.  Routing sixteen
                // constant-zero DataIn bits for a 512x2 SERV RF consumed the entire approach and left
                // three arcs permanently congested.  Disconnect true hardware don't-cares.
                unused_data.push_back(p.first);
                continue;
            }
            if (p.second.net == gnd)
                pins.push_back({p.first, false});
            else if (p.second.net == vcc)
                pins.push_back({p.first, true});
        }
        for (IdString p : unused_data)
            ci->disconnectPort(p);
        if (!unused_data.empty())
            log_info("agrv2k: narrow BRAM A=x%d B=x%d -> disconnected %d padded DataIn pin(s)\n",
                     active_a, active_b, int(unused_data.size()));
        for (auto &pr : pins) {
            const std::string pin_name = pr.first.str(ctx);
            int addr_a_bit = -1, addr_b_bit = -1;
            bool addr_a = std::sscanf(pin_name.c_str(), "AddressA[%d]", &addr_a_bit) == 1;
            bool addr_b = std::sscanf(pin_name.c_str(), "AddressB[%d]", &addr_b_bit) == 1;
            const bool default_high_suffix = pr.second &&
                    ((addr_a && addr_a_bit < suffix_bits(active_a)) ||
                     (addr_b && addr_b_bit < suffix_bits(active_b)));
            const bool characterized_control =
                    pin_name.rfind("ReA", 0) == 0 || pin_name.rfind("ReB", 0) == 0 ||
                    pin_name.rfind("WeA", 0) == 0 || pin_name.rfind("WeB", 0) == 0 ||
                    pin_name.rfind("ByteEnA", 0) == 0 || pin_name.rfind("ByteEnB", 0) == 0 ||
                    pin_name.rfind("ClkEn0", 0) == 0 || pin_name.rfind("ClkEn1", 0) == 0;
            const bool address_or_data = pin_name.rfind("AddressB[", 0) == 0;
            const bool routed_address_low = hardconst && !pr.second && address_or_data;
            if (hardconst && !routed_address_low &&
                    (!pr.second || characterized_control || default_high_suffix)) {
                // The BRAM control/default blob supplies fixed Re/ByteEn/ClkEn and the unused
                // address/data inputs default low.  The vendor's width adapter appends constant-one
                // address suffixes (x18:4, x9:3, x4:2, x2:1); its routed netlist has no path for those
                // pins because the BRAM input defaults realize the ones internally.  Routing a fabric
                // constant instead both wastes the narrow boundary and can select a dead terminal hop.
                ci->disconnectPort(pr.first);
                ++n; ++hard_n;
                continue;
            }
            std::string cn = "$BRAM_CONST_" + std::to_string(idx++);
            std::unique_ptr<CellInfo> cc = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), cn);
            if (pr.second)
                cc->params[ctx->id("INIT")] = Property(Property::S1).extract(0, 1 << ctx->args.K, Property::S1);
            else
                cc->params[ctx->id("INIT")] = Property(0, 1 << ctx->args.K);
            std::unique_ptr<NetInfo> nn = std::make_unique<NetInfo>(ctx->id(cn + "_NET"));
            nn->driver.cell = cc.get();
            nn->driver.port = ctx->id("F");
            cc->ports.at(ctx->id("F")).net = nn.get();
            ci->disconnectPort(pr.first);          // off the shared global constant net
            ci->connectPort(pr.first, nn.get());   // onto this pin's private local constant
            new_cells.push_back(std::move(cc));
            new_nets.push_back(std::move(nn));
            ++n; ++local_n;
        }
    }
    for (auto &c : new_cells)
        ctx->cells[c->name] = std::move(c);
    for (auto &nn : new_nets)
        ctx->nets[nn->name] = std::move(nn);
    if (hardconst && routed_gnd_n && gnd != nullptr && gnd->driver.cell != nullptr) {
        BelId gb = ctx->getBelByName(IdStringList(ctx->id("X14Y4_SLICE1")));
        if (gb == BelId() || !ctx->checkBelAvail(gb))
            log_error("agrv2k: vendor BRAM GND source bel X14Y4_SLICE1 is unavailable\n");
        gnd->driver.cell->attrs[ctx->id("AGRV2K_BRAM_PINPACKED")] = 1;
        ctx->bindBel(gb, gnd->driver.cell, STRENGTH_LOCKED);
        log_info("agrv2k: bound shared BRAM GND (%ld pin(s)) to X14Y4_SLICE1\n", routed_gnd_n);
    }
    if (n) {
        if (hardconst)
            log_info("agrv2k: hard-defaulted %ld and localized %ld BRAM constant input(s)\n",
                     hard_n, local_n);
        else
            log_info("agrv2k: localized %ld BRAM constant input(s)\n", local_n);
    }
}

// Bind dynamic BRAM-input drivers to slice slots whose output wire can actually reach the target
// BRAM pin in the loaded (possibly conduction-gated) graph.  Tile-only placement is insufficient:
// e.g. AddressA[7]/IMUX05 is fed by RMUX06, and gated RMUX06 is reachable only from OMUX02/05.
static void pack_bram_pin_drivers(Context *ctx)
{
    if (std::getenv("AGRV2K_BRAM_PINPACK") == nullptr)
        return;
    BelId bram_bel = ctx->getBelByName(IdStringList(ctx->id("X13Y4_BRAM")));
    if (bram_bel == BelId())
        return;
    struct PinCandidate { int score; BelId bel; };
    struct PinItem {
        IdString port;
        CellInfo *drv;
        std::vector<PinCandidate> candidates;
        int address_a_bit = -1;
        int address_b_bit = -1;
        bool clken1 = false;
    };
    std::vector<PinItem> items;
    for (auto &c : ctx->cells) {
        CellInfo *bram = c.second.get();
        if (bram->type != ctx->id("ALTA_BRAM9K"))
            continue;
        for (auto &p : bram->ports) {
            NetInfo *net = p.second.net;
            if (p.second.type != PORT_IN || net == nullptr || net->driver.cell == nullptr)
                continue;
            CellInfo *drv = net->driver.cell;
            if (drv->type != ctx->id("GENERIC_SLICE") || drv->bel != BelId())
                continue;
            if (p.first == ctx->id("Clk0") || p.first == ctx->id("Clk1"))
                continue;
            WireId target = ctx->getBelPinWire(bram_bel, p.first);
            if (target == WireId())
                continue;
            pool<WireId> reach;
            std::vector<WireId> q;
            std::unordered_set<int> entry_tiles;
            reach.insert(target); q.push_back(target);
            for (size_t h = 0; h < q.size(); h++) {
                for (PipId pip : ctx->getPipsUphill(q[h])) {
                    WireId src = ctx->getPipSrcWire(pip);
                    int sx = -1, sy = -1, dx = -1, dy = -1;
                    std::string sn = ctx->getWireName(src).str(ctx);
                    std::string dn = ctx->getWireName(q[h]).str(ctx);
                    if (std::sscanf(sn.c_str(), "X%dY%d_", &sx, &sy) == 2 &&
                        std::sscanf(dn.c_str(), "X%dY%d_", &dx, &dy) == 2 &&
                        dx == 13 && dy == 4 && (sx != 13 || sy != 4))
                        entry_tiles.insert((sx << 16) ^ (sy & 0xffff));
                    if (reach.insert(src).second)
                        q.push_back(src);
                }
            }
            Loc bloc = ctx->getBelLocation(bram_bel);
            // One vendor image routes the SERV-like x2 Port-A write address,
            // mixed registered/combinational Port-B read address and dynamic
            // ClkEn1 simultaneously.  Independent single-port observations
            // are not composable: their individually valid corridors can own
            // the same approach RMUX.  Use this conflict-free dual-port slot
            // assignment for the address/control pins exercised by SERV.
            static const Loc porta_addr_source[13] = {
                Loc(), Loc(), Loc(), Loc(14, 4, 1), Loc(14, 4, 0),
                Loc(14, 4, 9), Loc(14, 4, 8), Loc(14, 10, 0),
                Loc(14, 10, 8), Loc(14, 4, 13), Loc(14, 4, 4), Loc()};
            static const Loc portb_addr_source[13] = {
                Loc(14, 10, 6), Loc(14, 10, 9), Loc(14, 4, 12),
                Loc(14, 4, 2), Loc(14, 4, 7), Loc(14, 4, 6),
                Loc(14, 4, 3), Loc(14, 10, 4), Loc(14, 10, 15),
                Loc(14, 4, 10), Loc(14, 4, 11), Loc(14, 4, 14),
                Loc(14, 4, 15)};
            int address_a_bit = -1;
            bool exact_porta = std::sscanf(p.first.str(ctx).c_str(), "AddressA[%d]", &address_a_bit) == 1 &&
                               address_a_bit >= 3 && address_a_bit <= 10;
            int address_b_bit = -1;
            bool exact_portb = std::sscanf(p.first.str(ctx).c_str(), "AddressB[%d]", &address_b_bit) == 1 &&
                               address_b_bit >= 0 && address_b_bit < 13;
            bool exact_clken1 = p.first == ctx->id("ClkEn1");
            PinItem item{p.first, drv, {}, exact_porta ? address_a_bit : -1,
                         exact_portb ? address_b_bit : -1, exact_clken1};
            for (BelId b : ctx->getBels()) {
                if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE") || !ctx->checkBelAvail(b))
                    continue;
                WireId ow = ctx->getBelPinWire(b, net->driver.port);
                if (ow == WireId() || !reach.count(ow))
                    continue;
                Loc loc = ctx->getBelLocation(b);
                if (exact_porta && loc != porta_addr_source[address_a_bit])
                    continue;
                if (exact_portb && loc != portb_addr_source[address_b_bit])
                    continue;
                if (exact_clken1 && loc != Loc(14, 4, 5))
                    continue;
                int d = std::abs(loc.x - bloc.x) + std::abs(loc.y - bloc.y);
                int tk = (loc.x << 16) ^ (loc.y & 0xffff);
                int score = (entry_tiles.count(tk) ? 0 : 10000) + d * 100 + loc.z;
                item.candidates.push_back({score, b});
            }
            std::stable_sort(item.candidates.begin(), item.candidates.end(),
                             [](const PinCandidate &a, const PinCandidate &b) { return a.score < b.score; });
            if (item.candidates.empty()) {
                log_warning("agrv2k: no gated-graph slice output reaches dynamic BRAM pin %s (driver '%s')\n",
                            p.first.c_str(ctx), drv->name.c_str(ctx));
            } else {
                // One packed slice output can legitimately feed more than one
                // BRAM terminal (SERV shares a low address source between the
                // A and B ports).  Treat that as one placement variable whose
                // candidate set is the intersection for every driven pin;
                // binding the same cell independently twice silently moves it
                // away from the first terminal.
                auto prior = std::find_if(items.begin(), items.end(),
                                          [&](const PinItem &x) { return x.drv == drv; });
                if (prior == items.end()) {
                    items.push_back(std::move(item));
                } else {
                    std::unordered_set<int> allowed;
                    for (auto &candidate : item.candidates)
                        allowed.insert(candidate.bel.index);
                    prior->candidates.erase(
                        std::remove_if(prior->candidates.begin(), prior->candidates.end(),
                                       [&](const PinCandidate &candidate) {
                                           return !allowed.count(candidate.bel.index);
                                       }),
                        prior->candidates.end());
                    if (item.address_b_bit >= 0)
                        prior->address_b_bit = item.address_b_bit;
                    if (item.address_a_bit >= 0)
                        prior->address_a_bit = item.address_a_bit;
                    prior->clken1 = prior->clken1 || item.clken1;
                    if (prior->candidates.empty())
                        log_error("agrv2k: shared BRAM driver '%s' has no BEL reaching all of its terminals\n",
                                  drv->name.c_str(ctx));
                }
            }
        }
    }
    // Solve the pin/BEL assignment globally. Greedy pin order can consume the
    // sole reachable BEL for a later address bit even though a complete
    // matching exists (AddressA[7] in the dual-port SERV RF).
    std::vector<int> order(items.size()), chosen(items.size(), -1);
    for (size_t i = 0; i < items.size(); ++i) order[i] = int(i);
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
        return items[a].candidates.size() < items[b].candidates.size();
    });
    std::unordered_map<std::string, int> owner;
    std::function<bool(int, std::unordered_set<std::string> &)> match =
        [&](int ii, std::unordered_set<std::string> &seen) {
            for (size_t ci = 0; ci < items[ii].candidates.size(); ++ci) {
                BelId b = items[ii].candidates[ci].bel;
                std::string bn = ctx->getBelName(b).str(ctx);
                if (!seen.insert(bn).second) continue;
                auto it = owner.find(bn);
                if (it == owner.end() || match(it->second, seen)) {
                    owner[bn] = ii; chosen[ii] = int(ci); return true;
                }
            }
            return false;
        };
    int bound = 0;
    for (int ii : order) {
        std::unordered_set<std::string> seen;
        if (!match(ii, seen))
            log_warning("agrv2k: no simultaneous BEL assignment for dynamic BRAM pin %s\n",
                        items[ii].port.c_str(ctx));
    }
    for (size_t ii = 0; ii < items.size(); ++ii) {
        if (chosen[ii] < 0) continue;
        BelId b = items[ii].candidates.at(chosen[ii]).bel;
        items[ii].drv->attrs[ctx->id("AGRV2K_BRAM_PINPACKED")] = Property(1);
        int address_b_bit = items[ii].address_b_bit;
        int address_a_bit = items[ii].address_a_bit;
        static const int porta_omux_sel[13] = {-1, -1, -1, 2, 2, 2, 2, 0, 2, 2, 2, 2, -1};
        if (address_a_bit >= 3 && address_a_bit <= 10)
            items[ii].drv->attrs[ctx->id("AGRV2K_OMUX_SEL")] = Property(porta_omux_sel[address_a_bit]);
        if (address_b_bit >= 0) {
            static const int portb_omux_sel[13] = {2, 2, 2, 2, 2, 2, 2, 0, 0, 2, 2, 2, 2};
            if (address_b_bit >= 0 && address_b_bit < 13)
                items[ii].drv->attrs[ctx->id("AGRV2K_OMUX_SEL")] = Property(portb_omux_sel[address_b_bit]);
        }
        if (items[ii].clken1)
            items[ii].drv->attrs[ctx->id("AGRV2K_OMUX_SEL")] = Property(2);
        ctx->bindBel(b, items[ii].drv, STRENGTH_LOCKED);
        ++bound;
        log_info("agrv2k: BRAM-pin packed %s driver '%s'.%s (FF_USED=%d) -> %s\n",
                 items[ii].port.c_str(ctx), items[ii].drv->name.c_str(ctx),
                 items[ii].drv->ports.count(ctx->id("Q")) && items[ii].drv->getPort(ctx->id("Q")) != nullptr
                     ? "Q" : "F",
                 int_or_default(items[ii].drv->params, ctx->id("FF_USED"), 0),
                 ctx->getBelName(b).str(ctx).c_str());
    }
    log_info("agrv2k: BRAM-pin packed %d dynamic input driver(s)\n", bound);
}

// Reserve the simultaneously vendor-routed mixed SERV AddressB bus before
// router2 handles unrelated nets.  Merely locking source BELs is insufficient:
// a dense control net can consume one of the narrow approach RMUXes first and
// strand a later BRAM arc.  Pre-routed locked pips are a normal nextpnr
// mechanism and make the vendor oracle's conflict-free bus atomic.
static void lock_bram_portb_corridors(Context *ctx)
{
    if (std::getenv("AGRV2K_BRAM_PINPACK") == nullptr)
        return;
    int locked = 0;
    for (auto &c : ctx->cells) {
        CellInfo *bram = c.second.get();
        if (bram->type != ctx->id("ALTA_BRAM9K"))
            continue;
        // Reserve the complete simultaneously observed dual-port ingress as
        // one atomic routing unit before ordinary fabric nets.
        std::vector<IdString> ports;
        // Lock the fully characterized Port-B tree first.  Its complete
        // source-to-terminal paths are one simultaneous vendor solution;
        // allowing a flexible Port-A search to reserve one of those middle
        // RMUXes first can strand a later B lane despite that known solution.
        for (int bit = 0; bit <= 12; ++bit)
            ports.push_back(ctx->id("AddressB[" + std::to_string(bit) + "]"));
        // A[2] shares B[2]'s source in the SERV RF.  Extend that already
        // locked vendor tree before any independent ingress can consume its
        // short branch to the Port-A terminal.
        ports.push_back(ctx->id("AddressA[2]"));
        for (int bit = 3; bit <= 10; ++bit)
            ports.push_back(ctx->id("AddressA[" + std::to_string(bit) + "]"));
        ports.push_back(ctx->id("DataInA[0]"));
        ports.push_back(ctx->id("DataInA[1]"));
        ports.push_back(ctx->id("WeA"));
        ports.push_back(ctx->id("ClkEn1"));
        for (IdString port : ports) {
            NetInfo *net = bram->getPort(port);
            if (net == nullptr || net->driver.cell == nullptr)
                continue;
            WireId source = ctx->getBelPinWire(net->driver.cell->bel, net->driver.port);
            BelId bram_bel = ctx->getBelByNameStr("X13Y4_BRAM");
            WireId target = ctx->getBelPinWire(bram_bel, port);
            std::vector<WireId> queue{source};
            std::unordered_map<int, PipId> previous;
            previous[source.index] = PipId();
            for (size_t head = 0; head < queue.size() && !previous.count(target.index); ++head) {
                for (PipId pip : ctx->getPipsDownhill(queue[head])) {
                    if (!ctx->checkPipAvailForNet(pip, net))
                        continue;
                    WireId dst = ctx->getPipDstWire(pip);
                    NetInfo *wire_owner = ctx->getBoundWireNet(dst);
                    if (wire_owner != nullptr && wire_owner != net)
                        continue;
                    int x = -1, y = -1;
                    std::string name = ctx->getWireName(dst).str(ctx);
                    if (std::sscanf(name.c_str(), "X%dY%d_", &x, &y) != 2 ||
                        x < 12 || x > 16 || y < 4 || y > 10)
                        continue;
                    if (previous.emplace(dst.index, pip).second)
                        queue.push_back(dst);
                }
            }
            if (!previous.count(target.index))
                log_error("agrv2k: no simultaneous strict-graph corridor for %s\n", port.c_str(ctx));
            std::vector<PipId> route;
            for (WireId cursor = target; cursor != source; ) {
                PipId pip = previous.at(cursor.index);
                route.push_back(pip);
                cursor = ctx->getPipSrcWire(pip);
            }
            std::reverse(route.begin(), route.end());
            for (PipId pip : route) {
                ctx->bindPip(pip, net, STRENGTH_LOCKED);
                ++locked;
            }
            log_info("agrv2k: pre-routed %s over %d strict pip(s)\n", port.c_str(ctx), int(route.size()));
        }
    }
    log_info("agrv2k: pre-routed %d mixed-source Port-B corridor pip(s)\n", locked);
}

// Bind each physical output-pad driver to a slice BEL whose exact output wire reaches the pad input
// in the loaded graph.  A nearest-tile heuristic is not sufficient for the conduction-gated database:
// the pad approach IMUX can belong to a different connected component from a geometrically close OMUX.
static void pack_output_pin_drivers(Context *ctx)
{
    if (std::getenv("AGRV2K_IO_PINPACK") == nullptr)
        return;
    int bound = 0;
    for (auto &c : ctx->cells) {
        CellInfo *io = c.second.get();
        if (io->type != ctx->id("GENERIC_IOB") || io->bel == BelId())
            continue;
        NetInfo *net = io->getPort(ctx->id("I"));
        if (net == nullptr || net->driver.cell == nullptr)
            continue;
        CellInfo *drv = net->driver.cell;
        if (drv->type != ctx->id("GENERIC_SLICE") || drv->bel != BelId())
            continue;
        WireId target = ctx->getBelPinWire(io->bel, ctx->id("I"));
        if (target == WireId())
            continue;
        pool<WireId> reach;
        std::vector<WireId> q;
        reach.insert(target);
        q.push_back(target);
        for (size_t h = 0; h < q.size(); h++)
            for (PipId pip : ctx->getPipsUphill(q[h])) {
                WireId src = ctx->getPipSrcWire(pip);
                if (reach.insert(src).second)
                    q.push_back(src);
            }
        Loc iloc = ctx->getBelLocation(io->bel);
        BelId chosen;
        int bestd = 1000000;
        for (BelId b : ctx->getBels()) {
            if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE") || !ctx->checkBelAvail(b))
                continue;
            WireId ow = ctx->getBelPinWire(b, net->driver.port);
            if (ow == WireId() || !reach.count(ow))
                continue;
            Loc bloc = ctx->getBelLocation(b);
            int d = std::abs(bloc.x - iloc.x) + std::abs(bloc.y - iloc.y);
            if (d < bestd) { bestd = d; chosen = b; }
        }
        if (chosen != BelId()) {
            drv->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
            ctx->bindBel(chosen, drv, STRENGTH_LOCKED);
            ++bound;
            log_info("agrv2k: output-pin packed '%s' -> %s for pad '%s'\n", drv->name.c_str(ctx),
                     ctx->getBelName(chosen).str(ctx).c_str(), io->name.c_str(ctx));
        }
    }
    log_info("agrv2k: output-pin packed %d driver(s)\n", bound);
}

// Symmetric input-pad case: bind each direct fabric consumer to a BEL whose requested input pin is
// forward-reachable from the physical IPAD output in the gated graph.  In particular this fixes the
// root of a synthesized reset fanout tree; merely placing it on the nearest tile can select a dead IMUX.
static void pack_input_pin_consumers(Context *ctx)
{
    if (std::getenv("AGRV2K_IO_PINPACK") == nullptr)
        return;
    int bound = 0;
    for (auto &c : ctx->cells) {
        CellInfo *io = c.second.get();
        if (io->type != ctx->id("GENERIC_IOB") || io->bel == BelId())
            continue;
        NetInfo *net = io->getPort(ctx->id("O"));
        if (net == nullptr)
            continue;
        bool is_clock = false;
        for (auto &u : net->users)
            if (u.port == ctx->id("CLK") || u.port == ctx->id("Clk0") || u.port == ctx->id("Clk1"))
                is_clock = true;
        if (is_clock)
            continue;
        WireId source = ctx->getBelPinWire(io->bel, ctx->id("O"));
        if (source == WireId())
            continue;
        pool<WireId> reach;
        std::vector<WireId> q;
        reach.insert(source);
        q.push_back(source);
        for (size_t h = 0; h < q.size(); h++)
            for (PipId pip : ctx->getPipsDownhill(q[h])) {
                WireId dst = ctx->getPipDstWire(pip);
                if (reach.insert(dst).second)
                    q.push_back(dst);
            }
        Loc iloc = ctx->getBelLocation(io->bel);
        // Input permutation below rewires user lists, so iterate a stable copy.
        std::vector<PortRef> pad_users;
        for (auto &u : net->users)
            pad_users.push_back(u);
        for (auto &u : pad_users) {
            CellInfo *sink = u.cell;
            if (sink == nullptr || sink->type != ctx->id("GENERIC_SLICE") || sink->bel != BelId())
                continue;
            auto find_bel = [&](IdString pin) {
                BelId result;
                int bestd = 1000000;
                for (BelId b : ctx->getBels()) {
                    if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE") || !ctx->checkBelAvail(b))
                        continue;
                    if (const char *forced_z = std::getenv("AGRV2K_INPUT_SLICE")) {
                        std::string suffix = "_SLICE" + std::string(forced_z);
                        std::string bn = ctx->getBelName(b).str(ctx);
                        if (bn.size() < suffix.size() ||
                            bn.compare(bn.size() - suffix.size(), suffix.size(), suffix) != 0)
                            continue;
                    }
                    if (const char *forced_tile = std::getenv("AGRV2K_INPUT_TILE")) {
                        std::string prefix = "X" + std::string(forced_tile) + "_";
                        std::string bn = ctx->getBelName(b).str(ctx);
                        if (bn.find(prefix) != 0)
                            continue;
                    }
                    WireId iw = ctx->getBelPinWire(b, pin);
                    if (iw == WireId() || !reach.count(iw))
                        continue;
                    Loc bloc = ctx->getBelLocation(b);
                    // Slice 0 beside the qualified top-row inputs accepts the
                    // pad route but its Qin feedback is dead on silicon.  All
                    // other slots at the PIN_10 ingress were positive in the
                    // exhaustive 16-slot toggle sweep.  Prefer slot 1, then
                    // the remaining nonzero slots, without moving farther
                    // away from the pad.
                    int zcost = (bloc.z == 0) ? 31 : bloc.z;
                    int distance = std::abs(bloc.x - iloc.x) + std::abs(bloc.y - iloc.y);
                    // X19Y12 is the hardware-qualified common ingress anchor:
                    // PIN_10/11/15 all reach it, and pad-controlled Qin works
                    // there.  The geometrically nearer X20Y12/X20Y11 sites
                    // accept PIN_11 but their feedback remains dead.  Prefer
                    // the common anchor whenever it is graph-reachable.
                    int d = ((bloc.x == 19 && bloc.y == 12) ? 0 : 128) + 32 * distance + zcost;
                    if (d < bestd) { bestd = d; result = b; }
                }
                return result;
            };
            BelId chosen = find_bel(u.port);
            IdString bound_port = u.port;

            // ABC may put a physical input on an IMUX pin that this particular
            // pad cannot reach.  LUT inputs are logically symmetric if both the
            // nets and the INIT axes are swapped.  Try the other physical pins
            // before giving up.  Never move a registered slice's own-Q feedback:
            // qin_pack deliberately placed that net on I[2], the only Qin path.
            if (chosen == BelId()) {
                int original = -1;
                std::string up = u.port.str(ctx);
                if (up.size() == 4 && up[0] == 'I' && up[1] == '[' && up[3] == ']')
                    original = up[2] - '0';
                NetInfo *out = sink->getPort(ctx->id("Q"));
                if (out == nullptr)
                    out = sink->getPort(ctx->id("F"));
                NetInfo *original_net = sink->getPort(u.port);
                if (original >= 0 && original < 4 && original_net != out) {
                    for (int alt = 0; alt < 4 && chosen == BelId(); ++alt) {
                        if (alt == original)
                            continue;
                        IdString alt_port = ctx->id("I[" + std::to_string(alt) + "]");
                        NetInfo *alt_net = sink->getPort(alt_port);
                        if (alt_net == out)
                            continue;
                        BelId candidate = find_bel(alt_port);
                        if (candidate == BelId())
                            continue;

                        auto init_it = sink->params.find(ctx->id("INIT"));
                        if (init_it == sink->params.end())
                            continue;
                        uint64_t old_init = uint64_t(init_it->second.as_int64());
                        uint64_t new_init = 0;
                        for (int index = 0; index < 16; ++index) {
                            int old_index = index;
                            int abit = (index >> original) & 1;
                            int bbit = (index >> alt) & 1;
                            if (abit != bbit)
                                old_index ^= (1 << original) | (1 << alt);
                            if ((old_init >> old_index) & 1)
                                new_init |= uint64_t(1) << index;
                        }
                        sink->disconnectPort(u.port);
                        sink->disconnectPort(alt_port);
                        if (alt_net != nullptr)
                            sink->connectPort(u.port, alt_net);
                        if (original_net != nullptr)
                            sink->connectPort(alt_port, original_net);
                        sink->params[ctx->id("INIT")] = Property(new_init, 16);
                        chosen = candidate;
                        bound_port = alt_port;
                        log_info("agrv2k: input-pin permuted '%s'.%s -> %s for pad '%s'\n",
                                 sink->name.c_str(ctx), u.port.c_str(ctx), alt_port.c_str(ctx),
                                 io->name.c_str(ctx));
                    }
                }
            }
            if (chosen != BelId()) {
                sink->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
                ctx->bindBel(chosen, sink, STRENGTH_LOCKED);
                ++bound;
                log_info("agrv2k: input-pin packed pad '%s' consumer '%s'.%s -> %s\n", io->name.c_str(ctx),
                         sink->name.c_str(ctx), bound_port.c_str(ctx),
                         ctx->getBelName(chosen).str(ctx).c_str());
            } else {
                log_warning("agrv2k: no gated-graph slice input reaches '%s'.%s from pad '%s'\n",
                            sink->name.c_str(ctx), u.port.c_str(ctx), io->name.c_str(ctx));
            }
        }
    }
    log_info("agrv2k: input-pin packed %d consumer(s)\n", bound);
}

// Keep the SERV memory-acknowledge feedback cone inside one proven even-slot crossbar.  This is a
// first critical-net cluster (and a useful template for timing/handshake clustering generally): the
// gated graph still contains incompletely qualified long RMUX chains, while every even->even link in
// a single tile has direct silicon coverage.
static void pack_net_cluster(Context *ctx, const std::set<int> &slice_tiles, const char *netname,
                             bool expand_driver_cone = false)
{
    auto ni = ctx->nets.find(ctx->id(netname));
    if (ni == ctx->nets.end() || ni->second->driver.cell == nullptr) {
        return;
    }
    std::vector<CellInfo *> cells;
    auto add = [&](CellInfo *ci) {
        if (ci != nullptr && ci->type == ctx->id("GENERIC_SLICE") && ci->bel == BelId() &&
            std::find(cells.begin(), cells.end(), ci) == cells.end())
            cells.push_back(ci);
    };
    add(ni->second->driver.cell);
    for (auto &u : ni->second->users)
        add(u.cell);
    if (expand_driver_cone) {
        CellInfo *root = ni->second->driver.cell;
        for (auto &p : root->ports)
            if (p.second.type == PORT_IN && p.second.net != nullptr)
                add(p.second.net->driver.cell);
    }
    if (cells.empty() || cells.size() > 8) {
        log_warning("agrv2k: '%s' cluster has unsupported size %d\n", netname, int(cells.size()));
        return;
    }
    std::vector<int> tiles(slice_tiles.begin(), slice_tiles.end());
    std::sort(tiles.begin(), tiles.end(), [](int a, int b) {
        int da = std::abs((a >> 8) - 14) + std::abs((a & 0xff) - 4);
        int db = std::abs((b >> 8) - 14) + std::abs((b & 0xff) - 4);
        return da != db ? da < db : a < b;
    });
    for (int t : tiles) {
        std::vector<BelId> free;
        for (int z = 0; z < 16; z += 2) {
            std::string bn = "X" + std::to_string(t >> 8) + "Y" + std::to_string(t & 0xff) +
                             "_SLICE" + std::to_string(z);
            BelId b = ctx->getBelByName(IdStringList(ctx->id(bn)));
            if (ctx->checkBelAvail(b)) free.push_back(b);
        }
        if (free.size() < cells.size())
            continue;
        for (size_t i = 0; i < cells.size(); i++)
            ctx->bindBel(free[i], cells[i], STRENGTH_LOCKED);
        log_info("agrv2k: clustered '%s' producer/consumers (%d cells) at X%dY%d even slots\n",
                 netname, int(cells.size()), t >> 8, t & 0xff);
        return;
    }
    log_warning("agrv2k: no tile has %d free even slots for '%s' cluster\n", int(cells.size()), netname);
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
    std::vector<std::pair<Loc, BelId>> dense_bels;
    for (BelId b : ctx->getBels()) {
        if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE"))
            continue;
        Loc loc = ctx->getBelLocation(b);
        if (loc.x == tx && loc.y >= ty && loc.z >= 0 && loc.z <= 14 && (loc.z & 1) == 0)
            dense_bels.emplace_back(loc, b);
    }
    std::sort(dense_bels.begin(), dense_bels.end(), [](const auto &a, const auto &b) {
        if (a.first.y != b.first.y) return a.first.y < b.first.y;
        return a.first.z < b.first.z;
    });
    size_t next_bel = 0;
    int bound = 0;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != ctx->id("GENERIC_SLICE") || ci->bel != BelId())
            continue; // only unplaced slices (carry/MCU already bound)
        const std::string nm = ci->name.str(ctx);
        if (nm.find("PACKER") != std::string::npos || nm.find("CARRY_VCC") != std::string::npos)
            continue; // let constants float
        while (next_bel < dense_bels.size() && !ctx->checkBelAvail(dense_bels[next_bel].second))
            ++next_bel;
        if (next_bel == dense_bels.size())
            break;
        ctx->bindBel(dense_bels[next_bel++].second, ci, STRENGTH_LOCKED);
        ++bound;
    }
    if (bound)
        log_info("agrv2k: DENSE-placed %d data slices on even slots from (%d,%d)\n", bound, tx, ty);
}

// Apply a routed-checkpoint cell->BEL map before the constructive placer runs.
// The map is read after generic LUT/DFF packing, so its names are the stable
// packed names written by nextpnr rather than ambiguous synthesis precursors.
// AGRV2K_REPLAY_BELS names a CSV file containing `cell,bel` rows.
static void pack_replay_bels(Context *ctx, const std::string &map_in_db)
{
    const char *map_path = std::getenv("AGRV2K_REPLAY_BELS");
    std::string resolved;
    if (map_path != nullptr)
        resolved = map_path;
    else if (std::getenv("AGRV2K_REPLAY_BELS_IN_DB") != nullptr)
        resolved = map_in_db;
    else
        return;
    std::ifstream f(resolved);
    if (!f)
        log_error("agrv2k: cannot open replay BEL map '%s'\n", resolved.c_str());
    std::unordered_map<std::string, std::string> placements;
    std::string line;
    while (std::getline(f, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        auto comma = line.rfind(',');
        if (comma == std::string::npos) continue;
        placements[line.substr(0, comma)] = line.substr(comma + 1);
    }
    int bound = 0;
    for (auto &kv : ctx->cells) {
        CellInfo *ci = kv.second.get();
        auto it = placements.find(ci->name.str(ctx));
        if (it == placements.end())
            continue;
        BelId wanted = ctx->getBelByNameStr(it->second);
        if (wanted == BelId())
            log_error("agrv2k: replay constraint for '%s' names an unknown BEL\n", ci->name.c_str(ctx));
        if (ci->bel != BelId()) {
            if (ci->bel != wanted)
                log_error("agrv2k: replay constraint for '%s' conflicts with hard pin packing\n",
                          ci->name.c_str(ctx));
        } else {
            if (!ctx->checkBelAvail(wanted))
                log_error("agrv2k: replay BEL %s for '%s' is occupied by '%s'\n",
                          ctx->getBelName(wanted).str(ctx).c_str(), ci->name.c_str(ctx),
                          ctx->getBoundBelCell(wanted)->name.c_str(ctx));
            ctx->bindBel(wanted, ci, STRENGTH_LOCKED);
            ++bound;
        }
    }
    log_info("agrv2k: replay-bound %d checkpoint BEL constraint(s)\n", bound);
}

// ---- pack: CONDUCTION-AWARE placer (AGRV2K_CONDPLACE). Backtracking-embed the post-pack cell graph onto
// the silicon-conducting tile graph so EVERY driver->consumer edge is same-tile or a proven inter-tile
// RMUX->RMUX hop (tile_adj from master_conduction). This is the OTHER half of the solve: with the
// conduction-GATED devdb the router has no dead pip to fall back on, so a conducting PATH must exist by
// construction -- which naive even-slot placement (pack_dense) doesn't guarantee. Ports the proven
// engine_work/pin_ahb_condplace.py embedder (1 cell/tile default; the approach ahb_count2 computes with).
// Exit-driver FFs (feeding a bound MCU_DOUT) are anchored on tiles that conductingly reach EXIT_TILE(14,12).
static void pack_condplace(Context *ctx, const std::unordered_map<int, std::unordered_set<int>> &tile_adj,
                           const std::set<int> &slice_tiles, int bram_approach)
{
    if (std::getenv("AGRV2K_CONDPLACE") == nullptr || tile_adj.empty())
        return;
    auto tkey = [](int x, int y) { return (x << 8) | (y & 0xff); };
    // MCU-exit funnel tile: default (14,12); override AGRV2K_EXIT_TILE="x,y" (mirrors place_auto's
    // AGAMEMNON_EXIT_TILE) so the exit isn't a baked-in literal.
    int exx = 14, exy = 12;
    if (const char *e = std::getenv("AGRV2K_EXIT_TILE")) {
        std::string s(e);
        auto comma = s.find(',');
        if (comma != std::string::npos) {
            exx = std::atoi(s.substr(0, comma).c_str());
            exy = std::atoi(s.substr(comma + 1).c_str());
        }
    }
    const int EXIT = tkey(exx, exy);
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
    // Candidate tiles = tiles in the conducting graph that ALSO carry a GENERIC_SLICE bel. tile_adj is
    // built from RMUX->RMUX pips and includes non-LogicTILE columns (x=13 BRAM, IO/MCU edge) with no
    // slice bel -- binding a slice there asserts (getBelByName has no bel). slice_tiles is the arch's
    // ground truth; intersect against it so we never propose a bel-less tile.
    std::set<int> tileset;
    for (auto &kv : tile_adj) {
        if (slice_tiles.count(kv.first))
            tileset.insert(kv.first);
        for (int t : kv.second)
            if (slice_tiles.count(t))
                tileset.insert(t);
    }
    std::vector<int> cand(tileset.begin(), tileset.end()); // sorted (from std::set), SLICE-bearing only
    // ROUTE-DRIVEN SEARCH knob: perturb the spill-tile order deterministically by AGRV2K_CONDPLACE_SEED.
    // A residual inter-tile hop can be tile-conducting yet wire-UNROUTABLE (esp. long-range feedback/tap
    // nets); which spill tile a cell lands on decides that. The router is the wire-level oracle, so the CLI
    // sweeps seeds and keeps the first embedding that routes. seed 0 = sorted (unchanged default).
    unsigned cond_seed = 0;
    if (const char *e = std::getenv("AGRV2K_CONDPLACE_SEED")) {
        unsigned s = cond_seed = (unsigned)std::strtoul(e, nullptr, 10);
        if (s != 0)
            for (size_t i = cand.size(); i > 1; --i) {
                s = s * 1103515245u + 12345u;
                std::swap(cand[i - 1], cand[(s >> 16) % i]);
            }
    }

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
    // BRAM-aware anchoring: a GENERIC_SLICE that drives the BRAM's address/data inputs or reads its
    // outputs must sit on a tile conducting to the BRAM's approach column (bram_approach) -- otherwise its
    // address/data net can't route to the FIXED BRAM bel. (The BRAM itself is a hard block placed by
    // nextpnr on the sole ALTA_BRAM9K bel; pack_condplace only places slices, so it has to be taught which
    // slices are BRAM-adjacent and where the BRAM can be reached from.)
    std::set<CellInfo *> bramadj;
    if (bram_approach >= 0) {
        std::set<IdString> bram_nets;
        for (auto &c : ctx->cells) {
            if (c.second->type != ctx->id("ALTA_BRAM9K"))
                continue;
            for (auto &p : c.second->ports)
                if (p.second.net != nullptr)
                    bram_nets.insert(p.second.net->name);
        }
        if (!bram_nets.empty())
            for (auto ci : cells)
                for (auto &p : ci->ports)
                    if (p.second.net != nullptr && bram_nets.count(p.second.net->name)) {
                        bramadj.insert(ci);
                        break;
                    }
    }
    // Physical-I/O and MCU-bus anchors.  A bounded-fanout reset tree still fails if its root buffers are
    // placed across the die from the IPAD.  The sparse AHB entries have the same constraint: hwrite and
    // htrans1 emerge beside X14Y12, while hwdata0 emerges beside X14Y10.  Record the nearest slice tile for
    // direct endpoint consumers/drivers; regional placement reserves a patch around those endpoints.
    std::unordered_map<CellInfo *, int> iopref;
    std::vector<int> io_roots;
    for (auto &c : ctx->cells) {
        CellInfo *io = c.second.get();
        if (io->type != ctx->id("GENERIC_IOB") || io->bel == BelId())
            continue;
        Loc iloc = ctx->getBelLocation(io->bel);
        int near = -1, bestd = 1000000;
        for (int t : slice_tiles) {
            int d = std::abs((t >> 8) - iloc.x) + std::abs((t & 0xff) - iloc.y);
            if (d < bestd) { bestd = d; near = t; }
        }
        if (near < 0)
            continue;
        NetInfo *from_pad = io->getPort(ctx->id("O"));
        bool is_clock_iob = false;
        if (from_pad != nullptr)
            for (auto &u : from_pad->users)
                if (u.port == ctx->id("CLK") || u.port == ctx->id("Clk0") || u.port == ctx->id("Clk1"))
                    is_clock_iob = true;
        bool input_has_fabric_user = false;
        if (from_pad != nullptr && !is_clock_iob)
            for (auto &u : from_pad->users) {
                if (u.cell != nullptr && u.cell->type == ctx->id("GENERIC_SLICE")
                        && u.cell->bel != BelId()) {
                    Loc l = ctx->getBelLocation(u.cell->bel);
                    io_roots.push_back(tkey(l.x, l.y));
                }
                if (u.cell != nullptr && cellset.count(u.cell)) {
                    iopref[u.cell] = near;
                    input_has_fabric_user = true;
                }
            }
        if (input_has_fabric_user)
            io_roots.push_back(near);
        NetInfo *to_pad = io->getPort(ctx->id("I"));
        if (to_pad != nullptr && to_pad->driver.cell != nullptr) {
            if (to_pad->driver.cell->type == ctx->id("GENERIC_SLICE")
                    && to_pad->driver.cell->bel != BelId()) {
                Loc l = ctx->getBelLocation(to_pad->driver.cell->bel);
                io_roots.push_back(tkey(l.x, l.y));
            }
            if (cellset.count(to_pad->driver.cell))
                iopref[to_pad->driver.cell] = near;
        }
    }
    // Pin-packed slices are absent from `cells`, but their immediate consumers
    // must remain near the physical endpoint.  Otherwise a non-BRAM design is
    // region-rooted at the hard-block approach and its first registered-input
    // fanout crosses the die before ordinary dependency scoring can see it.
    for (auto &c : ctx->cells) {
        CellInfo *anchor = c.second.get();
        if (anchor->type != ctx->id("GENERIC_SLICE") || anchor->bel == BelId())
            continue;
        Loc l = ctx->getBelLocation(anchor->bel);
        int tile = tkey(l.x, l.y);
        NetInfo *out = anchor->getPort(ctx->id("Q"));
        if (out == nullptr) out = anchor->getPort(ctx->id("F"));
        if (out == nullptr) continue;
        bool feeds_unplaced = false;
        for (auto &u : out->users)
            if (u.cell != nullptr && cellset.count(u.cell)) {
                iopref[u.cell] = tile;
                feeds_unplaced = true;
            }
        // qin_pack represents a registered pad input as a pre-placed slice,
        // not as a direct GENERIC_IOB user.  Make that slice the regional
        // root when it actually feeds fabric logic.  (A pre-placed output
        // slice only feeds its IOB and therefore does not become a root.)
        if (feeds_unplaced)
            io_roots.push_back(tile);
    }
    for (auto &c : ctx->cells) {
        CellInfo *mcu = c.second.get();
        if (mcu->type != ctx->id("MCU_DIN") || mcu->bel == BelId())
            continue;
        std::string name = mcu->name.str(ctx);
        int near = -1;
        if (name.find("hwdata0") != std::string::npos)
            near = tkey(14, 10);
        else if (name.find("hwrite") != std::string::npos ||
                 name.find("htrans1") != std::string::npos)
            near = tkey(14, 12);
        NetInfo *from_mcu = mcu->getPort(ctx->id("DIN"));
        if (near >= 0 && from_mcu != nullptr)
            for (auto &u : from_mcu->users)
                if (u.cell != nullptr && cellset.count(u.cell))
                    iopref[u.cell] = near;
    }
    // CONNECTIVITY (BFS) ORDER: place cells breadth-first from the anchors so each cell is placed right
    // after one of its neighbours. The candidate order below then prefers that neighbour's OWN tile, so
    // connected cells CO-LOCATE on one tile (intra-tile even-slot = wire-guaranteed) up to CAP, spilling to
    // a conducting neighbour tile only when the tile is full. This minimises the number of risky inter-tile
    // hops -- the tile-vs-wire gap that fails a SCATTERED chain (hash-map order placed e.g. sr[5] before
    // sr[3], forcing them onto different tiles -> many inter-tile hops, some of which don't route).
    {
        std::vector<CellInfo *> order;
        order.reserve(cells.size());
        std::set<CellInfo *> seen;
        std::vector<CellInfo *> q;
        size_t head = 0;
        auto push = [&](CellInfo *c) { if (seen.insert(c).second) q.push_back(c); };
        for (auto ci : cells) // seed anchored cells first (exit-drivers, BRAM-adjacent), in current order
            if (exitdrv.count(ci) || bramadj.count(ci))
                push(ci);
        while (true) {
            if (head < q.size()) {
                CellInfo *ci = q[head++];
                order.push_back(ci);
                // deps/indeps are pointer-keyed sets; iterating them directly
                // makes placement depend on ASLR heap addresses.  Stable cell
                // names make an identical netlist produce an identical route.
                std::vector<CellInfo *> neighbours;
                neighbours.insert(neighbours.end(), deps[ci].begin(), deps[ci].end());
                neighbours.insert(neighbours.end(), indeps[ci].begin(), indeps[ci].end());
                bool reverse = std::getenv("AGRV2K_BFS_REVERSE") != nullptr;
                std::sort(neighbours.begin(), neighbours.end(), [&](CellInfo *a, CellInfo *b) {
                    return reverse ? a->name.str(ctx) > b->name.str(ctx) : a->name.str(ctx) < b->name.str(ctx);
                });
                for (auto nb : neighbours)
                    push(nb);
            } else { // queue drained -> seed the highest-degree unplaced cell as a new component root
                CellInfo *best = nullptr;
                size_t bd = 0;
                for (auto ci : cells)
                    if (!seen.count(ci)) {
                        size_t d = deps[ci].size() + indeps[ci].size();
                        if (best == nullptr || d > bd) { best = ci; bd = d; }
                    }
                if (best == nullptr)
                    break;
                push(best);
            }
        }
        cells = std::move(order);
    }
    int CAP = 1;
    if (const char *e = std::getenv("AGRV2K_CONDPLACE_CAP"))
        CAP = std::max(1, std::atoi(e));

    // COMPACTNESS (AGRV2K_COMPACT_MAXD): a HARD Manhattan bounding-box radius around the first-placed
    // (exit-driver) cell -- keep the WHOLE design inside a (2*maxd+1)^2 tile box. Silicon only conducts
    // hops within the fabric's ~4-tile data radius; the placer otherwise SCATTERS onto any conducting
    // tile-pair (johnson32 -> 17 tiles / 7x8 box -> froze). With the dense strict devdb (~92% per-position
    // proven) a compact box is now also ROUTABLE, so compact+routable+conducting can finally coincide.
    int compact_maxd = 0;
    if (const char *e = std::getenv("AGRV2K_COMPACT_MAXD"))
        compact_maxd = std::max(0, std::atoi(e));
    int compact_anchor = -1;

    std::unordered_map<CellInfo *, int> assign;
    std::unordered_map<int, int> occ;
    for (auto &c : ctx->cells) {
        CellInfo *ci = c.second.get();
        if (ci->type == ctx->id("GENERIC_SLICE") && ci->bel != BelId()) {
            Loc l = ctx->getBelLocation(ci->bel);
            occ[tkey(l.x, l.y)]++;
        }
    }
    auto feasible = [&](CellInfo *ci, int t) -> bool {
        if (!slice_tiles.count(t)) // neighbour tiles from tile_adj may be bel-less (BRAM/IO columns)
            return false;
        if (occ[t] >= CAP)
            return false;
        if (exitdrv.count(ci) && !reaches_exit(t))
            return false;
        if (compact_maxd > 0 && compact_anchor >= 0) { // keep this cell inside the design's bounding box
            int ax = compact_anchor >> 8, ay = compact_anchor & 0xff;
            if (std::abs((t >> 8) - ax) + std::abs((t & 0xff) - ay) > compact_maxd)
                return false;
        }
        // BRAM-adjacent cells are biased toward the approach via the candidate ordering below, but NOT
        // hard-rejected off it: the proven placement puts BRAM address FFs 2+ hops up the approach column
        // (X14Y9/10 reach the BRAM by a MULTI-hop route the gated router finds), which a single-hop reject
        // would forbid -> "could not embed". The preference + the gated router handle it.
        for (auto d : deps[ci])
            if (assign.count(d) && !conduct(t, assign[d]))
                return false;
        for (auto dr : indeps[ci])
            if (assign.count(dr) && !conduct(assign[dr], t))
                return false;
        return true;
    };
    // MEDIUM/LARGE-DESIGN REGIONAL placement. Requiring every logical edge to be a *single* conducting
    // tile hop is unnecessarily strong: the router can and does use multi-hop paths.  Worse, solving
    // that graph embedding with DFS is exponential (a generated 22-slice nonlinear state graph exhausted
    // every cap/fanout attempt, while regional placement routed and ran on silicon). For designs beyond
    // the small exact-embedding regime, grow a compact connected region from the BRAM
    // approach and greedily partition the already-BFS-ordered cell graph into CAP-sized tiles.  The
    // score strongly favours co-location, then adjacent tiles, but leaves longer nets to the real
    // wire-level router.  Small designs retain the exact embedder below because it is silicon-proven.
    bool large_placed = false;
    // Exact embedding remains the silicon-proven default for tiny counters and I/O probes. Above sixteen
    // cells its one-hop constraint and bounded DFS become both unnecessarily restrictive and extremely
    // slow. AGRV2K_CONDPLACE_EXACT retains the old search for diagnostics/reproduction.
    bool force_exact = std::getenv("AGRV2K_CONDPLACE_EXACT") != nullptr;
    bool use_regional = !force_exact &&
                        (cells.size() > 16 || std::getenv("AGRV2K_CONDPLACE_REGIONAL") != nullptr);
    if (use_regional) {
        std::unordered_map<int, std::set<int>> und;
        for (auto &kv : tile_adj)
            for (int n : kv.second)
                if (slice_tiles.count(kv.first) && slice_tiles.count(n)) {
                    und[kv.first].insert(n);
                    und[n].insert(kv.first);
                }

        int root = bram_approach;
        if (bramadj.empty() && !io_roots.empty())
            root = io_roots.front();
        if (!slice_tiles.count(root)) {
            root = cand.empty() ? -1 : cand.front();
            // Prefer a slice tile immediately connected to the hard-block approach.
            auto it = tile_adj.find(bram_approach);
            if (it != tile_adj.end())
                for (int n : it->second)
                    if (slice_tiles.count(n)) { root = n; break; }
        }

        std::vector<int> region, q;
        std::set<int> rseen;
        if (root >= 0) { q.push_back(root); rseen.insert(root); }
        for (size_t h = 0; h < q.size(); h++) {
            int t = q[h];
            region.push_back(t);
            for (int n : und[t])
                if (rseen.insert(n).second)
                    q.push_back(n);
        }
        // A sparse conduction corpus can have disconnected components.  Append remaining slice
        // tiles by distance from the root so capacity is still complete and deterministic.
        std::vector<int> rest;
        for (int t : cand) if (!rseen.count(t)) rest.push_back(t);
        std::sort(rest.begin(), rest.end(), [&](int a, int b) {
            int ax = a >> 8, ay = a & 0xff, bx = b >> 8, by = b & 0xff;
            int rx = root >> 8, ry = root & 0xff;
            int da = std::abs(ax-rx) + std::abs(ay-ry), db = std::abs(bx-rx) + std::abs(by-ry);
            if (da != db) return da < db;
            if (cond_seed != 0) {
                unsigned ha = (unsigned(a) ^ cond_seed) * 2654435761u;
                unsigned hb = (unsigned(b) ^ cond_seed) * 2654435761u;
                if (ha != hb) return ha < hb;
            }
            return a < b;
        });
        region.insert(region.end(), rest.begin(), rest.end());

        // The conduction graph contains long measured hops, so graph-BFS order alone can jump across
        // the die.  Sort by physical distance and expose only the minimum number of CAP-sized tiles;
        // this prevents a high-fanout control net from opening dozens of one-cell spill tiles.
        std::stable_sort(region.begin(), region.end(), [&](int a, int b) {
            int ax = a >> 8, ay = a & 0xff, bx = b >> 8, by = b & 0xff;
            int rx = root >> 8, ry = root & 0xff;
            int da = std::abs(ax-rx) + std::abs(ay-ry), db = std::abs(bx-rx) + std::abs(by-ry);
            if (da != db)
                return da < db;
            // Preserve deterministic default ordering, but make the documented
            // route-driven seed actually perturb equal-radius spill tiles. The
            // previous final `a < b` tie-break erased every earlier shuffle,
            // producing byte-identical routes for all nonzero seeds.
            if (cond_seed != 0) {
                unsigned ha = (unsigned(a) ^ cond_seed) * 2654435761u;
                unsigned hb = (unsigned(b) ^ cond_seed) * 2654435761u;
                if (ha != hb)
                    return ha < hb;
            }
            return a < b;
        });
        size_t preplaced_slices = 0;
        for (auto &kv : occ) preplaced_slices += kv.second;
        size_t need_tiles = (cells.size() + preplaced_slices + CAP - 1) / CAP;
        if (const char *e = std::getenv("AGRV2K_CONDPLACE_SLACK_TILES"))
            need_tiles += std::max(0, std::atoi(e));
        // Reserve enough nearest tiles around every I/O anchor to hold its direct root cells.
        std::unordered_map<int, int> pref_count;
        for (auto &kv : iopref) pref_count[kv.second]++;
        std::set<int> forced;
        for (auto &pc : pref_count) {
            std::vector<int> byio = cand;
            int px = pc.first >> 8, py = pc.first & 0xff;
            std::sort(byio.begin(), byio.end(), [&](int a, int b) {
                int da = std::abs((a >> 8)-px) + std::abs((a & 0xff)-py);
                int db = std::abs((b >> 8)-px) + std::abs((b & 0xff)-py);
                return da != db ? da < db : a < b;
            });
            int n = (pc.second + CAP - 1) / CAP;
            for (int i = 0; i < n && i < int(byio.size()); i++) forced.insert(byio[i]);
        }
        if (region.size() > need_tiles) {
            std::vector<int> chosen(region.begin(), region.begin() + need_tiles);
            std::set<int> have(chosen.begin(), chosen.end());
            for (int t : forced) if (!have.count(t)) {
                size_t pos = chosen.size();
                while (pos > 0 && forced.count(chosen[pos-1])) --pos;
                if (pos == 0) break;
                have.erase(chosen[pos-1]); chosen[pos-1] = t; have.insert(t);
            }
            region = std::move(chosen);
        }

        int region_preplaced = 0;
        for (int t : region) {
            auto oi = occ.find(t);
            if (oi != occ.end())
                region_preplaced += oi->second;
        }
        log_info("agrv2k: REGIONAL capacity: %d cells, %d preplaced total/%d in region, "
                 "%d/%d tiles exposed at cap %d\n", int(cells.size()), int(preplaced_slices),
                 region_preplaced, int(region.size()), int(cand.size()), CAP);

        std::unordered_map<int, int> rank;
        for (size_t i = 0; i < region.size(); i++) rank[region[i]] = int(i);
        large_placed = true;
        for (auto ci : cells) {
            int best = -1, best_score = -1000000000;
            for (int t : region) {
                auto oi = occ.find(t);
                int used = oi == occ.end() ? 0 : oi->second;
                if (used >= CAP)
                    continue;
                int score = -rank[t];
                if (bramadj.count(ci)) {
                    if (t == root) score += 5000;
                    else if (conduct(t, root)) score += 1500;
                }
                auto ip = iopref.find(ci);
                if (ip != iopref.end()) {
                    int px = ip->second >> 8, py = ip->second & 0xff;
                    int md = std::abs((t >> 8)-px) + std::abs((t & 0xff)-py);
                    score += (t == ip->second) ? 50000 : (5000 - 500 * md);
                }
                int assigned_nb = 0;
                for (auto nb : deps[ci]) if (assign.count(nb)) {
                    ++assigned_nb;
                    score += (assign[nb] == t) ? 10000 : (conduct(assign[nb], t) ? 1000 : 0);
                }
                for (auto nb : indeps[ci]) if (assign.count(nb)) {
                    ++assigned_nb;
                    score += (assign[nb] == t) ? 10000 : (conduct(assign[nb], t) ? 1000 : 0);
                }
                // Fill a used tile before opening a remote one when this cell begins a new component.
                if (assigned_nb == 0 && used > 0) score += 50;
                if (score > best_score) { best_score = score; best = t; }
            }
            if (best < 0) { large_placed = false; break; }
            assign[ci] = best;
            occ[best]++;
        }
        if (large_placed)
            log_info("agrv2k: REGIONAL-placed %d cells across %d/%d candidate tiles (cap %d, root %d,%d)\n",
                     int(cells.size()), int(occ.size()), int(region.size()), CAP, root >> 8, root & 0xff);
    }

    // BOUNDED-BACKTRACKING placement. Pure greedy corners itself even on a 4-bit counter (a cell's deps
    // land on tiles with no common conducting neighbour); unbounded backtracking is exponential and HANGS
    // past ~a couple dozen cells. This does a DFS with a NODE BUDGET: it explores/backtracks (so it finds
    // embeddings greedy misses) but bails cleanly at the cap instead of hanging. Candidate order puts a
    // cell's placed-neighbour tiles (and their conducting neighbours) first, so branching stays low and
    // solutions are found early. Budget scales with cell count; AGRV2K_CONDPLACE_BUDGET overrides.
    long budget = 4000000;
    if (const char *e = std::getenv("AGRV2K_CONDPLACE_BUDGET"))
        budget = std::atol(e);
    std::function<bool(size_t)> place = [&](size_t i) -> bool {
        if (i == cells.size())
            return true;
        if (--budget < 0)
            return false; // node cap hit -> fail gracefully (never hang)
        CellInfo *ci = cells[i];
        std::vector<int> pref;
        std::set<int> seen;
        auto addpref = [&](int t) { if (t >= 0 && !seen.count(t)) { seen.insert(t); pref.push_back(t); } };
        if (bramadj.count(ci)) { // BRAM-adjacent: try the approach tile + its conducting neighbours first
            addpref(bram_approach);
            auto it = tile_adj.find(bram_approach);
            if (it != tile_adj.end()) for (int n : it->second) addpref(n);
        }
        auto ip = iopref.find(ci);
        if (ip != iopref.end()) {
            addpref(ip->second);
            auto it = tile_adj.find(ip->second);
            if (it != tile_adj.end()) for (int n : it->second) addpref(n);
        }
        for (auto d : deps[ci])
            if (assign.count(d)) { addpref(assign[d]); auto it = tile_adj.find(assign[d]); if (it != tile_adj.end()) for (int n : it->second) addpref(n); }
        for (auto dr : indeps[ci])
            if (assign.count(dr)) { addpref(assign[dr]); auto it = tile_adj.find(assign[dr]); if (it != tile_adj.end()) for (int n : it->second) addpref(n); }
        for (int t : cand)
            addpref(t);
        for (int t : pref) {
            if (!feasible(ci, t))
                continue;
            assign[ci] = t;
            occ[t]++;
            if (i == 0) compact_anchor = t;   // anchor the bounding box on the first (exit-driver) cell
            if (place(i + 1))
                return true;
            assign.erase(ci);
            occ[t]--;
            if (i == 0) compact_anchor = -1;
        }
        return false;
    };
    if (!large_placed && !place(0)) {
        log_error("agrv2k: CONDPLACE could not embed %d cells within the search budget (raise "
                  "AGRV2K_CONDPLACE_CAP / AGRV2K_CONDPLACE_BUDGET, or the design exceeds the conducting "
                  "graph's capacity)\n", int(cells.size()));
        return;
    }
    for (auto ci : cells) {
        int t = assign[ci];
        BelId b;
        // Prefer silicon-proven even slots, but never overwrite a BRAM-pin/carry binding;
        // use a remaining odd slot only when explicitly permitted for diagnostics.
        for (int pass = 0; pass < 2 && b == BelId(); pass++)
            for (int z = pass; z < 16; z += 2) {
                // The strict graph shows that the combinational output of
                // X15Y12_SLICE4 (OMUX14) reaches only the right-hand routing
                // component.  A registered cell is safe here (Q uses OMUX12),
                // but placing an ordinary LUT here can make an otherwise
                // routable net impossible.  This is derived from the loaded
                // physical topology, not a placement-density limitation.
                if ((t >> 8) == 15 && (t & 0xff) == 12 && z == 4 &&
                    int_or_default(ci->params, ctx->id("FF_USED"), 0) == 0)
                    continue;
                std::string bn = "X" + std::to_string(t >> 8) + "Y" + std::to_string(t & 0xff) +
                                 "_SLICE" + std::to_string(z);
                BelId try_b = ctx->getBelByName(IdStringList(ctx->id(bn)));
                if (try_b != BelId() && ctx->checkBelAvail(try_b)) { b = try_b; break; }
            }
        if (b == BelId())
            log_error("agrv2k: no free slice bel on assigned tile (%d,%d)\n", t >> 8, t & 0xff);
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
    // Tile keys that actually carry GENERIC_SLICE bels (LogicTILEs). tile_adj is built from RMUX->RMUX
    // pips, which include non-LogicTILE columns (the x=13 BRAM column, IO/MCU edge tiles) with NO slice
    // bel -- pack_condplace must never try to bind e.g. X13Y4_SLICE0 (getBelByName ASSERTS on unknown).
    std::set<int> slice_tiles;
    int bram_xy = -1;        // the ALTA_BRAM9K bel's tile key (set in load_db), -1 if none
    int bram_approach = -1;  // the slice tile adjacent to the BRAM that its address/data pips reach through
    // K-hop conducting closure (undirected BFS over tile_adj, K = AGRV2K_CONDPAIR_HOPS). The data mesh
    // chains RMUX up to ~4 hops, so a single-hop conducting-pair rule is TOO strict for HeAP's legalizer to
    // satisfy at scale (it runs out of legal positions ~30 cells). Allowing <=K-hop pairs gives the
    // legalizer room to converge while every allowed pair is still a conducting path the gated router can
    // realize. Empty when K<=1 (single-hop, the default).
    std::unordered_map<int, std::unordered_set<int>> tile_reach;
    static int tkey(int x, int y) { return (x << 8) | (y & 0xff); }
    bool tiles_conduct(int ax, int ay, int bx, int by) const
    {
        if (ax == bx && ay == by)
            return true; // same tile: intra-tile crossbar (even-slot invariant guarantees the pair conducts)
        int ka = tkey(ax, ay), kb = tkey(bx, by);
        if (!tile_reach.empty()) { // K-hop closure (symmetric); one lookup suffices but check both to be safe
            auto it = tile_reach.find(ka);
            if (it != tile_reach.end() && it->second.count(kb))
                return true;
            auto jt = tile_reach.find(kb);
            return jt != tile_reach.end() && jt->second.count(ka);
        }
        auto it = tile_adj.find(ka);
        if (it != tile_adj.end() && it->second.count(kb))
            return true;
        auto jt = tile_adj.find(kb);
        if (jt != tile_adj.end() && jt->second.count(ka))
            return true;
        return false;
    }

    // ---- HeAP hybrid: anchor the EXIT-DRIVER FFs (those feeding an MCU_DOUT) onto tiles that conduct to
    // the MCU exit funnel (14,12), then let nextpnr's HeAP place the rest. WITHOUT this, HeAP puts the
    // readout FFs wherever wirelength likes (e.g. X9Y4/X10Y4) and the readout path can't reach the exit ->
    // hrdata reads the bus default (stuck, distinct=1) even though the internal logic clocks fine. This is
    // the backtracker's exit-reachability ingredient, ported to the analytic flow. Gated AGRV2K_HEAP_ANCHORS.
    void pack_exit_anchor()
    {
        if (std::getenv("AGRV2K_HEAP_ANCHORS") == nullptr)
            return;
        std::vector<int> exit_tiles; // exit-reaching slice tiles (nearest the exit first)
        for (int t : slice_tiles)
            if (tiles_conduct(t >> 8, t & 0xff, 14, 12))
                exit_tiles.push_back(t);
        if (exit_tiles.empty())
            return;
        std::sort(exit_tiles.begin(), exit_tiles.end(), [](int a, int b) {
            auto d = [](int t) { int x = t >> 8, y = t & 0xff; return std::abs(x - 14) + std::abs(y - 12); };
            return d(a) < d(b);
        });
        std::unordered_map<int, int> slot;
        long n = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            if (ci->type != ctx->id("GENERIC_SLICE") || ci->bel != BelId())
                continue;
            NetInfo *o = ci->getPort(ctx->id("Q"));
            if (o == nullptr)
                o = ci->getPort(ctx->id("F"));
            if (o == nullptr)
                continue;
            bool exitdrv = false;
            for (auto &u : o->users)
                if (u.cell != nullptr && u.cell->type == ctx->id("MCU_DOUT")) {
                    exitdrv = true;
                    break;
                }
            if (!exitdrv)
                continue;
            bool bound = false;
            for (int t : exit_tiles) {
                int x = t >> 8, y = t & 0xff;
                for (int z = slot[t]; z < 16 && !bound; z += 2) {
                    std::string bn = "X" + std::to_string(x) + "Y" + std::to_string(y) + "_SLICE" +
                                     std::to_string(z);
                    BelId b = ctx->getBelByName(IdStringList(ctx->id(bn)));
                    if (b != BelId() && ctx->checkBelAvail(b)) {
                        ctx->bindBel(b, ci, STRENGTH_LOCKED);
                        slot[t] = z + 2;
                        bound = true;
                        ++n;
                    }
                }
                if (bound)
                    break;
            }
        }
        if (n)
            log_info("agrv2k: HEAP anchors: bound %ld exit-driver FF(s) to exit-reaching tiles\n", n);
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
                if (c.at(1) == "GENERIC_SLICE")
                    slice_tiles.insert(tkey(loc.x, loc.y)); // this tile is a placement candidate
                else if (c.at(1) == "ALTA_BRAM9K")
                    bram_xy = tkey(loc.x, loc.y); // BRAM bel tile (its neighbour column is the approach)
                ++nb;
            }
        }
        // the BRAM's conduction "approach" for the placer = the neighbouring slice column that feeds its
        // IMUX/reads its BufMUX (the devdb shows x+1 carrying the address/data pips into X13Y4). Cells that
        // talk to the BRAM must be placed on tiles conducting to this approach, else their address/data nets
        // can't route to the fixed BRAM bel.
        if (bram_xy >= 0) {
            int bx = bram_xy >> 8, by = bram_xy & 0xff;
            if (slice_tiles.count(tkey(bx + 1, by)))
                bram_approach = tkey(bx + 1, by);
            else if (slice_tiles.count(tkey(bx - 1, by)))
                bram_approach = tkey(bx - 1, by);
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

        // Precompute the K-hop conducting closure for CONDPAIR legality (AGRV2K_CONDPAIR_HOPS, default 1 =
        // single-hop = unchanged). K>1 does an undirected BFS over tile_adj so the legalizer sees more legal
        // conducting positions (the mesh routes chained RMUX <=~4 hops), letting HeAP converge at scale.
        int K = 1;
        if (const char *e = std::getenv("AGRV2K_CONDPAIR_HOPS"))
            K = std::max(1, std::atoi(e));
        if (K > 1) {
            std::unordered_map<int, std::unordered_set<int>> u; // symmetric adjacency
            for (auto &kv : tile_adj)
                for (int b : kv.second) {
                    u[kv.first].insert(b);
                    u[b].insert(kv.first);
                }
            for (auto &kv : u) {
                int s = kv.first;
                std::unordered_set<int> seen{s};
                std::vector<int> frontier{s};
                for (int h = 0; h < K && !frontier.empty(); ++h) {
                    std::vector<int> nxt;
                    for (int x : frontier) {
                        auto it = u.find(x);
                        if (it == u.end())
                            continue;
                        for (int y : it->second)
                            if (seen.insert(y).second)
                                nxt.push_back(y);
                    }
                    frontier.swap(nxt);
                }
                seen.erase(s);
                tile_reach[s] = std::move(seen);
            }
            log_info("agrv2k: CONDPAIR K=%d conducting closure over %d tiles\n", K, int(tile_reach.size()));
        }
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
        pack_bram_trim(ctx); // drop a read-only BRAM's don't-care DataInA (avoids an unroutable GND fanout)
        pack_io(ctx);
        pack_carries(ctx);   // dedicated HW carry: fuse AG32_FA(+DFF) -> GENERIC_SLICE keeping CIN/COUT
        pack_lut_lutffs(ctx);
        pack_nonlut_ffs(ctx);
        pack_mcu_edge(ctx);  // bind MCU_DOUT exit cells AFTER fusion (binding before corrupts a readout net
                             // shared with a fusing LUT -> stale port). Names survive; bels still free.
        pack_clk(ctx);       // bind the clock input pad to CLKIN (else the placer may drop it on an OPAD)
        pack_exit_anchor();  // AGRV2K_HEAP_ANCHORS: anchor readout FFs to exit-reaching tiles, then let HeAP run
        pack_bram_localize_const(ctx); // per-pin local constants for BRAM control (not the stranded global net)
        pack_bram_pin_drivers(ctx); // slot-exact dynamic BRAM ingress on the loaded gated graph
        pack_input_pin_consumers(ctx); // slot-exact physical input-pad egress on the gated graph
        pack_output_pin_drivers(ctx); // slot-exact physical output-pad ingress on the gated graph
        pack_replay_bels(ctx, path("placement.csv"));
        if (std::getenv("AGRV2K_CLUSTER_MEM_ACK") != nullptr)
            pack_net_cluster(ctx, slice_tiles, "mem_ack");
        if (std::getenv("AGRV2K_CLUSTER_RF_READY") != nullptr)
            pack_net_cluster(ctx, slice_tiles, "rf_ready_debug");
        if (std::getenv("AGRV2K_CLUSTER_PC2") != nullptr)
            pack_net_cluster(ctx, slice_tiles, "cpu.wb_ibus_adr[2]", true);
        // An explicit constructive dense placement must run first; otherwise
        // CONDPLACE consumes every free slice and silently turns the documented
        // AGRV2K_DENSE_TILE diagnostic into a no-op.
        pack_dense(ctx);     // AGRV2K_DENSE_TILE: bind data slices to even slots (dense, conducting)
        pack_condplace(ctx, tile_adj, slice_tiles, bram_approach); // place anything still unbound
        lock_bram_portb_corridors(ctx); // reserve the vendor-routed mixed RF bus before router2
        add_slice_timing(ctx); // cells are final now: register conservative LUT/FF/carry arcs for timing-driven P&R
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
        bool is_pinpacked = ci->attrs.count(ctx->id("AGRV2K_BRAM_PINPACKED")) != 0 ||
                            ci->attrs.count(ctx->id("AGRV2K_IO_PINPACKED")) != 0;
        // EVEN-SLOT INVARIANT: the intra-tile OMUX->IMUX crossbar's only dead (zs,zd) pairs all involve
        // an ODD endpoint (chipdb/xbar_conduction.csv), so restricting NON-carry slices to even z
        // {0,2,..,14} makes every intra-tile crossbar link even->even => guaranteed to conduct.
        bool strict_allows_odd = std::getenv("AGRV2K_STRICT_ALLOW_ODD") != nullptr;
        if (!is_carry && !is_pinpacked && !strict_allows_odd && (loc.z & 1) != 0)
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
