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
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <limits>
#include <map>
#include <queue>
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

// Record one structured footprint as a native nextpnr cluster.  The supplied
// locations describe the already-qualified physical shape, not an absolute
// placement: x/y are converted to offsets from the root so the placer may
// translate the structure as a unit.  Carry seams require exact slice slots,
// hence the optional absolute-z constraint; x/y always remain relative.
static void make_relative_cluster(const std::vector<std::pair<CellInfo *, Loc>> &members,
                                  bool absolute_z)
{
    NPNR_ASSERT(!members.empty());
    CellInfo *root = members.front().first;
    const Loc root_loc = members.front().second;
    const ClusterId cluster = root->name;
    for (const auto &member : members) {
        CellInfo *cell = member.first;
        NPNR_ASSERT(cell->cluster == ClusterId());
        NPNR_ASSERT(cell->constr_children.empty());
        cell->cluster = cluster;
        cell->constr_x = member.second.x - root_loc.x;
        cell->constr_y = member.second.y - root_loc.y;
        cell->constr_z = absolute_z ? member.second.z : member.second.z - root_loc.z;
        cell->constr_abs_z = absolute_z;
        if (cell != root)
            root->constr_children.push_back(cell);
    }
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

    // ---- constructive placement: follow the exact physical site order seen in the vendor's
    // 16/24/32-bit packed carry graphs.  Short/multiple chains retain the silicon-qualified (15,1)
    // footprint.  Vendor LCCELL X1001/Y1001 maps to physical route tile X20Y12; its X coordinate
    // advances down the route grid.  A single longer chain therefore uses X20Y12 -> X20Y11 through
    // 25 total stages, or X20Y11 -> X20Y12 -> X20Y10 through 33.
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
        struct CarrySite { int x, y, z; };
        std::vector<CarrySite> sites;
        auto append_tile = [&](int x, int y, int limit = 16) {
            for (int z = 0; z < limit; ++z)
                sites.push_back({x, y, z});
        };
        if (total <= 9) {
            append_tile(15, 1, 9);
        } else if (chains.size() == 1 && total <= 25) {
            append_tile(20, 12);
            append_tile(20, 11, 9);
        } else if (chains.size() == 1 && total <= 33) {
            append_tile(20, 11);
            append_tile(20, 12);
            append_tile(20, 10, 1);
        } else {
            log_error("agrv2k: dedicated carry requires %ld slices across %ld chain(s), but the "
                      "qualified vendor-observed corridor supports one chain through 33 stages or "
                      "multiple same-tile chains through nine stages (including seeds)\n",
                      long(total), long(chains.size()));
        }
        std::vector<std::pair<CellInfo *, Loc>> clustered;
        size_t slot = 0;
        for (auto &chain : chains) {
            const CarrySite first = sites.at(slot);
            for (CellInfo *ci : chain) {
                const CarrySite site = sites.at(slot++);
                clustered.push_back({ci, Loc(site.x, site.y, site.z)});
            }
            const CarrySite last = sites.at(slot - 1);
            log_info("  carry chain: clustered %ld cells in relative shape "
                     "X%dY%d_SLICE%d to X%dY%d_SLICE%d\n",
                     long(chain.size()), first.x, first.y, first.z, last.x, last.y, last.z);
        }
        // All chains that shared the old nine-site footprint remain one
        // cluster, preserving their mutual offsets as well as each dedicated
        // carry chain.  Long footprints similarly retain their exact seam
        // shape.  Only the X/Y origin is released to the placer.
        make_relative_cluster(clustered, true);
        log_info("  carry placement: %ld chain(s), %ld cells clustered in qualified relative shape\n",
                 long(chains.size()), long(total));
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

// Internal BEL ids 20..22 are already the qualified AHB input signals.  Keep
// the original read ids 10..19 stable, then continue the remaining hrdata
// lanes at 23 so input and output cells never collapse into a bidirectional
// BEL merely because their internal ids collide.
static int hrdata_bel_bit(int k)
{
    if (k >= 0 && k <= 9)
        return 10 + k;
    if (k >= 10 && k <= 31)
        return 13 + k;
    return -1;
}

static int hwdata_bel_bit(int k)
{
    if (k == 0)
        return 20; // preserve the already public/qualified hwdata[0] BEL id
    if (k >= 1 && k <= 31)
        return 44 + k; // 45..75, clear of hrdata 10..44 and controls 21..22
    return -1;
}

static int haddr_bel_bit(int k)
{
    if (k >= 2 && k <= 27)
        return 74 + k; // 76..101, retained for compatibility
    if (k == 0 || k == 1)
        return 112 + k;
    if (k >= 28 && k <= 31)
        return 86 + k; // 114..117
    return -1;
}

// ---- G23 (2026-08-20): EXACT fabric->MCU boundary lane tables.
//
// The fabric-master (slave_ahb) payload lanes have fixed boundary bels exactly
// as the hrdata lanes do.  The mapping is vendor-derived and confirmed four
// independent ways:
//   1. tools/wide_boundary_witness/route_tx_decoded.txt   (reference backend, seed 666)
//   2. tools/indep_ahb_oracle/run_b666/route_decoded.txt    (64/64 lanes)
//   3. tools/indep_ahb_oracle/run_b1234/route_decoded.txt   (64/64 lanes)
//   4. examples/designs/mcu_slave_ahb_request_payload_shared_low_route_smoke.v,
//      which already hard-pins these very bels with (* BEL="..." *)
// and it agrees with the emitted dev_belpins.csv for all 64 lanes:
//   slave_ahb_haddr[k]  -> X0Y5_SinkMUXPseudo(45+k) -> bel X10Y5_MCU_DOUT(176+k)
//   slave_ahb_hwdata[k] -> X0Y5_SinkMUXPseudo(77+k) -> bel X10Y5_MCU_DOUT(208+k)
// Before this, such cells matched no name rule, were skipped with a warning and
// fell through to the generic placer -- 2 misplaced lanes at WIDTH=1 but 64 of
// 128 at WIDTH=32, so no wide-boundary comparison against the vendor was valid.
static int slave_haddr_bel_bit(int k)
{
    return (k >= 0 && k <= 31) ? 176 + k : -1;
}

static int slave_hwdata_bel_bit(int k)
{
    return (k >= 0 && k <= 31) ? 208 + k : -1;
}

// EXACT trailing-token lane parse, replacing parse_hk()'s "first 'h' followed by
// a digit ANYWHERE in the name" scan.  That scan had the [[silent-lookup-miss]]
// shape -- it MIS-BINDS rather than fails: any cell whose name merely contains
// an unrelated 'h'+digit (a hierarchy path through a module called `eth3`, a net
// called `bram_ch0_dout`) bound silently to hrdata[3]/hrdata[0] and scrambled
// the read bits with no diagnostic whatsoever.
//
// The lane index must be a decimal run at the very END of the cell's leaf name,
// immediately preceded by <token>, which must itself begin the leaf name or
// follow a non-alphanumeric separator.  So `mcu_h3`, `haddr31` and `u_hwdata7`
// parse; `eth3`, `out0` and `arch2` do not.  Returns the lane, or -1.
static int parse_lane_suffix(const std::string &name, const std::string &token)
{
    size_t leaf = name.find_last_of("./");
    std::string s = (leaf == std::string::npos) ? name : name.substr(leaf + 1);
    size_t end = s.size();
    if (end == 0 || !std::isdigit((unsigned char)s[end - 1]))
        return -1;
    size_t d = end;
    while (d > 0 && std::isdigit((unsigned char)s[d - 1]))
        --d;
    if (d < token.size() || s.compare(d - token.size(), token.size(), token) != 0)
        return -1;
    size_t t = d - token.size();
    if (t > 0 && std::isalnum((unsigned char)s[t - 1]))
        return -1; // the token is a fragment of a longer word, not a lane name
    return std::atoi(s.c_str() + d);
}

// Which boundary bus an MCU_DOUT cell belongs to, plus its lane index.
enum McuDoutLane
{
    LANE_NONE = 0,
    LANE_HRDATA,
    LANE_SHADDR,
    LANE_SHWDATA
};

static McuDoutLane mcu_dout_lane(const std::string &name, int &bit)
{
    if ((bit = parse_lane_suffix(name, "hwdata")) >= 0)
        return LANE_SHWDATA;
    if ((bit = parse_lane_suffix(name, "haddr")) >= 0)
        return LANE_SHADDR;
    if ((bit = parse_lane_suffix(name, "h")) >= 0)
        return LANE_HRDATA;
    bit = -1;
    return LANE_NONE;
}

static bool is_fabric_ahb_request_control(Context *ctx, const CellInfo *ci)
{
    return ci->type == ctx->id("MCU_SLAVE_AHB_HSEL") ||
           ci->type == ctx->id("MCU_SLAVE_AHB_HREADY") ||
           ci->type == ctx->id("MCU_SLAVE_AHB_HTRANS0") ||
           ci->type == ctx->id("MCU_SLAVE_AHB_HTRANS1") ||
           ci->type == ctx->id("MCU_SLAVE_AHB_HSIZE0") ||
           ci->type == ctx->id("MCU_SLAVE_AHB_HSIZE1") ||
           ci->type == ctx->id("MCU_SLAVE_AHB_HSIZE2") ||
           ci->type == ctx->id("MCU_SLAVE_AHB_HBURST0") ||
           ci->type == ctx->id("MCU_SLAVE_AHB_HBURST1") ||
           ci->type == ctx->id("MCU_SLAVE_AHB_HBURST2") ||
           ci->type == ctx->id("MCU_SLAVE_AHB_HWRITE");
}

static bool is_exact_fabric_ahb_safe_low(Context *ctx, NetInfo *net)
{
    if (net == nullptr || net->driver.cell == nullptr || net->driver.port != ctx->id("F"))
        return false;
    CellInfo *driver = net->driver.cell;
    if (driver->type != ctx->id("GENERIC_SLICE") ||
        int_or_default(driver->params, ctx->id("INIT"), -1) != 0 ||
        int_or_default(driver->params, ctx->id("FF_USED"), 0) != 0)
        return false;
    auto requested = driver->attrs.find(ctx->id("BEL"));
    return requested != driver->attrs.end() &&
           requested->second.as_string() == "X14Y12_SLICE0";
}

static void guard_fabric_ahb_request_controls(Context *ctx)
{
    NetInfo *shared = nullptr;
    int controls = 0;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (!is_fabric_ahb_request_control(ctx, ci))
            continue;
        auto dout = ci->ports.find(ctx->id("DOUT"));
        NetInfo *net = dout == ci->ports.end() ? nullptr : dout->second.net;
        // CLAIM: mcu-ahb-request-control-shared-source-oracle (agamemnon.engine.gate_claims)
        // Only the pinned combinational safe-low source has a complete exact
        // simultaneous route.  A non-idle or independently sourced control is
        // a protocol-capable fabric master and must not reach placement until
        // an independent-source oracle and silicon qualification exist.
        if (!is_exact_fabric_ahb_safe_low(ctx, net))
            log_error("agrv2k: fabric AHB master request control '%s' is not driven by the "
                      "exact X14Y12_SLICE0 shared safe-low oracle; non-idle and independently "
                      "sourced controls are unqualified and fail closed\n",
                      ci->name.c_str(ctx));
        if (shared != nullptr && shared != net)
            log_error("agrv2k: fabric AHB master request controls use independent sources; only "
                      "the exact shared safe-low oracle is qualified and all transactions fail "
                      "closed\n");
        shared = net;
        ++controls;
    }
    if (controls)
        log_info("agrv2k: admitted %d fabric AHB request control(s) on the exact shared safe-low "
                 "oracle\n", controls);
}

// Vendor boundary row for a lane, from tools/wide_boundary_witness/
// witness_corridors.txt (the x=13 sink column of the closed reference build):
//   hrdata[0..12]  -> (13,12)   hrdata[13..31] -> (13,11)
//   s_haddr[0..3]  -> (13,10)   s_haddr[4..18] -> (13,9)   s_haddr[19..31] -> (13,8)
//   s_hwdata[0..1] -> (13,8)    s_hwdata[2..17]-> (13,7)   s_hwdata[18..31]-> (13,6)
// Used to steer the driver slice in the x=14 column next to its own exit.
static int mcu_dout_exit_row(McuDoutLane kind, int bit)
{
    switch (kind) {
    case LANE_HRDATA:
        return bit <= 12 ? 12 : 11;
    case LANE_SHADDR:
        return bit <= 3 ? 10 : (bit <= 18 ? 9 : 8);
    case LANE_SHWDATA:
        return bit <= 1 ? 8 : (bit <= 17 ? 7 : 6);
    default:
        return 12;
    }
}

static int parse_after(const std::string &s, const std::string &marker)
{
    size_t p = s.find(marker);
    if (p == std::string::npos)
        return -1;
    p += marker.size();
    return p < s.size() && std::isdigit((unsigned char)s[p]) ? std::atoi(s.c_str() + p) : -1;
}

// ---- pack: bind MCU edge cells to their fixed bus lanes BY NAME. The fabric->MCU readout lanes are
// fixed by mcu_hrdata_lanes.csv; a cell named mcu_h<k> reads out on hrdata[k] (0x60000000 bit k), so we
// must bind by name -- nextpnr's arbitrary placement would scramble the read bits.  The three qualified
// MCU_DIN bels are likewise not interchangeable: DIN20=hwdata[0], DIN21=hwrite, DIN22=htrans[1].  Binding
// the conventional instance names used by the public AHB examples prevents a store-data/control scramble.
// All 32 lanes are vendor-route recovered; release routing still fails closed on any edge without an
// exact selector encoding.
static void pack_mcu_edge(Context *ctx)
{
    guard_fabric_ahb_request_controls(ctx);
    long nout = 0, nin = 0, nresp = 0, nslave = 0, npinned = 0;
    std::vector<std::string> skipped_dout;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        std::string name = ci->name.str(ctx);
        std::string bn;
        bool is_slave_lane = false;
        if (ci->type == ctx->id("MCU_DOUT")) {
            // An explicit (* keep, BEL="X10Y5_MCU_DOUT<n>" *) constraint wins:
            // the shared-low route smoke example pins all 64 slave-payload
            // lanes that way and must keep working untouched.
            if (ci->attrs.count(ctx->id("BEL"))) {
                ++npinned;
                continue;
            }
            int lane = -1;
            int k = parse_lane_suffix(name, "hwdata");
            if (k >= 0) {
                lane = slave_hwdata_bel_bit(k);
                if (lane < 0)
                    log_error("agrv2k: MCU_DOUT cell '%s' requests slave_ahb_hwdata[%d], valid "
                              "range is 0..31\n", name.c_str(), k);
                is_slave_lane = true;
            } else if ((k = parse_lane_suffix(name, "haddr")) >= 0) {
                lane = slave_haddr_bel_bit(k);
                if (lane < 0)
                    log_error("agrv2k: MCU_DOUT cell '%s' requests slave_ahb_haddr[%d], valid "
                              "range is 0..31\n", name.c_str(), k);
                is_slave_lane = true;
            } else if ((k = parse_lane_suffix(name, "h")) >= 0) {
                lane = hrdata_bel_bit(k);
                if (lane < 0)
                    log_error("agrv2k: MCU_DOUT cell '%s' requests hrdata[%d], valid range is "
                              "0..31\n", name.c_str(), k);
            } else {
                // FAIL CLOSED (G23).  An unrecognised MCU_DOUT name used to be
                // skipped with a warning and handed to the generic placer --
                // that is how 64 of 128 wide boundary lanes ended up at
                // arbitrary sites and silently invalidated the vendor
                // comparison.  AGRV2K_ALLOW_UNBOUND_MCU_DOUT=1 restores the old
                // lenient path for workbench probes that deliberately use a
                // generic MCU_DOUT with no lane meaning (for example
                // tools/lab/directd_phase_probe.v's `out0`).
                if (std::getenv("AGRV2K_ALLOW_UNBOUND_MCU_DOUT") != nullptr) {
                    skipped_dout.push_back(name);
                    continue;
                }
                log_error("agrv2k: MCU_DOUT cell '%s' has no recognised boundary lane. Name it "
                          "<..>h<k> for hrdata[k], <..>haddr<k> for slave_ahb_haddr[k], or "
                          "<..>hwdata<k> for slave_ahb_hwdata[k] (k=0..31), or pin it with "
                          "(* BEL=\"X10Y5_MCU_DOUT<n>\" *). Set AGRV2K_ALLOW_UNBOUND_MCU_DOUT=1 "
                          "to fall back to the generic placer instead -- the lane will then NOT "
                          "land on its vendor boundary bel.\n",
                          name.c_str());
            }
            bn = "X10Y5_MCU_DOUT" + std::to_string(lane);
        } else if (ci->type == ctx->id("MCU_DIN")) {
            int lane = -1;
            int hwbit = parse_after(name, "hwdata");
            int habit = parse_after(name, "haddr");
            if (habit >= 0)
                lane = haddr_bel_bit(habit);
            else if (hwbit >= 0)
                lane = hwdata_bel_bit(hwbit);
            else if (name.find("hwrite") != std::string::npos)
                lane = 21;
            else if (name.find("htrans1") != std::string::npos)
                lane = 22;
            if (lane < 0)
                log_error("agrv2k: MCU_DIN cell '%s' has no known AHB input lane\n", name.c_str());
            bn = "X10Y5_MCU_DIN" + std::to_string(lane);
        } else if (ci->type == ctx->id("MCU_AHB_HREADY") ||
                   ci->type == ctx->id("MCU_AHB_HREADYOUT") ||
                   ci->type == ctx->id("MCU_AHB_HRESP")) {
            // Fabric-driven External-AHB response controls have one fixed typed
            // bel each.  Bind them during pack — like the hrdata lanes — so the
            // joint exit-anchor matching and corridor locker can reserve the
            // response sources and the 32 read-data lanes as one problem.
            BelId tb;
            for (BelId cand : ctx->getBels())
                if (ctx->getBelType(cand) == ci->type) {
                    tb = cand;
                    break;
                }
            if (tb == BelId())
                log_error("agrv2k: no bel of type '%s' for cell '%s' (built without MCU features?)\n",
                          ci->type.c_str(ctx), name.c_str());
            bn = ctx->getBelName(tb).str(ctx);
        } else {
            continue;
        }
        BelId b = ctx->getBelByName(IdStringList(ctx->id(bn)));
        if (b != BelId() && ctx->checkBelAvail(b)) {
            ctx->bindBel(b, ci, STRENGTH_LOCKED);
            if (ci->type == ctx->id("MCU_DOUT")) {
                if (is_slave_lane)
                    ++nslave;
                else
                    ++nout;
            }
            else if (ci->type == ctx->id("MCU_DIN") || ci->type == ctx->id("MCU_AHB_HREADY"))
                ++nin;
            else
                ++nresp;
        } else {
            log_error("agrv2k: fixed MCU bus bel '%s' is unavailable for cell '%s'\n",
                      bn.c_str(), name.c_str());
        }
    }
    if (nout)
        log_info("agrv2k: bound %ld MCU_DOUT exit cell(s) to hrdata lanes by name\n", nout);
    if (nslave)
        log_info("agrv2k: bound %ld MCU_DOUT cell(s) to slave_ahb haddr/hwdata boundary lanes "
                 "by name\n", nslave);
    if (npinned)
        log_info("agrv2k: %ld MCU_DOUT cell(s) carry an explicit BEL constraint\n", npinned);
    if (nin)
        log_info("agrv2k: bound %ld MCU_DIN entry cell(s) to AHB lanes by name\n", nin);
    if (nresp)
        log_info("agrv2k: bound %ld AHB response control cell(s) to typed bels\n", nresp);
    if (!skipped_dout.empty()) {
        std::string joined;
        for (size_t i = 0; i < skipped_dout.size(); ++i) {
            if (i)
                joined += ", ";
            joined += skipped_dout[i];
        }
        log_warning("agrv2k: %d MCU_DOUT cell(s) left to the generic placer via "
                    "AGRV2K_ALLOW_UNBOUND_MCU_DOUT -- these lanes do NOT land on their vendor "
                    "boundary bels: %s\n",
                    int(skipped_dout.size()), joined.c_str());
    }
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
        // memory_libmap leaves the unused half of a single-port memory tied to
        // constants, including ReB=1 in the generic wrapper. If none of the
        // Port-B outputs has a consumer and WeB is absent/zero, the entire B
        // input surface is a hardware don't-care. Disconnect it instead of
        // consuming scarce strict BRAM-approach corridors with fabric constant
        // drivers. A write-only direct primitive remains intact because WeB
        // is then nonzero.
        bool port_b_read_used = false;
        for (auto &p : ci->ports) {
            if (p.first.str(ctx).rfind("DataOutB[", 0) != 0 || p.second.net == nullptr)
                continue;
            if (!p.second.net->users.empty()) {
                port_b_read_used = true;
                break;
            }
        }
        NetInfo *we_b = ci->getPort(ctx->id("WeB"));
        bool port_b_write_used = we_b != nullptr &&
                                 (gnd_net == IdString() || we_b->name != gnd_net);
        if (!port_b_read_used && !port_b_write_used) {
            for (auto &p : ci->ports) {
                if (p.second.type != PORT_IN || p.second.net == nullptr)
                    continue;
                std::string name = p.first.str(ctx);
                if (name.rfind("AddressB[", 0) == 0 ||
                    name.rfind("DataInB[", 0) == 0 ||
                    name.rfind("ByteEnB[", 0) == 0 ||
                    name == "WeB" || name == "ReB" || name == "Clk1" ||
                    name == "ClkEn1" || name == "AsyncReset1")
                    drop.push_back(p.first);
            }
            log_info("agrv2k: unused BRAM Port B -> disconnected constant input surface\n");
        }
        std::sort(drop.begin(), drop.end());
        drop.erase(std::unique(drop.begin(), drop.end()), drop.end());
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
            int data_a_bit = -1, data_b_bit = -1;
            bool data_a = std::sscanf(pin_name.c_str(), "DataInA[%d]", &data_a_bit) == 1;
            bool data_b = std::sscanf(pin_name.c_str(), "DataInB[%d]", &data_b_bit) == 1;
            const bool default_high_suffix = pr.second &&
                    ((addr_a && addr_a_bit < suffix_bits(active_a)) ||
                     (addr_b && addr_b_bit < suffix_bits(active_b)));
            const bool default_high_data = pr.second &&
                    ((data_a && data_a_bit < active_a) ||
                     (data_b && data_b_bit < active_b));
            const bool is_write_enable =
                    pin_name.rfind("WeA", 0) == 0 || pin_name.rfind("WeB", 0) == 0;
            const bool characterized_control =
                    pin_name.rfind("ReA", 0) == 0 || pin_name.rfind("ReB", 0) == 0 ||
                    is_write_enable ||
                    pin_name.rfind("ByteEnA", 0) == 0 || pin_name.rfind("ByteEnB", 0) == 0 ||
                    pin_name.rfind("ClkEn0", 0) == 0 || pin_name.rfind("ClkEn1", 0) == 0;
            // A constant-HIGH We*/WeB is an unconditional write.  The generic control blob
            // (bram_rom_ctrl.csv vs bram_dual_ctrl.csv, chosen in features/bram.py from
            // portb_read + WeA-connectivity) has only a write-DISABLED baseline for an
            // ordinary single-port memory.  Silently disconnecting this pin here -- as the
            // branch below does for every other characterized control default -- removes the
            // ONLY signal downstream bitgen has that a write was ever intended: the emitted
            // image quietly comes out as the ROM control blob (write permanently off) no
            // matter what the RTL asked for.  This exact shape (inferred BRAM write, constant
            // tied write-enable, no live Port-B read) has never been silicon-qualified for the
            // generic control-blob path -- refuse instead of guessing.  Route a dynamic
            // write-enable, exercise Port-B read alongside it, or use a
            // --qualified-bram-write profile for the individually qualified corridor.
            if (hardconst && is_write_enable && pr.second) {
                log_error(
                    "agrv2k: BRAM pin '%s' is tied to a constant 1 (an unconditional "
                    "write-enable). The generic control-blob path has no silicon-qualified "
                    "write-enabled default for this shape, so silently dropping it would fold "
                    "the image to the read-only ROM control blob. Route a dynamic "
                    "write-enable signal, pair the write with a live Port-B read, or use "
                    "--qualified-bram-write.\n",
                    pin_name.c_str());
            }
            if (hardconst &&
                    (!pr.second || characterized_control || default_high_suffix ||
                     default_high_data)) {
                // The BRAM control/default blob supplies fixed Re/ByteEn/ClkEn and the unused
                // address/data inputs default low.  The vendor's width adapter appends constant-one
                // address suffixes (x18:4, x9:3, x4:2, x2:1); its routed netlist has no path for those
                // pins because the BRAM input defaults realize the ones internally.  Routing a fabric
                // constant instead both wastes the narrow boundary and can select a dead terminal hop.
                // A controlled x9 vendor delta likewise shows an active constant-high DataIn pin as
                // direct VCC with no routed VCC net: its BRAM IMUX remains at the unselected HIGH
                // default, while constant LOW explicitly selects the shared GND tree.
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
    struct PinCandidate { int score; BelId bel; };
    struct PinItem {
        IdString port;
        CellInfo *drv;
        std::vector<PinCandidate> candidates;
        int address_a_bit = -1;
        int address_b_bit = -1;
        int data_a_bit = -1;
        bool write_a = false;
        bool clken1 = false;
    };
    std::vector<PinItem> items;
    for (auto &c : ctx->cells) {
        CellInfo *bram = c.second.get();
        if (bram->type != ctx->id("ALTA_BRAM9K"))
            continue;
        BelId bram_bel = bram->bel;
        auto requested_bram = bram->attrs.find(ctx->id("BEL"));
        if (bram_bel == BelId() && requested_bram != bram->attrs.end())
            bram_bel = ctx->getBelByNameStr(requested_bram->second.as_string());
        if (bram_bel == BelId())
            bram_bel = ctx->getBelByNameStr("X13Y4_BRAM");
        if (bram_bel == BelId())
            continue;
        Loc bloc = ctx->getBelLocation(bram_bel);
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
                        dx == bloc.x && dy == bloc.y &&
                        (sx != bloc.x || sy != bloc.y))
                        entry_tiles.insert((sx << 16) ^ (sy & 0xffff));
                    if (reach.insert(src).second)
                        q.push_back(src);
                }
            }
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
            int data_a_bit = -1;
            bool exact_data_a = std::sscanf(p.first.str(ctx).c_str(), "DataInA[%d]", &data_a_bit) == 1 &&
                                data_a_bit >= 0 && data_a_bit <= 1;
            bool exact_write_a = p.first == ctx->id("WeA");
            bool exact_clken1 = p.first == ctx->id("ClkEn1");
            PinItem item{p.first, drv, {}, exact_porta ? address_a_bit : -1,
                         exact_portb ? address_b_bit : -1,
                         exact_data_a ? data_a_bit : -1, exact_write_a, exact_clken1};
            auto requested_bel = drv->attrs.find(ctx->id("BEL"));
            for (BelId b : ctx->getBels()) {
                if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE") || !ctx->checkBelAvail(b))
                    continue;
                if (requested_bel != drv->attrs.end() &&
                        ctx->getBelName(b).str(ctx) != requested_bel->second.as_string())
                    continue;
                WireId ow = ctx->getBelPinWire(b, net->driver.port);
                if (ow == WireId() || !reach.count(ow))
                    continue;
                Loc loc = ctx->getBelLocation(b);
                if (exact_porta && bloc == Loc(13, 4, 0) &&
                        loc != porta_addr_source[address_a_bit])
                    continue;
                if (exact_portb && bloc == Loc(13, 4, 0) &&
                        loc != portb_addr_source[address_b_bit])
                    continue;
                // A routed BRAM terminal is not sufficient evidence that an
                // arbitrary source slot is selected by the frozen dual-port
                // control/selector image.  The qualified dependent SERV store
                // proves these three Q-output footprints together on silicon:
                //   DataInA[0] = X14Y4_SLICE4  / OMUX14
                //   DataInA[1] = X14Y4_SLICE13 / OMUX41
                //   WeA        = X15Y4_SLICE0  / OMUX02
                // Keep write builds on that measured source tuple.  This is
                // the BRAM analogue of the source-dependent pad-feed rule: a
                // clean route through another reachable source is not enough.
                const std::array<Loc, 2> serv_data_a_source = {
                    Loc(14, 4, 4), Loc(14, 4, 13)
                };
                if (exact_data_a && bloc == Loc(13, 4, 0) &&
                        loc != serv_data_a_source[data_a_bit])
                    continue;
                bool experimental_control =
                        std::getenv("AGAMEMNON_BRAM_SITE_READ_PATHS") != nullptr &&
                        drv->attrs.count(ctx->id("AGRV2K_ROUTE_THROUGH")) != 0;
                if (exact_write_a && !experimental_control &&
                        bloc == Loc(13, 4, 0) && loc != Loc(15, 4, 0))
                    continue;
                if (exact_clken1 && bloc == Loc(13, 4, 0) && loc != Loc(14, 4, 5))
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
                    if (item.data_a_bit >= 0)
                        prior->data_a_bit = item.data_a_bit;
                    prior->write_a = prior->write_a || item.write_a;
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
        // The requested BEL was consumed by this packer.  Leaving the source
        // attribute behind makes generic constraint placement try to bind the
        // same cell a second time and reject its own locked assignment.
        items[ii].drv->attrs.erase(ctx->id("BEL"));
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
    // The native x9 MCU-address oracle has a retained, simultaneous path for
    // every active AddressA lane.  Replaying those rows is both stricter and
    // more reliable than a fresh BFS: the latter can reject a legal first
    // hop after the MCU entry anchor has already reserved the source wire.
    // This does not add graph resources; every named pip must already exist
    // in the gated device database and be available for the same net.
    std::unordered_map<int, std::vector<std::pair<std::string, std::string>>> x9_exact;
    std::vector<std::pair<std::string, std::string>> x9_data4_pair_exact;
    std::unordered_map<std::string,
            std::vector<std::pair<std::string, std::string>>> site_read_exact;
    // Complete Port-A write-ingress branches from the dependent SERV store
    // that is already qualified on silicon.  Source BEL selection alone is
    // insufficient: several strict-graph routes reach the same BramTile pin,
    // but only these simultaneous source-to-terminal branches have a live
    // write witness.  Locking them also keeps the write oracle from silently
    // changing one of the source-dependent selector codewords.
    std::unordered_map<std::string,
            std::vector<std::pair<std::string, std::string>>> serv_write_exact;
    // The bounded x18 source-build profile exposes only its measured routing
    // graph.  Router2 owns the initial route; the CLI subsequently proves the
    // measured trees do not collide with any other routed net and replaces
    // those trees atomically before strict bitgen.
    const char *tmux9_profile = std::getenv("AGAMEMNON_BRAM_TMUX9_SOURCE_PROFILE");
    const bool tmux9_source = tmux9_profile != nullptr;
    const bool site_read_profile =
            std::getenv("AGAMEMNON_BRAM_SITE_READ_PATHS") != nullptr;
    const char *data_dir = std::getenv("AGAMEMNON_DATA");
    if (data_dir != nullptr) {
        std::ifstream write_paths(std::string(data_dir) + "/bram_serv_write_paths.csv");
        std::string line;
        std::getline(write_paths, line);
        while (std::getline(write_paths, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            std::vector<std::string> f; std::string field; std::istringstream row(line);
            while (std::getline(row, field, ',')) f.push_back(field);
            if (f.size() >= 4)
                serv_write_exact[f[0]].push_back({f[2], f[3]});
        }
        std::ifstream paths(std::string(data_dir) + "/bram_x9_haddr_paths.csv");
        std::getline(paths, line);
        while (std::getline(paths, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            std::vector<std::string> f; std::string field; std::istringstream row(line);
            while (std::getline(row, field, ',')) f.push_back(field);
            if (f.size() >= 7 && f[1] == "AddressA")
                x9_exact[to_int(f[2], -1)].push_back({f[4], f[5]});
        }
        std::ifstream data4_paths(std::string(data_dir) + "/bram_x9_data4_simultaneous_paths.csv");
        std::getline(data4_paths, line);
        while (std::getline(data4_paths, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            std::vector<std::string> f; std::string field; std::istringstream row(line);
            while (std::getline(row, field, ',')) f.push_back(field);
            if (f.size() >= 3 && f[0] == "4")
                x9_data4_pair_exact.push_back({f[1], f[2]});
        }
        if (site_read_profile) {
            std::ifstream site_paths(std::string(data_dir) + "/bram_site_read_paths.csv");
            std::getline(site_paths, line);
            while (std::getline(site_paths, line)) {
                if (!line.empty() && line.back() == '\r') line.pop_back();
                std::vector<std::string> f; std::string field; std::istringstream row(line);
                while (std::getline(row, field, ',')) f.push_back(field);
                if (f.size() >= 6)
                    site_read_exact[f[1]].push_back({f[4], f[5]});
            }
        }
    }
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
        // DataInA[0]/[1]/WeA carry a genuinely exact, source-matching witness
        // (bram_serv_write_paths.csv) over a resource-scarce approach to the
        // BRAM (the X14Y4/X15Y4 RMUX neighborhood). The remaining
        // AddressA[3..12] bits are only *sometimes* resolved by their own
        // exact table (bram_x9_haddr_paths.csv assumes an MCU-side X13Y12
        // entry point that a fresh, internally-driven design such as SERV
        // never matches), so an unmatched AddressA bit silently falls
        // through to the unconstrained generic BFS below and can greedily
        // consume a pip DataInA/WeA's real exact witness needs -- observed
        // on fresh serv_blinky as "SERV DataInA[0] corridor conflict at
        // X14Y4_RMUX15 -> X15Y4_RMUX63", claimed first by AddressA[4]'s BFS
        // fallback. Claim the genuinely exact, scarce DataInA/WeA corridor
        // before AddressA[3..12] so the BFS is forced to route any
        // source-mismatched AddressA bit around it instead of colliding
        // with it.
        ports.push_back(ctx->id("DataInA[0]"));
        ports.push_back(ctx->id("DataInA[1]"));
        ports.push_back(ctx->id("WeA"));
        for (int bit = 3; bit <= 12; ++bit)
            ports.push_back(ctx->id("AddressA[" + std::to_string(bit) + "]"));
        ports.push_back(ctx->id("DataInA[2]"));
        if (site_read_profile) {
            ports.push_back(ctx->id("ReA"));
            ports.push_back(ctx->id("ClkEn0"));
        }
        ports.push_back(ctx->id("ClkEn1"));
        for (IdString port : ports) {
            NetInfo *net = bram->getPort(port);
            if (net == nullptr || net->driver.cell == nullptr)
                continue;
            if (tmux9_source && port == ctx->id("WeA"))
                continue; // scoped graph plus post-route tree owns qualified WeA
            WireId source = ctx->getBelPinWire(net->driver.cell->bel, net->driver.port);
            // The newly qualified RMUX82 ingress is source-dependent.  The
            // four blocked x9 probes all drive DataInA[2] from OMUX29; older
            // OMUX11 probes already route simultaneously through RMUX28, and
            // forcing those onto the OMUX29 corridor displaces DataOutB[15].
            if (port == ctx->id("DataInA[2]") &&
                    ctx->getWireName(source).str(ctx) != "X14Y4_OMUX29")
                continue;
            BelId bram_bel = bram->bel;
            auto requested_bram = bram->attrs.find(ctx->id("BEL"));
            if (bram_bel == BelId() && requested_bram != bram->attrs.end())
                bram_bel = ctx->getBelByNameStr(requested_bram->second.as_string());
            if (bram_bel == BelId())
                bram_bel = ctx->getBelByNameStr("X13Y4_BRAM");
            WireId target = ctx->getBelPinWire(bram_bel, port);
            int address_a_bit = -1;
            bool exact_done = false;
            std::string route_net;
            if (std::sscanf(port.c_str(ctx), "AddressA[%d]", &address_a_bit) == 1 &&
                    address_a_bit >= 4 && address_a_bit <= 12)
                route_net = "mem_ahb_haddr[" + std::to_string(address_a_bit - 2) + "]";
            else if (site_read_profile && port == ctx->id("ClkEn0"))
                route_net = "mem_ahb_hready";
            else if (site_read_profile &&
                    (port == ctx->id("WeA") || port == ctx->id("ReA")))
                route_net = "mem_ahb_hwrite";
            if (!route_net.empty()) {
                auto exact = site_read_exact.find(route_net);
                if (exact != site_read_exact.end()) {
                    std::string source_name = ctx->getWireName(source).str(ctx);
                    std::string target_name = ctx->getWireName(target).str(ctx);
                    std::unordered_map<std::string,
                            std::vector<std::pair<std::string, PipId>>> adjacency;
                    for (const auto &edge : exact->second) {
                        PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
                        if (pip != PipId())
                            adjacency[edge.first].push_back({edge.second, pip});
                    }
                    std::vector<std::string> queue{source_name};
                    std::unordered_map<std::string,
                            std::pair<std::string, PipId>> previous;
                    previous[source_name] = {"", PipId()};
                    for (size_t head = 0;
                            head < queue.size() && !previous.count(target_name); ++head) {
                        for (const auto &step : adjacency[queue[head]]) {
                            if (previous.count(step.first) ||
                                    !ctx->checkPipAvailForNet(step.second, net))
                                continue;
                            previous[step.first] = {queue[head], step.second};
                            queue.push_back(step.first);
                        }
                    }
                    if (previous.count(target_name)) {
                        std::vector<PipId> route;
                        for (std::string cursor = target_name; cursor != source_name;
                                cursor = previous.at(cursor).first)
                            route.push_back(previous.at(cursor).second);
                        std::reverse(route.begin(), route.end());
                        for (PipId pip : route) {
                            ctx->bindPip(pip, net, STRENGTH_LOCKED);
                            ++locked;
                        }
                        exact_done = true;
                        log_info("agrv2k: pre-routed %s over %d exact four-site pip(s)\n",
                                 port.c_str(ctx), int(route.size()));
                    }
                }
            }
            if (exact_done)
                continue;
            auto serv_path = serv_write_exact.find(port.str(ctx));
            if (serv_path != serv_write_exact.end()) {
                std::string cursor = ctx->getWireName(source).str(ctx);
                const std::string target_name = ctx->getWireName(target).str(ctx);
                int exact_locked = 0;
                for (const auto &edge : serv_path->second) {
                    if (edge.first != cursor)
                        log_error("agrv2k: SERV %s source/path mismatch at %s -> %s\n",
                                  port.c_str(ctx), cursor.c_str(), edge.first.c_str());
                    PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
                    if (pip == PipId())
                        log_error("agrv2k: SERV %s pip absent: %s -> %s\n",
                                  port.c_str(ctx), edge.first.c_str(), edge.second.c_str());
                    if (!ctx->checkPipAvailForNet(pip, net))
                        log_error("agrv2k: SERV %s corridor conflict at %s -> %s\n",
                                  port.c_str(ctx), edge.first.c_str(), edge.second.c_str());
                    ctx->bindPip(pip, net, STRENGTH_LOCKED);
                    ++locked; ++exact_locked; cursor = edge.second;
                }
                if (cursor != target_name)
                    log_error("agrv2k: SERV %s path ends at %s, expected %s\n",
                              port.c_str(ctx), cursor.c_str(), target_name.c_str());
                exact_done = true;
                log_info("agrv2k: pre-routed %s over %d exact SERV pip(s)\n",
                         port.c_str(ctx), exact_locked);
            }
            if (std::sscanf(port.c_str(ctx), "AddressA[%d]", &address_a_bit) == 1 &&
                    x9_exact.count(address_a_bit)) {
                std::string cursor = ctx->getWireName(source).str(ctx);
                std::string target_name = ctx->getWireName(target).str(ctx);
                bool started = false;
                int exact_locked = 0;
                for (const auto &edge : x9_exact.at(address_a_bit)) {
                    if (!started && edge.first == cursor) started = true;
                    if (!started) continue;
                    if (edge.first != cursor)
                        log_error("agrv2k: discontinuous exact x9 AddressA[%d] path at %s -> %s\n",
                                  address_a_bit, cursor.c_str(), edge.first.c_str());
                    PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
                    if (pip == PipId())
                        log_error("agrv2k: exact x9 AddressA[%d] pip absent: %s -> %s\n",
                                  address_a_bit, edge.first.c_str(), edge.second.c_str());
                    if (!ctx->checkPipAvailForNet(pip, net))
                        log_error("agrv2k: exact x9 AddressA[%d] corridor conflict at %s -> %s\n",
                                  address_a_bit, edge.first.c_str(), edge.second.c_str());
                    ctx->bindPip(pip, net, STRENGTH_LOCKED);
                    ++locked; ++exact_locked; cursor = edge.second;
                    if (cursor == target_name) { exact_done = true; break; }
                }
                if (exact_done)
                    log_info("agrv2k: pre-routed AddressA[%d] over %d exact x9 pip(s)\n",
                             address_a_bit, exact_locked);
            }
            if (exact_done)
                continue;
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
                    // External-AHB MCU_DIN sources sit on y=12.  Retain that
                    // top entry row; the native x9 control then descends through
                    // the same bounded x=12..16 corridor to the BRAM at y=4.
                    if (std::sscanf(name.c_str(), "X%dY%d_", &x, &y) != 2 ||
                        x < 12 || x > 16 ||
                        y < (site_read_profile ? 1 : 4) || y > 12)
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

        // The arbitrary-site qualification tops observe DataOutA[0] on the
        // same per-site HRDATA lanes as the full-depth four-array silicon
        // oracle.  Lock that complete measured exit tree too.  Leaving only
        // the first hop constrained allowed router2 to choose a nearby but
        // unsensitized middle row (Y8 instead of the observed Y9 at Y1); the
        // image configured successfully but returned a constant zero.
        NetInfo *read_data = bram->getPort(ctx->id("DataOutA[0]"));
        if (read_data != nullptr && !read_data->users.empty()) {
            BelId bram_bel = bram->bel;
            auto requested_bram = bram->attrs.find(ctx->id("BEL"));
            if (bram_bel == BelId() && requested_bram != bram->attrs.end())
                bram_bel = ctx->getBelByNameStr(requested_bram->second.as_string());
            Loc bram_loc = ctx->getBelLocation(bram_bel);
            int hrdata_bit = -1;
            if (bram_loc.x == 13) {
                if (bram_loc.y == 4) hrdata_bit = 0;
                if (bram_loc.y == 1) hrdata_bit = 8;
                if (bram_loc.y == 2) hrdata_bit = 16;
                if (bram_loc.y == 3) hrdata_bit = 24;
            }
            std::string route_net = "mem_ahb_hrdata[" +
                                    std::to_string(hrdata_bit) + "]";
            auto exact = site_read_exact.find(route_net);
            if (hrdata_bit >= 0 && exact != site_read_exact.end()) {
                std::unordered_map<std::string,
                        std::vector<std::pair<std::string, PipId>>> adjacency;
                for (const auto &edge : exact->second) {
                    PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
                    if (pip != PipId())
                        adjacency[edge.first].push_back({edge.second, pip});
                }
                const std::string source_name = ctx->getWireName(
                        ctx->getBelPinWire(bram_bel, ctx->id("DataOutA[0]"))).str(ctx);
                for (auto &user : read_data->users) {
                    if (user.cell == nullptr || user.cell->bel == BelId() ||
                            user.cell->type != ctx->id("MCU_DOUT"))
                        continue;
                    const std::string target_name = ctx->getWireName(
                            ctx->getBelPinWire(user.cell->bel, user.port)).str(ctx);
                    std::vector<std::string> queue{source_name};
                    std::unordered_map<std::string,
                            std::pair<std::string, PipId>> previous;
                    previous[source_name] = {"", PipId()};
                    for (size_t head = 0;
                            head < queue.size() && !previous.count(target_name); ++head) {
                        for (const auto &step : adjacency[queue[head]]) {
                            if (previous.count(step.first) ||
                                    !ctx->checkPipAvailForNet(step.second, read_data))
                                continue;
                            previous[step.first] = {queue[head], step.second};
                            queue.push_back(step.first);
                        }
                    }
                    if (!previous.count(target_name))
                        log_error("agrv2k: no exact four-site DataOutA[0] path from %s to %s\n",
                                  source_name.c_str(), target_name.c_str());
                    std::vector<PipId> route;
                    for (std::string cursor = target_name; cursor != source_name;
                            cursor = previous.at(cursor).first)
                        route.push_back(previous.at(cursor).second);
                    std::reverse(route.begin(), route.end());
                    for (PipId pip : route) {
                        ctx->bindPip(pip, read_data, STRENGTH_LOCKED);
                        ++locked;
                    }
                    log_info("agrv2k: pre-routed DataOutA[0] over %d exact four-site pip(s)\n",
                             int(route.size()));
                }
            }
        }
    }
    // One x9 address lane is split by the vendor-observed identity slice.
    // Lock the MCU_DIN-to-slice prefix from the same path table; the suffix
    // above starts at the slice OMUX and ends at the BRAM terminal.
    for (auto &c : ctx->cells) {
        CellInfo *slice = c.second.get();
        if (slice->type != ctx->id("GENERIC_SLICE") || slice->bel == BelId())
            continue;
        for (auto &p : slice->ports) {
            NetInfo *net = p.second.net;
            if (p.second.type != PORT_IN || net == nullptr || net->driver.cell == nullptr ||
                    net->driver.cell->type != ctx->id("MCU_DIN") ||
                    net->driver.cell->bel == BelId())
                continue;
            WireId source = ctx->getBelPinWire(net->driver.cell->bel, net->driver.port);
            WireId target = ctx->getBelPinWire(slice->bel, p.first);
            std::string cursor = ctx->getWireName(source).str(ctx);
            std::string target_name = ctx->getWireName(target).str(ctx);
            for (const auto &entry : x9_exact) {
                std::vector<PipId> route;
                std::string trial = cursor;
                bool started = false, found = false;
                for (const auto &edge : entry.second) {
                    if (!started && edge.first == trial) started = true;
                    if (!started) continue;
                    if (edge.first != trial) break;
                    PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
                    if (pip == PipId()) break;
                    route.push_back(pip); trial = edge.second;
                    if (trial == target_name) { found = true; break; }
                }
                if (!found) continue;
                for (PipId pip : route) {
                    if (!ctx->checkPipAvailForNet(pip, net))
                        log_error("agrv2k: exact split x9 AddressA[%d] prefix conflict at %s\n",
                                  entry.first, ctx->getPipName(pip).str(ctx).c_str());
                    ctx->bindPip(pip, net, STRENGTH_LOCKED); ++locked;
                }
                log_info("agrv2k: pre-routed split AddressA[%d] prefix over %d exact x9 pip(s)\n",
                         entry.first, int(route.size()));
                break;
            }
        }
    }
    // The per-lane q4 and q5 paths both use RMUX92, so a simultaneous design
    // needs the separately qualified q4/BufMUX12 -> RMUX75 corridor.  Reserve
    // that exact path only when both physical x9 outputs are live.  This keeps
    // existing single-lane placement/routing unchanged and makes the paired
    // resource footprint atomic before router2 handles unrelated nets.
    for (auto &c : ctx->cells) {
        CellInfo *bram = c.second.get();
        if (bram->type != ctx->id("ALTA_BRAM9K"))
            continue;
        NetInfo *q4 = bram->getPort(ctx->id("DataOutA[13]"));
        NetInfo *q5 = bram->getPort(ctx->id("DataOutA[14]"));
        if (q4 == nullptr || q5 == nullptr || q4->users.empty() || q5->users.empty())
            continue;
        if (x9_data4_pair_exact.empty())
            log_error("agrv2k: simultaneous x9 q4/q5 requires a qualified q4 corridor\n");
        BelId bram_bel = ctx->getBelByNameStr("X13Y4_BRAM");
        std::string cursor = ctx->getWireName(
                ctx->getBelPinWire(bram_bel, ctx->id("DataOutA[13]"))).str(ctx);
        int pair_locked = 0;
        for (const auto &edge : x9_data4_pair_exact) {
            if (edge.first != cursor)
                log_error("agrv2k: discontinuous simultaneous x9 q4 path at %s -> %s\n",
                          cursor.c_str(), edge.first.c_str());
            PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
            if (pip == PipId())
                log_error("agrv2k: simultaneous x9 q4 pip absent: %s -> %s\n",
                          edge.first.c_str(), edge.second.c_str());
            if (!ctx->checkPipAvailForNet(pip, q4))
                log_error("agrv2k: simultaneous x9 q4 corridor conflict at %s -> %s\n",
                          edge.first.c_str(), edge.second.c_str());
            ctx->bindPip(pip, q4, STRENGTH_LOCKED);
            ++locked; ++pair_locked; cursor = edge.second;
        }
        log_info("agrv2k: pre-routed simultaneous x9 q4 over %d exact pip(s)\n",
                 pair_locked);
    }
    log_info("agrv2k: pre-routed %d mixed-source Port-B corridor pip(s)\n", locked);
}

// Vendor alta_rio lowers a constant-zero bidirectional-pad data input as a
// local IOB tie-off: the retained four-link route contains no fabric data net,
// while the dynamic OE nets alone reach IOMUX06..09.  Preserve that exact
// topology for the characterized left links.  Routing four equivalent GND
// LUTs wastes four long data corridors and, more importantly, conflicts with
// the independently recovered OE trunks.
static void tie_left_link_data_gnd(Context *ctx)
{
    int tied = 0;
    for (auto &kv : ctx->cells) {
        CellInfo *io = kv.second.get();
        if (io->type != ctx->id("GENERIC_IOB") || io->bel == BelId()) continue;
        std::string bel = ctx->getBelName(io->bel).str(ctx);
        if (bel.find("X0Y4_IOB") != 0) continue;
        NetInfo *old = io->getPort(ctx->id("I"));
        if (old == nullptr || old->driver.cell == nullptr ||
            old->driver.cell->name.str(ctx).find("PACKER_GND") == std::string::npos)
            continue;
        io->disconnectPort(ctx->id("I"));
        io->attrs[ctx->id("AGRV2K_IO_DATA_GND")] = Property(1);
        ++tied;
    }
    if (tied)
        log_info("agrv2k: lowered %d left-link data-low input(s) to exact local IOB tie-offs\n", tied);
}

// Bind each physical output-pad driver to a slice BEL whose exact output wire reaches the pad input
// in the loaded graph.  A nearest-tile heuristic is not sufficient for the conduction-gated database:
// the pad approach IMUX can belong to a different connected component from a geometrically close OMUX.
static void pack_output_pin_drivers(Context *ctx)
{
    if (std::getenv("AGRV2K_IO_PINPACK") == nullptr)
        return;
    std::unordered_map<int, std::vector<std::string>> left_corridor;
    const char *data_dir = std::getenv("AGAMEMNON_DATA");
    if (data_dir != nullptr) {
        std::ifstream f(std::string(data_dir) + "/padout_L48_left_corridors.csv");
        std::string line;
        std::getline(f, line);
        while (std::getline(f, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            std::istringstream ss(line); std::string zs, src, dst;
            if (!std::getline(ss, zs, ',') || !std::getline(ss, src, ',') || !std::getline(ss, dst, ','))
                continue;
            int z = std::atoi(zs.c_str()); auto &nodes = left_corridor[z];
            if (nodes.empty()) nodes.push_back(src);
            if (nodes.back() != src)
                log_error("agrv2k: discontinuous PIN_%d left-pad corridor at %s\n", 25 + z, src.c_str());
            nodes.push_back(dst);
        }
    }
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
        // The PIN10 ingress diagnostic intentionally observes the output of a
        // stage whose retained vendor position is X14Y4_SLICE4.  Do not let
        // the generic output-pad convenience packer move that stage next to
        // the observation pad; pack_left_oe_quad() below validates and binds
        // it, then the ordinary router may fan the same net out to the already
        // qualified top-pad output.  The attribute is fail-closed there.
        if (drv->attrs.count(ctx->id("AGRV2K_PIN25_VENDOR_STAGE")) ||
            drv->attrs.count(ctx->id("AGRV2K_PIN10_ENTRY_PROBE")))
            continue;
        WireId target = ctx->getBelPinWire(io->bel, ctx->id("I"));
        if (target == WireId())
            continue;
        // The silicon-positive pintest2 vendor oracle supplies one complete conducting corridor
        // per onboard LED pad.  Bind the driver to that corridor's source
        // slice and lock every pip, avoiding a merely selector-clean alternate
        // path that can still be electrically dead.  z0/z1 use selectable
        // +2 -> +0 OMUX presentations inserted by arch.py.
        int left_z = -1;
        std::string target_name = ctx->getWireName(target).str(ctx);
        if (std::sscanf(target_name.c_str(), "X0Y4_IOMUX%d", &left_z) == 1 &&
                left_z >= 0 && left_z <= 3 && left_corridor.count(left_z)) {
            static const char *source_bels[4] = {
                "X14Y11_SLICE4", "X14Y11_SLICE5", "X14Y11_SLICE6", "X14Y11_SLICE7"
            };
            BelId exact_bel = ctx->getBelByName(IdStringList(ctx->id(source_bels[left_z])));
            if (exact_bel == BelId() || !ctx->checkBelAvail(exact_bel))
                log_error("agrv2k: left-pad source BEL %s is unavailable\n", source_bels[left_z]);
            ctx->bindBel(exact_bel, drv, STRENGTH_LOCKED);
            WireId source = ctx->getBelPinWire(exact_bel, net->driver.port);
            std::string source_name = ctx->getWireName(source).str(ctx);
            const auto &nodes = left_corridor.at(left_z);
            int locked = 0;
            if (source_name != nodes.front()) {
                // Generic nextpnr asserts inside its named-pip lookup when a
                // name is absent. This optional presentation bridge is exactly
                // where two individually qualified features can conflict, so
                // probe the real downhill pips and emit a normal fail-closed
                // diagnostic when the composition has no bridge.
                PipId bridge;
                for (PipId candidate : ctx->getPipsDownhill(source)) {
                    if (ctx->getWireName(ctx->getPipDstWire(candidate)).str(ctx) == nodes.front()) {
                        bridge = candidate;
                        break;
                    }
                }
                if (bridge == PipId())
                    log_error("agrv2k: left-pad output bridge absent: %s -> %s\n",
                              source_name.c_str(), nodes.front().c_str());
                ctx->bindPip(bridge, net, STRENGTH_LOCKED); ++locked;
            }
            for (size_t i = 0; i + 1 < nodes.size(); ++i) {
                std::string pn = nodes[i] + "." + nodes[i + 1];
                PipId pip = ctx->getPipByNameStr(pn);
                if (pip == PipId())
                    log_error("agrv2k: exact left-pad corridor pip absent: %s\n", pn.c_str());
                if (!ctx->checkPipAvailForNet(pip, net))
                    log_error("agrv2k: exact left-pad corridor conflict at %s\n", pn.c_str());
                ctx->bindPip(pip, net, STRENGTH_LOCKED); ++locked;
            }
            drv->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
            ++bound;
            log_info("agrv2k: locked PIN_%d driver '%s' to %s over %d exact pip(s)\n",
                     25 + left_z, drv->name.c_str(ctx), source_bels[left_z], locked);
            continue;
        }
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

// UART TX data and output-enable are two independent hard-source nets which
// meet only at the characterized PIN_10 dynamic-output BEL.  Router2 can fail
// to allocate the pair even though the retained vendor solution is completely
// edge-disjoint.  When (and only when) that exact typed source pair terminates
// at X20Y13_OEPAD1, reserve both checked-in routes atomically before ordinary
// routing.  This adds no topology and every endpoint/pip is verified against
// the active strict device database.
static void lock_uart_tx_corridors(Context *ctx)
{
    const char *data_dir = std::getenv("AGAMEMNON_DATA");
    if (data_dir == nullptr)
        return;

    int uart_cells[3] = {0, 0, 0};
    for (auto &kv : ctx->cells) {
        CellInfo *candidate = kv.second.get();
        for (int i = 0; i < 3; ++i) {
            const std::string prefix = "MCU_UART" + std::to_string(i) + "_";
            if (candidate->type == ctx->id(prefix + "TXD_DATA") ||
                    candidate->type == ctx->id(prefix + "TXD_OE"))
                ++uart_cells[i];
        }
    }
    int controller = -1;
    for (int i = 0; i < 3; ++i) {
        if (uart_cells[i] == 0)
            continue;
        if (controller != -1)
            log_error("agrv2k: mixed UART controller typed composition is not characterized\n");
        controller = i;
    }
    if (controller == -1)
        return;
    const std::string index = std::to_string(controller);
    const std::string controller_name = "UART" + index;
    const std::string signal_prefix = "uart" + index + "_";
    const std::string hard_prefix = "MCU_UART" + index + "_";
    const std::string filename = "mcu_uart" + index + "_tx_l48_paths.csv";

    std::ifstream f(std::string(data_dir) + "/" + filename);
    if (!f.good())
        log_error("agrv2k: missing exact %s corridor table %s\n",
                  controller_name.c_str(), filename.c_str());
    std::map<std::string, std::vector<std::pair<std::string, std::string>>> paths;
    std::string line;
    std::getline(f, line);
    while (std::getline(f, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        std::istringstream ss(line);
        std::vector<std::string> c;
        std::string field;
        while (std::getline(ss, field, ',')) c.push_back(field);
        if (c.size() < 6)
            log_error("agrv2k: malformed %s TX corridor row: %s\n",
                      controller_name.c_str(), line.c_str());
        paths[c[0]].push_back({c[3], c[4]});
    }

    CellInfo *iob = nullptr;
    for (auto &kv : ctx->cells) {
        CellInfo *candidate = kv.second.get();
        if (candidate->type != ctx->id("GENERIC_IOB") || candidate->bel == BelId())
            continue;
        if (ctx->getBelName(candidate->bel).str(ctx) == "X20Y13_OEPAD1") {
            iob = candidate;
            break;
        }
    }
    // A hard UART source may legitimately feed internal fabric logic.  The
    // corridor lock is a physical-PIN_10 composition, not a global primitive
    // restriction, so it is inert unless that exact pad BEL is present.
    if (iob == nullptr)
        return;

    struct Lane {
        std::string signal;
        std::string driver_type;
        std::string iob_port;
    };
    const std::vector<Lane> lanes = {
        {signal_prefix + "txd_data", hard_prefix + "TXD_DATA", "I"},
        {signal_prefix + "txd_oe", hard_prefix + "TXD_OE", "EN"},
    };
    int typed_lanes = 0;
    for (const Lane &lane : lanes) {
        NetInfo *net = iob->getPort(ctx->id(lane.iob_port));
        if (net != nullptr && net->driver.cell != nullptr &&
                net->driver.cell->type == ctx->id(lane.driver_type))
            ++typed_lanes;
    }
    if (typed_lanes == 0)
        return;
    if (typed_lanes != 2)
        log_error("agrv2k: partial %s typed composition (%d/2 lanes)\n",
                  controller_name.c_str(), typed_lanes);
    int locked = 0;
    for (const Lane &lane : lanes) {
        IdString port = ctx->id(lane.iob_port);
        NetInfo *net = iob->getPort(port);
        if (net == nullptr || net->driver.cell == nullptr ||
                net->driver.cell->type != ctx->id(lane.driver_type))
            log_error("agrv2k: X20Y13_OEPAD1.%s requires typed %s driver\n",
                      lane.iob_port.c_str(), lane.driver_type.c_str());
        CellInfo *driver = net->driver.cell;
        auto found = paths.find(lane.signal);
        if (found == paths.end() || found->second.empty())
            log_error("agrv2k: missing exact %s corridor\n", lane.signal.c_str());
        const auto &path = found->second;
        // Viaduct performs hard-macro placement after pack(), but this exact
        // corridor must be reserved during pack() before ordinary routing can
        // claim either lane.  Bind the uniquely typed hard-source BEL whose
        // output is the retained path's first wire.  This is endpoint-derived,
        // not a cell-name or design-specific placement shortcut.
        if (driver->bel == BelId()) {
            BelId source_bel;
            int candidates = 0;
            for (BelId bel : ctx->getBels()) {
                if (ctx->getBelType(bel) != driver->type)
                    continue;
                WireId output = ctx->getBelPinWire(bel, net->driver.port);
                if (output == WireId() ||
                        ctx->getWireName(output).str(ctx) != path.front().first)
                    continue;
                source_bel = bel;
                ++candidates;
            }
            if (candidates != 1)
                log_error("agrv2k: %s corridor has %d matching hard-source BELs\n",
                          lane.driver_type.c_str(), candidates);
            if (!ctx->checkBelAvail(source_bel))
                log_error("agrv2k: %s hard-source BEL is occupied\n",
                          lane.driver_type.c_str());
            ctx->bindBel(source_bel, driver, STRENGTH_LOCKED);
        }
        WireId source = ctx->getBelPinWire(driver->bel, net->driver.port);
        WireId target = ctx->getBelPinWire(iob->bel, port);
        std::string cursor = ctx->getWireName(source).str(ctx);
        std::string target_name = ctx->getWireName(target).str(ctx);
        if (cursor != path.front().first || target_name != path.back().second)
            log_error("agrv2k: %s corridor endpoint mismatch (%s -> %s, expected %s -> %s)\n",
                      lane.signal.c_str(), cursor.c_str(), target_name.c_str(),
                      path.front().first.c_str(), path.back().second.c_str());
        for (const auto &edge : path) {
            if (edge.first != cursor)
                log_error("agrv2k: discontinuous %s corridor at %s\n",
                          lane.signal.c_str(), cursor.c_str());
            PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
            if (pip == PipId())
                log_error("agrv2k: exact %s pip absent: %s -> %s\n",
                          lane.signal.c_str(), edge.first.c_str(), edge.second.c_str());
            if (!ctx->checkPipAvailForNet(pip, net))
                log_error("agrv2k: exact %s corridor conflict: %s -> %s\n",
                          lane.signal.c_str(), edge.first.c_str(), edge.second.c_str());
            ctx->bindPip(pip, net, STRENGTH_LOCKED);
            cursor = edge.second;
            ++locked;
        }
    }
    log_info("agrv2k: locked %s TX data/OE pair over %d exact pip(s)\n",
             controller_name.c_str(), locked);
}

// SPI0 master TX exposes six independently routed hard-source nets.  The
// structural-6907 vendor witness is a simultaneous, edge-disjoint composition
// ending at exactly PIN_12/SCK, PIN_13/CSN and PIN_14/MOSI.  Reserve it only
// when that complete OEPAD triplet is present; internal uses of any typed SPI0
// source remain ordinary routable nets.
static void lock_spi0_tx_corridors(Context *ctx)
{
    const char *data_dir = std::getenv("AGAMEMNON_DATA");
    if (data_dir == nullptr)
        return;
    std::ifstream f(std::string(data_dir) + "/mcu_spi0_tx_l48_paths.csv");
    if (!f.good())
        return;
    std::map<std::string, std::vector<std::pair<std::string, std::string>>> paths;
    std::string line;
    std::getline(f, line);
    while (std::getline(f, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        std::istringstream ss(line);
        std::vector<std::string> c;
        std::string field;
        while (std::getline(ss, field, ',')) c.push_back(field);
        if (c.size() < 6)
            log_error("agrv2k: malformed SPI0 TX corridor row: %s\n", line.c_str());
        paths[c[0]].push_back({c[3], c[4]});
    }

    const std::set<std::string> required_pads = {
        "X20Y13_OEPAD3", "X19Y13_OEPAD3", "X19Y13_OEPAD2"
    };
    std::map<std::string, CellInfo *> pads;
    for (auto &kv : ctx->cells) {
        CellInfo *candidate = kv.second.get();
        if (candidate->type != ctx->id("GENERIC_IOB") || candidate->bel == BelId())
            continue;
        std::string bel_name = ctx->getBelName(candidate->bel).str(ctx);
        if (required_pads.count(bel_name))
            pads[bel_name] = candidate;
    }
    if (pads.size() != required_pads.size())
        return;

    struct Lane {
        const char *signal;
        const char *driver_type;
        const char *pad_bel;
        const char *iob_port;
    };
    const Lane lanes[] = {
        {"spi0_sck_data", "MCU_SPI0_SCK_DATA", "X20Y13_OEPAD3", "I"},
        {"spi0_sck_oe", "MCU_SPI0_SCK_OE", "X20Y13_OEPAD3", "EN"},
        {"spi0_csn_data", "MCU_SPI0_CSN_DATA", "X19Y13_OEPAD3", "I"},
        {"spi0_csn_oe", "MCU_SPI0_CSN_OE", "X19Y13_OEPAD3", "EN"},
        {"spi0_mosi_data", "MCU_SPI0_MOSI_DATA", "X19Y13_OEPAD2", "I"},
        {"spi0_mosi_oe", "MCU_SPI0_MOSI_OE", "X19Y13_OEPAD2", "EN"},
    };
    int typed_lanes = 0;
    for (const Lane &lane : lanes) {
        CellInfo *iob = pads.at(lane.pad_bel);
        NetInfo *net = iob->getPort(ctx->id(lane.iob_port));
        if (net != nullptr && net->driver.cell != nullptr &&
                net->driver.cell->type == ctx->id(lane.driver_type))
            ++typed_lanes;
    }
    if (typed_lanes == 0)
        return;
    if (typed_lanes != 6)
        log_error("agrv2k: partial SPI0 TX typed composition (%d/6 lanes)\n", typed_lanes);
    int locked = 0;
    for (const Lane &lane : lanes) {
        CellInfo *iob = pads.at(lane.pad_bel);
        IdString port = ctx->id(lane.iob_port);
        NetInfo *net = iob->getPort(port);
        if (net == nullptr || net->driver.cell == nullptr ||
                net->driver.cell->type != ctx->id(lane.driver_type))
            log_error("agrv2k: %s.%s requires typed %s driver\n",
                      lane.pad_bel, lane.iob_port, lane.driver_type);
        CellInfo *driver = net->driver.cell;
        auto found = paths.find(lane.signal);
        if (found == paths.end() || found->second.empty())
            log_error("agrv2k: missing exact %s corridor\n", lane.signal);
        const auto &path = found->second;
        if (driver->bel == BelId()) {
            BelId source_bel;
            int candidates = 0;
            for (BelId bel : ctx->getBels()) {
                if (ctx->getBelType(bel) != driver->type)
                    continue;
                WireId output = ctx->getBelPinWire(bel, net->driver.port);
                if (output == WireId() ||
                        ctx->getWireName(output).str(ctx) != path.front().first)
                    continue;
                source_bel = bel;
                ++candidates;
            }
            if (candidates != 1)
                log_error("agrv2k: %s corridor has %d matching hard-source BELs\n",
                          lane.driver_type, candidates);
            if (!ctx->checkBelAvail(source_bel))
                log_error("agrv2k: %s hard-source BEL is occupied\n", lane.driver_type);
            ctx->bindBel(source_bel, driver, STRENGTH_LOCKED);
        }
        WireId source = ctx->getBelPinWire(driver->bel, net->driver.port);
        WireId target = ctx->getBelPinWire(iob->bel, port);
        std::string cursor = ctx->getWireName(source).str(ctx);
        std::string target_name = ctx->getWireName(target).str(ctx);
        if (cursor != path.front().first || target_name != path.back().second)
            log_error("agrv2k: %s corridor endpoint mismatch (%s -> %s, expected %s -> %s)\n",
                      lane.signal, cursor.c_str(), target_name.c_str(),
                      path.front().first.c_str(), path.back().second.c_str());
        for (const auto &edge : path) {
            if (edge.first != cursor)
                log_error("agrv2k: discontinuous %s corridor at %s\n",
                          lane.signal, cursor.c_str());
            PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
            if (pip == PipId())
                log_error("agrv2k: exact %s pip absent: %s -> %s\n",
                          lane.signal, edge.first.c_str(), edge.second.c_str());
            if (!ctx->checkPipAvailForNet(pip, net))
                log_error("agrv2k: exact %s corridor conflict: %s -> %s\n",
                          lane.signal, edge.first.c_str(), edge.second.c_str());
            ctx->bindPip(pip, net, STRENGTH_LOCKED);
            cursor = edge.second;
            ++locked;
        }
    }
    log_info("agrv2k: locked SPI0 TX six-lane composition over %d exact pip(s)\n", locked);
}

// SPI1 reaches the same L48 pad triplet through six different hard roots and
// a separately recovered simultaneous composition.  Never substitute SPI0's
// source identity merely because the package terminals coincide.
static void lock_spi1_tx_corridors(Context *ctx)
{
    const char *data_dir = std::getenv("AGAMEMNON_DATA");
    if (data_dir == nullptr)
        return;
    std::ifstream f(std::string(data_dir) + "/mcu_spi1_tx_l48_paths.csv");
    if (!f.good())
        return;
    std::map<std::string, std::vector<std::pair<std::string, std::string>>> paths;
    std::string line;
    std::getline(f, line);
    while (std::getline(f, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        std::istringstream ss(line);
        std::vector<std::string> c;
        std::string field;
        while (std::getline(ss, field, ',')) c.push_back(field);
        if (c.size() < 6)
            log_error("agrv2k: malformed SPI1 TX corridor row: %s\n", line.c_str());
        paths[c[0]].push_back({c[3], c[4]});
    }

    const std::set<std::string> required_pads = {
        "X20Y13_OEPAD3", "X19Y13_OEPAD3", "X19Y13_OEPAD2"
    };
    std::map<std::string, CellInfo *> pads;
    for (auto &kv : ctx->cells) {
        CellInfo *candidate = kv.second.get();
        if (candidate->type != ctx->id("GENERIC_IOB") || candidate->bel == BelId())
            continue;
        std::string bel_name = ctx->getBelName(candidate->bel).str(ctx);
        if (required_pads.count(bel_name))
            pads[bel_name] = candidate;
    }
    if (pads.size() != required_pads.size())
        return;

    struct Lane {
        const char *signal;
        const char *driver_type;
        const char *pad_bel;
        const char *iob_port;
    };
    const Lane lanes[] = {
        {"spi1_sck_data", "MCU_SPI1_SCK_DATA", "X20Y13_OEPAD3", "I"},
        {"spi1_sck_oe", "MCU_SPI1_SCK_OE", "X20Y13_OEPAD3", "EN"},
        {"spi1_csn_data", "MCU_SPI1_CSN_DATA", "X19Y13_OEPAD3", "I"},
        {"spi1_csn_oe", "MCU_SPI1_CSN_OE", "X19Y13_OEPAD3", "EN"},
        {"spi1_mosi_data", "MCU_SPI1_MOSI_DATA", "X19Y13_OEPAD2", "I"},
        {"spi1_mosi_oe", "MCU_SPI1_MOSI_OE", "X19Y13_OEPAD2", "EN"},
    };
    int typed_lanes = 0;
    for (const Lane &lane : lanes) {
        CellInfo *iob = pads.at(lane.pad_bel);
        NetInfo *net = iob->getPort(ctx->id(lane.iob_port));
        if (net != nullptr && net->driver.cell != nullptr &&
                net->driver.cell->type == ctx->id(lane.driver_type))
            ++typed_lanes;
    }
    if (typed_lanes == 0)
        return;
    if (typed_lanes != 6)
        log_error("agrv2k: partial SPI1 TX typed composition (%d/6 lanes)\n", typed_lanes);
    int locked = 0;
    for (const Lane &lane : lanes) {
        CellInfo *iob = pads.at(lane.pad_bel);
        IdString port = ctx->id(lane.iob_port);
        NetInfo *net = iob->getPort(port);
        if (net == nullptr || net->driver.cell == nullptr ||
                net->driver.cell->type != ctx->id(lane.driver_type))
            log_error("agrv2k: %s.%s requires typed %s driver\n",
                      lane.pad_bel, lane.iob_port, lane.driver_type);
        CellInfo *driver = net->driver.cell;
        auto found = paths.find(lane.signal);
        if (found == paths.end() || found->second.empty())
            log_error("agrv2k: missing exact %s corridor\n", lane.signal);
        const auto &path = found->second;
        if (driver->bel == BelId()) {
            BelId source_bel;
            int candidates = 0;
            for (BelId bel : ctx->getBels()) {
                if (ctx->getBelType(bel) != driver->type)
                    continue;
                WireId output = ctx->getBelPinWire(bel, net->driver.port);
                if (output == WireId() ||
                        ctx->getWireName(output).str(ctx) != path.front().first)
                    continue;
                source_bel = bel;
                ++candidates;
            }
            if (candidates != 1)
                log_error("agrv2k: %s corridor has %d matching hard-source BELs\n",
                          lane.driver_type, candidates);
            if (!ctx->checkBelAvail(source_bel))
                log_error("agrv2k: %s hard-source BEL is occupied\n", lane.driver_type);
            ctx->bindBel(source_bel, driver, STRENGTH_LOCKED);
        }
        WireId source = ctx->getBelPinWire(driver->bel, net->driver.port);
        WireId target = ctx->getBelPinWire(iob->bel, port);
        std::string cursor = ctx->getWireName(source).str(ctx);
        std::string target_name = ctx->getWireName(target).str(ctx);
        if (cursor != path.front().first || target_name != path.back().second)
            log_error("agrv2k: %s corridor endpoint mismatch (%s -> %s, expected %s -> %s)\n",
                      lane.signal, cursor.c_str(), target_name.c_str(),
                      path.front().first.c_str(), path.back().second.c_str());
        for (const auto &edge : path) {
            if (edge.first != cursor)
                log_error("agrv2k: discontinuous %s corridor at %s\n",
                          lane.signal, cursor.c_str());
            PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
            if (pip == PipId())
                log_error("agrv2k: exact %s pip absent: %s -> %s\n",
                          lane.signal, edge.first.c_str(), edge.second.c_str());
            if (!ctx->checkPipAvailForNet(pip, net))
                log_error("agrv2k: exact %s corridor conflict: %s -> %s\n",
                          lane.signal, edge.first.c_str(), edge.second.c_str());
            ctx->bindPip(pip, net, STRENGTH_LOCKED);
            cursor = edge.second;
            ++locked;
        }
    }
    log_info("agrv2k: locked SPI1 TX six-lane composition over %d exact pip(s)\n", locked);
}

// I2C0 uses two fully bidirectional physical pads.  Preserve the one exact
// vendor-observed six-lane composition atomically: hard data/OE to each pad,
// plus the same pad's sampled value back to its typed hard sink.  This avoids
// treating independently legal open-drain halves as freely recombinable.
static void lock_i2c_corridors(Context *ctx)
{
    const char *data_dir = std::getenv("AGAMEMNON_DATA");
    if (data_dir == nullptr)
        return;

    const char *suffixes[] = {
        "SCL_DATA", "SCL_OE", "SCL_INPUT",
        "SDA_DATA", "SDA_OE", "SDA_INPUT",
    };
    int i2c0_cells = 0, i2c1_cells = 0;
    for (auto &kv : ctx->cells) {
        CellInfo *candidate = kv.second.get();
        for (const char *suffix : suffixes) {
            if (candidate->type == ctx->id(std::string("MCU_I2C0_") + suffix))
                ++i2c0_cells;
            if (candidate->type == ctx->id(std::string("MCU_I2C1_") + suffix))
                ++i2c1_cells;
        }
    }
    if (i2c0_cells == 0 && i2c1_cells == 0)
        return;
    if (i2c0_cells != 0 && i2c1_cells != 0)
        log_error("agrv2k: mixed I2C0/I2C1 typed composition is not characterized\n");
    const int controller = i2c1_cells ? 1 : 0;
    const std::string controller_name = controller ? "I2C1" : "I2C0";
    const std::string signal_prefix = controller ? "i2c1_" : "i2c0_";
    const std::string hard_prefix = controller ? "MCU_I2C1_" : "MCU_I2C0_";
    const std::string filename = controller
            ? "mcu_i2c1_l48_paths.csv" : "mcu_i2c0_l48_paths.csv";

    std::ifstream f(std::string(data_dir) + "/" + filename);
    if (!f.good())
        log_error("agrv2k: missing exact %s corridor table %s\n",
                  controller_name.c_str(), filename.c_str());
    std::map<std::string, std::vector<std::pair<std::string, std::string>>> paths;
    std::string line;
    std::getline(f, line);
    while (std::getline(f, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        std::istringstream ss(line);
        std::vector<std::string> c;
        std::string field;
        while (std::getline(ss, field, ',')) c.push_back(field);
        if (c.size() < 6)
            log_error("agrv2k: malformed %s corridor row: %s\n",
                      controller_name.c_str(), line.c_str());
        paths[c[0]].push_back({c[3], c[4]});
    }

    const std::set<std::string> required_pads = {
        "X19Y13_IOB1", "X20Y13_IOB2"
    };
    std::map<std::string, CellInfo *> pads;
    for (auto &kv : ctx->cells) {
        CellInfo *candidate = kv.second.get();
        if (candidate->type != ctx->id("GENERIC_IOB") || candidate->bel == BelId())
            continue;
        std::string bel_name = ctx->getBelName(candidate->bel).str(ctx);
        if (required_pads.count(bel_name))
            pads[bel_name] = candidate;
    }
    if (pads.size() != required_pads.size())
        return;

    struct Lane {
        std::string signal;
        std::string hard_type;
        std::string pad_bel;
        std::string iob_port;
        bool input;
    };
    const std::vector<Lane> lanes = {
        {signal_prefix + "scl_data", hard_prefix + "SCL_DATA", "X19Y13_IOB1", "I", false},
        {signal_prefix + "scl_oe", hard_prefix + "SCL_OE", "X19Y13_IOB1", "EN", false},
        {signal_prefix + "scl_input", hard_prefix + "SCL_INPUT", "X19Y13_IOB1", "O", true},
        {signal_prefix + "sda_data", hard_prefix + "SDA_DATA", "X20Y13_IOB2", "I", false},
        {signal_prefix + "sda_oe", hard_prefix + "SDA_OE", "X20Y13_IOB2", "EN", false},
        {signal_prefix + "sda_input", hard_prefix + "SDA_INPUT", "X20Y13_IOB2", "O", true},
    };

    auto input_sink = [&](NetInfo *net, IdString type) -> CellInfo * {
        if (net == nullptr)
            return nullptr;
        CellInfo *found = nullptr;
        for (const PortRef &user : net->users) {
            if (user.cell->type != type || user.port != ctx->id("DOUT"))
                continue;
            if (found != nullptr)
                log_error("agrv2k: multiple typed %s sinks share one pad-input net\n",
                          controller_name.c_str());
            found = user.cell;
        }
        return found;
    };

    int typed_lanes = 0;
    for (const Lane &lane : lanes) {
        CellInfo *iob = pads.at(lane.pad_bel);
        NetInfo *net = iob->getPort(ctx->id(lane.iob_port));
        CellInfo *hard = lane.input
                ? input_sink(net, ctx->id(lane.hard_type))
                : ((net != nullptr) ? net->driver.cell : nullptr);
        if (hard != nullptr && hard->type == ctx->id(lane.hard_type))
            ++typed_lanes;
    }
    if (typed_lanes == 0)
        return;
    if (typed_lanes != 6)
        log_error("agrv2k: partial %s typed composition (%d/6 lanes)\n",
                  controller_name.c_str(), typed_lanes);

    int locked = 0;
    for (const Lane &lane : lanes) {
        CellInfo *iob = pads.at(lane.pad_bel);
        IdString iob_port = ctx->id(lane.iob_port);
        NetInfo *net = iob->getPort(iob_port);
        CellInfo *hard = lane.input
                ? input_sink(net, ctx->id(lane.hard_type))
                : ((net != nullptr) ? net->driver.cell : nullptr);
        if (hard == nullptr || hard->type != ctx->id(lane.hard_type))
            log_error("agrv2k: %s.%s requires typed %s endpoint\n",
                      lane.pad_bel.c_str(), lane.iob_port.c_str(), lane.hard_type.c_str());
        auto found = paths.find(lane.signal);
        if (found == paths.end() || found->second.empty())
            log_error("agrv2k: missing exact %s corridor\n", lane.signal.c_str());
        const auto &path = found->second;
        IdString hard_port = ctx->id(lane.input ? "DOUT" : "DIN");

        if (hard->bel == BelId()) {
            BelId exact_bel;
            int candidates = 0;
            for (BelId bel : ctx->getBels()) {
                if (ctx->getBelType(bel) != hard->type)
                    continue;
                WireId endpoint = ctx->getBelPinWire(bel, hard_port);
                if (endpoint == WireId())
                    continue;
                std::string endpoint_name = ctx->getWireName(endpoint).str(ctx);
                std::string expected = lane.input ? path.back().second : path.front().first;
                if (endpoint_name != expected)
                    continue;
                exact_bel = bel;
                ++candidates;
            }
            if (candidates != 1)
                log_error("agrv2k: %s corridor has %d matching hard BELs\n",
                          lane.hard_type.c_str(), candidates);
            if (!ctx->checkBelAvail(exact_bel))
                log_error("agrv2k: %s hard BEL is occupied\n", lane.hard_type.c_str());
            ctx->bindBel(exact_bel, hard, STRENGTH_LOCKED);
        }

        WireId source = lane.input
                ? ctx->getBelPinWire(iob->bel, iob_port)
                : ctx->getBelPinWire(hard->bel, hard_port);
        WireId target = lane.input
                ? ctx->getBelPinWire(hard->bel, hard_port)
                : ctx->getBelPinWire(iob->bel, iob_port);
        std::string cursor = ctx->getWireName(source).str(ctx);
        std::string target_name = ctx->getWireName(target).str(ctx);
        if (cursor != path.front().first || target_name != path.back().second)
            log_error("agrv2k: %s corridor endpoint mismatch (%s -> %s, expected %s -> %s)\n",
                      lane.signal.c_str(), cursor.c_str(), target_name.c_str(),
                      path.front().first.c_str(), path.back().second.c_str());
        for (const auto &edge : path) {
            if (edge.first != cursor)
                log_error("agrv2k: discontinuous %s corridor at %s\n",
                          lane.signal.c_str(), cursor.c_str());
            PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
            if (pip == PipId())
                log_error("agrv2k: exact %s pip absent: %s -> %s\n",
                          lane.signal.c_str(), edge.first.c_str(), edge.second.c_str());
            if (!ctx->checkPipAvailForNet(pip, net))
                log_error("agrv2k: exact %s corridor conflict: %s -> %s\n",
                          lane.signal.c_str(), edge.first.c_str(), edge.second.c_str());
            ctx->bindPip(pip, net, STRENGTH_LOCKED);
            cursor = edge.second;
            ++locked;
        }
    }
    log_info("agrv2k: locked %s six-lane bidirectional composition over %d exact pip(s)\n",
             controller_name.c_str(), locked);
}

// The four L48 bidirectional link pads have independent dynamic-OE corridors,
// recovered together in one vendor-routed control.  The ordinary placer sees
// only the terminal IOMUX and can collapse several EN nets onto one left-edge
// trunk.  Read the retained complete chains, bind each live EN driver to its
// observed source BEL, and reserve every exact pip before general placement.
// This is build/topology evidence only; package-electrical behavior remains a
// separate bench gate.
static void pack_left_oe_quad(Context *ctx)
{
    const char *data_dir = std::getenv("AGAMEMNON_DATA");
    if (data_dir == nullptr)
        return;
    std::ifstream f(std::string(data_dir) + "/pad_oe_L48_left_corridors.csv");
    if (!f.good())
        return;
    struct Row {
        int link;
        std::string source_bel, src, dst;
    };
    std::map<int, std::vector<Row>> paths;
    std::string line;
    std::getline(f, line);
    while (std::getline(f, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        std::istringstream ss(line);
        std::vector<std::string> c;
        std::string field;
        while (std::getline(ss, field, ',')) c.push_back(field);
        if (c.size() < 5)
            log_error("agrv2k: malformed L48 OE corridor row: %s\n", line.c_str());
        paths[std::atoi(c[0].c_str())].push_back(
                Row{std::atoi(c[0].c_str()), c[2], c[3], c[4]});
    }
    int bound = 0, locked = 0;
    for (const auto &entry : paths) {
        int link = entry.first;
        const auto &path = entry.second;
        if (path.empty()) continue;
        std::string target_name = path.back().dst;
        CellInfo *iob = nullptr;
        for (auto &kv : ctx->cells) {
            CellInfo *candidate = kv.second.get();
            if (candidate->type != ctx->id("GENERIC_IOB") || candidate->bel == BelId())
                continue;
            std::string candidate_bel = ctx->getBelName(candidate->bel).str(ctx);
            if (candidate_bel.find("X0Y4_IOB") != 0)
                continue;
            WireId en = ctx->getBelPinWire(candidate->bel, ctx->id("EN"));
            if (en != WireId() && ctx->getWireName(en).str(ctx) == target_name) {
                iob = candidate;
                break;
            }
        }
        // A design may use any subset of the four characterized links.
        if (iob == nullptr)
            continue;
        // The characterized left-edge BEL is shared by scalar input, scalar
        // output, and combined bidirectional cells.  Matching the BEL's EN
        // wire therefore does not mean this logical IOB has a live EN net.  A
        // plain input/output must bypass the dynamic-OE packer; only a cell
        // that actually connects EN is subject to the fail-closed driver and
        // exact-corridor checks below.  nextpnr's generic I/O packer may retain
        // an unconnected EN PortInfo even for a scalar input, hence the net
        // check in addition to the port-presence check.
        IdString en_port = ctx->id("EN");
        if (!iob->ports.count(en_port))
            continue;
        NetInfo *net = iob->getPort(en_port);
        if (net == nullptr)
            continue;
        if (net->driver.cell == nullptr)
            log_error("agrv2k: PIN_%d OE has no fabric driver\n", 25 + link);
        BelId exact_bel = ctx->getBelByName(IdStringList(ctx->id(path.front().source_bel)));
        if (exact_bel == BelId())
            log_error("agrv2k: L48 OE source BEL absent: %s\n", path.front().source_bel.c_str());
        // The fourth observed source is LUT-F on OMUX00.  The unchanged node
        // RTL drives its OE directly from a register Q, so represent that one
        // connection through a transparent identity LUT at the observed site.
        // Do the same for an externally driven OE: its driver is an input IOB
        // already fixed to another BEL and cannot itself present the measured
        // OMUX.  The original control net and all its other users remain
        // untouched; only the IOB's EN branch receives the identity output.
        CellInfo *incoming_driver = net->driver.cell;
        auto requested_bel = incoming_driver->attrs.find(ctx->id("BEL"));
        bool requested_away = requested_bel != incoming_driver->attrs.end() &&
                              requested_bel->second.as_string() != path.front().source_bel;
        // Matched entry control for the failed vendor-stage ingress.  PIN10 is
        // already silicon-qualified through this exact three-pip path in the
        // retained serial_mux image.  Terminate it at the same X19Y12 slice2
        // I3 boundary, then observe that stage through the same GP8/PIN18 sink
        // and PIN25 OE composition used by the X14 experiment.  This tests pad
        // entry before the earliest divergent RMUX15/RMUX20 hop.
        bool entry_probe = incoming_driver->attrs.count(
                ctx->id("AGRV2K_PIN10_ENTRY_PROBE")) != 0;
        if (entry_probe) {
            if (link != 0 || incoming_driver->type != ctx->id("GENERIC_SLICE") ||
                requested_bel == incoming_driver->attrs.end() ||
                requested_bel->second.as_string() != "X19Y12_SLICE2")
                log_error("agrv2k: PIN10 entry probe must be X19Y12_SLICE2\n");
            BelId probe_bel = ctx->getBelByNameStr("X19Y12_SLICE2");
            if (probe_bel == BelId() || !ctx->checkBelAvail(probe_bel))
                log_error("agrv2k: PIN10 entry probe BEL unavailable\n");
            ctx->bindBel(probe_bel, incoming_driver, STRENGTH_LOCKED);
            incoming_driver->attrs.erase(ctx->id("BEL"));
            NetInfo *input_net = incoming_driver->getPort(ctx->id("I[3]"));
            if (input_net == nullptr || input_net->driver.cell == nullptr ||
                input_net->driver.cell->bel == BelId())
                log_error("agrv2k: PIN10 entry probe has no bound input\n");
            const std::vector<std::pair<std::string, std::string>> ingress = {
                {"X20Y13_InputMUX02", "X20Y12_RMUX15"},
                {"X20Y12_RMUX15", "X19Y12_RMUX53"},
                {"X19Y12_RMUX53", "X19Y12_IMUX11"},
            };
            for (const auto &edge : ingress) {
                PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
                if (pip == PipId() || !ctx->checkPipAvailForNet(pip, input_net))
                    log_error("agrv2k: unavailable PIN10 entry-probe edge %s -> %s\n",
                              edge.first.c_str(), edge.second.c_str());
                ctx->bindPip(pip, input_net, STRENGTH_LOCKED);
            }
            incoming_driver->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
            log_info("agrv2k: locked qualified PIN10 entry probe over %d exact pip(s)\n",
                     int(ingress.size()));
        }
        // The retained vendor PIN_10 -> PIN_25 OE control does not cross the
        // mesh directly.  It enters X14Y4 slice4 on IMUX18, crosses an
        // identity/XOR LUT, and leaves OMUX14 for the X10Y4 presentation LUT.
        // A purpose-built diagnostic requests that exact pre-stage explicitly;
        // lock both surrounding paths here so its A/B differs from the failed
        // direct route by this one architectural re-buffering boundary.  This
        // is deliberately fail-closed to link0, one BEL, one LUT input, and the
        // vendor-observed wires.  Electrical qualification remains separate.
        bool vendor_stage = incoming_driver->attrs.count(
                ctx->id("AGRV2K_PIN25_VENDOR_STAGE")) != 0;
        if (vendor_stage) {
            if (link != 0 || incoming_driver->type != ctx->id("GENERIC_SLICE") ||
                requested_bel == incoming_driver->attrs.end() ||
                requested_bel->second.as_string() != "X14Y4_SLICE4")
                log_error("agrv2k: PIN25 vendor OE stage must be X14Y4_SLICE4\n");
            BelId stage_bel = ctx->getBelByNameStr("X14Y4_SLICE4");
            if (stage_bel == BelId() || !ctx->checkBelAvail(stage_bel))
                log_error("agrv2k: PIN25 vendor OE stage BEL unavailable\n");
            ctx->bindBel(stage_bel, incoming_driver, STRENGTH_LOCKED);
            incoming_driver->attrs.erase(ctx->id("BEL"));

            NetInfo *input_net = incoming_driver->getPort(ctx->id("I[2]"));
            if (input_net == nullptr || input_net->driver.cell == nullptr ||
                input_net->driver.cell->bel == BelId())
                log_error("agrv2k: PIN25 vendor OE stage has no bound PIN10 input\n");
            const std::vector<std::pair<std::string, std::string>> ingress = {
                {"X20Y13_InputMUX02", "X20Y12_RMUX20"},
                {"X20Y12_RMUX20", "X18Y12_RMUX80"},
                {"X18Y12_RMUX80", "X18Y8_RMUX43"},
                {"X18Y8_RMUX43", "X14Y8_RMUX73"},
                {"X14Y8_RMUX73", "X14Y4_RMUX22"},
                {"X14Y4_RMUX22", "X14Y4_IMUX18"},
            };
            const std::vector<std::pair<std::string, std::string>> egress = {
                {"X14Y4_OMUX14", "X14Y4_RMUX43"},
                {"X14Y4_RMUX43", "X10Y4_RMUX94"},
                {"X10Y4_RMUX94", "X10Y4_IMUX00"},
            };
            auto lock_exact = [&](NetInfo *locked_net,
                                  const std::vector<std::pair<std::string, std::string>> &edges,
                                  const char *which) {
                for (const auto &edge : edges) {
                    PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
                    if (pip == PipId() || !ctx->checkPipAvailForNet(pip, locked_net))
                        log_error("agrv2k: unavailable PIN25 vendor %s edge %s -> %s\n",
                                  which, edge.first.c_str(), edge.second.c_str());
                    ctx->bindPip(pip, locked_net, STRENGTH_LOCKED);
                }
            };
            lock_exact(input_net, ingress, "ingress");
            lock_exact(net, egress, "egress");
            incoming_driver->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
            log_info("agrv2k: locked PIN10 through vendor X14Y4_SLICE4 OE pre-stage "
                     "over %d exact pip(s)\n", int(ingress.size() + egress.size()));
        }
        // Production PIN10 -> PIN25 OE uses the entry boundary that passed the
        // constant-controlled silicon A/B, rather than asking the general
        // router to cross the unqualified RMUX20 mesh branch directly.  Insert
        // the same transparent X19Y12 slice2 stage as the diagnostic, lock only
        // the three qualified entry pips, and leave the stage output to the
        // ordinary exact X10 presentation buffer below.  This match is narrow
        // and fail-closed: link0, the bonded PIN10 input BEL, and no other
        // external-input fanout or RMUX20 topology are promoted by it.
        bool qualified_pin10_oe = link == 0 &&
                incoming_driver->type == ctx->id("GENERIC_IOB") &&
                incoming_driver->bel != BelId() &&
                ctx->getBelName(incoming_driver->bel).str(ctx) == "X20Y13_IPAD1";
        if (qualified_pin10_oe) {
            std::string sname = "$pin10_entry_oe0_identity";
            auto stage = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), sname);
            stage->params[ctx->id("INIT")] = Property(0xff00, 1 << ctx->args.K);
            auto staged = std::make_unique<NetInfo>(ctx->id(sname + "_NET"));
            NetInfo *staged_net = staged.get();
            stage->connectPort(ctx->id("I[3]"), net);
            stage->connectPort(ctx->id("F"), staged_net);
            iob->disconnectPort(ctx->id("EN"));
            iob->connectPort(ctx->id("EN"), staged_net);
            CellInfo *stage_cell = stage.get();
            ctx->cells[stage->name] = std::move(stage);
            ctx->nets[staged->name] = std::move(staged);

            BelId stage_bel = ctx->getBelByNameStr("X19Y12_SLICE2");
            if (stage_bel == BelId() || !ctx->checkBelAvail(stage_bel))
                log_error("agrv2k: qualified PIN10 OE entry BEL unavailable\n");
            ctx->bindBel(stage_bel, stage_cell, STRENGTH_LOCKED);
            const std::vector<std::pair<std::string, std::string>> ingress = {
                {"X20Y13_InputMUX02", "X20Y12_RMUX15"},
                {"X20Y12_RMUX15", "X19Y12_RMUX53"},
                {"X19Y12_RMUX53", "X19Y12_IMUX11"},
            };
            for (const auto &edge : ingress) {
                PipId pip = ctx->getPipByNameStr(edge.first + "." + edge.second);
                if (pip == PipId() || !ctx->checkPipAvailForNet(pip, net))
                    log_error("agrv2k: unavailable qualified PIN10 OE edge %s -> %s\n",
                              edge.first.c_str(), edge.second.c_str());
                ctx->bindPip(pip, net, STRENGTH_LOCKED);
            }
            stage_cell->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
            net = staged_net;
            incoming_driver = stage_cell;
            requested_away = true;
            log_info("agrv2k: inserted qualified PIN10 entry stage for PIN25 OE "
                     "over %d exact pip(s)\n", int(ingress.size()));
        }
        bool needs_identity = link == 3 || incoming_driver->type != ctx->id("GENERIC_SLICE") ||
                              (incoming_driver->bel != BelId() && incoming_driver->bel != exact_bel) ||
                              requested_away;
        if (needs_identity) {
            std::string bname = "$quad_oe" + std::to_string(link) + "_identity";
            auto buf = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), bname);
            buf->params[ctx->id("INIT")] = Property(0xaaaa, 1 << ctx->args.K);
            auto buffered = std::make_unique<NetInfo>(ctx->id(bname + "_NET"));
            NetInfo *buffered_net = buffered.get();
            buf->connectPort(ctx->id("I[0]"), net);
            buf->connectPort(ctx->id("F"), buffered_net);
            iob->disconnectPort(ctx->id("EN"));
            iob->connectPort(ctx->id("EN"), buffered_net);
            CellInfo *buf_cell = buf.get();
            ctx->cells[buf->name] = std::move(buf);
            ctx->nets[buffered->name] = std::move(buffered);
            net = buffered_net;
            NPNR_ASSERT(net->driver.cell == buf_cell);
            log_info("agrv2k: inserted exact PIN_%d OE identity presentation buffer\n",
                     25 + link);
        }
        CellInfo *driver = net->driver.cell;
        if (driver->bel != BelId() && driver->bel != exact_bel)
            log_error("agrv2k: PIN_%d OE driver already bound away from %s\n",
                      25 + link, path.front().source_bel.c_str());
        if (driver->bel == BelId()) {
            if (!ctx->checkBelAvail(exact_bel))
                log_error("agrv2k: L48 OE source BEL unavailable: %s\n",
                          path.front().source_bel.c_str());
            ctx->bindBel(exact_bel, driver, STRENGTH_LOCKED);
        }
        WireId source = ctx->getBelPinWire(exact_bel, net->driver.port);
        std::string cursor = ctx->getWireName(source).str(ctx);
        if (cursor != path.front().src)
            log_error("agrv2k: %s presents %s, expected %s\n",
                      path.front().source_bel.c_str(), cursor.c_str(), path.front().src.c_str());
        for (const Row &row : path) {
            if (row.src != cursor)
                log_error("agrv2k: discontinuous PIN_%d OE corridor at %s\n",
                          25 + link, cursor.c_str());
            PipId pip = ctx->getPipByNameStr(row.src + "." + row.dst);
            if (pip == PipId())
                log_error("agrv2k: exact L48 OE pip absent: %s -> %s\n",
                          row.src.c_str(), row.dst.c_str());
            if (!ctx->checkPipAvailForNet(pip, net))
                log_error("agrv2k: exact PIN_%d OE corridor conflict at %s -> %s\n",
                          25 + link, row.src.c_str(), row.dst.c_str());
            ctx->bindPip(pip, net, STRENGTH_LOCKED);
            cursor = row.dst;
            ++locked;
        }
        driver->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
        ++bound;
        log_info("agrv2k: locked PIN_%d OE driver to %s over %d exact pip(s)\n",
                 25 + link, path.front().source_bel.c_str(), int(path.size()));
    }
    if (bound)
        log_info("agrv2k: locked %d L48 dynamic-OE driver(s) over %d exact pip(s)\n",
                 bound, locked);
}

// Lock the four already-recorded left-link input corridors into the two LUTs
// of the unchanged node reduction tree.  LUT inputs are symmetric: swapping a
// net and the matching INIT axes preserves the exact logical function while
// selecting the physical IMUX pin that the vendor route reaches.
static void pack_left_link_inputs(Context *ctx)
{
    const char *data_dir = std::getenv("AGAMEMNON_DATA");
    if (data_dir == nullptr) return;
    std::ifstream f(std::string(data_dir) + "/pad_input_L48_left_corridors.csv");
    if (!f.good()) return;
    struct Row { int link, target_pin; std::string target_bel, src, dst; };
    std::map<int, std::vector<Row>> paths;
    std::string line;
    std::getline(f, line);
    while (std::getline(f, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        std::istringstream ss(line); std::vector<std::string> c; std::string field;
        while (std::getline(ss, field, ',')) c.push_back(field);
        if (c.size() < 6)
            log_error("agrv2k: malformed L48 link-input row: %s\n", line.c_str());
        paths[std::atoi(c[0].c_str())].push_back(
                Row{std::atoi(c[0].c_str()), std::atoi(c[3].c_str()), c[2], c[4], c[5]});
    }
    int locked = 0;
    // Each link pair terminates on two pins of one observed slice.  Insert an
    // exact two-input XOR at each site and substitute that combined bit into
    // the unchanged synthesized UART reduction tree.  This keeps the UART/HSE
    // consumers free to occupy their separately characterized top-edge cone.
    for (int pair_start : {0, 2}) {
        if (!paths.count(pair_start) || !paths.count(pair_start + 1)) continue;
        NetInfo *nets[2] = {nullptr, nullptr};
        PortRef users[2];
        for (int k = 0; k < 2; ++k) {
            int link = pair_start + k; const auto &path = paths.at(link);
            CellInfo *iob = nullptr;
            for (auto &kv : ctx->cells) {
                CellInfo *candidate = kv.second.get();
                if (candidate->type != ctx->id("GENERIC_IOB") || candidate->bel == BelId()) continue;
                std::string bn = ctx->getBelName(candidate->bel).str(ctx);
                if (bn.find("X0Y4_IOB") != 0) continue;
                WireId out = ctx->getBelPinWire(candidate->bel, ctx->id("O"));
                if (out != WireId() && ctx->getWireName(out).str(ctx) == path.front().src) {
                    iob = candidate; break;
                }
            }
            if (iob == nullptr) continue;
            nets[k] = iob->getPort(ctx->id("O"));
            // Scalar outputs share these physical BELs but have no live input
            // net.  They are not members of the link-input campaign and must
            // bypass this packer just as scalar inputs bypass the OE packer.
            if (nets[k] == nullptr)
                continue;
            int count = 0;
            for (auto &u : nets[k]->users) { users[k] = u; ++count; }
            if (count != 1)
                log_error("agrv2k: PIN_%d input requires one reduction-LUT consumer\n", 25 + link);
        }
        if ((nets[0] != nullptr) != (nets[1] != nullptr)) {
            // A scalar input or a one-link bidirectional probe still has to
            // terminate at the characterized X1Y4 boundary.  The original
            // four-link node happened to exercise links in pairs, so the
            // first packer only created the two-input XOR case below.  Insert
            // a transparent one-input LUT for the lone link, then leave its
            // original consumer free to route onward (for example to the
            // qualified PIN_18 observation pad).
            int k = nets[0] != nullptr ? 0 : 1;
            int link = pair_start + k;
            const auto &path = paths.at(link);
            CellInfo *sink = users[k].cell;
            if (sink == nullptr || sink->type != ctx->id("GENERIC_SLICE"))
                log_error("agrv2k: PIN_%d input consumer is not a LUT\n", 25 + link);
            std::string bname = "$single_link" + std::to_string(link) + "_identity";
            auto buf = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), bname);
            int target_pin = path.front().target_pin;
            uint64_t identity_init = 0;
            for (int index = 0; index < (1 << ctx->args.K); ++index)
                if ((index >> target_pin) & 1)
                    identity_init |= uint64_t(1) << index;
            buf->params[ctx->id("INIT")] = Property(identity_init, 1 << ctx->args.K);
            auto buffered = std::make_unique<NetInfo>(ctx->id(bname + "_NET"));
            NetInfo *buffered_net = buffered.get();
            buf->connectPort(ctx->id("I[" + std::to_string(target_pin) + "]"), nets[k]);
            buf->connectPort(ctx->id("F"), buffered_net);
            sink->disconnectPort(users[k].port);
            sink->connectPort(users[k].port, buffered_net);
            CellInfo *buf_cell = buf.get();
            ctx->cells[buf->name] = std::move(buf);
            ctx->nets[buffered->name] = std::move(buffered);
            BelId exact_bel = ctx->getBelByName(IdStringList(ctx->id(path.front().target_bel)));
            if (exact_bel == BelId() || !ctx->checkBelAvail(exact_bel))
                log_error("agrv2k: PIN_%d input identity BEL unavailable: %s\n",
                          25 + link, path.front().target_bel.c_str());
            ctx->bindBel(exact_bel, buf_cell, STRENGTH_LOCKED);
            std::string target = ctx->getWireName(ctx->getBelPinWire(
                    exact_bel, ctx->id("I[" + std::to_string(target_pin) + "]"))).str(ctx);
            if (target != path.back().dst)
                log_error("agrv2k: PIN_%d input identity endpoint mismatch\n", 25 + link);
            std::string cursor = path.front().src;
            for (const Row &row : path) {
                if (row.src != cursor)
                    log_error("agrv2k: discontinuous PIN_%d input corridor\n", 25 + link);
                PipId pip = ctx->getPipByNameStr(row.src + "." + row.dst);
                if (pip == PipId() || !ctx->checkPipAvailForNet(pip, nets[k]))
                    log_error("agrv2k: unavailable exact PIN_%d input pip %s -> %s\n",
                              25 + link, row.src.c_str(), row.dst.c_str());
                ctx->bindPip(pip, nets[k], STRENGTH_LOCKED);
                cursor = row.dst;
                ++locked;
            }
            buf_cell->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
            log_info("agrv2k: locked PIN_%d through one exact input identity at %s\n",
                     25 + link, path.front().target_bel.c_str());
        } else if (nets[0] != nullptr && nets[1] != nullptr) {
            CellInfo *sink = users[0].cell;
            if (sink == nullptr || sink != users[1].cell || sink->type != ctx->id("GENERIC_SLICE"))
                log_error("agrv2k: PIN_%d/%d do not share one reduction LUT\n",
                          25 + pair_start, 26 + pair_start);
            auto pin_index = [&](IdString port) {
                std::string p = port.str(ctx);
                return (p.size() == 4 && p[0] == 'I' && p[1] == '[' && p[3] == ']') ? p[2] - '0' : -1;
            };
            int p2 = pin_index(users[0].port), p3 = pin_index(users[1].port);
            if (p2 < 0 || p3 < 0 || p2 == p3)
                log_error("agrv2k: PIN_%d/%d reduction ports are invalid\n",
                          25 + pair_start, 26 + pair_start);
            auto init_it = sink->params.find(ctx->id("INIT"));
            if (init_it == sink->params.end())
                log_error("agrv2k: link-pair reduction LUT has no INIT\n");
            uint64_t old_init = uint64_t(init_it->second.as_int64());
            for (int base = 0; base < 16; ++base) {
                if (base & ((1 << p2) | (1 << p3))) continue;
                int v00 = (old_init >> base) & 1;
                int v10 = (old_init >> (base | (1 << p2))) & 1;
                int v01 = (old_init >> (base | (1 << p3))) & 1;
                int v11 = (old_init >> (base | (1 << p2) | (1 << p3))) & 1;
                if (v00 != v11 || v10 != v01)
                    log_error("agrv2k: PIN_%d/%d inputs are not XOR-composable in the unchanged LUT\n",
                              25 + pair_start, 26 + pair_start);
            }
            std::string bname = "$quad_link" + std::to_string(pair_start) +
                                std::to_string(pair_start + 1) + "_xor";
            auto buf = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), bname);
            int tp0 = paths.at(pair_start).front().target_pin;
            int tp1 = paths.at(pair_start + 1).front().target_pin;
            uint64_t xor_init = 0;
            for (int index = 0; index < 16; ++index)
                if (((index >> tp0) & 1) != ((index >> tp1) & 1))
                    xor_init |= uint64_t(1) << index;
            buf->params[ctx->id("INIT")] = Property(xor_init, 1 << ctx->args.K);
            auto combined = std::make_unique<NetInfo>(ctx->id(bname + "_NET"));
            NetInfo *combined_net = combined.get();
            buf->connectPort(ctx->id("I[" + std::to_string(tp0) + "]"), nets[0]);
            buf->connectPort(ctx->id("I[" + std::to_string(tp1) + "]"), nets[1]);
            buf->connectPort(ctx->id("F"), combined_net);
            sink->disconnectPort(users[0].port);
            sink->disconnectPort(users[1].port);
            sink->connectPort(users[0].port, combined_net);
            uint64_t new_init = 0;
            for (int index = 0; index < 16; ++index) {
                int old_index = index & ~(1 << p3);
                if ((old_init >> old_index) & 1) new_init |= uint64_t(1) << index;
            }
            sink->params[ctx->id("INIT")] = Property(new_init, 16);
            CellInfo *buf_cell = buf.get();
            ctx->cells[buf->name] = std::move(buf);
            ctx->nets[combined->name] = std::move(combined);
            BelId exact_bel = ctx->getBelByName(
                    IdStringList(ctx->id(paths.at(pair_start).front().target_bel)));
            if (exact_bel == BelId() || !ctx->checkBelAvail(exact_bel))
                log_error("agrv2k: PIN_%d/%d XOR BEL unavailable: %s\n",
                          25 + pair_start, 26 + pair_start,
                          paths.at(pair_start).front().target_bel.c_str());
            ctx->bindBel(exact_bel, buf_cell, STRENGTH_LOCKED);
            for (int k = 0; k < 2; ++k) {
                int link = pair_start + k; const auto &path = paths.at(link);
                std::string target = ctx->getWireName(ctx->getBelPinWire(
                        exact_bel, ctx->id("I[" + std::to_string(path.front().target_pin) + "]"))).str(ctx);
                if (target != path.back().dst)
                    log_error("agrv2k: PIN_%d XOR endpoint mismatch\n", 25 + link);
                std::string cursor = path.front().src;
                for (const Row &row : path) {
                    if (row.src != cursor)
                        log_error("agrv2k: discontinuous PIN_%d input corridor\n", 25 + link);
                    PipId pip = ctx->getPipByNameStr(row.src + "." + row.dst);
                    if (pip == PipId() || !ctx->checkPipAvailForNet(pip, nets[k]))
                        log_error("agrv2k: unavailable exact PIN_%d input pip %s -> %s\n",
                                  25 + link, row.src.c_str(), row.dst.c_str());
                    ctx->bindPip(pip, nets[k], STRENGTH_LOCKED);
                    cursor = row.dst; ++locked;
                }
            }
            buf_cell->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
            log_info("agrv2k: locked PIN_%d/%d through one exact input XOR at %s\n",
                     25 + pair_start, 26 + pair_start,
                     paths.at(pair_start).front().target_bel.c_str());
        }
    }
    if (locked) log_info("agrv2k: locked four-link input reduction over %d exact pip(s)\n", locked);
}

// Symmetric input-pad case: bind each direct fabric consumer to a BEL whose requested input pin is
// forward-reachable from the physical IPAD output in the gated graph.  In particular this fixes the
// root of a synthesized reset fanout tree; merely placing it on the nearest tile can select a dead IMUX.
static void pack_input_pin_consumers(Context *ctx)
{
    if (std::getenv("AGRV2K_IO_PINPACK") == nullptr)
        return;
    // ABC can fold several unrelated physical inputs into one LUT.  A single
    // BEL then has to lie in the intersection of all pad-egress components;
    // the characterized HSE and PIN_19 components have no such common slice.
    // Split only that multi-pad boundary with transparent one-input LUTs.  The
    // ordinary logic function and its truth table stay unchanged, while each
    // physical input receives its own independently reachable placement.
    struct PadUse { NetInfo *net; PortRef user; };
    std::map<CellInfo *, std::vector<PadUse>> shared_sinks;
    for (auto &c : ctx->cells) {
        CellInfo *io = c.second.get();
        if (io->type != ctx->id("GENERIC_IOB") || io->bel == BelId()) continue;
        NetInfo *net = io->getPort(ctx->id("O"));
        if (net == nullptr) continue;
        for (auto &u : net->users)
            if (u.cell != nullptr && u.cell->type == ctx->id("GENERIC_SLICE") &&
                    u.cell->bel == BelId() && u.port != ctx->id("CLK") &&
                    u.port != ctx->id("Clk0") && u.port != ctx->id("Clk1"))
                shared_sinks[u.cell].push_back(PadUse{net, u});
    }
    int isolated = 0;
    for (auto &entry : shared_sinks) {
        if (entry.second.size() < 2) continue;
        CellInfo *sink = entry.first;
        for (const PadUse &use : entry.second) {
            std::string name = "$pad_input_identity" + std::to_string(isolated++);
            auto cell = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), name);
            cell->params[ctx->id("INIT")] = Property(0xaaaa, 1 << ctx->args.K);
            cell->attrs[ctx->id("AGRV2K_PAD_INPUT_IDENTITY")] = Property(1);
            auto net = std::make_unique<NetInfo>(ctx->id(name + "_NET"));
            NetInfo *buffered = net.get();
            cell->connectPort(ctx->id("I[0]"), use.net);
            cell->connectPort(ctx->id("F"), buffered);
            sink->disconnectPort(use.user.port);
            sink->connectPort(use.user.port, buffered);
            ctx->cells[cell->name] = std::move(cell);
            ctx->nets[net->name] = std::move(net);
        }
        log_info("agrv2k: isolated %d physical-pad inputs from shared LUT '%s'\n",
                 int(entry.second.size()), sink->name.c_str(ctx));
    }
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
                    // X1Y4 slice4 accepts every HSE input pin, but its default
                    // F output component is bounded locally (116 wires and no
                    // path to the top-edge UART cone).  It is therefore not a
                    // valid presentation site for an inserted pad identity.
                    if (sink->attrs.count(ctx->id("AGRV2K_PAD_INPUT_IDENTITY")) &&
                            bloc.x == 1 && bloc.y == 4 && bloc.z == 4)
                        continue;
                    // Registered input roots must obey the same silicon-
                    // qualified even-slot invariant as the rest of the
                    // sequential fabric.  The old pin-pack exemption placed
                    // the three UART roots in slots 1/3/6; only channel A was
                    // reproducible.  Slot 0 has a separately isolated dead
                    // Qin feedback, so reserve it as well.
                    if (bloc.z == 0 || (bloc.z & 1) != 0)
                        continue;
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
            // qin_pack deliberately placed that net on I[3], the characterized
            // direct-D branch.
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

                auto stage = sink->attrs.find(ctx->id("agamemnon_pad_sync_stage"));
                auto group_attr = sink->attrs.find(ctx->id("agamemnon_pad_sync_group"));
                if (stage != sink->attrs.end() && group_attr != sink->attrs.end() &&
                    stage->second.as_string() == "stage1") {
                    const std::string group = group_attr->second.as_string();
                    CellInfo *follow = nullptr;
                    for (auto &candidate : ctx->cells) {
                        CellInfo *ci = candidate.second.get();
                        auto cs = ci->attrs.find(ctx->id("agamemnon_pad_sync_stage"));
                        auto cg = ci->attrs.find(ctx->id("agamemnon_pad_sync_group"));
                        if (ci->type == ctx->id("GENERIC_SLICE") && ci->bel == BelId() &&
                            cs != ci->attrs.end() && cg != ci->attrs.end() &&
                            cs->second.as_string() == "stage2" && cg->second.as_string() == group) {
                            follow = ci;
                            break;
                        }
                    }
                    NetInfo *qnet = sink->getPort(ctx->id("Q"));
                    IdString follow_port;
                    if (follow != nullptr && qnet != nullptr)
                        for (auto &user : qnet->users)
                            if (user.cell == follow) {
                                follow_port = user.port;
                                break;
                            }
                    WireId qwire = ctx->getBelPinWire(chosen, ctx->id("Q"));
                    if (follow != nullptr && follow_port != IdString() && qwire != WireId()) {
                        pool<WireId> reach;
                        std::vector<WireId> queue;
                        reach.insert(qwire); queue.push_back(qwire);
                        for (size_t head = 0; head < queue.size(); ++head)
                            for (PipId pip : ctx->getPipsDownhill(queue[head])) {
                                WireId dst = ctx->getPipDstWire(pip);
                                if (reach.insert(dst).second)
                                    queue.push_back(dst);
                            }
                        Loc root = ctx->getBelLocation(chosen);
                        BelId best;
                        int best_cost = 1000000;
                        for (BelId bel : ctx->getBels()) {
                            if (ctx->getBelType(bel) != ctx->id("GENERIC_SLICE") ||
                                !ctx->checkBelAvail(bel))
                                continue;
                            WireId iw = ctx->getBelPinWire(bel, follow_port);
                            if (iw == WireId() || !reach.count(iw))
                                continue;
                            Loc loc = ctx->getBelLocation(bel);
                            if (loc.z == 0 || (loc.z & 1) != 0)
                                continue;
                            int cost = 64 * (std::abs(loc.x - root.x) + std::abs(loc.y - root.y)) +
                                       std::abs(loc.z - root.z);
                            if (cost < best_cost) {
                                best_cost = cost;
                                best = bel;
                            }
                        }
                        if (best == BelId())
                            log_error("agrv2k: no same-cone stage-2 BEL for '%s'\n", sink->name.c_str(ctx));
                        follow->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
                        ctx->bindBel(best, follow, STRENGTH_LOCKED);
                        log_info("agrv2k: input-sync packed stage 2 '%s' -> %s\n",
                                 follow->name.c_str(ctx), ctx->getBelName(best).str(ctx).c_str());

                        // Route the synchronizer handoff before router2 can
                        // consume its qualified RMUX choice.  In the dense
                        // three-UART image router2 selected equal-length
                        // alternatives that simulated correctly but changed
                        // PIN_11 B->A8 and PIN_15 C->FF on silicon.  Each path
                        // below is copied from the matching single-lane L48
                        // build that returned the exact byte on hardware.
                        Loc target = ctx->getBelLocation(best);
                        std::vector<std::string> nodes;
                        if (root.x == 19 && root.y == 12 && target.x == 19 && target.y == 12) {
                            if (root.z == 2 && target.z == 4)
                                nodes = {"X19Y12_OMUX08", "X19Y12_RMUX20", "X18Y12_RMUX81",
                                         "X19Y12_RMUX29", "X19Y12_IMUX19"};
                            else if (root.z == 6 && target.z == 8)
                                nodes = {"X19Y12_OMUX20", "X19Y12_RMUX33", "X18Y12_RMUX45",
                                         "X19Y12_RMUX77", "X19Y12_IMUX35"};
                            else if (root.z == 10 && target.z == 12)
                                nodes = {"X19Y12_OMUX32", "X19Y12_RMUX59", "X19Y12_IMUX51"};
                        }
                        if (!nodes.empty()) {
                            const std::string source_name = ctx->getWireName(qwire).str(ctx);
                            const std::string target_name =
                                    ctx->getWireName(ctx->getBelPinWire(best, follow_port)).str(ctx);
                            if (source_name != nodes.front() || target_name != nodes.back())
                                log_error("agrv2k: qualified input-sync corridor endpoint mismatch\n");
                            for (size_t ni = 0; ni + 1 < nodes.size(); ++ni) {
                                PipId pip = ctx->getPipByNameStr(nodes[ni] + "." + nodes[ni + 1]);
                                if (pip == PipId())
                                    log_error("agrv2k: missing qualified input-sync pip %s -> %s\n",
                                              nodes[ni].c_str(), nodes[ni + 1].c_str());
                                if (!ctx->checkPipAvailForNet(pip, qnet))
                                    log_error("agrv2k: qualified input-sync corridor conflict at %s -> %s\n",
                                              nodes[ni].c_str(), nodes[ni + 1].c_str());
                                ctx->bindPip(pip, qnet, STRENGTH_LOCKED);
                            }
                            log_info("agrv2k: pre-routed qualified input-sync corridor over %ld pip(s)\n",
                                     long(nodes.size() - 1));
                        }
                    }
                }

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

// Form bounded native clusters around fabric cells that touch the fixed MCU
// boundary. A GENERIC_SLICE already fuses its LUT and optional FF, so that
// atomic boundary cell is the movable cluster root; ordinary fabric neighbors
// remain available to the normal placer rather than expanding a boundary
// constraint across an arbitrary logic cone. Fixed-endpoint reachability is
// checked later by isBelLocationValid for every translated candidate.
static void pack_mcu_relative_clusters(Context *ctx)
{
    const IdString slice = ctx->id("GENERIC_SLICE");
    auto is_boundary_sink = [&](CellInfo *cell) {
        return cell != nullptr &&
               (cell->type == ctx->id("MCU_DOUT") ||
                cell->type == ctx->id("MCU_AHB_HREADYOUT") ||
                cell->type == ctx->id("MCU_AHB_HRESP"));
    };
    auto eligible = [&](CellInfo *cell) {
        if (cell == nullptr || cell->type != slice || cell->bel != BelId() ||
            cell->cluster != ClusterId() || cell->attrs.count(ctx->id("BEL")) ||
            cell->ports.count(ctx->id("CIN")) || cell->ports.count(ctx->id("COUT")))
            return false;
        const std::string name = cell->name.str(ctx);
        return name.find("PACKER") == std::string::npos &&
               name.find("CARRY_VCC") == std::string::npos;
    };

    std::vector<CellInfo *> roots;
    std::unordered_map<CellInfo *, bool> output_boundary;
    for (auto &entry : ctx->cells) {
        CellInfo *cell = entry.second.get();
        if (!eligible(cell))
            continue;
        bool boundary = false, boundary_output = false;
        for (auto &port : cell->ports) {
            NetInfo *net = port.second.net;
            if (net == nullptr)
                continue;
            if (port.second.type == PORT_IN && net->driver.cell != nullptr &&
                net->driver.cell->type == ctx->id("MCU_DIN"))
                boundary = true;
            if (port.second.type == PORT_OUT)
                for (auto &user : net->users)
                    if (is_boundary_sink(user.cell)) {
                        boundary = true;
                        boundary_output = true;
                    }
        }
        if (boundary) {
            roots.push_back(cell);
            output_boundary[cell] = boundary_output;
        }
    }
    std::sort(roots.begin(), roots.end(), [&](CellInfo *a, CellInfo *b) {
        return a->name.str(ctx) < b->name.str(ctx);
    });

    int clusters = 0, members = 0, paired_outputs = 0;
    for (CellInfo *root : roots) {
        if (!eligible(root))
            continue; // already absorbed by an earlier boundary root
        std::vector<std::pair<CellInfo *, Loc>> shape{{root, Loc(0, 0, 0)}};
        // The vendor can fuse a boundary register's D function and FF into one
        // alta_slice using native enable controls. GENERIC_SLICE has no CE,
        // so synthesis may leave one private combinational D producer beside
        // the registered boundary cell. Preserve that atomic relation as a
        // same-tile relative pair. Shared reset/event producers deliberately
        // remain outside the cluster: only a single-user combinational driver
        // is eligible, keeping the grouping bounded and signal-agnostic.
        if (output_boundary[root]) {
            std::vector<CellInfo *> private_drivers;
            for (auto &port : root->ports) {
                NetInfo *net = port.second.net;
                if (port.first == ctx->id("CLK") || port.second.type != PORT_IN ||
                    net == nullptr || net->driver.cell == nullptr)
                    continue;
                int live_users = 0;
                for (auto &user : net->users)
                    if (user.cell != nullptr)
                        ++live_users;
                if (live_users != 1)
                    continue;
                CellInfo *driver = net->driver.cell;
                if (eligible(driver) &&
                    int_or_default(driver->params, ctx->id("FF_USED"), 0) == 0)
                    private_drivers.push_back(driver);
            }
            std::sort(private_drivers.begin(), private_drivers.end(), [&](CellInfo *a, CellInfo *b) {
                return a->name.str(ctx) < b->name.str(ctx);
            });
            if (!private_drivers.empty()) {
                shape.push_back({private_drivers.front(), Loc(0, 0, 2)});
                ++paired_outputs;
            }
        }
        make_relative_cluster(shape, false);
        ++clusters;
        members += int(shape.size());
    }
    if (clusters)
        log_info("agrv2k: formed %d native MCU relative cluster(s), %d cells "
                 "(%d private output producer pair(s))\n",
                 clusters, members, paired_outputs);
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

// Give the constructive MCU entry/exit anchors the routed checkpoint's exact
// BEL choices without binding those cells early.  The anchors must still run:
// they validate both hard-bus directions, mark AGRV2K_MCU_PINPACKED and own
// the odd-slot legality exception used by several qualified captures.
static void hint_replay_bels(Context *ctx, const std::string &map_in_db)
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
    int hinted = 0;
    for (auto &kv : ctx->cells) {
        CellInfo *ci = kv.second.get();
        if (ci->type != ctx->id("GENERIC_SLICE") || ci->bel != BelId())
            continue;
        auto it = placements.find(ci->name.str(ctx));
        if (it == placements.end())
            continue;
        auto existing = ci->attrs.find(ctx->id("BEL"));
        if (existing != ci->attrs.end() && existing->second.as_string() != it->second)
            log_error("agrv2k: replay BEL hint for '%s' conflicts with source BEL attribute\n",
                      ci->name.c_str(ctx));
        ci->attrs[ctx->id("BEL")] = Property(it->second);
        ++hinted;
    }
    log_info("agrv2k: supplied %d checkpoint BEL hint(s) to constructive packers\n", hinted);
}

// Reserve direct global-clock taps as one tree before router2 decomposes a
// high-fanout clock into independent arcs.  The exact sixteen-lane checkpoint
// has eighteen GCLK0->ClkMUX taps; router2 consistently routed sixteen and
// then rejected the seventeenth even though every tap is a direct pip on the
// same net.  Binding the dedicated taps atomically reflects their hardware
// topology and leaves ordinary data routing untouched.
static void lock_global_clock_taps(Context *ctx)
{
    int locked = 0;
    std::set<int> seen;
    for (auto &kv : ctx->nets) {
        NetInfo *net = kv.second.get();
        if (net->driver.cell == nullptr || net->driver.cell->bel == BelId())
            continue;
        WireId source = ctx->getBelPinWire(
            net->driver.cell->bel, net->driver.port);
        if (source == WireId())
            continue;
        std::string sw = ctx->getWireName(source).str(ctx);
        if (sw.rfind("GCLK", 0) != 0)
            continue;
        for (auto &user : net->users) {
            if (user.cell == nullptr || user.cell->bel == BelId())
                continue;
            std::string port = user.port.str(ctx);
            if (port != "CLK" && port != "Clk0" && port != "Clk1")
                continue;
            WireId target = ctx->getBelPinWire(user.cell->bel, user.port);
            if (target == WireId())
                log_error("agrv2k: clock sink '%s.%s' has no BEL pin wire\n",
                          user.cell->name.c_str(ctx), port.c_str());
            std::string tw = ctx->getWireName(target).str(ctx);
            PipId pip = ctx->getPipByNameStr(sw + "." + tw);
            if (pip == PipId())
                log_error("agrv2k: direct global-clock tap absent: %s -> %s\n",
                          sw.c_str(), tw.c_str());
            if (!seen.insert(pip.index).second)
                continue;
            if (!ctx->checkPipAvailForNet(pip, net))
                log_error("agrv2k: global-clock tap conflict: %s -> %s\n",
                          sw.c_str(), tw.c_str());
            ctx->bindPip(pip, net, STRENGTH_LOCKED);
            ++locked;
        }
    }
    if (locked)
        log_info("agrv2k: pre-routed %d direct global-clock tap(s)\n", locked);
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
    bool hard_boundary_replay =
            std::getenv("AGRV2K_REPLAY_BELS_HARD") != nullptr;
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
        // A placement-only boundary replay deliberately fixes an already
        // silicon-qualified MCU ingress/egress cell before the constructive
        // anchors inspect its newly-added interior users.  Mark the same
        // legality exception the anchors would have supplied; the strict
        // router still has to prove every new interior path.
        if (hard_boundary_replay && ci->type == ctx->id("GENERIC_SLICE"))
            ci->attrs[ctx->id("AGRV2K_MCU_PINPACKED")] = Property(1);
        if (hard_boundary_replay)
            ci->attrs.erase(ctx->id("BEL"));
    }
    log_info("agrv2k: replay-bound %d checkpoint BEL constraint(s)\n", bound);
}

// Explicit complete-footprint route-throughs need their characterized sites
// reserved before the generic entry/exit placers consume them.  Viaduct does
// not run generic nextpnr's later BEL-attribute binder, so bind these exact
// constraints here and leave the footprint attribute for routing/bitgen.
static void pack_route_through_bels(Context *ctx)
{
    int bound = 0;
    for (auto &kv : ctx->cells) {
        CellInfo *ci = kv.second.get();
        if (ci->type != ctx->id("GENERIC_SLICE") ||
            ci->attrs.count(ctx->id("AGRV2K_ROUTE_THROUGH")) == 0)
            continue;
        auto requested = ci->attrs.find(ctx->id("BEL"));
        // A route-through that directly drives a BRAM input may already have
        // been bound by pack_bram_pin_drivers(), which consumes its BEL
        // attribute after checking the exact pin-driver slot.  Retain that
        // concrete binding; an unbound cell still requires an explicit BEL.
        if (requested == ci->attrs.end() && ci->bel == BelId())
            log_error("agrv2k: explicit route-through '%s' requires an exact BEL\n",
                      ci->name.c_str(ctx));
        BelId wanted = requested == ci->attrs.end()
                ? ci->bel : ctx->getBelByNameStr(requested->second.as_string());
        if (wanted == BelId())
            log_error("agrv2k: route-through cell '%s' names unknown BEL '%s'\n",
                      ci->name.c_str(ctx), requested == ci->attrs.end()
                              ? "<invalid prebinding>" : requested->second.as_string().c_str());
        if (ci->bel != BelId()) {
            if (ci->bel != wanted)
                log_error("agrv2k: route-through BEL for '%s' conflicts with prior hard packing\n",
                          ci->name.c_str(ctx));
        } else {
            if (!ctx->checkBelAvail(wanted))
                log_error("agrv2k: route-through BEL %s for '%s' is occupied by '%s'\n",
                          ctx->getBelName(wanted).str(ctx).c_str(), ci->name.c_str(ctx),
                          ctx->getBoundBelCell(wanted)->name.c_str(ctx));
            ctx->bindBel(wanted, ci, STRENGTH_LOCKED);
            ++bound;
        }
        if (requested != ci->attrs.end())
            ci->attrs.erase(ctx->id("BEL"));
    }
    if (bound)
        log_info("agrv2k: bound %d explicit route-through cell(s) to characterized BELs\n", bound);
}

static void pack_distribution_root_bels(Context *ctx)
{
    int bound = 0;
    for (auto &kv : ctx->cells) {
        CellInfo *ci = kv.second.get();
        if (ci->type != ctx->id("GENERIC_SLICE") ||
            ci->attrs.count(ctx->id("AGRV2K_DISTRIBUTION_ROOT")) == 0)
            continue;
        auto requested = ci->attrs.find(ctx->id("BEL"));
        if (requested == ci->attrs.end() || requested->second.as_string() != "X17Y12_SLICE0")
            log_error("agrv2k: distribution root '%s' is outside X17Y12_SLICE0\n",
                      ci->name.c_str(ctx));
        BelId wanted = ctx->getBelByNameStr("X17Y12_SLICE0");
        if (ci->bel == BelId()) {
            if (!ctx->checkBelAvail(wanted))
                log_error("agrv2k: distribution-root BEL is occupied\n");
            ctx->bindBel(wanted, ci, STRENGTH_LOCKED);
            ++bound;
        } else if (ci->bel != wanted) {
            log_error("agrv2k: distribution-root BEL conflicts with prior hard packing\n");
        }
        ci->attrs.erase(ctx->id("BEL"));
    }
    if (bound)
        log_info("agrv2k: bound %d distribution root(s)\n", bound);
}

// qin_pack assigns inferred own-Q feedback cells only to the bounded,
// silicon-qualified X14Y11 direct-D pool.  The ordinary uarch constructive
// placers intentionally skip cells carrying a BEL attribute, but the Viaduct
// pack path does not run generic nextpnr's later BEL-attribute binder.  Bind
// these explicit direct-D constraints here after MCU entry/exit anchoring and
// fail closed on any conflict instead of letting analytical placement move a
// state cell onto an unqualified site.
static void pack_direct_d_bels(Context *ctx)
{
    int bound = 0;
    for (auto &kv : ctx->cells) {
        CellInfo *ci = kv.second.get();
        if (ci->type != ctx->id("GENERIC_SLICE") ||
            ci->attrs.count(ctx->id("agamemnon_direct_d_feedback")) == 0)
            continue;
        auto requested = ci->attrs.find(ctx->id("BEL"));
        if (requested == ci->attrs.end())
            continue;
        BelId wanted = ctx->getBelByNameStr(requested->second.as_string());
        if (wanted == BelId())
            log_error("agrv2k: direct-D cell '%s' names unknown BEL '%s'\n",
                      ci->name.c_str(ctx), requested->second.as_string().c_str());
        if (ci->bel != BelId()) {
            if (ci->bel != wanted)
                log_error("agrv2k: direct-D BEL for '%s' conflicts with prior hard packing\n",
                          ci->name.c_str(ctx));
        } else {
            if (!ctx->checkBelAvail(wanted))
                log_error("agrv2k: direct-D BEL %s for '%s' is occupied by '%s'\n",
                          ctx->getBelName(wanted).str(ctx).c_str(), ci->name.c_str(ctx),
                          ctx->getBoundBelCell(wanted)->name.c_str(ctx));
            ctx->bindBel(wanted, ci, STRENGTH_LOCKED);
            ++bound;
        }
        ci->attrs.erase(ctx->id("BEL"));
    }
    if (bound)
        log_info("agrv2k: bound %d inferred direct-D cell(s) to qualified BELs\n", bound);
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
        if (ci->type != ctx->id("GENERIC_SLICE") || ci->bel != BelId() ||
            ci->cluster != ClusterId() ||
            ci->attrs.count(ctx->id("BEL")))
            continue;
        const std::string nm = ci->name.str(ctx);
        if (nm.find("PACKER") != std::string::npos || nm.find("CARRY_VCC") != std::string::npos)
            continue;
        cells.push_back(ci);
    }
    std::set<CellInfo *> cellset(cells.begin(), cells.end());
    std::unordered_map<CellInfo *, std::set<CellInfo *>> deps, indeps;
    std::set<CellInfo *> exitdrv;
    std::unordered_map<CellInfo *, int> exitpref;
    for (auto ci : cells) {
        // A slice may expose distinct registered-Q and combinational-F nets.
        // Treating Q as an alternative to F silently dropped the combinational
        // producer/consumer arcs whenever both ports were present, which in
        // turn broke MCU-cone propagation and co-placement.  Walk both unique
        // output nets so the placement graph matches the actual netlist.
        std::set<NetInfo *> outputs;
        for (const char *pn : {"Q", "F", "COUT"}) {
            NetInfo *o = ci->getPort(ctx->id(pn));
            if (o == nullptr || !outputs.insert(o).second)
                continue;
            for (auto &u : o->users) {
                if (u.cell == nullptr)
                    continue;
                if (pn[0] != 'C' && u.cell->type == ctx->id("MCU_DOUT")) {
                    exitdrv.insert(ci);
                    int k = -1;
                    McuDoutLane kind = mcu_dout_lane(u.cell->name.str(ctx), k);
                    if (kind != LANE_NONE && k >= 0 && k <= 31)
                        exitpref[ci] = tkey(14, mcu_dout_exit_row(kind, k));
                }
                if (cellset.count(u.cell) && u.cell != ci) {
                    deps[ci].insert(u.cell);
                    indeps[u.cell].insert(ci);
                }
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
    std::unordered_map<CellInfo *, int> iopref = exitpref;
    std::vector<int> io_roots;
    std::set<int> exit_roots;
    for (auto &kv : exitpref) exit_roots.insert(kv.second);
    for (auto it = exit_roots.rbegin(); it != exit_roots.rend(); ++it)
        io_roots.push_back(*it);
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
        // A pin-packed MCU_DOUT driver is itself absent from `cells`.  Anchor
        // the unplaced logic feeding each of its input pins at the driver's
        // physical tile; otherwise a readback mux can be rooted at the BRAM
        // approach and leave a captured-data arc spanning the whole die.
        bool fed_by_unplaced = false;
        for (auto &p : anchor->ports)
            if (p.second.type == PORT_IN && p.second.net != nullptr &&
                p.second.net->driver.cell != nullptr && cellset.count(p.second.net->driver.cell)) {
                iopref[p.second.net->driver.cell] = tile;
                fed_by_unplaced = true;
            }
        // qin_pack represents a registered pad input as a pre-placed slice,
        // not as a direct GENERIC_IOB user.  Make that slice the regional
        // root when it actually feeds fabric logic.  (A pre-placed output
        // slice only feeds its IOB and therefore does not become a root.)
        if (feeds_unplaced)
            io_roots.push_back(tile);
        if (fed_by_unplaced)
            io_roots.push_back(tile);
    }
    // Carry the allocator's source-row decision into the ordinary placement
    // problem.  Pin-packed entry slices are already bound (and therefore are
    // absent from `cells`/`deps`), so without an explicit bridge only their
    // immediate users know where the MCU boundary is.  Multi-source BFS over
    // the forward slice graph gives the bounded downstream cone a preferred
    // row and a depth.  Regional placement can then grow that cone eastward
    // instead of collapsing unrelated state/carry back onto the boundary.
    struct McuConePref { int row; int depth; };
    struct McuConeState { CellInfo *cell; int row; int depth; };
    std::unordered_map<CellInfo *, std::map<int, int>> mcu_row_depth;
    std::map<int, int> mcu_anchor_rows;
    std::deque<McuConeState> mcu_queue;
    int mcu_cone_limit = 8;
    if (const char *e = std::getenv("AGRV2K_MCU_CONE_DEPTH"))
        mcu_cone_limit = std::max(1, std::atoi(e));
    for (auto &c : ctx->cells) {
        CellInfo *anchor = c.second.get();
        if (anchor->type != ctx->id("GENERIC_SLICE") || anchor->bel == BelId())
            continue;
        auto row_attr = anchor->attrs.find(ctx->id("AGRV2K_MCU_ENTRY_ROW"));
        if (row_attr == anchor->attrs.end())
            continue;
        int row = int(row_attr->second.as_int64());
        mcu_anchor_rows[row]++;
        std::set<NetInfo *> outputs;
        for (const char *pn : {"Q", "F"}) {
            NetInfo *out = anchor->getPort(ctx->id(pn));
            if (out == nullptr || !outputs.insert(out).second)
                continue;
            for (auto &u : out->users)
                if (u.cell != nullptr && cellset.count(u.cell))
                    mcu_queue.push_back({u.cell, row, 1});
        }
    }
    while (!mcu_queue.empty()) {
        McuConeState s = mcu_queue.front();
        mcu_queue.pop_front();
        if (s.depth > mcu_cone_limit)
            continue;
        auto &by_row = mcu_row_depth[s.cell];
        auto old = by_row.find(s.row);
        if (old != by_row.end() && old->second <= s.depth)
            continue;
        by_row[s.row] = s.depth;
        for (CellInfo *next : deps[s.cell])
            mcu_queue.push_back({next, s.row, s.depth + 1});
    }
    std::unordered_map<CellInfo *, McuConePref> mcu_pref;
    for (auto &kv : mcu_row_depth) {
        int best_depth = 1000000, row_sum = 0, row_count = 0;
        for (auto &rd : kv.second)
            best_depth = std::min(best_depth, rd.second);
        for (auto &rd : kv.second)
            if (rd.second == best_depth) {
                row_sum += rd.first;
                ++row_count;
            }
        mcu_pref[kv.first] = {(row_sum + row_count / 2) / row_count, best_depth};
    }
    // Turn each direct MCU-fed producer and its immediate fanout into a
    // bounded packing unit.  A previous per-root BFS walked the full
    // transitive cone; the first root therefore claimed nearly the entire
    // design and later roots lost their local consumers.  The vendor
    // ensembles instead keep each immediate cone together, spilling that
    // cone once before opening another.  Ownership is deterministic for
    // shared consumers and is derived only from connectivity.
    struct McuPackingGroup {
        CellInfo *root;
        std::vector<CellInfo *> members;
        int row;
        bool carry_atomic;
        int atomic_count;
    };
    std::vector<CellInfo *> mcu_roots;
    for (auto &kv : mcu_pref)
        if (kv.second.depth == 1)
            mcu_roots.push_back(kv.first);
    auto cell_name_less = [&](CellInfo *a, CellInfo *b) {
        return a->name.str(ctx) < b->name.str(ctx);
    };
    std::sort(mcu_roots.begin(), mcu_roots.end(), [&](CellInfo *a, CellInfo *b) {
        size_t af = deps[a].size(), bf = deps[b].size();
        if (af != bf)
            return af > bf;
        return cell_name_less(a, b);
    });
    std::vector<McuPackingGroup> mcu_groups;
    std::unordered_map<CellInfo *, int> mcu_group_for_cell;
    std::set<CellInfo *> mcu_carry_atomic_members;
    for (CellInfo *root_ci : mcu_roots) {
        if (mcu_group_for_cell.count(root_ci))
            continue;
        McuPackingGroup group{root_ci, {root_ci}, mcu_pref[root_ci].row, false, 1};
        std::vector<CellInfo *> immediate(deps[root_ci].begin(), deps[root_ci].end());
        std::sort(immediate.begin(), immediate.end(), cell_name_less);
        for (CellInfo *consumer : immediate)
            if (!mcu_group_for_cell.count(consumer))
                group.members.push_back(consumer);
        auto has_carry_port = [&](CellInfo *member) {
            return member->ports.count(ctx->id("CIN")) || member->ports.count(ctx->id("COUT"));
        };
        for (CellInfo *member : group.members)
            if (has_carry_port(member))
                group.carry_atomic = true;
        // Keep the root and its first three owned consumers atomic even when
        // the complete immediate fanout needs the adjacent spill tile.  This
        // stronger connectivity-only rule necessarily covers the observed
        // carry[0]/carry-in prefix, including soft arithmetic whose packed
        // GENERIC_SLICE ports no longer retain semantic carry names.  Prefer
        // hard-carry consumers when those ports do survive, then stable names.
        mcu_carry_atomic_members.insert(root_ci);
        std::vector<CellInfo *> atomic_consumers(group.members.begin() + 1, group.members.end());
        std::stable_sort(atomic_consumers.begin(), atomic_consumers.end(), [&](CellInfo *a, CellInfo *b) {
            if (has_carry_port(a) != has_carry_port(b))
                return has_carry_port(a) > has_carry_port(b);
            return cell_name_less(a, b);
        });
        for (size_t i = 0; i < atomic_consumers.size() && i < 3; ++i)
            mcu_carry_atomic_members.insert(atomic_consumers[i]);
        group.atomic_count = 1 + int(std::min<size_t>(3, atomic_consumers.size()));
        int gid = int(mcu_groups.size());
        for (CellInfo *member : group.members)
            mcu_group_for_cell[member] = gid;
        mcu_groups.push_back(std::move(group));
    }
    int mcu_region_root = -1;
    for (auto &rc : mcu_anchor_rows)
        if (mcu_region_root < 0 || rc.second > mcu_anchor_rows[mcu_region_root])
            mcu_region_root = rc.first;
    if (!mcu_pref.empty())
        log_info("agrv2k: MCU consumer-first placement carries %d source row(s) into "
                 "%d downstream cell(s), depth <= %d\n",
                 int(mcu_anchor_rows.size()), int(mcu_pref.size()), mcu_cone_limit);
    for (auto &c : ctx->cells) {
        CellInfo *mcu = c.second.get();
        if (mcu->type != ctx->id("MCU_DIN") || mcu->bel == BelId())
            continue;
        std::string name = mcu->name.str(ctx);
        int near = -1;
        int hwbit = parse_after(name, "hwdata");
        int habit = parse_after(name, "haddr");
        if (hwbit >= 0 && hwbit <= 31)
            near = tkey(14, hwbit <= 17 ? 10 : 9);
        else if (habit >= 0 && habit <= 31)
            near = tkey(14, habit <= 9 ? 12 : (habit <= 29 ? 11 : 10));
        else if (name.find("hwrite") != std::string::npos ||
                 name.find("hready") != std::string::npos ||
                 name.find("htrans") != std::string::npos ||
                 name.find("hsize") != std::string::npos ||
                 name.find("hburst") != std::string::npos)
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
        // Group each MCU-fed producer with its immediate consumers before
        // opening the next entry-root cluster.  A global depth sort placed all
        // depth-1 word-lane producers first, filling their preferred tiles
        // before any depth-2 arithmetic consumer was considered.  The vendor
        // instead co-locates each producer with its immediate fanout.  A
        // immediate-cone order makes same-tile capacity available to that
        // local producer/consumer cluster.  This is signal- and design-agnostic.
        for (auto &group : mcu_groups)
            for (CellInfo *member : group.members)
                if (seen.insert(member).second)
                    order.push_back(member);
        if (!mcu_groups.empty())
            log_info("agrv2k: ordered %d immediate MCU-fed packing group(s), %d carry-atomic\n",
                     int(mcu_groups.size()), int(std::count_if(mcu_groups.begin(), mcu_groups.end(),
                         [](const McuPackingGroup &g) { return g.carry_atomic; })));
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
    // The vendor density measured for the wide-MCU ensembles (up to 171 LUTs
    // in 11 tiles) is mathematically impossible under the historical
    // even-only eight-site sufficient condition.  Promote only the cap-8
    // wide-MCU rung to the complete 16-site modeled tile.  Odd sites remain
    // subject to normal BEL legality and strict routed-PIP admission; the
    // scoped cell attribute below avoids weakening unrelated designs.
    bool dense_mcu_odd = !mcu_groups.empty() && cells.size() > 16 && CAP >= 8;
    if (dense_mcu_odd) {
        CAP = 16;
        log_info("agrv2k: wide-MCU density rung enables all 16 modeled slice sites per tile\n");
    }

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
    // Combinational-only (FF_USED==0) occupancy per tile. X15Y12_SLICE4 is reachable only via the
    // registered Q path (OMUX12); an ordinary LUT placed there (OMUX14) cannot reach the right-hand
    // routing component (see the final bel-binding loop below), so that ONE tile has 7 usable even
    // slots for combinational cells, not 8. The CAP-vs-occ accounting below otherwise assumes every
    // tile has a full 8 even slots -- tracked separately so the tile-SELECTION phase spills the excess
    // combinational cell to a different tile instead of the bel-binding loop silently falling back to
    // an odd slice (found via a WIDTH=3 fanout-split attempt that densely packed 8 identity buffers
    // onto X15Y12: isBelLocationValid then correctly rejected the 8th, which had nowhere even to go).
    std::unordered_map<int, int> occ_comb;
    for (auto &c : ctx->cells) {
        CellInfo *ci = c.second.get();
        if (ci->type == ctx->id("GENERIC_SLICE") && ci->bel != BelId()) {
            Loc l = ctx->getBelLocation(ci->bel);
            int t = tkey(l.x, l.y);
            occ[t]++;
            if (int_or_default(ci->params, ctx->id("FF_USED"), 0) == 0)
                occ_comb[t]++;
        }
    }
    auto is_combinational = [&](CellInfo *ci) -> bool {
        return int_or_default(ci->params, ctx->id("FF_USED"), 0) == 0;
    };
    auto even_slot_cap = [&](int t, CellInfo *ci) -> int {
        if (dense_mcu_odd)
            return is_combinational(ci) && (t >> 8) == 15 && (t & 0xff) == 12 ? 15 : 16;
        if (!is_combinational(ci))
            return 8; // a registered cell may use every even slot, including X15Y12_SLICE4
        return ((t >> 8) == 15 && (t & 0xff) == 12) ? 7 : 8;
    };
    auto feasible = [&](CellInfo *ci, int t) -> bool {
        if (!slice_tiles.count(t)) // neighbour tiles from tile_adj may be bel-less (BRAM/IO columns)
            return false;
        if (occ[t] >= CAP)
            return false;
        if (is_combinational(ci) && occ_comb[t] >= even_slot_cap(t, ci))
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
        if (bramadj.empty() && mcu_region_root >= 0)
            root = tkey(14, mcu_region_root);
        else if (bramadj.empty() && !io_roots.empty())
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
        // The historical compactness check lived only in the exact DFS below,
        // which regional placement bypasses for every design above 16 cells.
        // Apply the same opt-in Manhattan bound to the regional candidate set
        // before capacity/forced-anchor selection. This is deliberately not a
        // default: the CLI exposes it as an experiment until corpus A/B data
        // shows a routing win instead of merely a smaller placement span.
        if (compact_maxd > 0) {
            int rx = root >> 8, ry = root & 0xff;
            region.erase(std::remove_if(region.begin(), region.end(), [&](int t) {
                return std::abs((t >> 8) - rx) + std::abs((t & 0xff) - ry) > compact_maxd;
            }), region.end());
            log_info("agrv2k: REGIONAL compact radius %d exposes %d/%d candidate tiles around %d,%d\n",
                     compact_maxd, int(region.size()), int(cand.size()), rx, ry);
            if (region.empty()) {
                log_error("agrv2k: REGIONAL compact radius %d leaves no slice tile around root %d,%d\n",
                          compact_maxd, rx, ry);
                return;
            }
        }
        size_t preplaced_slices = 0;
        for (auto &kv : occ) preplaced_slices += kv.second;
        size_t need_tiles = (cells.size() + preplaced_slices + CAP - 1) / CAP;
        if (dense_mcu_odd) {
            // A mathematically full 16-site packing leaves no switch freedom:
            // one legal local path can consume the sole endpoint needed by a
            // later arc.  Expose 20% deterministic routing slack while still
            // staying far below the prior 32--91-tile scatter.
            size_t route_slack = std::max<size_t>(2, (need_tiles + 4) / 5);
            need_tiles += route_slack;
            log_info("agrv2k: wide-MCU density exposes %d routing-slack tile(s)\n",
                     int(route_slack));
        }
        if (const char *e = std::getenv("AGRV2K_CONDPLACE_SLACK_TILES"))
            need_tiles += std::max(0, std::atoi(e));
        // Reserve enough nearest tiles around every I/O anchor to hold its direct root cells.
        std::unordered_map<int, int> pref_count;
        for (auto &kv : iopref) pref_count[kv.second]++;
        std::set<int> forced;
        for (auto &pc : pref_count) {
            // When compactness is active, forced I/O capacity must come from
            // inside the same bounded region; reintroducing a tile from the
            // unfiltered candidate set would silently violate the option.
            std::vector<int> byio = compact_maxd > 0 ? region : cand;
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
        std::unordered_map<int, int> mcu_group_primary, mcu_group_spill;
        large_placed = true;
        for (auto ci : cells) {
            int best = -1, best_score = -1000000000;
            for (int t : region) {
                auto oi = occ.find(t);
                int used = oi == occ.end() ? 0 : oi->second;
                if (used >= CAP)
                    continue;
                if (is_combinational(ci)) {
                    auto ci_oi = occ_comb.find(t);
                    int comb_used = ci_oi == occ_comb.end() ? 0 : ci_oi->second;
                    if (comb_used >= even_slot_cap(t, ci))
                        continue;
                }
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
                auto mp = mcu_pref.find(ci);
                if (mp != mcu_pref.end()) {
                    int px = std::min(20, 14 + (mp->second.depth + 1) / 2);
                    int py = mp->second.row;
                    int md = std::abs((t >> 8)-px) + 2 * std::abs((t & 0xff)-py);
                    score += 8000 - 500 * md;
                    if ((t >> 8) < 14)
                        score -= 8000;
                }
                auto mg = mcu_group_for_cell.find(ci);
                if (mg != mcu_group_for_cell.end()) {
                    int gid = mg->second;
                    if (int(mcu_groups[gid].members.size()) > 2 * CAP)
                        continue;
                    auto primary = mcu_group_primary.find(gid);
                    if (primary == mcu_group_primary.end()) {
                        // A group's first cell selects its primary tile.  Do
                        // not start on a nearly-full tile that cannot hold the
                        // atomic four-cell prefix, and preflight enough free
                        // capacity in one physical neighbour for the rest.
                        int free_primary = CAP - used;
                        if (free_primary < mcu_groups[gid].atomic_count)
                            continue;
                        int remaining = int(mcu_groups[gid].members.size()) - free_primary;
                        if (remaining > 0) {
                            bool adjacent_capacity = false;
                            for (int n : region) {
                                int md = std::abs((n >> 8) - (t >> 8)) +
                                         std::abs((n & 0xff) - (t & 0xff));
                                int nused = occ.count(n) ? occ.at(n) : 0;
                                if (md == 1 && CAP - nused >= remaining) {
                                    adjacent_capacity = true;
                                    break;
                                }
                            }
                            if (!adjacent_capacity)
                                continue;
                        }
                        score += 2000 * free_primary;
                    }
                    if (primary != mcu_group_primary.end()) {
                        bool same = t == primary->second;
                        int md = std::abs((t >> 8) - (primary->second >> 8)) +
                                 std::abs((t & 0xff) - (primary->second & 0xff));
                        auto spill = mcu_group_spill.find(gid);
                        bool fits_two = int(mcu_groups[gid].members.size()) <= 2 * CAP;
                        if (mcu_carry_atomic_members.count(ci) && !same)
                            continue;
                        if (fits_two && !same) {
                            if (spill != mcu_group_spill.end()) {
                                if (t != spill->second)
                                    continue;
                            } else if (md != 1) {
                                continue;
                            }
                        }
                        if (same)
                            score += 120000;
                        else if (spill != mcu_group_spill.end() && t == spill->second)
                            score += 100000;
                        else if (md == 1)
                            score += 90000;
                    }
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
            if (best < 0) {
                auto mg = mcu_group_for_cell.find(ci);
                if (mg != mcu_group_for_cell.end()) {
                    int gid = mg->second;
                    log_info("agrv2k: density group %d failed at cell '%s' (size %d, atomic %d, "
                             "primary %s, spill %s)\n", gid, ctx->nameOf(ci),
                             int(mcu_groups[gid].members.size()), mcu_groups[gid].atomic_count,
                             mcu_group_primary.count(gid) ? "set" : "unset",
                             mcu_group_spill.count(gid) ? "set" : "unset");
                }
                large_placed = false;
                break;
            }
            assign[ci] = best;
            occ[best]++;
            if (is_combinational(ci))
                occ_comb[best]++;
            auto mg = mcu_group_for_cell.find(ci);
            if (mg != mcu_group_for_cell.end()) {
                int gid = mg->second;
                auto primary = mcu_group_primary.find(gid);
                if (primary == mcu_group_primary.end())
                    mcu_group_primary[gid] = best;
                else if (best != primary->second && !mcu_group_spill.count(gid))
                    mcu_group_spill[gid] = best;
            }
        }
        if (large_placed)
            log_info("agrv2k: REGIONAL-placed %d cells across %d/%d candidate tiles (cap %d, root %d,%d)\n",
                     int(cells.size()), int(occ.size()), int(region.size()), CAP, root >> 8, root & 0xff);
        if (large_placed && !mcu_groups.empty())
            log_info("agrv2k: density-packed %d MCU groups into %d primary/%d adjacent spill tiles\n",
                     int(mcu_groups.size()), int(mcu_group_primary.size()), int(mcu_group_spill.size()));
    }

    // A wide MCU design must not silently fall through to the legacy exact
    // embedder after a density constraint fails.  The CLI will retry the next
    // bounded capacity rung; allowing fallback here would erase the policy
    // under test and recreate the 32--91-tile scatter failure.
    if (use_regional && !large_placed && !mcu_groups.empty()) {
        log_error("agrv2k: MCU density packing could not fit %d immediate group(s) at cap %d; "
                  "retry a higher bounded capacity rung\n", int(mcu_groups.size()), CAP);
        return;
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
        auto mp = mcu_pref.find(ci);
        if (mp != mcu_pref.end()) {
            int px = std::min(20, 14 + (mp->second.depth + 1) / 2);
            addpref(tkey(px, mp->second.row));
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
            bool ci_comb = is_combinational(ci);
            if (ci_comb) occ_comb[t]++;
            if (i == 0) compact_anchor = t;   // anchor the bounding box on the first (exit-driver) cell
            if (place(i + 1))
                return true;
            assign.erase(ci);
            occ[t]--;
            if (ci_comb) occ_comb[t]--;
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
    bool allow_odd_fallback = dense_mcu_odd || std::getenv("AGRV2K_STRICT_ALLOW_ODD") != nullptr;
    std::unordered_map<uint64_t, bool> local_reach_cache;
    auto wire_reaches = [&](WireId source, WireId target) -> bool {
        if (source == WireId() || target == WireId())
            return false;
        uint64_t key = (uint64_t(uint32_t(source.index)) << 32) | uint32_t(target.index);
        auto cached = local_reach_cache.find(key);
        if (cached != local_reach_cache.end())
            return cached->second;
        std::unordered_set<int> seen{source.index};
        std::vector<WireId> queue{source};
        bool found = source == target;
        for (size_t head = 0; head < queue.size() && !found; ++head)
            for (PipId pip : ctx->getPipsDownhill(queue[head])) {
                WireId next = ctx->getPipDstWire(pip);
                if (next == target) {
                    found = true;
                    break;
                }
                if (seen.insert(next.index).second)
                    queue.push_back(next);
            }
        local_reach_cache[key] = found;
        return found;
    };
    auto preserves_bound_local_arcs = [&](CellInfo *ci, BelId candidate, int tile) -> bool {
        // Odd slots make full vendor-like density possible, but the intra-tile
        // crossbar has a small set of dead endpoint pairs.  Validate every
        // already concrete same-tile producer/consumer arc against the loaded
        // strict graph before committing this BEL.  Later cells perform the
        // symmetric check back to this cell, so every local pair is covered.
        for (auto &port : ci->ports) {
            NetInfo *net = port.second.net;
            if (net == nullptr)
                continue;
            if (port.second.type == PORT_IN && net->driver.cell != nullptr &&
                net->driver.cell->bel != BelId()) {
                Loc other = ctx->getBelLocation(net->driver.cell->bel);
                if (tkey(other.x, other.y) == tile &&
                    !wire_reaches(ctx->getBelPinWire(net->driver.cell->bel, net->driver.port),
                                  ctx->getBelPinWire(candidate, port.first)))
                    return false;
            }
            if (port.second.type == PORT_OUT)
                for (auto &user : net->users) {
                    if (user.cell == nullptr || user.cell->bel == BelId())
                        continue;
                    Loc other = ctx->getBelLocation(user.cell->bel);
                    if (tkey(other.x, other.y) == tile &&
                        !wire_reaches(ctx->getBelPinWire(candidate, port.first),
                                      ctx->getBelPinWire(user.cell->bel, user.port)))
                        return false;
                }
        }
        return true;
    };
    for (auto ci : cells) {
        int t = assign[ci];
        BelId b;
        // Prefer silicon-proven even slots, but never overwrite a BRAM-pin/carry binding;
        // use a remaining odd slot only when explicitly permitted for diagnostics
        // (AGRV2K_STRICT_ALLOW_ODD -- the same escape hatch isBelLocationValid honours).
        // The tile-selection phase above accounts for every known even-slot capacity
        // reduction (see occ_comb/even_slot_cap), so this pass should not be needed in
        // ordinary operation; reaching it means a NEW capacity gap exists that the
        // accounting above does not yet model.
        int passes = allow_odd_fallback ? 2 : 1;
        if (dense_mcu_odd)
            ci->attrs[ctx->id("AGRV2K_DENSE_MCU_ODD_OK")] = Property(1);
        for (int pass = 0; pass < passes && b == BelId(); pass++)
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
                if (try_b != BelId() && ctx->checkBelAvail(try_b) &&
                    preserves_bound_local_arcs(ci, try_b, t)) {
                    b = try_b;
                    break;
                }
            }
        if (b == BelId())
            log_error("agrv2k: no free even slice bel on assigned tile (%d,%d) for cell '%s' "
                      "(tile capacity accounting under-counted an even-slot restriction; rerun with "
                      "AGRV2K_STRICT_ALLOW_ODD=1 for a diagnostic odd-slot placement)\n",
                      t >> 8, t & 0xff, ctx->nameOf(ci));
        ctx->bindBel(b, ci, STRENGTH_LOCKED);
    }
    if (dense_mcu_odd && std::getenv("AGRV2K_LOCK_DENSE_LOCAL_EARLY") != nullptr) {
        struct DenseLocalArc {
            NetInfo *net;
            CellInfo *user;
            IdString port;
            int tile;
            int flex;
        };
        std::vector<DenseLocalArc> local_arcs;
        for (auto &net_kv : ctx->nets) {
            NetInfo *net = net_kv.second.get();
            CellInfo *driver = net->driver.cell;
            if (driver == nullptr || driver->type != ctx->id("GENERIC_SLICE") ||
                driver->bel == BelId())
                continue;
            Loc dl = ctx->getBelLocation(driver->bel);
            int tile = tkey(dl.x, dl.y);
            for (auto &user : net->users) {
                if (user.cell == nullptr || user.cell->type != ctx->id("GENERIC_SLICE") ||
                    user.cell->bel == BelId())
                    continue;
                Loc ul = ctx->getBelLocation(user.cell->bel);
                if (tkey(ul.x, ul.y) != tile)
                    continue;
                WireId target = ctx->getBelPinWire(user.cell->bel, user.port);
                std::unordered_set<int> uphill{target.index};
                std::vector<WireId> q{target};
                for (size_t head = 0; head < q.size(); ++head)
                    for (PipId pip : ctx->getPipsUphill(q[head])) {
                        Loc pl = ctx->getPipLocation(pip);
                        if (tkey(pl.x, pl.y) != tile)
                            continue;
                        WireId src = ctx->getPipSrcWire(pip);
                        if (uphill.insert(src.index).second)
                            q.push_back(src);
                    }
                local_arcs.push_back({net, user.cell, user.port, tile, int(uphill.size())});
            }
        }
        std::stable_sort(local_arcs.begin(), local_arcs.end(), [&](const DenseLocalArc &a,
                                                                   const DenseLocalArc &b) {
            if (a.flex != b.flex)
                return a.flex < b.flex;
            if (a.net->name != b.net->name)
                return a.net->name.str(ctx) < b.net->name.str(ctx);
            return a.user->name.str(ctx) < b.user->name.str(ctx);
        });
        int locked_arcs = 0, locked_pips = 0, deferred_arcs = 0;
        for (const DenseLocalArc &arc : local_arcs) {
            WireId source = ctx->getBelPinWire(arc.net->driver.cell->bel, arc.net->driver.port);
            WireId target = ctx->getBelPinWire(arc.user->bel, arc.port);
            if (ctx->getBoundWireNet(target) == arc.net) {
                ++locked_arcs;
                continue;
            }
            std::vector<WireId> q{source};
            std::unordered_map<int, PipId> previous;
            previous[source.index] = PipId();
            for (size_t head = 0; head < q.size() && !previous.count(target.index); ++head)
                for (PipId pip : ctx->getPipsDownhill(q[head])) {
                    Loc pl = ctx->getPipLocation(pip);
                    if (tkey(pl.x, pl.y) != arc.tile ||
                        !ctx->checkPipAvailForNet(pip, arc.net))
                        continue;
                    WireId dst = ctx->getPipDstWire(pip);
                    if (previous.emplace(dst.index, pip).second)
                        q.push_back(dst);
                }
            if (!previous.count(target.index)) {
                ++deferred_arcs;
                continue;
            }
            std::vector<PipId> route;
            for (WireId cursor = target; cursor != source;) {
                PipId pip = previous.at(cursor.index);
                route.push_back(pip);
                cursor = ctx->getPipSrcWire(pip);
            }
            std::reverse(route.begin(), route.end());
            if (ctx->getBoundWireNet(source) == nullptr)
                ctx->bindWire(source, arc.net, STRENGTH_LOCKED);
            for (PipId pip : route) {
                WireId dst = ctx->getPipDstWire(pip);
                if (ctx->getBoundWireNet(dst) == arc.net)
                    continue;
                ctx->bindPip(pip, arc.net, STRENGTH_LOCKED);
                ++locked_pips;
            }
            ++locked_arcs;
        }
        log_info("agrv2k: pre-routed %d dense same-tile arc(s) over %d strict pip(s); "
                 "%d deferred to router2\n", locked_arcs, locked_pips, deferred_arcs);
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

    // Interconnect timing is edge-lumped in dev_pips.csv: every row already
    // carries the decoded BAR source-family charge, with only the three
    // NNLS-supported measured families allowed to replace their conservative
    // BAR maxima. Keep the exact per-pip values for STA/router accounting and
    // collapse the admitted graph by (tile, wire type) for a fast, witnessed
    // lower-bound lookahead. No geometry formula or unadmitted edge enters it.
    std::unordered_map<int, delay_t> pip_delay_by_index;
    std::vector<int> timing_node_by_wire;
    std::vector<std::unordered_map<int, delay_t>> timing_uphill;
    mutable std::unordered_map<int, std::vector<delay_t>> timing_distance_cache;
    mutable std::deque<int> timing_cache_order;
    static constexpr size_t TIMING_CACHE_LIMIT = 64;

    // Conducting inter-tile tile-graph (RMUX->RMUX, silicon-verified), for isBelLocationValid's
    // conducting-pair check. Loaded from master_conduction.csv in the chipdb dir (if present).
    std::unordered_map<int, std::unordered_set<int>> tile_adj;
    // Tile keys that actually carry GENERIC_SLICE bels (LogicTILEs). tile_adj is built from RMUX->RMUX
    // pips, which include non-LogicTILE columns (the x=13 BRAM column, IO/MCU edge tiles) with NO slice
    // bel -- pack_condplace must never try to bind e.g. X13Y4_SLICE0 (getBelByName ASSERTS on unknown).
    std::set<int> slice_tiles;
    int bram_xy = -1;        // the ALTA_BRAM9K bel's tile key (set in load_db), -1 if none
    int bram_approach = -1;  // the slice tile adjacent to the BRAM that its address/data pips reach through
    struct McuRegionWitness {
        bool loaded = false;
        int min_x = 0, max_x = 0, min_y = 0, max_y = 0;
        int decoded_builds = 0, max_logic_slices = 0;
        int max_occupied_tiles = 0, max_slices_per_tile = 0;
    } mcu_region_witness;
    // K-hop conducting closure (undirected BFS over tile_adj, K = AGRV2K_CONDPAIR_HOPS). The data mesh
    // chains RMUX up to ~4 hops, so a single-hop conducting-pair rule is TOO strict for HeAP's legalizer to
    // satisfy at scale (it runs out of legal positions ~30 cells). Allowing <=K-hop pairs gives the
    // legalizer room to converge while every allowed pair is still a conducting path the gated router can
    // realize. Empty when K<=1 (single-hop, the default).
    std::unordered_map<int, std::unordered_set<int>> tile_reach;
    // Candidate-BEL legality repeatedly asks whether a fixed hard endpoint can
    // reach a movable structured cell (or vice versa).  Cache reachability by
    // the fixed endpoint wire; the admitted architecture graph is immutable
    // after load_db(), so these sets are safe for the whole placement run.
    mutable std::unordered_map<int, std::unordered_set<int>> downhill_reach;
    mutable std::unordered_map<int, std::unordered_set<int>> uphill_reach;
    mutable std::unordered_map<int, std::set<int>> first_slice_tiles;
    mutable std::unordered_map<int, std::set<int>> last_slice_tiles;
    struct McuCorridorBounds {
        bool constrained = false;
        int min_x = 0, min_y = 0, max_y = 0;
    };
    mutable std::unordered_map<CellInfo *, McuCorridorBounds> mcu_corridor_bounds;
    mutable std::unordered_map<CellInfo *, int> mcu_exit_min_x;
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

    const std::unordered_set<int> &reachable_from(WireId source) const
    {
        auto found = downhill_reach.find(source.index);
        if (found != downhill_reach.end())
            return found->second;
        std::unordered_set<int> seen{source.index};
        std::vector<WireId> queue{source};
        for (size_t head = 0; head < queue.size(); ++head)
            for (PipId pip : ctx->getPipsDownhill(queue[head])) {
                WireId dst = ctx->getPipDstWire(pip);
                if (seen.insert(dst.index).second)
                    queue.push_back(dst);
            }
        return downhill_reach.emplace(source.index, std::move(seen)).first->second;
    }

    const std::unordered_set<int> &reaching(WireId target) const
    {
        auto found = uphill_reach.find(target.index);
        if (found != uphill_reach.end())
            return found->second;
        std::unordered_set<int> seen{target.index};
        std::vector<WireId> queue{target};
        for (size_t head = 0; head < queue.size(); ++head)
            for (PipId pip : ctx->getPipsUphill(queue[head])) {
                WireId src = ctx->getPipSrcWire(pip);
                if (seen.insert(src.index).second)
                    queue.push_back(src);
            }
        return uphill_reach.emplace(target.index, std::move(seen)).first->second;
    }

    const std::set<int> &first_slice_tiles_from(WireId source) const
    {
        auto found = first_slice_tiles.find(source.index);
        if (found != first_slice_tiles.end())
            return found->second;
        std::set<int> entries;
        std::unordered_set<int> seen{source.index};
        std::vector<WireId> queue{source};
        for (size_t head = 0; head < queue.size(); ++head)
            for (PipId pip : ctx->getPipsDownhill(queue[head])) {
                WireId dst = ctx->getPipDstWire(pip);
                if (!seen.insert(dst.index).second)
                    continue;
                int x = -1, y = -1;
                const std::string name = ctx->getWireName(dst).str(ctx);
                if (std::sscanf(name.c_str(), "X%dY%d_", &x, &y) == 2 &&
                    slice_tiles.count(tkey(x, y))) {
                    entries.insert(tkey(x, y));
                    continue; // first fabric tile only; do not wander across the mesh
                }
                queue.push_back(dst);
            }
        return first_slice_tiles.emplace(source.index, std::move(entries)).first->second;
    }

    const std::set<int> &last_slice_tiles_to(WireId target) const
    {
        auto found = last_slice_tiles.find(target.index);
        if (found != last_slice_tiles.end())
            return found->second;
        std::set<int> exits;
        std::unordered_set<int> seen{target.index};
        std::vector<WireId> queue{target};
        for (size_t head = 0; head < queue.size(); ++head)
            for (PipId pip : ctx->getPipsUphill(queue[head])) {
                WireId src = ctx->getPipSrcWire(pip);
                if (!seen.insert(src.index).second)
                    continue;
                int x = -1, y = -1;
                const std::string name = ctx->getWireName(src).str(ctx);
                if (std::sscanf(name.c_str(), "X%dY%d_", &x, &y) == 2 &&
                    slice_tiles.count(tkey(x, y))) {
                    exits.insert(tkey(x, y));
                    continue; // last fabric tile only; do not wander back into the mesh
                }
                queue.push_back(src);
            }
        return last_slice_tiles.emplace(target.index, std::move(exits)).first->second;
    }

    // The hard MCU BEL is physically named at X10Y5, but its wide AHB roots
    // emerge from the fixed X13Y9..12 boundary.  Ordinary wirelength therefore
    // pulls native placement toward the wrong coordinate unless legality names
    // the real corridor.  Derive its first admitted slice tile from the graph:
    // X13 entries stay inside the envelope of the actual hard-input rows feeding
    // the fused cell and may spread east.  A one-row operand therefore stays on
    // its assigned row; a LUT combining adjacent operand/control rows remains
    // placeable between them.  This matches the vendor-observed capacity rule
    // without an absolute BEL or per-design pin.
    bool mcu_entry_corridor_contains(CellInfo *cell, BelId candidate) const
    {
        auto cached = mcu_corridor_bounds.find(cell);
        if (cached == mcu_corridor_bounds.end()) {
            McuCorridorBounds bounds;
            const IdString mcu_din = ctx->id("MCU_DIN");
            for (auto &port : cell->ports) {
                NetInfo *net = port.second.net;
                if (port.second.type != PORT_IN || net == nullptr ||
                    net->driver.cell == nullptr || net->driver.cell->type != mcu_din ||
                    net->driver.cell->bel == BelId())
                    continue;
                WireId source = ctx->getBelPinWire(net->driver.cell->bel, net->driver.port);
                int sx = -1, sy = -1;
                const std::string source_name = ctx->getWireName(source).str(ctx);
                if (std::sscanf(source_name.c_str(), "X%dY%d_", &sx, &sy) != 2 || sx != 13)
                    continue; // evidenced only at the fixed X13 wide-AHB boundary
                for (int entry : first_slice_tiles_from(source)) {
                    int ex = entry >> 8, ey = entry & 0xff;
                    if (!bounds.constrained) {
                        bounds = {true, ex, ey, ey};
                    } else {
                        bounds.min_x = std::max(bounds.min_x, ex);
                        bounds.min_y = std::min(bounds.min_y, ey);
                        bounds.max_y = std::max(bounds.max_y, ey);
                    }
                }
            }
            cached = mcu_corridor_bounds.emplace(cell, bounds).first;
        }
        const McuCorridorBounds &bounds = cached->second;
        if (!bounds.constrained)
            return true;
        Loc loc = ctx->getBelLocation(candidate);
        return loc.x >= bounds.min_x && loc.y >= bounds.min_y && loc.y <= bounds.max_y;
    }

    // Native clusters bypass the historical absolute exit-anchor pass. A
    // plain graph-reachability check is therefore too weak: long mesh paths
    // can pull an HRDATA driver west of the hard boundary even though decoded
    // placements keep the logic on the fabric side. Recover the invariant
    // from the admitted graph by reverse-walking each fixed MCU_DOUT sink to
    // its last fabric tile. Candidate drivers may spread east, but never cross
    // west of that physical exit column.
    bool mcu_exit_corridor_contains(CellInfo *cell, BelId candidate) const
    {
        auto cached = mcu_exit_min_x.find(cell);
        if (cached == mcu_exit_min_x.end()) {
            int min_x = -1;
            for (auto &port : cell->ports) {
                NetInfo *net = port.second.net;
                if (port.second.type != PORT_OUT || net == nullptr)
                    continue;
                for (auto &user : net->users) {
                    if (user.cell == nullptr || user.cell->type != ctx->id("MCU_DOUT") ||
                        user.cell->bel == BelId())
                        continue;
                    WireId target = ctx->getBelPinWire(user.cell->bel, user.port);
                    for (int exit : last_slice_tiles_to(target))
                        min_x = std::max(min_x, exit >> 8);
                }
            }
            cached = mcu_exit_min_x.emplace(cell, min_x).first;
        }
        if (cached->second < 0)
            return true;
        return ctx->getBelLocation(candidate).x >= cached->second;
    }

    // A structured fabric cell adjacent to a fixed MCU/IO/BRAM endpoint must
    // be placed where every such endpoint connection exists in the admitted
    // graph.  This is deliberately a topology predicate, not a reservation:
    // the placer may move a cluster among all conducting alternatives and the
    // ordinary router still arbitrates simultaneous resource ownership.
    bool fixed_endpoint_pins_reachable(CellInfo *cell, BelId candidate,
                                       bool explain_invalid) const
    {
        const IdString slice = ctx->id("GENERIC_SLICE");
        for (auto &port : cell->ports) {
            if (port.first == ctx->id("CLK") || port.second.net == nullptr)
                continue;
            NetInfo *net = port.second.net;
            if (port.second.type == PORT_IN && net->driver.cell != nullptr) {
                CellInfo *driver = net->driver.cell;
                if (driver != cell && driver->type != slice && driver->bel != BelId()) {
                    WireId source = ctx->getBelPinWire(driver->bel, net->driver.port);
                    WireId target = ctx->getBelPinWire(candidate, port.first);
                    if ((driver->type == ctx->id("MCU_DIN") &&
                         !mcu_entry_corridor_contains(cell, candidate)) ||
                        source == WireId() || target == WireId() ||
                        !reachable_from(source).count(target.index)) {
                        if (explain_invalid)
                            log_info("agrv2k validity: cell '%s' at %s cannot conduct fixed input net "
                                     "'%s' from '%s'\n",
                                     ctx->nameOf(cell), ctx->nameOfBel(candidate), ctx->nameOf(net),
                                     ctx->nameOf(driver));
                        return false;
                    }
                }
            }
            if (port.second.type != PORT_OUT)
                continue;
            WireId source = ctx->getBelPinWire(candidate, port.first);
            for (auto &user : net->users) {
                if (user.cell == nullptr || user.cell == cell || user.cell->type == slice ||
                    user.cell->bel == BelId())
                    continue;
                WireId target = ctx->getBelPinWire(user.cell->bel, user.port);
                if ((user.cell->type == ctx->id("MCU_DOUT") &&
                     !mcu_exit_corridor_contains(cell, candidate)) ||
                    source == WireId() || target == WireId() ||
                    !reaching(target).count(source.index)) {
                    if (explain_invalid)
                        log_info("agrv2k validity: cell '%s' at %s cannot conduct fixed output net "
                                 "'%s' to '%s'\n",
                                 ctx->nameOf(cell), ctx->nameOfBel(candidate), ctx->nameOf(net),
                                 ctx->nameOf(user.cell));
                    return false;
                }
            }
        }
        return true;
    }

    bool direct_pip_exists(WireId source, WireId target) const
    {
        if (source == WireId() || target == WireId())
            return false;
        for (PipId pip : ctx->getPipsDownhill(source))
            if (ctx->getPipDstWire(pip) == target)
                return true;
        return false;
    }

    // Relative constraints preserve a carry footprint's geometry, but not
    // every translation of a characterized seam has a dedicated carry pip.
    // Reject a translated cluster unless each already-placed CIN/COUT
    // neighbour is joined by the exact admitted one-hop resource.
    bool dedicated_carry_pins_reachable(CellInfo *cell, BelId candidate,
                                        bool explain_invalid) const
    {
        NetInfo *cin = cell->getPort(ctx->id("CIN"));
        if (cin != nullptr && cin->driver.cell != nullptr &&
            cin->driver.cell->bel != BelId()) {
            WireId source = ctx->getBelPinWire(cin->driver.cell->bel, cin->driver.port);
            WireId target = ctx->getBelPinWire(candidate, ctx->id("CIN"));
            if (!direct_pip_exists(source, target)) {
                if (explain_invalid)
                    log_info("agrv2k validity: carry cell '%s' at %s has no dedicated CIN pip "
                             "from '%s'\n",
                             ctx->nameOf(cell), ctx->nameOfBel(candidate),
                             ctx->nameOf(cin->driver.cell));
                return false;
            }
        }
        NetInfo *cout = cell->getPort(ctx->id("COUT"));
        if (cout == nullptr)
            return true;
        WireId source = ctx->getBelPinWire(candidate, ctx->id("COUT"));
        for (auto &user : cout->users) {
            if (user.cell == nullptr || user.cell->bel == BelId())
                continue;
            WireId target = ctx->getBelPinWire(user.cell->bel, user.port);
            if (!direct_pip_exists(source, target)) {
                if (explain_invalid)
                    log_info("agrv2k validity: carry cell '%s' at %s has no dedicated COUT pip "
                             "to '%s'\n",
                             ctx->nameOf(cell), ctx->nameOfBel(candidate),
                             ctx->nameOf(user.cell));
                return false;
            }
        }
        return true;
    }

    // Bind every dynamic MCU_DOUT driver to a slice output that can reach that
    // lane's exact sink in the loaded graph.  Tile proximity is insufficient:
    // the 32-bit bus spans two rows and three boundary-mux families, and two
    // slots on the same tile can belong to different routing components.  A
    // global matching avoids greedily consuming a later lane's sole BEL.
    void pack_exit_anchor()
    {
        struct Item { CellInfo *drv; IdString source_port; int bit; std::string label; WireId target; std::vector<BelId> candidates; };
        std::vector<Item> items;
        std::unordered_set<CellInfo *> seen_drivers;
        std::unordered_map<int, std::unordered_set<int>> downhill_cache;
        auto hard_source_reaches = [&](WireId source, WireId target) {
            if (source == WireId() || target == WireId()) return false;
            auto found = downhill_cache.find(source.index);
            if (found == downhill_cache.end()) {
                std::unordered_set<int> reach{source.index};
                std::vector<WireId> queue{source};
                for (size_t head = 0; head < queue.size(); ++head)
                    for (PipId pip : ctx->getPipsDownhill(queue[head])) {
                        WireId dst = ctx->getPipDstWire(pip);
                        if (reach.insert(dst.index).second) queue.push_back(dst);
                    }
                found = downhill_cache.emplace(source.index, std::move(reach)).first;
            }
            return found->second.count(target.index) != 0;
        };
        bool addr_mode = false;
        for (auto &cell : ctx->cells)
            if (cell.second->type == ctx->id("MCU_DIN") &&
                cell.second->name.str(ctx).find("haddr") != std::string::npos)
                addr_mode = true;
        for (auto &cell : ctx->cells) {
            CellInfo *mcu = cell.second.get();
            bool response_sink = mcu->type == ctx->id("MCU_AHB_HREADYOUT") ||
                                 mcu->type == ctx->id("MCU_AHB_HRESP");
            if ((mcu->type != ctx->id("MCU_DOUT") && !response_sink) || mcu->bel == BelId())
                continue;
            NetInfo *net = mcu->getPort(ctx->id("DOUT"));
            if (net == nullptr || net->driver.cell == nullptr)
                continue;
            CellInfo *drv = net->driver.cell;
            if (drv->type != ctx->id("GENERIC_SLICE") || drv->bel != BelId() ||
                drv->cluster != ClusterId())
                continue;
            // One fabric net may intentionally fan out to several MCU_DOUT
            // lanes.  It has one physical driver and therefore needs one BEL
            // assignment; the corridor locker below builds the shared tree.
            if (!seen_drivers.insert(drv).second)
                continue;
            WireId target = ctx->getBelPinWire(mcu->bel, ctx->id("DOUT"));
            if (target == WireId())
                continue;
            std::unordered_map<int, int> reach;
            std::vector<WireId> q{target};
            reach[target.index] = 0;
            for (size_t h = 0; h < q.size(); ++h)
                for (PipId pip : ctx->getPipsUphill(q[h])) {
                    WireId src = ctx->getPipSrcWire(pip);
                    if (reach.emplace(src.index, reach.at(q[h].index) + 1).second)
                        q.push_back(src);
                }
            int bit = -1;
            McuDoutLane kind =
                    response_sink ? LANE_NONE : mcu_dout_lane(mcu->name.str(ctx), bit);
            const char *bus = kind == LANE_SHADDR    ? "slave_ahb_haddr"
                              : kind == LANE_SHWDATA ? "slave_ahb_hwdata"
                                                     : "hrdata";
            std::string label =
                    response_sink ? (mcu->type == ctx->id("MCU_AHB_HRESP") ? std::string("hresp")
                                                                           : std::string("hreadyout"))
                                  : std::string(bus) + "[" + std::to_string(bit) + "]";
            int exy = response_sink ? 12 : mcu_dout_exit_row(kind, bit);
            auto requested_bel = drv->attrs.find(ctx->id("BEL"));
            std::vector<std::pair<int, BelId>> scored;
            for (BelId b : ctx->getBels()) {
                if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE") || !ctx->checkBelAvail(b))
                    continue;
                if (requested_bel != drv->attrs.end() &&
                    ctx->getBelName(b).str(ctx) != requested_bel->second.as_string())
                    continue;
                WireId ow = ctx->getBelPinWire(b, net->driver.port);
                auto ri = reach.find(ow.index);
                if (ow == WireId() || ri == reach.end())
                    continue;
                // A registered AHB readback cell is both an exit driver and a
                // direct consumer of one fixed HWDATA source.  Candidate BELs
                // must satisfy both halves.  Output-only matching previously
                // chose an excellent HRDATA exit whose D pin was unreachable
                // from the assigned hard input, so router2 failed on a tiny
                // four-register slave despite each side being routable alone.
                bool hard_inputs_ok = true;
                for (auto &port : drv->ports) {
                    if (port.second.type != PORT_IN || port.second.net == nullptr ||
                        port.second.net->driver.cell == nullptr ||
                        port.second.net->driver.cell->type != ctx->id("MCU_DIN"))
                        continue;
                    CellInfo *din = port.second.net->driver.cell;
                    if (din->bel == BelId()) { hard_inputs_ok = false; break; }
                    WireId iw = ctx->getBelPinWire(din->bel, port.second.net->driver.port);
                    WireId tw = ctx->getBelPinWire(b, port.first);
                    if (!hard_source_reaches(iw, tw)) { hard_inputs_ok = false; break; }
                }
                if (!hard_inputs_ok)
                    continue;
                Loc loc = ctx->getBelLocation(b);
                // Prefer the electrically shortest known path first.  Pure
                // geometry packs every lane into the boundary row even when
                // that output reaches its endpoint only through a long shared
                // corridor, which makes the simultaneous 32-bit bus
                // impossible despite every lane being individually reachable.
                int score = ri->second * 1000 +
                            (std::abs(loc.x - 14) + std::abs(loc.y - exy)) * 100 + loc.z;
                static const std::unordered_map<int, std::string> hw_buffer_bel = {
                    {1, "X14Y10_SLICE3"}, {5, "X14Y12_SLICE15"},
                    {6, "X14Y10_SLICE1"}, {19, "X14Y9_SLICE8"},
                    {21, "X14Y9_SLICE7"},
                };
                static const std::unordered_map<int, std::string> addr_buffer_bel = {
                    // Native x9 BRAM control uses these two identity buffers
                    // on hrdata[0:1] before the External-AHB sink boundary.
                    {0, "X14Y4_SLICE5"}, {1, "X14Y8_SLICE8"},
                    {9, "X14Y11_SLICE4"}, {15, "X14Y11_SLICE13"},
                };
                const auto &preferred = addr_mode ? addr_buffer_bel : hw_buffer_bel;
                auto vb = preferred.find(bit);
                if (vb != preferred.end() && ctx->getBelName(b).str(ctx) == vb->second)
                    score -= 1000000;
                scored.push_back({score, b});
            }
            std::stable_sort(scored.begin(), scored.end(),
                             [](auto &a, auto &b) { return a.first < b.first; });
            Item item{drv, net->driver.port, bit, label, target, {}};
            for (auto &candidate : scored) item.candidates.push_back(candidate.second);
            if (item.candidates.empty())
                log_warning("agrv2k: no strict-graph slice output reaches %s for '%s'\n",
                            label.c_str(), drv->name.c_str(ctx));
            else
                items.push_back(std::move(item));
        }

        std::vector<int> order(items.size()), chosen(items.size(), -1);
        for (size_t i = 0; i < items.size(); ++i) order[i] = int(i);
        std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
            return items[a].candidates.size() < items[b].candidates.size();
        });
        // Two adjacent slice BELs can expose the same physical OMUX wire.
        // Match on that source wire, not on the BEL name, or a nominally
        // unique 32-BEL assignment can still double-book half its exits.
        // Candidates on an item's exclusion list (corridor-infeasible from a
        // previous trial round) are skipped during re-matching.
        std::vector<std::unordered_set<int>> excluded(items.size());
        std::unordered_map<std::string, int> owner;
        auto source_wire_of = [&](int ii, BelId b) {
            return ctx->getBelPinWire(b, items[ii].source_port);
        };
        std::function<bool(int, std::unordered_set<std::string> &)> match =
            [&](int ii, std::unordered_set<std::string> &seen) {
                for (size_t ci = 0; ci < items[ii].candidates.size(); ++ci) {
                    if (excluded[ii].count(int(ci))) continue;
                    BelId b = items[ii].candidates[ci];
                    WireId source = source_wire_of(ii, b);
                    std::string wn = ctx->getWireName(source).str(ctx);
                    if (!seen.insert(wn).second) continue;
                    auto it = owner.find(wn);
                    if (it == owner.end() || match(it->second, seen)) {
                        owner[wn] = ii; chosen[ii] = int(ci); return true;
                    }
                }
                return false;
            };
        auto run_matching = [&]() {
            owner.clear();
            std::fill(chosen.begin(), chosen.end(), -1);
            for (int ii : order) {
                std::unordered_set<std::string> seen;
                if (!match(ii, seen))
                    log_error("agrv2k: no simultaneous strict-graph BEL assignment for %s\n",
                              items[ii].label.c_str());
            }
        };
        // CORRIDOR TRIAL.  A source-wire-unique assignment can still be
        // corridor-infeasible: several chosen BELs may reach their sinks only
        // through one shared boundary approach (observed as a rip-up livelock
        // among hrdata lanes).  Trial-route the whole assignment against local
        // wire claims; when a lane livelocks or has no corridor, exclude that
        // candidate and re-match.  Wires already bound in ctx stay hard
        // obstacles.  Nothing is bound here — the post-placement corridor
        // locker performs the real binding on the surviving assignment.
        auto corridor_trial = [&](int &loser) {
            std::unordered_map<int, int> claim; // wire index -> item
            std::vector<std::vector<int>> claimed(items.size());
            std::vector<int> fails(items.size(), 0);
            std::deque<int> pending;
            for (int ii : order) pending.push_back(ii);
            int budget = 600;
            auto trial_bfs = [&](int ii, bool permissive, std::vector<int> &path_wires,
                                 std::unordered_set<int> &blockers) {
                path_wires.clear();
                blockers.clear();
                WireId source = source_wire_of(ii, items[ii].candidates[chosen[ii]]);
                WireId target = items[ii].target;
                if (source == WireId() || target == WireId()) return false;
                std::vector<WireId> queue{source};
                std::unordered_map<int, PipId> previous;
                previous[source.index] = PipId();
                for (size_t head = 0; head < queue.size() && !previous.count(target.index); ++head) {
                    for (PipId pip : ctx->getPipsDownhill(queue[head])) {
                        WireId dst = ctx->getPipDstWire(pip);
                        if (ctx->getBoundWireNet(dst) != nullptr)
                            continue; // pre-existing hard binding (BRAM/IO buses)
                        auto cl = claim.find(dst.index);
                        if (cl != claim.end() && cl->second != ii && !permissive)
                            continue;
                        if (previous.emplace(dst.index, pip).second)
                            queue.push_back(dst);
                    }
                }
                if (!previous.count(target.index))
                    return false;
                for (WireId cursor = target; cursor != source;) {
                    PipId pip = previous.at(cursor.index);
                    path_wires.push_back(cursor.index);
                    auto cl = claim.find(cursor.index);
                    if (cl != claim.end() && cl->second != ii)
                        blockers.insert(cl->second);
                    cursor = ctx->getPipSrcWire(pip);
                }
                return true;
            };
            while (!pending.empty()) {
                int ii = pending.front();
                pending.pop_front();
                std::vector<int> path;
                std::unordered_set<int> blockers;
                if (trial_bfs(ii, false, path, blockers)) {
                    for (int w : path) claim[w] = ii;
                    claimed[ii] = path;
                    continue;
                }
                // Escalate to candidate exclusion only on TRUE infeasibility
                // (no path even through negotiable claims) or after sustained
                // thrash.  A sink-side funnel (one approach shared as transit
                // by other corridors) resolves through rip-up negotiation, not
                // by moving this item's driver.
                if (!trial_bfs(ii, true, path, blockers) || blockers.empty() || ++fails[ii] >= 12) {
                    loser = ii;
                    return false;
                }
                budget -= int(blockers.size());
                if (budget < 0) {
                    loser = ii;
                    return false;
                }
                for (int bi : blockers) {
                    for (int w : claimed[bi]) claim.erase(w);
                    claimed[bi].clear();
                    pending.push_back(bi);
                }
                pending.push_front(ii);
            }
            return true;
        };
        // The trial is a warm start, not a gate: full corridor-disjointness
        // before placement is stronger than required, because the post-
        // placement corridor locker still negotiates with rip-up and swap
        // re-anchoring.  On non-convergence, keep the best assignment.
        if (!items.empty()) {
            run_matching();
            for (int attempt = 0; std::getenv("AGRV2K_NO_EXIT_TRIAL") == nullptr && attempt < 16;
                 ++attempt) {
                int loser = -1;
                if (corridor_trial(loser))
                    break;
                if (attempt == 15) {
                    log_info("agrv2k: exit-corridor trial did not fully converge (last conflict "
                             "at %s); deferring to lock-stage negotiation\n",
                             items[loser].label.c_str());
                    break;
                }
                log_info("agrv2k: %s corridor-infeasible from %s; re-anchoring\n",
                         items[loser].label.c_str(),
                         ctx->getBelName(items[loser].candidates[chosen[loser]]).str(ctx).c_str());
                excluded[loser].insert(chosen[loser]);
                run_matching();
            }
        }
        int bound = 0;
        for (size_t i = 0; i < items.size(); ++i) {
            if (chosen[i] < 0) continue;
            BelId b = items[i].candidates.at(chosen[i]);
            items[i].drv->attrs[ctx->id("AGRV2K_MCU_PINPACKED")] = Property(1);
            ctx->bindBel(b, items[i].drv, STRENGTH_LOCKED);
            // A source-level BEL constraint helped select this exact corridor.
            // The cell is now already locked there; leaving the attribute for
            // nextpnr's generic constraint pass attempts to bind it a second
            // time and reports a self-conflict.
            items[i].drv->attrs.erase(ctx->id("BEL"));
            ++bound;
            log_info("agrv2k: MCU-pin packed %s driver '%s' -> %s\n", items[i].label.c_str(),
                     items[i].drv->name.c_str(ctx), ctx->getBelName(b).str(ctx).c_str());
        }
        if (bound)
            log_info("agrv2k: MCU-pin packed %d dynamic MCU exit driver(s)\n", bound);
    }

    // A LUT that consumes TWO different MCU entries may be physically
    // unanchorable when each entry's conducting cone reaches only its own
    // identity-buffer site.  Insert one identity buffer per lane only when no
    // exact slice can carry all direct pins together.  Coherent multi-input
    // corridors recovered later must remain direct; eagerly buffering them
    // would discard the very topology the vendor route establishes.
    void pack_entry_buffers()
    {
        std::vector<std::unique_ptr<CellInfo>> new_cells;
        std::vector<std::unique_ptr<NetInfo>> new_nets;
        int n_buf = 0;
        std::vector<std::pair<CellInfo *, std::vector<IdString>>> victims;
        std::unordered_map<int, std::unordered_set<int>> reach_cache;
        auto reach = [&](WireId root) -> const std::unordered_set<int> & {
            auto found = reach_cache.find(root.index);
            if (found == reach_cache.end()) {
                std::unordered_set<int> seen;
                std::vector<WireId> q;
                if (root != WireId()) { seen.insert(root.index); q.push_back(root); }
                for (size_t head = 0; head < q.size(); ++head)
                    for (PipId pip : ctx->getPipsDownhill(q[head])) {
                        WireId dst = ctx->getPipDstWire(pip);
                        if (seen.insert(dst.index).second) q.push_back(dst);
                    }
                found = reach_cache.emplace(root.index, std::move(seen)).first;
            }
            return found->second;
        };
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            if (ci->type != ctx->id("GENERIC_SLICE") || ci->bel != BelId() ||
                ci->cluster != ClusterId())
                continue;
            std::vector<IdString> mcu_pins;
            for (auto &port : ci->ports)
                if (port.second.type == PORT_IN && port.second.net != nullptr &&
                    port.second.net->driver.cell != nullptr &&
                    port.second.net->driver.cell->type == ctx->id("MCU_DIN"))
                    mcu_pins.push_back(port.first);
            if (mcu_pins.size() < 2)
                continue;
            bool direct_site = false;
            for (BelId bel : ctx->getBels()) {
                if (ctx->getBelType(bel) != ctx->id("GENERIC_SLICE") ||
                    !ctx->checkBelAvail(bel))
                    continue;
                bool all = true;
                for (IdString pin : mcu_pins) {
                    NetInfo *net = ci->getPort(pin);
                    WireId root = ctx->getBelPinWire(net->driver.cell->bel,
                                                     net->driver.port);
                    WireId target = ctx->getBelPinWire(bel, pin);
                    if (target == WireId() || !reach(root).count(target.index)) {
                        all = false;
                        break;
                    }
                }
                if (all) { direct_site = true; break; }
            }
            if (!direct_site)
                victims.push_back({ci, std::move(mcu_pins)});
        }
        // ONE buffer per entry net (the vendor has one identity buffer per
        // lane); every victim pin of that lane reconnects to the shared
        // buffered net.  Single-entry consumers keep their direct connection.
        std::unordered_map<NetInfo *, NetInfo *> buffered;
        for (auto &victim : victims) {
            CellInfo *ci = victim.first;
            for (IdString pin : victim.second) {
                NetInfo *entry_net = ci->getPort(pin);
                NetInfo *bnet;
                auto existing = buffered.find(entry_net);
                if (existing != buffered.end()) {
                    bnet = existing->second;
                } else {
                    // The lane's conducting cone reaches only the IMUX index
                    // the vendor identity site used; pick the buffer's input
                    // pin from what the cone actually offers.
                    CellInfo *din = entry_net->driver.cell;
                    WireId root = ctx->getBelPinWire(din->bel, entry_net->driver.port);
                    bool pin_seen[4] = {false, false, false, false};
                    std::unordered_set<int> seen;
                    if (root != WireId()) {
                        seen.insert(root.index);
                        std::vector<WireId> q{root};
                        for (size_t h = 0; h < q.size(); ++h)
                            for (PipId pip : ctx->getPipsDownhill(q[h])) {
                                WireId dst = ctx->getPipDstWire(pip);
                                if (!seen.insert(dst.index).second)
                                    continue;
                                q.push_back(dst);
                            }
                        // Do not infer a LUT pin merely from an IMUX-number
                        // suffix.  The cone can also enter BRAM terminals
                        // (HADDR[4], for example, reaches BramTILE IMUX07),
                        // which previously selected I[3] even though no logic
                        // slice exposed a reachable I[3].  Query actual slice
                        // BEL pins so the inserted identity buffer is
                        // guaranteed to have at least one legal placement.
                        for (BelId b : ctx->getBels()) {
                            if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE") ||
                                !ctx->checkBelAvail(b))
                                continue;
                            for (int cand = 0; cand < 4; ++cand) {
                                WireId pw = ctx->getBelPinWire(
                                    b, ctx->id("I[" + std::to_string(cand) + "]"));
                                if (pw != WireId() && seen.count(pw.index))
                                    pin_seen[cand] = true;
                            }
                        }
                    }
                    int k = -1;
                    for (int cand : {3, 2, 1, 0})
                        if (pin_seen[cand]) { k = cand; break; }
                    if (k < 0)
                        log_error("agrv2k: entry %s reaches no LUT input pin; cannot buffer it\n",
                                  din->name.c_str(ctx));
                    static const uint32_t identity_init[4] = {0xaaaa, 0xcccc, 0xf0f0, 0xff00};
                    std::string bname = din->name.str(ctx) + "_MCUBUF";
                    auto buf = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), bname);
                    buf->params[ctx->id("INIT")] = Property(identity_init[k], 1 << ctx->args.K);
                    auto bnet_uptr = std::make_unique<NetInfo>(ctx->id(bname + "_NET"));
                    bnet = bnet_uptr.get();
                    buf->connectPort(ctx->id("I[" + std::to_string(k) + "]"), entry_net);
                    buf->connectPort(ctx->id("F"), bnet);
                    new_nets.push_back(std::move(bnet_uptr));
                    new_cells.push_back(std::move(buf));
                    buffered[entry_net] = bnet;
                    ++n_buf;
                }
                ci->disconnectPort(pin);
                ci->connectPort(pin, bnet);
            }
        }
        for (auto &nc : new_cells)
            ctx->cells[nc->name] = std::move(nc);
        for (auto &nn : new_nets)
            ctx->nets[nn->name] = std::move(nn);
        if (n_buf)
            log_info("agrv2k: buffered %d multi-entry MCU input pin(s) through identity LUT(s)\n",
                     n_buf);
    }

    // Anchor every unplaced consumer of a direct MCU_DIN input BEFORE
    // condplace fills the boundary region.  Each entry has one fixed physical
    // root with a bounded conducting region; a consumer left to condplace
    // regularly lands where its entry cannot reach it (or the reachable
    // slices are already full).  A candidate must carry EVERY hard-input pin
    // of the cell on its exact pin wires.  Fewest-candidate cells bind first.
    void pack_entry_anchor()
    {
        if (std::getenv("AGRV2K_NO_ENTRY_ANCHOR") != nullptr)
            return; // crash/behaviour bisection switch
        std::unordered_map<int, std::unordered_set<int>> reach_cache;
        auto entry_reach = [&](WireId source) -> const std::unordered_set<int> & {
            auto found = reach_cache.find(source.index);
            if (found == reach_cache.end()) {
                std::unordered_set<int> seen{source.index};
                std::vector<WireId> q{source};
                for (size_t h = 0; h < q.size(); ++h)
                    for (PipId pip : ctx->getPipsDownhill(q[h])) {
                        WireId dst = ctx->getPipDstWire(pip);
                        if (seen.insert(dst.index).second)
                            q.push_back(dst);
                    }
                found = reach_cache.emplace(source.index, std::move(seen)).first;
            }
            return found->second;
        };
        struct Entry { CellInfo *cell; std::vector<std::pair<WireId, IdString>> pins;
                       std::vector<std::string> roots; std::vector<BelId> candidates;
                       std::string forced_bel; int preferred_row; };
        std::vector<Entry> entries;
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            if (ci->type != ctx->id("GENERIC_SLICE") || ci->bel != BelId() ||
                ci->cluster != ClusterId())
                continue;
            // Exit drivers (feeding an MCU_DOUT / response sink) are anchored
            // by pack_exit_anchor, whose candidate scoring already checks the
            // hard-input side; anchoring them here by entry constraints alone
            // would ignore exit-corridor feasibility.
            bool drives_exit = false;
            for (auto &port : ci->ports) {
                if (port.second.type != PORT_OUT || port.second.net == nullptr)
                    continue;
                for (auto &user : port.second.net->users)
                    if (user.cell != nullptr &&
                        (user.cell->type == ctx->id("MCU_DOUT") ||
                         user.cell->type == ctx->id("MCU_AHB_HREADYOUT") ||
                         user.cell->type == ctx->id("MCU_AHB_HRESP"))) {
                        drives_exit = true;
                        break;
                    }
                if (drives_exit)
                    break;
            }
            if (drives_exit)
                continue;
            std::vector<std::pair<WireId, IdString>> pins;
            std::vector<std::string> roots;
            bool placed_sources = true;
            for (auto &port : ci->ports) {
                if (port.second.type != PORT_IN || port.second.net == nullptr ||
                    port.second.net->driver.cell == nullptr ||
                    port.second.net->driver.cell->type != ctx->id("MCU_DIN"))
                    continue;
                CellInfo *din = port.second.net->driver.cell;
                if (din->bel == BelId()) { placed_sources = false; break; }
                pins.push_back({ctx->getBelPinWire(din->bel, port.second.net->driver.port),
                                port.first});
                roots.push_back(din->name.str(ctx) + ":" + port.first.str(ctx));
            }
            if (pins.empty() || !placed_sources)
                continue;
            std::string requested_bel;
            auto requested = ci->attrs.find(ctx->id("BEL"));
            if (requested != ci->attrs.end())
                requested_bel = requested->second.as_string();
            entries.push_back({ci, std::move(pins), std::move(roots), {},
                               requested_bel, 9});
        }
        // Exact silicon-qualified hard-input consumer footprints may require a
        // logical LUT input to move onto the physical pin reached by that
        // lane.  Apply only the declared single-input rules; swap the INIT
        // axes with the nets, and lock the resulting consumer to the recorded
        // site.  Undeclared lanes and multi-MCU-input cells remain unchanged.
        struct ConsumerRule { std::string token, bel, evidence; int pin; };
        std::vector<ConsumerRule> consumer_rules;
        {
            std::ifstream probe(path("mcu_logic_consumer_footprints.csv"));
            if (probe) {
                probe.close();
                Csv rules(path("mcu_logic_consumer_footprints.csv"));
                rules.next(); // header
                while (rules.next())
                    consumer_rules.push_back({rules.at(0), rules.at(1), rules.at(3),
                                              to_int(rules.at(2), -1)});
            }
        }
        // Fail closed on two rows claiming the identical physical (bel, pin) --
        // but only once this build actually APPLIES both to a live entry.  The
        // table is shared by every uarch build; the vast majority never
        // instantiate the handful of cells any given row's token matches, and a
        // duplicate elsewhere in the table is not this build's problem.  A live
        // double-claim, on the other hand, is not a resource-contention edge
        // case the packer can negotiate around (pack_entry_anchor's soft-
        // preference fallback already makes shared-BEL contention survivable
        // when the pins differ) -- it is two silicon captures asserting the
        // same physical (bel, pin) carries two different named signals in the
        // very design being built, which is a table error.  Surface it here,
        // right where the row is applied, instead of as an opaque "lost every
        // candidate slice to earlier anchors" packing failure much later.
        // Pass 1: find, for every eligible single-pin entry, the (at most one)
        // consumer-footprint rule that matches it -- WITHOUT mutating
        // anything yet.  Mutating inline (as a single pass used to) means a
        // later collision is discovered only after the earlier of the two
        // colliding entries has already had its INIT permuted and its
        // forced_bel locked in; there would be no clean way to undo just
        // that one entry's half of the damage.  Collecting matches first
        // lets us decide, per physical (bel, pin) site, whether every rule
        // that lands there agrees BEFORE any cell is touched.
        struct Match { size_t entry_idx; ConsumerRule rule; };
        std::vector<Match> matches;
        for (size_t ei = 0; ei < entries.size(); ++ei) {
            Entry &e = entries[ei];
            if (e.pins.size() != 1)
                continue;
            NetInfo *entry_net = e.cell->getPort(e.pins[0].second);
            int entry_users = 0;
            if (entry_net != nullptr)
                for (auto &user : entry_net->users) { (void) user; ++entry_users; }
            if (entry_net == nullptr || entry_users != 1)
                continue; // fanout needs one separately qualified identity-buffer footprint
            for (const auto &rule : consumer_rules) {
                if (e.roots[0].find(rule.token) == std::string::npos)
                    continue;
                if (rule.pin < 0 || rule.pin >= 4)
                    log_error("agrv2k: invalid qualified MCU consumer pin %d for '%s'\n",
                              rule.pin, rule.token.c_str());
                matches.push_back({ei, rule});
                break;
            }
        }
        // Pass 2: group matches by the physical (bel, pin) site they claim.
        // A site claimed by more than one DISTINCT token is a live
        // contradiction between two independently-recovered silicon
        // captures -- not a resource-contention case the packer can
        // negotiate around (that case, same-signal fan-in to a shared BEL on
        // different pins, is already handled by the soft-preference
        // fallback below).  Two rows naming two different signals at the
        // exact same (bel, pin) means at least one capture is simply wrong,
        // and we have no way from here to tell which.  Trusting neither is
        // the honest default: drop BOTH preferences and let the entries fall
        // back through to the general reach-based candidate search a few
        // lines down, same as any entry with no footprint match at all.
        // AGRV2K_STRICT_FOOTPRINT_COLLISIONS restores the old hard-stop for
        // anyone who wants the build to refuse to guess.
        bool strict_collisions = std::getenv("AGRV2K_STRICT_FOOTPRINT_COLLISIONS") != nullptr;
        std::unordered_map<std::string, std::vector<size_t>> site_matches; // "bel#pin" -> indices into matches
        for (size_t mi = 0; mi < matches.size(); ++mi)
            site_matches[matches[mi].rule.bel + "#" + std::to_string(matches[mi].rule.pin)]
                .push_back(mi);
        std::unordered_set<size_t> dropped; // match indices whose rule must NOT be applied
        for (auto &kv : site_matches) {
            std::vector<size_t> &idxs = kv.second;
            std::vector<size_t> distinct; // one representative match index per distinct token
            for (size_t idx : idxs) {
                bool seen = false;
                for (size_t d : distinct)
                    if (matches[d].rule.token == matches[idx].rule.token) { seen = true; break; }
                if (!seen)
                    distinct.push_back(idx);
            }
            if (distinct.size() < 2)
                continue; // same site, same signal (or only one claimant) -- not a collision
            std::string listing;
            for (size_t d : distinct) {
                if (!listing.empty())
                    listing += " and ";
                listing += "'" + matches[d].rule.token + "' (" + matches[d].rule.evidence + ")";
            }
            const std::string &site_bel = matches[idxs[0]].rule.bel;
            int site_pin = matches[idxs[0]].rule.pin;
            if (strict_collisions)
                log_error("agrv2k: mcu_logic_consumer_footprints.csv claims (%s, pin %d) twice: "
                          "%s -- AGRV2K_STRICT_FOOTPRINT_COLLISIONS is set, refusing to guess\n",
                          site_bel.c_str(), site_pin, listing.c_str());
            log_warning("agrv2k: mcu_logic_consumer_footprints.csv claims (%s, pin %d) twice: %s "
                        "-- two silicon captures contradict each other at this exact site, so "
                        "neither is trustworthy; DROPPING BOTH preferences and falling back to "
                        "the general reach-based candidate search for these signals\n",
                        site_bel.c_str(), site_pin, listing.c_str());
            for (size_t idx : idxs)
                dropped.insert(idx);
        }
        // Pass 3: apply the surviving (non-colliding) matches exactly as the
        // single-pass version used to -- permute the logical pin onto the
        // rule's physical pin, then lock the entry's forced_bel.
        for (size_t mi = 0; mi < matches.size(); ++mi) {
            if (dropped.count(mi))
                continue;
            Entry &e = entries[matches[mi].entry_idx];
            const ConsumerRule &rule = matches[mi].rule;
            IdString old_port = e.pins[0].second;
            IdString new_port = ctx->id("I[" + std::to_string(rule.pin) + "]");
            if (old_port != new_port) {
                std::string old_name = old_port.str(ctx);
                int old_pin = (old_name.size() == 4 && old_name[0] == 'I' &&
                               old_name[1] == '[' && old_name[3] == ']') ?
                                  old_name[2] - '0' : -1;
                auto init_it = e.cell->params.find(ctx->id("INIT"));
                if (old_pin < 0 || old_pin >= 4 || init_it == e.cell->params.end())
                    log_error("agrv2k: cannot permute qualified MCU consumer '%s'.%s\n",
                              e.cell->name.c_str(ctx), old_port.c_str(ctx));
                NetInfo *old_net = e.cell->getPort(old_port);
                NetInfo *new_net = e.cell->getPort(new_port);
                uint64_t old_init = uint64_t(init_it->second.as_int64());
                uint64_t new_init = 0;
                for (int index = 0; index < 16; ++index) {
                    int old_index = index;
                    int abit = (index >> old_pin) & 1;
                    int bbit = (index >> rule.pin) & 1;
                    if (abit != bbit)
                        old_index ^= (1 << old_pin) | (1 << rule.pin);
                    if ((old_init >> old_index) & 1)
                        new_init |= uint64_t(1) << index;
                }
                e.cell->disconnectPort(old_port);
                e.cell->disconnectPort(new_port);
                if (new_net != nullptr)
                    e.cell->connectPort(old_port, new_net);
                if (old_net != nullptr)
                    e.cell->connectPort(new_port, old_net);
                e.cell->params[ctx->id("INIT")] = Property(new_init, 16);
                e.pins[0].second = new_port;
                log_info("agrv2k: qualified MCU consumer permuted '%s'.%s -> %s\n",
                         e.cell->name.c_str(ctx), old_port.c_str(ctx), new_port.c_str(ctx));
            }
            if (!e.forced_bel.empty() && e.forced_bel != rule.bel)
                log_error("agrv2k: explicit BEL '%s' conflicts with MCU consumer footprint '%s'\n",
                          e.forced_bel.c_str(), rule.bel.c_str());
            e.forced_bel = rule.bel;
        }
        // The wide-MCU vendor atlas exposes one entry column with finite source
        // pools.  HWDATA occupies X13Y10/X13Y9, while address/control occupies
        // a fixed twenty-root row at X13Y12 and spills HADDR into X13Y11/Y10.
        // The physical MCU_DIN BEL mapping has already fixed every logical lane
        // to one of those roots.  Validate that assignment before spending any
        // boundary resource, and retain its row as placement metadata for the
        // downstream consumer cone.
        std::map<int, std::unordered_set<int>> hwdata_roots;
        std::map<int, std::unordered_set<int>> address_control_roots;
        for (auto &e : entries) {
            int row_sum = 0, row_count = 0;
            for (size_t pi = 0; pi < e.pins.size(); ++pi) {
                std::string tile, res;
                int idx = 0, x = -1, y = -1;
                if (parse_wire(ctx->getWireName(e.pins[pi].first).str(ctx), tile, res, idx) &&
                    std::sscanf(tile.c_str(), "X%dY%d", &x, &y) == 2) {
                    row_sum += y;
                    ++row_count;
                    if (e.roots[pi].find("hwdata") != std::string::npos) {
                        if (x != 13 || (y != 9 && y != 10))
                            log_error("agrv2k: HWDATA entry root '%s' is outside the atlas source pools\n",
                                      ctx->getWireName(e.pins[pi].first).str(ctx).c_str());
                        hwdata_roots[y].insert(e.pins[pi].first.index);
                    }
                    const std::string &root_name = e.roots[pi];
                    int habit = parse_after(root_name, "haddr");
                    int expected_row = -1, expected_buf = -1;
                    if (habit >= 0 && habit <= 9) {
                        expected_row = 12;
                        expected_buf = habit + 10;
                    } else if (habit >= 10 && habit <= 29) {
                        expected_row = 11;
                        expected_buf = habit - 10;
                    } else if (habit >= 30 && habit <= 31) {
                        expected_row = 10;
                        expected_buf = habit - 30;
                    } else if (root_name.find("hready") != std::string::npos &&
                               root_name.find("hreadyout") == std::string::npos) {
                        expected_row = 12;
                        expected_buf = 0;
                    } else {
                        int control_bit = parse_after(root_name, "htrans");
                        if (control_bit >= 0 && control_bit <= 1) {
                            expected_row = 12;
                            expected_buf = control_bit + 1;
                        } else {
                            control_bit = parse_after(root_name, "hsize");
                            if (control_bit >= 0 && control_bit <= 2) {
                                expected_row = 12;
                                expected_buf = control_bit + 3;
                            } else {
                                control_bit = parse_after(root_name, "hburst");
                                if (control_bit >= 0 && control_bit <= 2) {
                                    expected_row = 12;
                                    expected_buf = control_bit + 6;
                                } else if (root_name.find("hwrite") != std::string::npos) {
                                    expected_row = 12;
                                    expected_buf = 9;
                                }
                            }
                        }
                    }
                    if (expected_row >= 0) {
                        if (x != 13 || y != expected_row || res != "BufMUX" || idx != expected_buf)
                            log_error("agrv2k: address/control entry root '%s' violates its fixed "
                                      "X13Y%d_BufMUX%02d assignment\n",
                                      ctx->getWireName(e.pins[pi].first).str(ctx).c_str(),
                                      expected_row, expected_buf);
                        address_control_roots[y].insert(e.pins[pi].first.index);
                    }
                }
            }
            if (row_count != 0)
                e.preferred_row = (row_sum + row_count / 2) / row_count;
        }
        if (hwdata_roots[10].size() > 18 || hwdata_roots[9].size() > 14)
            log_error("agrv2k: wide MCU source allocation exceeds atlas capacity "
                      "(X13Y10 %d/18, X13Y9 %d/14)\n",
                      int(hwdata_roots[10].size()), int(hwdata_roots[9].size()));
        if (!hwdata_roots.empty())
            log_info("agrv2k: allocated HWDATA sources before consumers "
                     "(X13Y10 %d/18, X13Y9 %d/14)\n",
                     int(hwdata_roots[10].size()), int(hwdata_roots[9].size()));
        if (address_control_roots[12].size() > 20 ||
            address_control_roots[11].size() > 20 ||
            address_control_roots[10].size() > 2)
            log_error("agrv2k: fixed address/control root allocation exceeds atlas capacity "
                      "(X13Y12 %d/20, X13Y11 %d/20, X13Y10 %d/2)\n",
                      int(address_control_roots[12].size()),
                      int(address_control_roots[11].size()),
                      int(address_control_roots[10].size()));
        if (!address_control_roots.empty())
            log_info("agrv2k: allocated each fixed address/control root before consumers "
                     "(X13Y12 %d/20, X13Y11 %d/20, X13Y10 %d/2)\n",
                     int(address_control_roots[12].size()),
                     int(address_control_roots[11].size()),
                     int(address_control_roots[10].size()));

        for (auto &e : entries) {
            // forced_bel (from the qualified MCU consumer footprint table) is a
            // SOFT preference, not a hard filter: it is folded into the front of
            // the candidate list below, once the full reach-based pool is built.
            // A hard filter here collapses every entry sharing a forced BEL onto
            // a single-candidate pool, which is a Hall violator the instant two
            // entries share one BEL (see F19/F27) -- the fallback pool is what
            // makes a shared-BEL collision survivable instead of fatal.
            for (BelId b : ctx->getBels()) {
                if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE") || !ctx->checkBelAvail(b))
                    continue;
                bool ok = true;
                for (auto &pin : e.pins) {
                    WireId pw = ctx->getBelPinWire(b, pin.second);
                    if (pw == WireId() || !entry_reach(pin.first).count(pw.index)) {
                        ok = false;
                        break;
                    }
                }
                if (ok)
                    e.candidates.push_back(b);
            }
            if (e.candidates.empty()) {
                std::string what;
                for (auto &r : e.roots) what += (what.empty() ? "" : ", ") + r;
                for (BelId b : ctx->getBels()) {
                    if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE") || ctx->checkBelAvail(b))
                        continue;
                    bool reachable = true;
                    for (auto &pin : e.pins) {
                        WireId pw = ctx->getBelPinWire(b, pin.second);
                        if (pw == WireId() || !entry_reach(pin.first).count(pw.index)) {
                            reachable = false;
                            break;
                        }
                    }
                    if (reachable) {
                        CellInfo *occupant = ctx->getBoundBelCell(b);
                        log_info("agrv2k:   reachable entry BEL %s is occupied by '%s'\n",
                                 ctx->getBelName(b).str(ctx).c_str(),
                                 occupant == nullptr ? "?" : occupant->name.c_str(ctx));
                    }
                }
                for (auto &pin : e.pins)
                    log_info("agrv2k:   entry cone from wire %s: %d wires\n",
                             ctx->getWireName(pin.first).str(ctx).c_str(),
                             int(entry_reach(pin.first).size()));
                log_error("agrv2k: no strict-graph slice carries all %d MCU input pin(s) of '%s' (%s)\n",
                          int(e.pins.size()), e.cell->name.c_str(ctx), what.c_str());
            }
            // Nearest-first: assignments start compact next to the entry root
            // and re-anchors walk outward.  Raw bel-iteration order scatters
            // consumers across the fabric and manufactures corridor
            // contention that no amount of negotiation can drain.
            std::string rt, rr;
            int ri = 0, rx = 13, ry = 9;
            if (parse_wire(ctx->getWireName(e.pins[0].first).str(ctx), rt, rr, ri))
                std::sscanf(rt.c_str(), "X%dY%d", &rx, &ry);
            std::stable_sort(e.candidates.begin(), e.candidates.end(), [&](BelId a, BelId b) {
                Loc la = ctx->getBelLocation(a), lb = ctx->getBelLocation(b);
                // Keep the direct consumers on their allocated source row;
                // spill vertically only after the row-local sites.  Within a
                // row, consume the boundary-nearest site first and walk east.
                // This is deterministic and retains every reachable BEL as a
                // fallback; it does not pin a decoded vendor route.
                int aya = std::abs(la.y - e.preferred_row);
                int ayb = std::abs(lb.y - e.preferred_row);
                int ada = std::abs(la.x - rx) + std::abs(la.y - ry);
                int adb = std::abs(lb.x - rx) + std::abs(lb.y - ry);
                return std::tie(aya, ada, la.x, la.y, la.z) <
                       std::tie(ayb, adb, lb.x, lb.y, lb.z);
            });
            // Soft preference: if the qualified forced BEL is among the
            // (unrestricted) reachable candidates, move it to the front so the
            // greedy assignment tries it first.  Everything else in the pool
            // stays as fallback, nearest-first, so a collision on the
            // preferred site degrades to the general search instead of
            // failing the build.
            if (!e.forced_bel.empty()) {
                auto it = std::find_if(e.candidates.begin(), e.candidates.end(), [&](BelId b) {
                    return ctx->getBelName(b).str(ctx) == e.forced_bel;
                });
                if (it != e.candidates.end()) {
                    BelId preferred = *it;
                    e.candidates.erase(it);
                    e.candidates.insert(e.candidates.begin(), preferred);
                }
            }
        }
        // Sort by ascending pool size so the tightest-constrained entries get
        // first pick.  An entry with a forced BEL sorts as if its pool were
        // size 1 (its true, pre-soft-preference constraint) rather than by
        // the size of its now much larger fallback-inclusive candidate list:
        // otherwise a large unconstrained entry could process first and take
        // the preferred site out from under the very entry the table meant to
        // steer there, silently defeating the preference on every collision
        // instead of only on genuine multi-way ties.
        std::stable_sort(entries.begin(), entries.end(), [](const Entry &a, const Entry &b) {
            size_t ka = a.forced_bel.empty() ? a.candidates.size() : size_t(1);
            size_t kb = b.forced_bel.empty() ? b.candidates.size() : size_t(1);
            return ka < kb;
        });
        // Assign candidates with a wire-claimed corridor trial, mirroring the
        // exit side: a greedy nearest-bel assignment packs consumers onto
        // tiles whose IMUX feeders share wires, and the resulting arc
        // contention cannot be fixed by any lock-time rip-up order.  Nothing
        // binds until the whole assignment trial-routes.
        std::vector<int> assigned(entries.size(), -1);
        std::unordered_set<int> taken_bels; // BelId hash via name index
        auto bel_key = [&](BelId b) { return b.index; };
        auto pick_next = [&](size_t ei, int after) -> int {
            for (int ci = after + 1; ci < int(entries[ei].candidates.size()); ++ci) {
                BelId b = entries[ei].candidates[ci];
                if (ctx->checkBelAvail(b) && !taken_bels.count(bel_key(b)))
                    return ci;
            }
            return -1;
        };
        for (size_t ei = 0; ei < entries.size(); ++ei) {
            assigned[ei] = pick_next(ei, -1);
            if (assigned[ei] < 0)
                log_error("agrv2k: MCU input consumer '%s' lost every candidate slice to earlier anchors\n",
                          entries[ei].cell->name.c_str(ctx));
            taken_bels.insert(bel_key(entries[ei].candidates[assigned[ei]]));
        }
        struct EArc { int entry; int pin; };
        std::vector<EArc> earcs;
        for (size_t ei = 0; ei < entries.size(); ++ei)
            for (size_t pi = 0; pi < entries[ei].pins.size(); ++pi)
                earcs.push_back({int(ei), int(pi)});
        std::unordered_map<int, int> claim; // wire -> earc index
        std::vector<std::vector<int>> claimed(earcs.size());
        std::vector<std::vector<PipId>> claimed_pips(earcs.size());
        std::vector<int> efails(earcs.size(), 0);
        std::deque<int> pend;
        for (size_t i = 0; i < earcs.size(); ++i)
            pend.push_back(int(i));
        int ebudget = 4000, reanchors = 256;
        // PathFinder-style history: wires repeatedly fought over accumulate
        // cost, steering later searches onto the longer disjoint corridors
        // that the simultaneous vendor oracle proves exist.  Plain BFS
        // re-proposes the identical shortest conflicting path forever.
        std::unordered_map<int, int> hist;
        std::vector<int> contested;
        auto earc_bfs = [&](int ai, bool permissive, std::vector<int> &path,
                            std::vector<PipId> &route,
                            std::unordered_set<int> &blockers) -> bool {
            path.clear();
            route.clear();
            blockers.clear();
            contested.clear();
            const Entry &e = entries[earcs[ai].entry];
            WireId source = e.pins[earcs[ai].pin].first;
            BelId bel = e.candidates[assigned[earcs[ai].entry]];
            WireId target = ctx->getBelPinWire(bel, e.pins[earcs[ai].pin].second);
            if (source == WireId() || target == WireId())
                return false;
            // Sharing is legal only between arcs of the SAME entry root (one
            // physical net fanning out); two pins of one cell come from
            // different nets and must stay wire-disjoint.
            auto root_of = [&](int k) {
                return entries[earcs[k].entry].pins[earcs[k].pin].first;
            };
            struct QE { int cost; WireId w; };
            struct QCmp { bool operator()(const QE &a, const QE &b) const { return a.cost > b.cost; } };
            std::priority_queue<QE, std::vector<QE>, QCmp> pq;
            std::unordered_map<int, PipId> previous;
            std::unordered_map<int, int> dist;
            pq.push({0, source});
            dist[source.index] = 0;
            previous[source.index] = PipId();
            while (!pq.empty()) {
                QE top = pq.top();
                pq.pop();
                if (top.w == target)
                    break;
                auto di = dist.find(top.w.index);
                if (di != dist.end() && top.cost > di->second)
                    continue;
                for (PipId pip : ctx->getPipsDownhill(top.w)) {
                    WireId dst = ctx->getPipDstWire(pip);
                    if (ctx->getBoundWireNet(dst) != nullptr)
                        continue;
                    auto cl = claim.find(dst.index);
                    if (cl != claim.end() && root_of(cl->second) != source && !permissive)
                        continue;
                    auto hi = hist.find(dst.index);
                    int c = top.cost + 1 + (hi == hist.end() ? 0 : hi->second);
                    auto dj = dist.find(dst.index);
                    if (dj == dist.end() || c < dj->second) {
                        dist[dst.index] = c;
                        previous[dst.index] = pip;
                        pq.push({c, dst});
                    }
                }
            }
            if (!previous.count(target.index))
                return false;
            for (WireId cursor = target; cursor != source;) {
                PipId pip = previous.at(cursor.index);
                path.push_back(cursor.index);
                route.push_back(pip);
                auto cl = claim.find(cursor.index);
                if (cl != claim.end() && root_of(cl->second) != source) {
                    blockers.insert(cl->second);
                    contested.push_back(cursor.index);
                }
                cursor = ctx->getPipSrcWire(pip);
            }
            std::reverse(route.begin(), route.end());
            return true;
        };
        while (!pend.empty()) {
            int ai = pend.front();
            pend.pop_front();
            std::vector<int> path;
            std::vector<PipId> route;
            std::unordered_set<int> blockers;
            if (earc_bfs(ai, false, path, route, blockers)) {
                for (int w : path)
                    claim[w] = ai;
                claimed[ai] = path;
                claimed_pips[ai] = route;
                continue;
            }
            bool permissive_ok = earc_bfs(ai, true, path, route, blockers);
            if (!permissive_ok || blockers.empty())
                log_error("agrv2k: no entry-anchor route at all for MCU input consumer '%s' "
                          "(permissive=%d blockers=%d)\n",
                          entries[earcs[ai].entry].cell->name.c_str(ctx), permissive_ok ? 1 : 0,
                          int(blockers.size()));
            ++efails[ai];
            // Negotiate long before moving: adjacent lanes share most of
            // their cones, and history costs need rounds to separate them.
            // Eager moves ping-pong near-identical arcs across the fabric
            // and drain the global re-anchor pool without converging.
            if (efails[ai] >= 10) {
                // Sustained contention: move this consumer to its next
                // candidate; if it has none left, move one of the BLOCKING
                // consumers instead (they usually still have alternatives).
                // Only after both options are exhausted fall back to bounded
                // rip patience.
                size_t ei = earcs[ai].entry;
                auto move_entry = [&](size_t mi) -> bool {
                    int nx = reanchors > 0 ? pick_next(mi, assigned[mi]) : -1;
                    if (nx < 0)
                        return false;
                    --reanchors;
                    taken_bels.erase(bel_key(entries[mi].candidates[assigned[mi]]));
                    assigned[mi] = nx;
                    taken_bels.insert(bel_key(entries[mi].candidates[nx]));
                    for (size_t k = 0; k < earcs.size(); ++k) {
                        if (earcs[k].entry != int(mi))
                            continue;
                        for (int w : claimed[k])
                            claim.erase(w);
                        claimed[k].clear();
                        claimed_pips[k].clear();
                        efails[k] = std::max(0, efails[k] - 4); // keep some pressure
                        pend.push_back(int(k));
                    }
                    return true;
                };
                if (move_entry(ei))
                    continue;
                bool moved_blocker = false;
                for (int bi : blockers)
                    if (move_entry(earcs[bi].entry)) {
                        moved_blocker = true;
                        break;
                    }
                if (moved_blocker) {
                    efails[ai] = std::max(0, efails[ai] - 4);
                    pend.push_front(ai);
                    continue;
                }
                if (efails[ai] >= 60) {
                    log_info("agrv2k: STUCK detail: reanchors_left=%d ebudget=%d assigned=%d/%d "
                             "root=%s\n", reanchors, ebudget, assigned[ei],
                             int(entries[ei].candidates.size()),
                             ctx->getWireName(entries[ei].pins[earcs[ai].pin].first).str(ctx).c_str());
                    for (int w : contested) {
                        auto cl = claim.find(w);
                        int owner = cl == claim.end() ? -1 : cl->second;
                        log_info("agrv2k: STUCK contested wire idx %d owner-entry '%s' root %s\n", w,
                                 owner < 0 ? "?" : entries[earcs[owner].entry].cell->name.c_str(ctx),
                                 owner < 0 ? "?" : ctx->getWireName(
                                     entries[earcs[owner].entry].pins[earcs[owner].pin].first)
                                     .str(ctx).c_str());
                    }
                    log_error("agrv2k: entry-anchor negotiation stuck at MCU input consumer '%s' "
                              "(no remaining candidates on any side, fails=%d)\n",
                              entries[ei].cell->name.c_str(ctx), efails[ai]);
                }
            }
            ebudget -= int(blockers.size());
            if (ebudget < 0)
                log_error("agrv2k: entry-anchor trial exceeded its rip-up budget at '%s'\n",
                          entries[earcs[ai].entry].cell->name.c_str(ctx));
            for (int w : contested)
                hist[w] += 4; // steer both parties away from the fought-over wires
            for (int bi : blockers) {
                for (int w : claimed[bi])
                    claim.erase(w);
                claimed[bi].clear();
                claimed_pips[bi].clear();
                pend.push_back(bi);
            }
            pend.push_front(ai);
        }
        int bound = 0;
        for (size_t ei = 0; ei < entries.size(); ++ei) {
            BelId b = entries[ei].candidates[assigned[ei]];
            CellInfo *cell = entries[ei].cell;
            // A combined registered MCU-input consumer may also carry an
            // explicit direct-D BEL request.  Treat an already-established
            // binding to the very same qualified BEL as idempotent; a
            // different binding is still an architectural conflict.
            if (cell->bel == BelId()) {
                ctx->bindBel(b, cell, STRENGTH_LOCKED);
                ++bound;
            } else if (cell->bel != b) {
                log_error("agrv2k: MCU input consumer '%s' was bound to a BEL other than its corridor-trialed assignment\n",
                          cell->name.c_str(ctx));
            }
            auto requested = cell->attrs.find(ctx->id("BEL"));
            if (requested != cell->attrs.end()) {
                if (requested->second.as_string() != ctx->getBelName(b).str(ctx))
                    log_error("agrv2k: MCU input consumer '%s' explicit BEL disagrees with its corridor-trialed assignment\n",
                              cell->name.c_str(ctx));
                cell->attrs.erase(requested);
            }
            cell->attrs[ctx->id("AGRV2K_MCU_PINPACKED")] = Property(1);
            cell->attrs[ctx->id("AGRV2K_MCU_ENTRY_ROW")] = Property(entries[ei].preferred_row);
        }
        // The simultaneous trial above is the allocator decision, not a
        // disposable feasibility probe.  Reserve its paths now, before
        // downstream cells are placed.  The old flow threw these negotiated
        // paths away and later ran a different history-free BFS; on a 32-bit
        // entry that second search repeatedly chose the same contested
        // shortest paths and stranded a late lane despite the proven joint
        // assignment.  Shared prefixes of one fanout net are bound once.
        int locked = 0;
        for (size_t ai = 0; ai < earcs.size(); ++ai) {
            Entry &e = entries[earcs[ai].entry];
            NetInfo *net = e.cell->getPort(e.pins[earcs[ai].pin].second);
            if (net == nullptr)
                log_error("agrv2k: allocated MCU entry pin on '%s' lost its net\n",
                          e.cell->name.c_str(ctx));
            WireId source = e.pins[earcs[ai].pin].first;
            NetInfo *source_owner = ctx->getBoundWireNet(source);
            if (source_owner == nullptr)
                ctx->bindWire(source, net, STRENGTH_LOCKED);
            else if (source_owner != net)
                log_error("agrv2k: allocated MCU entry source for '%s' is already owned by '%s'\n",
                          e.cell->name.c_str(ctx), source_owner->name.c_str(ctx));
            for (PipId pip : claimed_pips[ai]) {
                WireId dst = ctx->getPipDstWire(pip);
                NetInfo *owner = ctx->getBoundWireNet(dst);
                if (owner == net)
                    continue;
                if (owner != nullptr || !ctx->checkPipAvailForNet(pip, net))
                    log_error("agrv2k: allocated MCU entry route for '%s' changed before reservation\n",
                              e.cell->name.c_str(ctx));
                ctx->bindPip(pip, net, STRENGTH_LOCKED);
                ++locked;
            }
        }
        if (bound)
            log_info("agrv2k: entry-anchored %d MCU input consumer(s) and reserved %d pip(s) "
                     "from the corridor-trialed assignment\n", bound, locked);
    }

    // Reserve dense same-tile arcs only after the MCU entry/exit negotiators
    // have completed their bounded rip-up.  An earlier version ran this from
    // pack_condplace; a later corridor rip could then unbind a shared wire
    // while leaving the local pip bound, which nextpnr correctly rejected as
    // an inconsistent routing map.
    void lock_dense_mcu_local_arcs()
    {
        bool active = false;
        for (auto &cell : ctx->cells)
            if (cell.second->attrs.count(ctx->id("AGRV2K_DENSE_MCU_ODD_OK"))) {
                active = true;
                break;
            }
        if (!active)
            return;
        struct Arc { NetInfo *net; CellInfo *user; IdString port; int tile; int flex; };
        std::vector<Arc> arcs;
        for (auto &net_kv : ctx->nets) {
            NetInfo *net = net_kv.second.get();
            CellInfo *driver = net->driver.cell;
            if (driver == nullptr || driver->type != ctx->id("GENERIC_SLICE") ||
                driver->bel == BelId())
                continue;
            Loc dl = ctx->getBelLocation(driver->bel);
            int tile = tkey(dl.x, dl.y);
            for (auto &user : net->users) {
                if (user.cell == nullptr || user.cell->type != ctx->id("GENERIC_SLICE") ||
                    user.cell->bel == BelId())
                    continue;
                Loc ul = ctx->getBelLocation(user.cell->bel);
                if (tkey(ul.x, ul.y) != tile)
                    continue;
                WireId target = ctx->getBelPinWire(user.cell->bel, user.port);
                std::unordered_set<int> uphill{target.index};
                std::vector<WireId> q{target};
                for (size_t head = 0; head < q.size(); ++head)
                    for (PipId pip : ctx->getPipsUphill(q[head])) {
                        Loc pl = ctx->getPipLocation(pip);
                        if (tkey(pl.x, pl.y) != tile)
                            continue;
                        WireId src = ctx->getPipSrcWire(pip);
                        if (uphill.insert(src.index).second)
                            q.push_back(src);
                    }
                arcs.push_back({net, user.cell, user.port, tile, int(uphill.size())});
            }
        }
        std::stable_sort(arcs.begin(), arcs.end(), [&](const Arc &a, const Arc &b) {
            if (a.flex != b.flex)
                return a.flex < b.flex;
            if (a.net->name != b.net->name)
                return a.net->name.str(ctx) < b.net->name.str(ctx);
            return a.user->name.str(ctx) < b.user->name.str(ctx);
        });
        int locked_arcs = 0, locked_pips = 0, deferred_arcs = 0;
        for (const Arc &arc : arcs) {
            WireId source = ctx->getBelPinWire(arc.net->driver.cell->bel, arc.net->driver.port);
            WireId target = ctx->getBelPinWire(arc.user->bel, arc.port);
            NetInfo *source_owner = ctx->getBoundWireNet(source);
            if (source_owner != nullptr && source_owner != arc.net) {
                ++deferred_arcs;
                continue;
            }
            if (ctx->getBoundWireNet(target) == arc.net) {
                ++locked_arcs;
                continue;
            }
            std::vector<WireId> q{source};
            std::unordered_map<int, PipId> previous;
            previous[source.index] = PipId();
            for (size_t head = 0; head < q.size() && !previous.count(target.index); ++head)
                for (PipId pip : ctx->getPipsDownhill(q[head])) {
                    Loc pl = ctx->getPipLocation(pip);
                    if (tkey(pl.x, pl.y) != arc.tile ||
                        !ctx->checkPipAvailForNet(pip, arc.net))
                        continue;
                    WireId dst = ctx->getPipDstWire(pip);
                    NetInfo *owner = ctx->getBoundWireNet(dst);
                    if (owner != nullptr && owner != arc.net)
                        continue;
                    if (previous.emplace(dst.index, pip).second)
                        q.push_back(dst);
                }
            if (!previous.count(target.index)) {
                ++deferred_arcs;
                continue;
            }
            std::vector<PipId> route;
            for (WireId cursor = target; cursor != source;) {
                PipId pip = previous.at(cursor.index);
                route.push_back(pip);
                cursor = ctx->getPipSrcWire(pip);
            }
            std::reverse(route.begin(), route.end());
            if (source_owner == nullptr)
                ctx->bindWire(source, arc.net, STRENGTH_LOCKED);
            for (PipId pip : route) {
                WireId dst = ctx->getPipDstWire(pip);
                if (ctx->getBoundWireNet(dst) == arc.net)
                    continue;
                ctx->bindPip(pip, arc.net, STRENGTH_LOCKED);
                ++locked_pips;
            }
            ++locked_arcs;
        }
        log_info("agrv2k: post-corridor pre-routed %d dense same-tile arc(s) over %d strict pip(s); "
                 "%d deferred to router2\n", locked_arcs, locked_pips, deferred_arcs);
    }

    // Reserve every direct hard-input arc before the read-data exits.
    // pack_exit_anchor proves that each selected exit BEL is reachable from
    // both sides, but an output-first route can consume the only entry
    // approach and strand a consumer pin.  Each MCU_DIN net has one fixed
    // physical root; pre-routing its consumer arcs (least-flexible first)
    // lets the exit search adapt around the inputs.  A consumer that
    // condplace dropped outside its entry's conducting region is re-anchored
    // onto a still-available slice all of whose hard-input pins are
    // reachable, before any of its arcs lock.
    void lock_registered_mcu_inputs()
    {
        struct Arc { NetInfo *net; CellInfo *user; IdString port; int flex; std::string name; };
        std::vector<Arc> arcs;
        std::unordered_map<int, std::unordered_set<int>> reach_cache; // entry wire -> downhill set
        auto entry_reach = [&](WireId source) -> const std::unordered_set<int> & {
            auto found = reach_cache.find(source.index);
            if (found == reach_cache.end()) {
                std::unordered_set<int> seen{source.index};
                std::vector<WireId> q{source};
                for (size_t h = 0; h < q.size(); ++h)
                    for (PipId pip : ctx->getPipsDownhill(q[h])) {
                        WireId dst = ctx->getPipDstWire(pip);
                        if (seen.insert(dst.index).second)
                            q.push_back(dst);
                    }
                found = reach_cache.emplace(source.index, std::move(seen)).first;
            }
            return found->second;
        };
        auto hard_source_of = [&](const PortInfo &port) -> CellInfo * {
            if (port.type != PORT_IN || port.net == nullptr || port.net->driver.cell == nullptr ||
                port.net->driver.cell->type != ctx->id("MCU_DIN") ||
                port.net->driver.cell->bel == BelId())
                return nullptr;
            return port.net->driver.cell;
        };
        int n_din = 0, n_nonet = 0, n_nosrc = 0, n_users = 0, n_badcell = 0, n_notarget = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *din = cell.second.get();
            if (din->type != ctx->id("MCU_DIN") || din->bel == BelId()) continue;
            ++n_din;
            std::string name = din->name.str(ctx);
            NetInfo *net = din->getPort(ctx->id("DIN"));
            if (net == nullptr) { ++n_nonet; continue; }
            WireId source = ctx->getBelPinWire(din->bel, ctx->id("DIN"));
            if (source == WireId()) { ++n_nosrc; continue; }
            for (auto &user : net->users) {
                ++n_users;
                if (user.cell == nullptr || user.cell->type != ctx->id("GENERIC_SLICE") ||
                    user.cell->bel == BelId()) {
                    ++n_badcell;
                    continue;
                }
                WireId target = ctx->getBelPinWire(user.cell->bel, user.port);
                if (target == WireId()) { ++n_notarget; continue; }
                pool<WireId> uphill{target}; std::vector<WireId> q{target};
                for (size_t head = 0; head < q.size(); ++head)
                    for (PipId pip : ctx->getPipsUphill(q[head])) {
                        WireId wire = ctx->getPipSrcWire(pip);
                        if (uphill.insert(wire).second) q.push_back(wire);
                    }
                arcs.push_back({net, user.cell, user.port, int(uphill.size()), name});
            }
        }
        log_info("agrv2k: MCU input scan: %d din, %d no-net, %d no-src, %d users, %d non-slice/unplaced, "
                 "%d no-pin-wire, %d arcs\n", n_din, n_nonet, n_nosrc, n_users, n_badcell, n_notarget,
                 int(arcs.size()));
        std::stable_sort(arcs.begin(), arcs.end(), [](const Arc &a, const Arc &b) {
            return std::tie(a.flex, a.name) < std::tie(b.flex, b.name);
        });
        // Phase 1: move every consumer whose current placement is outside one
        // of its entries' conducting regions BEFORE any arc locks, so no
        // locked route can dangle at a vacated BEL.  A candidate must carry
        // every hard-input pin of the cell.
        int moved = 0;
        std::unordered_set<CellInfo *> checked;
        for (const Arc &probe : arcs) {
            if (!checked.insert(probe.user).second)
                continue;
            bool feasible = true;
            for (auto &port : probe.user->ports) {
                CellInfo *din = hard_source_of(port.second);
                if (din == nullptr) continue;
                WireId ew = ctx->getBelPinWire(din->bel, port.second.net->driver.port);
                WireId pw = ctx->getBelPinWire(probe.user->bel, port.first);
                if (ew == WireId() || pw == WireId() || !entry_reach(ew).count(pw.index)) {
                    feasible = false;
                    break;
                }
            }
            if (feasible)
                continue;
            BelId best;
            int best_score = 0;
            for (BelId b : ctx->getBels()) {
                if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE") || !ctx->checkBelAvail(b))
                    continue;
                bool ok = true;
                for (auto &port : probe.user->ports) {
                    CellInfo *din = hard_source_of(port.second);
                    if (din == nullptr) continue;
                    WireId ew = ctx->getBelPinWire(din->bel, port.second.net->driver.port);
                    WireId pw = ctx->getBelPinWire(b, port.first);
                    if (ew == WireId() || pw == WireId() || !entry_reach(ew).count(pw.index)) {
                        ok = false;
                        break;
                    }
                }
                if (!ok) continue;
                Loc loc = ctx->getBelLocation(b);
                int d = std::abs(loc.x - 13) + std::abs(loc.y - 9);
                if (best == BelId() || d < best_score) { best = b; best_score = d; }
            }
            if (best == BelId())
                log_error("agrv2k: no strict-graph slice reachable from %s for consumer '%s'\n",
                          probe.name.c_str(), probe.user->name.c_str(ctx));
            BelId old = probe.user->bel;
            ctx->unbindBel(old);
            ctx->bindBel(best, probe.user, STRENGTH_LOCKED);
            probe.user->attrs[ctx->id("AGRV2K_MCU_PINPACKED")] = Property(1);
            ++moved;
            log_info("agrv2k: re-anchored MCU input consumer '%s' %s -> %s for %s\n",
                     probe.user->name.c_str(ctx), ctx->getBelName(old).str(ctx).c_str(),
                     ctx->getBelName(best).str(ctx).c_str(), probe.name.c_str());
        }
        // Phase 2: lock the arcs, least flexible first, with the same bounded
        // rip-up negotiation as the exit corridors.  Greedy ordering strands
        // arcs whose entry funnels overlap.  Rips act on whole nets (one net
        // can carry several arcs), so requeueing re-locks every arc of a
        // ripped net.
        std::unordered_map<const NetInfo *, std::vector<PipId>> net_locked;
        std::unordered_map<const NetInfo *, std::vector<int>> net_arcs;
        for (size_t i = 0; i < arcs.size(); ++i)
            net_arcs[arcs[i].net].push_back(int(i));
        std::deque<int> pending;
        for (size_t i = 0; i < arcs.size(); ++i)
            pending.push_back(int(i));
        std::vector<int> fails(arcs.size(), 0);
        int locked = 0, budget = 400;
        auto arc_bfs = [&](const Arc &arc, bool permissive, std::vector<PipId> &route,
                           std::unordered_set<const NetInfo *> &blockers) -> bool {
            route.clear();
            blockers.clear();
            WireId source = ctx->getBelPinWire(arc.net->driver.cell->bel, arc.net->driver.port);
            WireId target = ctx->getBelPinWire(arc.user->bel, arc.port);
            if (source == WireId() || target == WireId())
                return false;
            std::vector<WireId> queue{source};
            std::unordered_map<int, PipId> previous;
            previous[source.index] = PipId();
            for (size_t head = 0; head < queue.size() && !previous.count(target.index); ++head)
                for (PipId pip : ctx->getPipsDownhill(queue[head])) {
                    WireId dst = ctx->getPipDstWire(pip);
                    NetInfo *owner = ctx->getBoundWireNet(dst);
                    bool foreign = owner != nullptr && owner != arc.net;
                    if (foreign) {
                        auto oi = net_locked.find(owner);
                        if (!permissive || oi == net_locked.end() || oi->second.empty())
                            continue;
                    } else if (!ctx->checkPipAvailForNet(pip, arc.net)) {
                        continue;
                    }
                    if (previous.emplace(dst.index, pip).second)
                        queue.push_back(dst);
                }
            if (!previous.count(target.index))
                return false;
            for (WireId cursor = target; cursor != source;) {
                PipId pip = previous.at(cursor.index);
                route.push_back(pip);
                NetInfo *owner = ctx->getBoundWireNet(ctx->getPipDstWire(pip));
                if (owner != nullptr && owner != arc.net)
                    blockers.insert(owner);
                cursor = ctx->getPipSrcWire(pip);
            }
            std::reverse(route.begin(), route.end());
            return true;
        };
        while (!pending.empty()) {
            int ai = pending.front();
            pending.pop_front();
            const Arc &arc = arcs[ai];
            WireId target = ctx->getBelPinWire(arc.user->bel, arc.port);
            if (target != WireId() && ctx->getBoundWireNet(target) == arc.net)
                continue; // already re-locked via a duplicate queue entry
            std::vector<PipId> route;
            std::unordered_set<const NetInfo *> blockers;
            if (arc_bfs(arc, false, route, blockers)) {
                WireId src_wire =
                        ctx->getBelPinWire(arc.net->driver.cell->bel, arc.net->driver.port);
                if (src_wire != WireId() && ctx->getBoundWireNet(src_wire) == nullptr)
                    ctx->bindWire(src_wire, arc.net, STRENGTH_LOCKED);
                for (PipId pip : route) {
                    // A net with several arcs shares its locked tree: the
                    // second arc's path re-traverses the common prefix.
                    // Binding a pip twice (and later double-unbinding it on a
                    // rip) corrupts the router state, so attach only the new
                    // suffix and record each pip exactly once.
                    if (ctx->getBoundWireNet(ctx->getPipDstWire(pip)) == arc.net)
                        continue;
                    ctx->bindPip(pip, arc.net, STRENGTH_LOCKED);
                    ++locked;
                    net_locked[arc.net].push_back(pip);
                }
                continue;
            }
            bool arc_permissive = arc_bfs(arc, true, route, blockers);
            if (!arc_permissive || blockers.empty() || ++fails[ai] >= 25) {
                for (const NetInfo *bn : blockers)
                    log_info("agrv2k: MCU input blocker for %s: net '%s'\n",
                             arc.name.c_str(), bn->name.c_str(ctx));
                log_error("agrv2k: no simultaneous strict-graph MCU input route for %s "
                          "(permissive=%d blockers=%d fails=%d budget=%d)\n",
                          arc.name.c_str(), arc_permissive ? 1 : 0, int(blockers.size()),
                          fails[ai], budget);
            }
            budget -= int(blockers.size());
            if (budget < 0)
                log_error("agrv2k: MCU input arc negotiation exceeded its rip-up budget at %s\n",
                          arc.name.c_str());
            for (const NetInfo *bn : blockers) {
                for (PipId pip : net_locked[bn])
                    ctx->unbindPip(pip);
                locked -= int(net_locked[bn].size());
                net_locked[bn].clear();
                for (int oi2 : net_arcs[bn])
                    pending.push_back(oi2);
            }
            pending.push_front(ai);
        }
        if (!arcs.empty())
            log_info("agrv2k: pre-routed %d MCU input arc(s) over %d pip(s), %d consumer(s) re-anchored\n",
                     int(arcs.size()), locked, moved);
    }

    // Route the 32-bit fabric-to-MCU bus as one atomic resource before
    // router2 handles unrelated nets.  Each lane is individually connected
    // by the strict graph, but the MCU boundary has narrow shared approaches;
    // ordinary net ordering can consume one and strand a later lane.  This is
    // the same pre-routing mechanism used for the qualified BRAM Port-B bus.
    void lock_mcu_dout_corridors()
    {
        // Prefer the one conflict-free simultaneous route recovered from the
        // vendor's 32-bit AHB loopback.  Five lanes pass through an actual LUT
        // buffer; for those, lock the MCU_DIN net up to the LUT input and the
        // MCU_DOUT net from the LUT output onward.  Ordinary fabric drivers do
        // not match these roots and fall through to the general BFS below.
        bool addr_mode = false;
        for (auto &cell : ctx->cells)
            if (cell.second->type == ctx->id("MCU_DIN") &&
                cell.second->name.str(ctx).find("haddr") != std::string::npos)
                addr_mode = true;
        int dout_count = 0;
        for (auto &cell : ctx->cells)
            if (cell.second->type == ctx->id("MCU_DOUT"))
                ++dout_count;
        bool exact_topology = dout_count == 32;
        for (auto &cell : ctx->cells) {
            CellInfo *dout = cell.second.get();
            if (!exact_topology || dout->type != ctx->id("MCU_DOUT")) continue;
            NetInfo *net = dout->getPort(ctx->id("DOUT"));
            if (net == nullptr || net->driver.cell == nullptr) {
                exact_topology = false; break;
            }
            CellInfo *driver = net->driver.cell;
            if (driver->type == ctx->id("GENERIC_SLICE")) {
                // The qualified vendor topology contains only combinational
                // identity buffers fed directly by an MCU_DIN lane.  Merely
                // seeing an F-driven slice is not enough: packer-created
                // constant LUTs and ordinary peripheral logic also use F and
                // must use the general simultaneous router.  A Q-driven slice
                // is likewise a registered AHB slave, not the oracle loopback.
                bool has_mcu_input = false;
                for (auto &port : driver->ports) {
                    if (port.second.type == PORT_IN && port.second.net != nullptr &&
                        port.second.net->driver.cell != nullptr &&
                        port.second.net->driver.cell->type == ctx->id("MCU_DIN")) {
                        has_mcu_input = true;
                        break;
                    }
                }
                if (net->driver.port == ctx->id("Q") || !has_mcu_input)
                    exact_topology = false;
            } else if (driver->type != ctx->id("MCU_DIN")) {
                exact_topology = false;
            }
        }
        std::unordered_map<int, std::vector<std::string>> exact;
        std::unordered_map<int, int> exact_source;
        if (exact_topology) {
            std::ifstream probe(path(addr_mode ? "mcu_ahb32_addr_corridors.csv" :
                                                "mcu_ahb32_corridors.csv"));
            if (probe) {
                std::string line;
                std::getline(probe, line);
                while (std::getline(probe, line)) {
                    if (!line.empty() && line.back() == '\r') line.pop_back();
                    std::vector<std::string> f; std::string cur; std::istringstream ss(line);
                    while (std::getline(ss, cur, ',')) f.push_back(cur);
                    if (f.size() < 4) continue;
                    int bit = to_int(f[0], -1);
                    int src_col = addr_mode ? 3 : 2;
                    int dst_col = src_col + 1;
                    exact_source[bit] = addr_mode ? to_int(f[1], -1) : bit;
                    auto &nodes = exact[bit];
                    if (nodes.empty()) nodes.push_back(f[src_col]);
                    if (nodes.back() != f[src_col])
                        log_error("agrv2k: discontinuous exact MCU corridor for hrdata[%d]\n", bit);
                    nodes.push_back(f[dst_col]);
                }
            }
        }
        auto bind_exact = [&](int bit, NetInfo *net, WireId source, WireId target) -> int {
            auto it = exact.find(bit);
            if (it == exact.end()) return -1;
            std::string sw = ctx->getWireName(source).str(ctx);
            std::string tw = ctx->getWireName(target).str(ctx);
            auto &nodes = it->second;
            auto first = std::find(nodes.begin(), nodes.end(), sw);
            // Two vendor buffers use alternate OMUX[3z+0].  The generic BEL
            // presents F on +2, so bind the qualified internal output-select
            // pip first and continue at the vendor node.
            if (first == nodes.end()) {
                int x = -1, y = -1, oi = -1;
                if (std::sscanf(sw.c_str(), "X%dY%d_OMUX%d", &x, &y, &oi) == 3 && oi % 3 == 2) {
                    char altbuf[64]; std::snprintf(altbuf, sizeof(altbuf), "X%dY%d_OMUX%02d", x, y, oi - 2);
                    std::string alt(altbuf);
                    auto ai = std::find(nodes.begin(), nodes.end(), alt);
                    if (ai != nodes.end()) {
                        PipId bridge = ctx->getPipByNameStr(sw + "." + alt);
                        if (bridge == PipId())
                            log_error("agrv2k: missing vendor-output bridge %s -> %s\n", sw.c_str(), alt.c_str());
                        ctx->bindPip(bridge, net, STRENGTH_LOCKED);
                        source = ctx->getPipDstWire(bridge); sw = alt; first = ai;
                    }
                }
            }
            auto last = std::find(nodes.begin(), nodes.end(), tw);
            if (first == nodes.end() || last == nodes.end() || first > last)
                return -1;
            int locked = 0;
            for (auto n = first; n != last; ++n) {
                std::string pn = *n + "." + *(n + 1);
                PipId pip = ctx->getPipByNameStr(pn);
                if (pip == PipId())
                    log_error("agrv2k: exact MCU corridor pip absent: %s\n", pn.c_str());
                if (!ctx->checkPipAvailForNet(pip, net))
                    log_error("agrv2k: exact MCU corridor conflict at %s\n", pn.c_str());
                ctx->bindPip(pip, net, STRENGTH_LOCKED); ++locked;
            }
            return locked;
        };
        int exact_locked = 0, exact_nets = 0;
        if (!exact.empty()) {
            // Prefixes for the five buffered lanes: MCU_DIN root -> slice I[3].
            for (auto &cell : ctx->cells) {
                CellInfo *din = cell.second.get();
                if (din->type != ctx->id("MCU_DIN") || din->bel == BelId()) continue;
                int source_bit = parse_after(din->name.str(ctx), addr_mode ? "haddr" : "hwdata");
                if (source_bit < 0) continue;
                NetInfo *net = din->getPort(ctx->id("DIN"));
                if (net == nullptr) continue;
                for (auto &u : net->users) {
                    if (u.cell == nullptr || u.cell->type != ctx->id("GENERIC_SLICE") || u.cell->bel == BelId())
                        continue;
                    WireId source = ctx->getBelPinWire(din->bel, ctx->id("DIN"));
                    WireId target = ctx->getBelPinWire(u.cell->bel, u.port);
                    for (auto &es : exact_source) {
                        if (es.second != source_bit) continue;
                        int n = bind_exact(es.first, net, source, target);
                        if (n >= 0) { exact_locked += n; ++exact_nets; break; }
                    }
                }
            }
            // Complete direct lanes, or suffixes from a buffered slice output.
            for (auto &cell : ctx->cells) {
                CellInfo *dout = cell.second.get();
                if (dout->type != ctx->id("MCU_DOUT") || dout->bel == BelId()) continue;
                int bit = parse_hk(dout->name.str(ctx));
                NetInfo *net = dout->getPort(ctx->id("DOUT"));
                if (bit < 0 || net == nullptr || net->driver.cell == nullptr || net->driver.cell->bel == BelId())
                    continue;
                WireId source = ctx->getBelPinWire(net->driver.cell->bel, net->driver.port);
                WireId target = ctx->getBelPinWire(dout->bel, ctx->id("DOUT"));
                int n = bind_exact(bit, net, source, target);
                if (n >= 0) { exact_locked += n; ++exact_nets; }
            }
            int expected_segments = addr_mode ? 34 : 37;
            if (exact_nets == expected_segments) {
                log_info("agrv2k: pre-routed exact vendor AHB32 corridor (%d net segments, %d pips)\n",
                         exact_nets, exact_locked);
                return;
            }
            // Do not partially retain an exact route and then mix in BFS.
            if (exact_nets != 0)
                log_error("agrv2k: incomplete exact AHB32 corridor (%d/%d net segments)\n",
                          exact_nets, expected_segments);
        }
        struct Item { std::string label; NetInfo *net; WireId source, target; int reach; };
        std::vector<Item> items;
        for (auto &cell : ctx->cells) {
            CellInfo *mcu = cell.second.get();
            bool response_sink = mcu->type == ctx->id("MCU_AHB_HREADYOUT") ||
                                 mcu->type == ctx->id("MCU_AHB_HRESP");
            if ((mcu->type != ctx->id("MCU_DOUT") && !response_sink) || mcu->bel == BelId())
                continue;
            NetInfo *net = mcu->getPort(ctx->id("DOUT"));
            if (net == nullptr || net->driver.cell == nullptr || net->driver.cell->bel == BelId())
                continue;
            WireId source = ctx->getBelPinWire(net->driver.cell->bel, net->driver.port);
            WireId target = ctx->getBelPinWire(mcu->bel, ctx->id("DOUT"));
            if (source == WireId() || target == WireId())
                continue;
            pool<WireId> uphill{target};
            std::vector<WireId> q{target};
            for (size_t head = 0; head < q.size(); ++head)
                for (PipId pip : ctx->getPipsUphill(q[head])) {
                    WireId src = ctx->getPipSrcWire(pip);
                    if (uphill.insert(src).second)
                        q.push_back(src);
                }
            int lk = -1;
            McuDoutLane lkind =
                    response_sink ? LANE_NONE : mcu_dout_lane(mcu->name.str(ctx), lk);
            const char *lbus = lkind == LANE_SHADDR    ? "slave_ahb_haddr"
                               : lkind == LANE_SHWDATA ? "slave_ahb_hwdata"
                                                       : "hrdata";
            std::string label =
                    response_sink ? (mcu->type == ctx->id("MCU_AHB_HRESP") ? std::string("hresp")
                                                                           : std::string("hreadyout"))
                                  : std::string(lbus) + "[" + std::to_string(lk) + "]";
            items.push_back({label, net, source, target, int(uphill.size())});
        }
        // Constrain the least flexible boundary lanes first.  The label is
        // only a deterministic tie-breaker.
        std::stable_sort(items.begin(), items.end(), [](const Item &a, const Item &b) {
            return std::tie(a.reach, a.label) < std::tie(b.reach, b.label);
        });
        // BOUNDED JOINT ALLOCATION.  Route in flexibility order; when a
        // corridor is blocked, find the shortest path through wires owned by
        // other locked corridors, rip exactly those corridors up, requeue
        // them, and retry the blocked one first.  Greedy single-order locking
        // strands lanes (control-first strands HRDATA[18], HRDATA-first
        // strands HRESP); the rip-up budget bounds the negotiation and makes
        // exhaustion a hard, named failure instead of a silent fallback.
        std::unordered_map<const NetInfo *, int> net_item;
        for (size_t i = 0; i < items.size(); ++i)
            net_item.emplace(items[i].net, int(i));
        std::vector<std::vector<PipId>> locked_pips(items.size());
        std::vector<int> fails(items.size(), 0);
        std::deque<int> pending;
        for (size_t i = 0; i < items.size(); ++i)
            pending.push_back(int(i));
        int budget = 400, locked = 0, reanchors_left = 48;
        // Post-placement re-anchor: when two lanes livelock over one remaining
        // approach, exhaustive strict BFS has already proven the loser's BEL
        // has no alternative corridor in the *current* bound graph (input-arc
        // locks landed after the pack-time trial).  Move the loser's driver to
        // a still-available slice that reaches its sink now.  The driver's
        // other nets are unrouted at this stage, so rebinding is safe.
        auto reanchor = [&](Item &item, std::unordered_set<int> &rips) -> bool {
            CellInfo *drv = item.net->driver.cell;
            if (drv == nullptr || drv->type != ctx->id("GENERIC_SLICE") || drv->bel == BelId())
                return false;
            // Direct-D feedback is a complete characterized site footprint,
            // not a placement hint. Moving it to obtain a convenient MCU
            // exit corridor silently leaves the qualified slice pool and is
            // rejected only by the later legality check. Keep the hard site
            // and let the locker report the missing corridor instead.
            if (drv->attrs.count(ctx->id("agamemnon_direct_d_feedback")) != 0)
                return false;
            // Uphill reach from the sink.  Wires owned by other LOCKED
            // corridors are negotiable (we may rip their owners); any other
            // binding (registered-input arcs, BRAM buses) stays a hard wall.
            std::unordered_map<int, int> reach;
            std::unordered_map<int, WireId> pred;
            std::vector<WireId> q{item.target};
            reach[item.target.index] = 0;
            for (size_t h = 0; h < q.size(); ++h)
                for (PipId pip : ctx->getPipsUphill(q[h])) {
                    WireId src = ctx->getPipSrcWire(pip);
                    NetInfo *own = ctx->getBoundWireNet(src);
                    if (own != nullptr && own != item.net) {
                        auto oi = net_item.find(own);
                        if (oi == net_item.end() || locked_pips[oi->second].empty())
                            continue;
                    }
                    if (reach.emplace(src.index, reach.at(q[h].index) + 1).second) {
                        pred[src.index] = q[h];
                        q.push_back(src);
                    }
                }
            auto path_owners = [&](WireId from, std::unordered_set<int> &owners) {
                owners.clear();
                for (WireId w = from; w != item.target;) {
                    NetInfo *own = ctx->getBoundWireNet(w);
                    if (own != nullptr && own != item.net) {
                        auto oi = net_item.find(own);
                        if (oi != net_item.end())
                            owners.insert(oi->second);
                    }
                    auto p = pred.find(w.index);
                    if (p == pred.end())
                        return false;
                    w = p->second;
                }
                return true;
            };
            std::vector<std::pair<WireId, IdString>> hard_ins;
            for (auto &port : drv->ports) {
                if (port.second.type != PORT_IN || port.second.net == nullptr ||
                    port.second.net->driver.cell == nullptr ||
                    port.second.net->driver.cell->type != ctx->id("MCU_DIN"))
                    continue;
                CellInfo *din = port.second.net->driver.cell;
                if (din->bel == BelId())
                    return false;
                hard_ins.push_back({ctx->getBelPinWire(din->bel, port.second.net->driver.port),
                                    port.first});
            }
            auto reaches_downhill = [&](WireId source, WireId sink) {
                if (source == WireId() || sink == WireId())
                    return false;
                std::unordered_set<int> seen{source.index};
                std::vector<WireId> qq{source};
                for (size_t h = 0; h < qq.size(); ++h) {
                    if (qq[h] == sink)
                        return true;
                    for (PipId pip : ctx->getPipsDownhill(qq[h])) {
                        WireId dst = ctx->getPipDstWire(pip);
                        if (ctx->getBoundWireNet(dst) != nullptr)
                            continue;
                        if (seen.insert(dst.index).second)
                            qq.push_back(dst);
                    }
                }
                return false;
            };
            std::unordered_set<int> taken_sources;
            for (auto &other : items)
                if (&other != &item && other.source != WireId())
                    taken_sources.insert(other.source.index);
            IdString out_port = item.net->driver.port;
            BelId best;
            int best_score = 0;
            std::unordered_set<int> best_owners, owners;
            for (BelId b : ctx->getBels()) {
                if (ctx->getBelType(b) != ctx->id("GENERIC_SLICE") || !ctx->checkBelAvail(b))
                    continue;
                WireId ow = ctx->getBelPinWire(b, out_port);
                auto ri = ow == WireId() ? reach.end() : reach.find(ow.index);
                if (ri == reach.end() || taken_sources.count(ow.index))
                    continue;
                bool ok = true;
                for (auto &hi : hard_ins)
                    if (!reaches_downhill(hi.first, ctx->getBelPinWire(b, hi.second))) {
                        ok = false;
                        break;
                    }
                if (!ok || !path_owners(ow, owners))
                    continue;
                // Prefer the anchor that disturbs the fewest locked corridors;
                // among those, the electrically shortest.
                int score = int(owners.size()) * 1000 + ri->second;
                if (best == BelId() || score < best_score) {
                    best = b;
                    best_score = score;
                    best_owners = owners;
                }
            }
            if (best == BelId())
                return false;
            BelId old = drv->bel;
            ctx->unbindBel(old);
            ctx->bindBel(best, drv, STRENGTH_LOCKED);
            WireId new_source = ctx->getBelPinWire(best, out_port);
            for (auto &it2 : items)
                if (it2.net == item.net)
                    it2.source = new_source;
            rips = best_owners;
            log_info("agrv2k: re-anchored %s driver %s -> %s at corridor lock (%d corridor rip(s))\n",
                     item.label.c_str(), ctx->getBelName(old).str(ctx).c_str(),
                     ctx->getBelName(best).str(ctx).c_str(), int(rips.size()));
            return true;
        };
        auto corridor_bfs = [&](const Item &item, bool permissive, std::vector<PipId> &route,
                                std::unordered_set<int> &blockers) -> bool {
            route.clear();
            blockers.clear();
            std::vector<WireId> queue{item.source};
            std::unordered_map<int, PipId> previous;
            previous[item.source.index] = PipId();
            for (size_t head = 0; head < queue.size() && !previous.count(item.target.index); ++head) {
                for (PipId pip : ctx->getPipsDownhill(queue[head])) {
                    WireId dst = ctx->getPipDstWire(pip);
                    NetInfo *wire_owner = ctx->getBoundWireNet(dst);
                    bool foreign = wire_owner != nullptr && wire_owner != item.net;
                    if (foreign) {
                        // Only another locked corridor is negotiable; wires
                        // owned by registered-input arcs or BRAM buses stay
                        // hard obstacles in both passes.
                        auto oi = net_item.find(wire_owner);
                        if (!permissive || oi == net_item.end() || locked_pips[oi->second].empty())
                            continue;
                    } else if (!ctx->checkPipAvailForNet(pip, item.net)) {
                        continue;
                    }
                    if (previous.emplace(dst.index, pip).second)
                        queue.push_back(dst);
                }
            }
            if (!previous.count(item.target.index))
                return false;
            for (WireId cursor = item.target; cursor != item.source;) {
                PipId pip = previous.at(cursor.index);
                route.push_back(pip);
                NetInfo *wire_owner = ctx->getBoundWireNet(ctx->getPipDstWire(pip));
                if (wire_owner != nullptr && wire_owner != item.net)
                    blockers.insert(net_item.at(wire_owner));
                cursor = ctx->getPipSrcWire(pip);
            }
            std::reverse(route.begin(), route.end());
            return true;
        };
        while (!pending.empty()) {
            int ii = pending.front();
            pending.pop_front();
            Item &item = items[ii];
            std::vector<PipId> route;
            std::unordered_set<int> blockers;
            if (corridor_bfs(item, false, route, blockers)) {
                // Routers bind a net's source wire (pipless) when they route
                // it; a fully pre-locked net never passes through them, and
                // router1's legality checker requires the source in
                // net->wires.
                if (ctx->getBoundWireNet(item.source) == nullptr)
                    ctx->bindWire(item.source, item.net, STRENGTH_LOCKED);
                locked_pips[ii].clear();
                for (PipId pip : route) {
                    // Shared-net fanout (one driver feeding several exit
                    // sinks) re-traverses the common tree prefix; bind and
                    // record only the new suffix so a later rip never
                    // double-unbinds a pip.
                    if (ctx->getBoundWireNet(ctx->getPipDstWire(pip)) == item.net)
                        continue;
                    ctx->bindPip(pip, item.net, STRENGTH_LOCKED);
                    ++locked;
                    locked_pips[ii].push_back(pip);
                }
                // fails deliberately NOT reset here: in an A/B livelock each
                // participant alternates fail/route, so resetting on success
                // would erase the livelock evidence and never escalate.
                log_info("agrv2k: pre-routed %s over %d strict pip(s)\n", item.label.c_str(),
                         int(locked_pips[ii].size()));
                continue;
            }
            bool permissive_ok = corridor_bfs(item, true, route, blockers);
            if (++fails[ii] >= 8 || !permissive_ok || blockers.empty()) {
                std::unordered_set<int> swap_rips;
                if (reanchors_left > 0 && reanchor(item, swap_rips)) {
                    --reanchors_left;
                    fails[ii] = 0;
                    blockers = swap_rips; // fall through to the shared rip path
                } else {
                    if (!permissive_ok || blockers.empty())
                        log_error("agrv2k: no simultaneous strict-graph MCU corridor for %s\n",
                                  item.label.c_str());
                    log_error("agrv2k: MCU corridor livelock at %s with no alternative anchor\n",
                              item.label.c_str());
                }
            }
            budget -= int(blockers.size());
            if (budget < 0)
                log_error("agrv2k: joint MCU corridor allocation exceeded its rip-up budget at %s\n",
                          item.label.c_str());
            for (int bi : blockers) {
                for (PipId pip : locked_pips[bi])
                    ctx->unbindPip(pip);
                locked -= int(locked_pips[bi].size());
                locked_pips[bi].clear();
                pending.push_back(bi);
                log_info("agrv2k: ripped up %s to free a blocked MCU corridor approach\n",
                         items[bi].label.c_str());
            }
            pending.push_front(ii);
        }
        if (!items.empty())
            log_info("agrv2k: pre-routed %d full-width MCU corridor pip(s)\n", locked);
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

    const std::vector<delay_t> &timing_distances_to(int destination) const
    {
        auto cached = timing_distance_cache.find(destination);
        if (cached != timing_distance_cache.end())
            return cached->second;

        const delay_t inf = std::numeric_limits<delay_t>::infinity();
        std::vector<delay_t> distance(timing_uphill.size(), inf);
        using QueueItem = std::pair<delay_t, int>;
        std::priority_queue<QueueItem, std::vector<QueueItem>, std::greater<QueueItem>> queue;
        distance.at(destination) = 0;
        queue.emplace(0, destination);
        while (!queue.empty()) {
            QueueItem item = queue.top();
            queue.pop();
            const delay_t current = item.first;
            const int node = item.second;
            if (current != distance.at(node))
                continue;
            for (const auto &edge : timing_uphill.at(node)) {
                const int predecessor = edge.first;
                const delay_t candidate = current + edge.second;
                if (candidate >= distance.at(predecessor))
                    continue;
                distance.at(predecessor) = candidate;
                queue.emplace(candidate, predecessor);
            }
        }

        if (timing_distance_cache.size() >= TIMING_CACHE_LIMIT) {
            timing_distance_cache.erase(timing_cache_order.front());
            timing_cache_order.pop_front();
        }
        timing_cache_order.push_back(destination);
        return timing_distance_cache.emplace(destination, std::move(distance)).first->second;
    }

    delay_t estimateDelay(WireId src, WireId dst) const override
    {
        if (src == WireId() || dst == WireId() || src.index < 0 || dst.index < 0 ||
            size_t(src.index) >= timing_node_by_wire.size() ||
            size_t(dst.index) >= timing_node_by_wire.size())
            return ctx->getDelayFromNS(0.0);
        const int source = timing_node_by_wire.at(src.index);
        const int destination = timing_node_by_wire.at(dst.index);
        if (source < 0 || destination < 0)
            return ctx->getDelayFromNS(0.0);
        const delay_t delay = timing_distances_to(destination).at(source);
        // An absent admitted-graph path gets no invented HPWL/model charge.
        // Zero is an admissible router heuristic and leaves the real refusal
        // to graph reachability.
        return std::isfinite(delay) ? delay : ctx->getDelayFromNS(0.0);
    }

    delay_t predictDelay(BelId src_bel, IdString src_pin, BelId dst_bel,
                         IdString dst_pin) const override
    {
        if (src_bel == BelId() || dst_bel == BelId())
            return ctx->getDelayFromNS(0.0);
        return estimateDelay(ctx->getBelPinWire(src_bel, src_pin),
                             ctx->getBelPinWire(dst_bel, dst_pin));
    }

    bool getWireDelay(WireId wire, DelayQuad &delay) const override
    {
        (void) wire;
        // Source-family timing is deliberately charged once on each pip. A
        // nonzero wire charge would double-count the same BAR/NNLS evidence.
        delay = DelayQuad(ctx->getDelayFromNS(0.0));
        return true;
    }

    bool getPipDelay(PipId pip, DelayQuad &delay) const override
    {
        auto found = pip_delay_by_index.find(pip.index);
        if (found == pip_delay_by_index.end())
            return false;
        delay = DelayQuad(found->second);
        return true;
    }

    void init(Context *ctx) override
    {
        ViaductAPI::init(ctx);
        h.init(ctx);
        load_db();
        load_mcu_region_witness();
        load_conduction();
    }

    void load_mcu_region_witness()
    {
        Csv c(path("mcu_region_witness.csv"));
        if (!c.next() || c.at(0) != "scope" || c.at(1) != "x_min" ||
            c.at(2) != "x_max" || c.at(3) != "y_min" || c.at(4) != "y_max")
            log_error("agrv2k: malformed mcu_region_witness.csv header\n");
        if (!c.next() || c.at(0) != "wide_mcu_release")
            log_error("agrv2k: mcu_region_witness.csv has no wide_mcu_release row\n");
        mcu_region_witness.min_x = to_int(c.at(1));
        mcu_region_witness.max_x = to_int(c.at(2));
        mcu_region_witness.min_y = to_int(c.at(3));
        mcu_region_witness.max_y = to_int(c.at(4));
        mcu_region_witness.decoded_builds = to_int(c.at(5));
        mcu_region_witness.max_logic_slices = to_int(c.at(6));
        mcu_region_witness.max_occupied_tiles = to_int(c.at(7));
        mcu_region_witness.max_slices_per_tile = to_int(c.at(8));
        if (mcu_region_witness.min_x > mcu_region_witness.max_x ||
            mcu_region_witness.min_y > mcu_region_witness.max_y ||
            mcu_region_witness.decoded_builds < 1 ||
            mcu_region_witness.max_logic_slices < 1 ||
            mcu_region_witness.max_occupied_tiles < 1 ||
            mcu_region_witness.max_slices_per_tile < 1 ||
            mcu_region_witness.max_logic_slices >
                    mcu_region_witness.max_occupied_tiles *
                            mcu_region_witness.max_slices_per_tile)
            log_error("agrv2k: invalid witnessed wide-MCU placement bounds\n");
        if (c.next())
            log_error("agrv2k: mcu_region_witness.csv must contain exactly one data row\n");
        mcu_region_witness.loaded = true;
        log_info("agrv2k: loaded witnessed wide-MCU placement envelope X%d..%d Y%d..%d "
                 "from %d decoded builds\n",
                 mcu_region_witness.min_x, mcu_region_witness.max_x,
                 mcu_region_witness.min_y, mcu_region_witness.max_y,
                 mcu_region_witness.decoded_builds);
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
            std::unordered_map<std::string, int> timing_node_by_key;
            while (c.next()) {
                if (c.at(0).empty())
                    continue;
                IdString id = ctx->id(c.at(0));
                const int x = to_int(c.at(2)), y = to_int(c.at(3));
                WireId wire = ctx->addWire(IdStringList(id), ctx->id(c.at(1)), x, y);
                wire_by_name[id] = wire;
                std::string key = std::to_string(x) + "," + std::to_string(y) + "," + c.at(1);
                auto inserted = timing_node_by_key.emplace(key, int(timing_uphill.size()));
                if (inserted.second)
                    timing_uphill.emplace_back();
                if (timing_node_by_wire.size() <= size_t(wire.index))
                    timing_node_by_wire.resize(size_t(wire.index) + 1, -1);
                timing_node_by_wire.at(wire.index) = inserted.first->second;
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
                const delay_t pip_delay = ctx->getDelayFromNS(to_double(c.at(4), 0.05));
                PipId pip = ctx->addPip(IdStringList(ctx->id(c.at(0))), ctx->id(c.at(1)), si->second,
                                        di->second, pip_delay, loc);
                pip_delay_by_index[pip.index] = pip_delay;
                const int source_node = timing_node_by_wire.at(si->second.index);
                const int destination_node = timing_node_by_wire.at(di->second.index);
                auto &aggregate = timing_uphill.at(destination_node);
                auto old_delay = aggregate.find(source_node);
                if (old_delay == aggregate.end() || pip_delay < old_delay->second)
                    aggregate[source_node] = pip_delay;
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

        log_info("agrv2k: witnessed interconnect timing active for %ld pips over %ld lookahead nodes\n",
                 long(pip_delay_by_index.size()), long(timing_uphill.size()));

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

    // Lock an explicitly requested route-through onto the exact characterized
    // final edge.  The ordinary router may otherwise choose another legal
    // RMUX->IMUX edge and bitgen must then reject the incomplete footprint.
    // Routing only the prefix here keeps the policy constructive without
    // admitting any additional site or selector.
    void lock_route_through_inputs()
    {
        int locked = 0;
        for (auto &entry : ctx->cells) {
            CellInfo *cell = entry.second.get();
            if (cell->type != ctx->id("GENERIC_SLICE") || cell->bel == BelId() ||
                    cell->attrs.count(ctx->id("AGRV2K_ROUTE_THROUGH")) == 0)
                continue;
            Loc loc = ctx->getBelLocation(cell->bel);
            std::string edge;
            if (loc.x == 14 && loc.y == 4 && loc.z == 5)
                edge = "X14Y4_RMUX22.X14Y4_IMUX20";
            else if (loc.x == 14 && loc.y == 8 && loc.z == 8)
                edge = "X15Y8_RMUX00.X14Y8_IMUX32";
            else if (loc.x == 14 && loc.y == 4 && loc.z == 0)
                edge = "X14Y4_RMUX71.X14Y4_IMUX03";
            else if (loc.x == 14 && loc.y == 7 && loc.z == 3)
                edge = "X14Y7_RMUX47.X14Y7_IMUX15";
            else if (std::getenv("AGAMEMNON_BRAM_SITE_READ_PATHS") != nullptr &&
                    loc.x == 14 && loc.y == 9 && loc.z == 9)
                edge = "X14Y9_RMUX41.X14Y9_IMUX39";
            else if (std::getenv("AGAMEMNON_BRAM_SITE_READ_PATHS") != nullptr &&
                    loc.x == 14 && loc.y == 8 && loc.z == 14)
                edge = "X14Y8_RMUX47.X14Y8_IMUX59";
            else if (std::getenv("AGAMEMNON_BRAM_SITE_READ_PATHS") != nullptr &&
                    loc.x == 14 && loc.y == 5 && loc.z == 7)
                edge = "X14Y5_RMUX41.X14Y5_IMUX31";
            else if (std::getenv("AGAMEMNON_BRAM_SITE_READ_PATHS") != nullptr &&
                    loc.x == 14 && loc.y == 5 && loc.z == 4)
                edge = "X14Y5_RMUX41.X14Y5_IMUX19";
            else if (std::getenv("AGAMEMNON_BRAM_SITE_READ_PATHS") != nullptr &&
                    loc.x == 14 && loc.y == 4 && loc.z == 3)
                edge = "X14Y4_RMUX47.X14Y4_IMUX15";
            else
                log_error("agrv2k: no characterized route-through edge for %s\n",
                          ctx->nameOfBel(cell->bel));

            PipId final_pip = ctx->getPipByNameStr(edge);
            if (final_pip == PipId())
                log_error("agrv2k: characterized route-through pip is absent: %s\n", edge.c_str());
            WireId prefix_target = ctx->getPipSrcWire(final_pip);
            WireId input_target = ctx->getPipDstWire(final_pip);
            NetInfo *net = nullptr;
            for (auto &port : cell->ports) {
                if (ctx->getBelPinWire(cell->bel, port.first) == input_target) {
                    net = port.second.net;
                    break;
                }
            }
            if (net == nullptr || net->driver.cell == nullptr)
                log_error("agrv2k: characterized route-through %s has no driven input net\n",
                          ctx->nameOf(cell));
            WireId source = ctx->getBelPinWire(net->driver.cell->bel, net->driver.port);
            const bool experimental_control =
                    std::getenv("AGAMEMNON_BRAM_SITE_READ_PATHS") != nullptr &&
                    ((loc.x == 14 && loc.y == 9 && loc.z == 9) ||
                     (loc.x == 14 && loc.y == 8 && loc.z == 14) ||
                     (loc.x == 14 && loc.y == 5 && (loc.z == 4 || loc.z == 7)) ||
                     (loc.x == 14 && loc.y == 4 && loc.z == 3));
            std::unordered_set<std::string> experimental_edges;
            if (experimental_control) {
                const char *data_dir = std::getenv("AGAMEMNON_DATA");
                if (data_dir == nullptr)
                    log_error("agrv2k: experimental BRAM-control route-through has no AGAMEMNON_DATA\n");
                std::ifstream paths(std::string(data_dir) + "/bram_site_read_paths.csv");
                std::string line;
                std::getline(paths, line);
                while (std::getline(paths, line)) {
                    if (!line.empty() && line.back() == '\r') line.pop_back();
                    std::vector<std::string> f; std::string field; std::istringstream row(line);
                    while (std::getline(row, field, ',')) f.push_back(field);
                    if (f.size() >= 6 && (f[0] == "hready" || f[0] == "hwrite"))
                        experimental_edges.insert(f[4] + "." + f[5]);
                }
            }
            std::vector<WireId> queue{source};
            std::unordered_map<int, PipId> previous;
            previous[source.index] = PipId();
            for (size_t head = 0; head < queue.size() && !previous.count(prefix_target.index); ++head) {
                for (PipId pip : ctx->getPipsDownhill(queue[head])) {
                    if (pip == final_pip || !ctx->checkPipAvailForNet(pip, net))
                        continue;
                    if (experimental_control &&
                            !experimental_edges.count(ctx->getPipName(pip).str(ctx)))
                        continue;
                    WireId dst = ctx->getPipDstWire(pip);
                    NetInfo *owner = ctx->getBoundWireNet(dst);
                    if (owner != nullptr && owner != net)
                        continue;
                    if (previous.emplace(dst.index, pip).second)
                        queue.push_back(dst);
                }
            }
            if (!previous.count(prefix_target.index))
                log_error("agrv2k: no strict prefix route for characterized route-through %s\n",
                          ctx->nameOf(cell));
            std::vector<PipId> route;
            for (WireId cursor = prefix_target; cursor != source;) {
                PipId pip = previous.at(cursor.index);
                route.push_back(pip);
                cursor = ctx->getPipSrcWire(pip);
            }
            std::reverse(route.begin(), route.end());
            if (ctx->getBoundWireNet(source) == nullptr)
                ctx->bindWire(source, net, STRENGTH_LOCKED);
            for (PipId pip : route) {
                if (ctx->getBoundWireNet(ctx->getPipDstWire(pip)) == net)
                    continue;
                ctx->bindPip(pip, net, STRENGTH_LOCKED);
                ++locked;
            }
            if (ctx->getBoundWireNet(input_target) != net) {
                if (!ctx->checkPipAvailForNet(final_pip, net))
                    log_error("agrv2k: characterized route-through final edge conflicts: %s\n",
                              edge.c_str());
                ctx->bindPip(final_pip, net, STRENGTH_LOCKED);
                ++locked;
            }
        }
        if (locked)
            log_info("agrv2k: pre-routed characterized route-through inputs over %d pip(s)\n", locked);
    }

    void constrain_mcu_regions()
    {
        // CONDPLACE is the already-qualified constructive placer and binds
        // every ordinary slice during pack(). Native Regions are for the
        // untouched nextpnr placement rung; B4 can select its placer without
        // changing the region definition landed here.
        if (std::getenv("AGRV2K_CONDPLACE") != nullptr)
            return;
        if (!mcu_region_witness.loaded)
            log_error("agrv2k: native MCU Regions require witnessed placement bounds\n");

        const IdString slice_type = ctx->id("GENERIC_SLICE");
        const IdString bel_attr = ctx->id("BEL");
        const IdString entry_row = ctx->id("AGRV2K_MCU_ENTRY_ROW");
        std::set<CellInfo *> candidates;
        for (auto &item : ctx->cells) {
            CellInfo *cell = item.second.get();
            if (cell->type == slice_type && cell->bel == BelId() &&
                !cell->attrs.count(bel_attr) && cell->region == nullptr)
                candidates.insert(cell);
        }
        if (candidates.empty())
            return;

        std::unordered_map<CellInfo *, std::set<CellInfo *>> downstream, upstream;
        for (CellInfo *cell : candidates) {
            std::set<NetInfo *> outputs;
            for (const char *port : {"Q", "F", "COUT"}) {
                NetInfo *net = cell->getPort(ctx->id(port));
                if (net == nullptr || !outputs.insert(net).second)
                    continue;
                for (auto &user : net->users)
                    if (user.cell != nullptr && user.cell != cell && candidates.count(user.cell)) {
                        downstream[cell].insert(user.cell);
                        upstream[user.cell].insert(cell);
                    }
            }
        }

        struct ConeState {
            CellInfo *cell;
            int row;
            int depth;
        };
        std::vector<ConeState> seeds;
        for (auto &item : ctx->cells) {
            CellInfo *anchor = item.second.get();
            if (anchor->type != slice_type || anchor->bel == BelId())
                continue;
            auto row_attr = anchor->attrs.find(entry_row);
            if (row_attr == anchor->attrs.end())
                continue;
            const int row = int(row_attr->second.as_int64());
            std::set<NetInfo *> outputs;
            for (const char *port : {"Q", "F"}) {
                NetInfo *net = anchor->getPort(ctx->id(port));
                if (net == nullptr || !outputs.insert(net).second)
                    continue;
                for (auto &user : net->users)
                    if (user.cell != nullptr && candidates.count(user.cell))
                        seeds.push_back({user.cell, row, 1});
            }
        }
        // Typed AHB inputs such as HSIZE have their own fixed hard BELs and
        // therefore do not pass through pack_entry_anchor(). Discover them
        // generically from a unique MCU-typed BEL whose DIN/RESETN output is
        // rooted on the same witnessed X13 boundary. This covers the complete
        // typed input surface without a signal-name list or guessed row.
        int typed_seeds = 0;
        for (auto &item : ctx->cells) {
            CellInfo *source = item.second.get();
            if (source->type.str(ctx).rfind("MCU", 0) != 0)
                continue;
            BelId source_bel = source->bel;
            if (source_bel == BelId()) {
                int matches = 0;
                for (BelId bel : ctx->getBels())
                    if (ctx->getBelType(bel) == source->type) {
                        source_bel = bel;
                        ++matches;
                    }
                if (matches != 1)
                    continue;
            }
            for (const char *port_name : {"DIN", "RESETN"}) {
                IdString port = ctx->id(port_name);
                auto port_it = source->ports.find(port);
                if (port_it == source->ports.end() || port_it->second.type != PORT_OUT ||
                    port_it->second.net == nullptr)
                    continue;
                WireId source_wire = ctx->getBelPinWire(source_bel, port);
                if (source_wire == WireId())
                    continue;
                int boundary_x = -1, row = -1;
                std::string wire_name = ctx->getWireName(source_wire).str(ctx);
                if (std::sscanf(wire_name.c_str(), "X%dY%d_", &boundary_x, &row) != 2 ||
                    boundary_x != 13 || row < mcu_region_witness.min_y ||
                    row > mcu_region_witness.max_y)
                    continue;
                for (auto &user : port_it->second.net->users)
                    if (user.cell != nullptr && candidates.count(user.cell)) {
                        seeds.push_back({user.cell, row, 1});
                        ++typed_seeds;
                    }
            }
        }
        std::sort(seeds.begin(), seeds.end(), [&](const ConeState &a, const ConeState &b) {
            if (a.row != b.row)
                return a.row < b.row;
            return a.cell->name.str(ctx) < b.cell->name.str(ctx);
        });
        if (seeds.empty())
            return;
        if (typed_seeds)
            log_info("agrv2k: native MCU Regions added %d typed hard-input cone seed(s)\n",
                     typed_seeds);

        int depth_limit = 8;
        if (const char *value = std::getenv("AGRV2K_MCU_CONE_DEPTH"))
            depth_limit = std::max(1, std::atoi(value));
        std::unordered_map<CellInfo *, std::map<int, int>> row_depth;
        std::deque<ConeState> queue(seeds.begin(), seeds.end());
        while (!queue.empty()) {
            ConeState state = queue.front();
            queue.pop_front();
            if (state.depth > depth_limit)
                continue;
            auto &rows = row_depth[state.cell];
            auto old = rows.find(state.row);
            if (old != rows.end() && old->second <= state.depth)
                continue;
            rows[state.row] = state.depth;
            for (CellInfo *next : downstream[state.cell])
                queue.push_back({next, state.row, state.depth + 1});
        }

        std::set<CellInfo *> reachable;
        for (auto &item : row_depth)
            reachable.insert(item.first);
        std::vector<CellInfo *> stable_cells(reachable.begin(), reachable.end());
        std::sort(stable_cells.begin(), stable_cells.end(), [&](CellInfo *a, CellInfo *b) {
            return a->name.str(ctx) < b->name.str(ctx);
        });

        int region_index = 0, constrained_cells = 0;
        std::set<CellInfo *> assigned;
        for (CellInfo *origin : stable_cells) {
            if (assigned.count(origin))
                continue;
            std::vector<CellInfo *> component;
            std::deque<CellInfo *> component_queue;
            assigned.insert(origin);
            component_queue.push_back(origin);
            while (!component_queue.empty()) {
                CellInfo *cell = component_queue.front();
                component_queue.pop_front();
                component.push_back(cell);
                for (CellInfo *next : downstream[cell])
                    if (reachable.count(next) && assigned.insert(next).second)
                        component_queue.push_back(next);
                for (CellInfo *next : upstream[cell])
                    if (reachable.count(next) && assigned.insert(next).second)
                        component_queue.push_back(next);
            }
            std::sort(component.begin(), component.end(), [&](CellInfo *a, CellInfo *b) {
                return a->name.str(ctx) < b->name.str(ctx);
            });

            int min_row = mcu_region_witness.max_y;
            int max_row = mcu_region_witness.min_y;
            for (CellInfo *cell : component)
                for (auto &row : row_depth[cell]) {
                    min_row = std::min(min_row, row.first);
                    max_row = std::max(max_row, row.first);
                }
            min_row = std::max(mcu_region_witness.min_y, min_row);
            max_row = std::min(mcu_region_witness.max_y, max_row);
            int y0 = std::max(mcu_region_witness.min_y, min_row - 1);
            int y1 = std::max(y0, max_row);
            while (y1 - y0 + 1 < 3) {
                if (y0 > mcu_region_witness.min_y)
                    --y0;
                else if (y1 < mcu_region_witness.max_y)
                    ++y1;
                else
                    break;
            }

            // The retained 16-build ensemble reaches the architectural
            // maximum of 16 occupied slices per tile. Size a broad Region
            // from the real component cell count, then add 20% routing slack.
            // This chooses legal area, never a BEL or a predicted route.
            const int dense_tiles =
                    (int(component.size()) + mcu_region_witness.max_slices_per_tile - 1) /
                    mcu_region_witness.max_slices_per_tile;
            const int desired_tiles = dense_tiles + std::max(1, (dense_tiles + 4) / 5);
            const int height = y1 - y0 + 1;
            int width = std::max(2, (desired_tiles + height - 1) / height);
            int x0 = mcu_region_witness.min_x;
            int x1 = std::min(mcu_region_witness.max_x, x0 + width - 1);
            auto free_slice_bels = [&](int xmax) {
                int count = 0;
                for (int x = x0; x <= xmax; ++x)
                    for (int y = y0; y <= y1; ++y)
                        for (BelId bel : ctx->getBelsByTile(x, y))
                            if (ctx->getBelType(bel) == slice_type && ctx->checkBelAvail(bel))
                                ++count;
                return count;
            };
            while (free_slice_bels(x1) < int(component.size()) &&
                   x1 < mcu_region_witness.max_x)
                ++x1;
            if (free_slice_bels(x1) < int(component.size()))
                log_error("agrv2k: witnessed MCU Region X%d..%d Y%d..%d has only %d free "
                          "slice BELs for a %d-cell cone\n",
                          x0, x1, y0, y1, free_slice_bels(x1), int(component.size()));

            IdString region_name = ctx->id("AGRV2K_MCU_CONE_" + std::to_string(region_index++));
            ctx->createRectangularRegion(region_name, x0, y0, x1, y1);
            for (CellInfo *cell : component) {
                ctx->constrainCellToRegion(cell->name, region_name);
                ++constrained_cells;
            }
            log_info("agrv2k: native Region %s constrains %d-cell MCU-fed cone to "
                     "X%d..%d Y%d..%d (%d dense + routing-slack tiles)\n",
                     region_name.c_str(ctx), int(component.size()), x0, x1, y0, y1,
                     desired_tiles);
        }
        if (constrained_cells)
            log_info("agrv2k: native Region-constrained %d MCU-fed cell(s) in %d cone(s)\n",
                     constrained_cells, region_index);
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
        lock_uart_tx_corridors(ctx); // exact simultaneous hard-UART0/UART1/UART2 data/OE route to PIN_10
        lock_spi0_tx_corridors(ctx); // exact simultaneous SCK/CSN/MOSI data+OE routes
        lock_spi1_tx_corridors(ctx); // independent hard-SPI1 roots to the same L48 pad triplet
        lock_i2c_corridors(ctx); // exact SCL/SDA data+OE+input open-drain composition
        pack_clk(ctx);       // bind the clock input pad to CLKIN (else the placer may drop it on an OPAD)
        pack_bram_localize_const(ctx); // per-pin local constants for BRAM control (not the stranded global net)
        pack_bram_pin_drivers(ctx); // slot-exact dynamic BRAM ingress on the loaded gated graph
        tie_left_link_data_gnd(ctx); // exact alta_rio-style local zero; only OE needs a fabric route
        pack_output_pin_drivers(ctx); // slot-exact physical output-pad ingress on the gated graph
        pack_left_oe_quad(ctx); // four independent exact left-edge dynamic-OE trunks
        pack_left_link_inputs(ctx); // exact bidirectional-link input reduction corridors
        pack_distribution_root_bels(ctx); // source must exist before exact route-through prefixes lock
        pack_route_through_bels(ctx); // reserve exact complete-footprint sites first
        pack_entry_buffers(); // vendor-style identity buffer per lane for multi-entry LUTs
        pack_mcu_relative_clusters(ctx); // movable, conducting MCU boundary producer/consumer units
        // The anchors must perform their normal reachability checks and set
        // MCU_PINPACKED, but should choose the checkpoint's exact BELs.
        hint_replay_bels(ctx, path("placement.csv"));
        if (std::getenv("AGRV2K_REPLAY_BELS_HARD") != nullptr)
            pack_replay_bels(ctx, path("placement.csv"));
        pack_entry_anchor(); // entry cones are the scarcer resource: anchor direct MCU_DIN consumers first
        // Explicit direct-D BELs are hard architectural constraints.  Bind
        // them before generic MCU exit matching so a cell that also drives
        // HRDATA/HREADYOUT cannot be moved to an unqualified response-friendly
        // slice and rejected only by the later validity check.
        pack_direct_d_bels(ctx);
        pack_exit_anchor();  // anchor remaining MCU_DOUT drivers after a shared physical output has priority
        pack_input_pin_consumers(ctx); // slot-exact physical input-pad egress on the gated graph
        constrain_mcu_regions(); // native placer only: bounded, witnessed eastward MCU cone Regions
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
        lock_global_clock_taps(ctx); // one atomic GCLK tree, before router2 splits fanout into arcs
        lock_route_through_inputs(); // exact final edges before other corridor reservations
        lock_bram_portb_corridors(ctx); // reserve the vendor-routed mixed RF bus before router2
        lock_registered_mcu_inputs(); // registered AHB inputs own their D-pin approaches first
        // Regional placement happens inside pack(), so its hard MCU corridors
        // must be allocated here.  The analytic fallback places ordinary
        // fabric later; pre-locking corridors before that placement can seize
        // future BEL outputs and makes otherwise joint-routeable designs
        // impossible.  Leave those lanes to router2 on that bounded rung so
        // it negotiates fabric inputs and MCU exits together.
        if (std::getenv("AGRV2K_CONDPLACE") != nullptr)
            lock_mcu_dout_corridors(); // reserve simultaneous fabric-to-MCU read-data lanes
        lock_dense_mcu_local_arcs(); // after both corridor allocators: neither may rip these reservations
        // Both corridor lockers may re-anchor a cell to resolve an atomic
        // conflict.  Verify the complete checkpoint only after those moves;
        // a replay build must fail rather than silently drift from its map.
        pack_replay_bels(ctx, path("placement.csv"));
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
        if (is_carry && !dedicated_carry_pins_reachable(ci, bel, explain_invalid))
            return false;
        bool is_pinpacked = ci->attrs.count(ctx->id("AGRV2K_BRAM_PINPACKED")) != 0 ||
                            ci->attrs.count(ctx->id("AGRV2K_IO_PINPACKED")) != 0 ||
                            ci->attrs.count(ctx->id("AGRV2K_MCU_PINPACKED")) != 0;
        bool direct_d_site = loc.x == 14 && loc.y == 11 && loc.z >= 4 && loc.z <= 7;
        if (std::getenv("AGAMEMNON_DIRECT_D_X15Y8_S12_EXPERIMENT") != nullptr)
            direct_d_site = direct_d_site || (loc.x == 15 && loc.y == 8 && loc.z == 12);
        if (std::getenv("AGRV2K_DIRECT_D_X14Y11_S8_EXPERIMENT") != nullptr)
            direct_d_site = direct_d_site || (loc.x == 14 && loc.y == 11 && loc.z == 8);
        // F6 direct-D site-broadening campaign: an arbitrary-length, semicolon-
        // separated EXPERIMENTAL site list read once (nextpnr's legality check
        // runs in a hot per-cell/per-placement loop, so parse AGAMEMNON_DIRECT_D_EXTRA_SITES
        // into a static set on first use rather than getenv+split per call). Exactly
        // as unreleased as the two single-site flags above; see
        // AG32-Docs/tools/direct_d_site_campaign/PROPOSED_AGAMEMNON_PATCH.md.
        {
            static const std::unordered_set<std::string> extra_sites = [] {
                std::unordered_set<std::string> s;
                const char *raw = std::getenv("AGAMEMNON_DIRECT_D_EXTRA_SITES");
                if (raw != nullptr) {
                    std::string token;
                    std::istringstream stream((std::string(raw)));
                    while (std::getline(stream, token, ';'))
                        if (!token.empty()) s.insert(token);
                }
                return s;
            }();
            if (!extra_sites.empty())
                direct_d_site = direct_d_site || extra_sites.count(std::string(ctx->nameOfBel(bel))) != 0;
        }
        bool direct_d_cell = ci->attrs.count(ctx->id("agamemnon_direct_d_feedback")) != 0;
        // CLAIM: direct-d-four-site-pool-is-hardware-limit (agamemnon.engine.gate_claims) -- status DISPUTED:
        // The reference packed netlist uses own-Q feedback device-wide with zero site restriction and zero
        // buffering, which is evidence this four-site pool is a coverage gap rather than a hardware wall, but
        // our own board campaign to test wider sites is inconclusive (apparatus fault). See the ledger entry.
        if (direct_d_cell && !direct_d_site) {
            if (explain_invalid)
                log_info("agrv2k validity: direct-D cell '%s' at %s is outside the qualified direct-D site pool\n",
                         ctx->nameOf(ci), ctx->nameOfBel(bel));
            return false; // direct-D cells stay on the silicon-qualified site
        }
        if (!fixed_endpoint_pins_reachable(ci, bel, explain_invalid))
            return false;
        bool route_through_cell = ci->attrs.count(ctx->id("AGRV2K_ROUTE_THROUGH")) != 0;
        bool route_through_site =
                (loc.x == 14 && loc.y == 4 && (loc.z == 0 || loc.z == 5)) ||
                (loc.x == 14 && loc.y == 8 && loc.z == 8) ||
                (loc.x == 14 && loc.y == 7 && loc.z == 3);
        if (std::getenv("AGAMEMNON_BRAM_SITE_READ_PATHS") != nullptr)
            route_through_site = route_through_site ||
                    (loc.x == 14 && loc.y == 9 && loc.z == 9) ||
                    (loc.x == 14 && loc.y == 8 && loc.z == 14) ||
                    (loc.x == 14 && loc.y == 5 && (loc.z == 4 || loc.z == 7)) ||
                    (loc.x == 14 && loc.y == 4 && loc.z == 3);
        if (route_through_cell && !route_through_site) {
            if (explain_invalid)
                log_info("agrv2k validity: route-through cell '%s' at %s is outside the characterized site pool\n",
                         ctx->nameOf(ci), ctx->nameOfBel(bel));
            return false;
        }
        // EVEN-SLOT INVARIANT: the intra-tile OMUX->IMUX crossbar's only dead (zs,zd) pairs all involve
        // an ODD endpoint (chipdb/xbar_conduction.csv), so restricting NON-carry slices to even z
        // {0,2,..,14} makes every intra-tile crossbar link even->even => guaranteed to conduct.
        // CLAIM: xbar-conduction-even-slot-shape (agamemnon.engine.gate_claims) -- still live as a safe
        // sufficient condition, but the cited xbar_conduction.csv is NOT shipped in AGaMEMnon/agamemnon/chipdb/,
        // only in the AG32-Docs workbench, so this citation is not independently checkable from this repo alone.
        bool strict_allows_odd = std::getenv("AGRV2K_STRICT_ALLOW_ODD") != nullptr ||
                ci->attrs.count(ctx->id("AGRV2K_DENSE_MCU_ODD_OK")) != 0;
        if (!is_carry && !is_pinpacked && !direct_d_site &&
                !(route_through_cell && route_through_site) &&
                !strict_allows_odd && (loc.z & 1) != 0) {
            if (explain_invalid)
                log_info("agrv2k validity: ordinary cell '%s' at %s uses an unqualified odd slice\n",
                         ctx->nameOf(ci), ctx->nameOfBel(bel));
            return false;
        }

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
            if (net->driver.cell != nullptr && !reaches(net->driver.cell)) {
                if (explain_invalid)
                    log_info("agrv2k validity: cell '%s' at %s cannot conduct net '%s' from placed driver '%s'\n",
                             ctx->nameOf(ci), ctx->nameOfBel(bel), ctx->nameOf(net),
                             ctx->nameOf(net->driver.cell));
                return false;
            }
            for (auto &u : net->users)
                if (!reaches(u.cell)) {
                    if (explain_invalid)
                        log_info("agrv2k validity: cell '%s' at %s cannot conduct net '%s' to placed user '%s'\n",
                                 ctx->nameOf(ci), ctx->nameOfBel(bel), ctx->nameOf(net), ctx->nameOf(u.cell));
                    return false;
                }
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
