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
#include <mutex>
#include <queue>
#include <functional>
#include <set>
#include <memory>
#include <sstream>
#include <string>
#include <tuple>
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

// ---- tiny fail-closed CSV reader.  dev_*.csv have no multiline fields, but
// Python's csv.writer correctly quotes metadata values containing commas (for
// example AGAMEMNON_VENDOR_OUT_SLICE=14,9,4).  Honour those quoted fields and
// doubled quotes; reject every malformed quote rather than silently changing
// the column count or metadata authority. ----
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
        if (line.empty())
            return true;
        std::string cur;
        bool in_quotes = false;
        bool closed_quote = false;
        for (size_t i = 0; i < line.size(); ++i) {
            const char ch = line.at(i);
            if (in_quotes) {
                if (ch != '"') {
                    cur.push_back(ch);
                    continue;
                }
                if (i + 1 < line.size() && line.at(i + 1) == '"') {
                    cur.push_back('"');
                    ++i;
                    continue;
                }
                in_quotes = false;
                closed_quote = true;
                continue;
            }
            if (closed_quote) {
                if (ch != ',')
                    log_error("agrv2k: malformed quoted CSV field\n");
                fields.push_back(cur);
                cur.clear();
                closed_quote = false;
                continue;
            }
            if (ch == ',') {
                fields.push_back(cur);
                cur.clear();
            } else if (ch == '"') {
                if (!cur.empty())
                    log_error("agrv2k: malformed quoted CSV field\n");
                in_quotes = true;
            } else {
                cur.push_back(ch);
            }
        }
        if (in_quotes)
            log_error("agrv2k: unterminated quoted CSV field\n");
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

// A registered slice consumes the tile's one shared clock control.  The
// packed graph already provides exactly the two typed facts needed by this
// first control-set unit: FF_USED says whether physical state exists, and the
// CLK PortInfo names the driving NetInfo.  Do not infer any unrepresented
// enable, reset or load semantics here.
enum class SharedClockState
{
    INACTIVE,
    ACTIVE,
    MALFORMED_MISSING_PORT,
    MALFORMED_UNBOUND_PORT,
};

struct SharedClockRequirement
{
    SharedClockState state = SharedClockState::INACTIVE;
    const CellInfo *cell = nullptr;
    NetInfo *clock = nullptr;

    bool active() const { return state == SharedClockState::ACTIVE; }
    bool malformed() const
    {
        return state == SharedClockState::MALFORMED_MISSING_PORT ||
               state == SharedClockState::MALFORMED_UNBOUND_PORT;
    }
    const char *malformed_reason() const
    {
        NPNR_ASSERT(malformed());
        return state == SharedClockState::MALFORMED_MISSING_PORT
                       ? "missing CLK port"
                       : "CLK port has no bound net";
    }
};

static SharedClockRequirement shared_clock_requirement(Context *ctx, const CellInfo *cell)
{
    if (cell == nullptr || cell->type != ctx->id("GENERIC_SLICE") ||
        int_or_default(cell->params, ctx->id("FF_USED"), 0) == 0)
        return {SharedClockState::INACTIVE, cell, nullptr};
    auto clock = cell->ports.find(ctx->id("CLK"));
    if (clock == cell->ports.end())
        return {SharedClockState::MALFORMED_MISSING_PORT, cell, nullptr};
    if (clock->second.net == nullptr)
        return {SharedClockState::MALFORMED_UNBOUND_PORT, cell, nullptr};
    return {SharedClockState::ACTIVE, cell, clock->second.net};
}

static bool shared_clock_requirements_compatible(const SharedClockRequirement &a,
                                                 const SharedClockRequirement &b)
{
    NPNR_ASSERT(!a.malformed() && !b.malformed());
    return !a.active() || !b.active() || a.clock == b.clock;
}

static void require_cluster_shared_clock_compatibility(
        Context *ctx, const std::vector<std::pair<CellInfo *, Loc>> &members)
{
    std::map<std::pair<int, int>, SharedClockRequirement> per_tile;
    for (const auto &member : members) {
        SharedClockRequirement requirement = shared_clock_requirement(ctx, member.first);
        if (requirement.malformed())
            log_error("agrv2k: relative cluster rejects malformed active registered slice "
                      "'%s' at tile offset X%dY%d: %s\n",
                      ctx->nameOf(requirement.cell), member.second.x, member.second.y,
                      requirement.malformed_reason());
        if (!requirement.active())
            continue;
        const std::pair<int, int> tile{member.second.x, member.second.y};
        auto prior = per_tile.find(tile);
        if (prior == per_tile.end()) {
            per_tile.emplace(tile, requirement);
            continue;
        }
        if (!shared_clock_requirements_compatible(prior->second, requirement))
            log_error("agrv2k: relative cluster has incompatible shared CLOCK requirements "
                      "at tile offset X%dY%d: '%s' uses net '%s', while '%s' uses net '%s'\n",
                      tile.first, tile.second, ctx->nameOf(prior->second.cell),
                      ctx->nameOf(prior->second.clock), ctx->nameOf(requirement.cell),
                      ctx->nameOf(requirement.clock));
    }
}

// N4.1 preserves one exact frontend control oracle but intentionally admits
// no active physical shared control.  Keep mode, polarity, reset value, and
// bound control net together so later graph work cannot accidentally infer
// one fact from a cell name or a generic data port.
static const IdString shared_control_mode_attr(Context *ctx)
{
    return ctx->id("AGRV2K_SHARED_CONTROL_MODE");
}

enum class SharedControlMode
{
    NONE,
    ASYNC_CLEAR_POS_ZERO,
    UNKNOWN,
    MALFORMED,
};

static constexpr const char *SHARED_CONTROL_MODE_TOKENS[] = {
        "NONE",
        "ASYNC_CLEAR_POS_ZERO",
        "UNKNOWN",
        "MALFORMED",
};

static constexpr const char *SHARED_CONTROL_PORT_TOKENS[] = {
        "ARST", "R", "ASET", "SET", "CE", "EN", "SRST", "SCLR",
        "SLOAD", "ALOAD",
};

enum class SharedControlPolarity
{
    INACTIVE,
    POSITIVE,
};

struct SharedControlRequirement
{
    SharedControlMode mode = SharedControlMode::NONE;
    SharedControlPolarity polarity = SharedControlPolarity::INACTIVE;
    int clear_value = -1;
    NetInfo *control = nullptr;
    std::string error;

    bool active() const { return mode == SharedControlMode::ASYNC_CLEAR_POS_ZERO; }
    bool malformed() const { return !error.empty(); }
};

static SharedControlMode parse_shared_control_mode(const std::string &token)
{
    for (int i = 0; i < int(sizeof(SHARED_CONTROL_MODE_TOKENS) /
                            sizeof(SHARED_CONTROL_MODE_TOKENS[0])); ++i)
        if (token == SHARED_CONTROL_MODE_TOKENS[i])
            return SharedControlMode(i);
    return SharedControlMode::UNKNOWN;
}

static bool string_starts_with(const std::string &value, const char *prefix)
{
    return value.rfind(prefix, 0) == 0;
}

static SharedControlRequirement shared_control_requirement(Context *ctx,
                                                           const CellInfo *cell)
{
    SharedControlRequirement result;
    if (cell == nullptr)
        return result;

    const std::string cell_type = cell->type.str(ctx);
    const bool generic_slice = cell->type == ctx->id("GENERIC_SLICE");
    const bool raw_async_clear = cell_type == "$_DFF_PP0_";
    const bool frontend_register = raw_async_clear || cell->type == ctx->id("DFF");
    if (!generic_slice && !frontend_register)
        return result;

    auto mode_it = cell->attrs.find(shared_control_mode_attr(ctx));
    if (mode_it != cell->attrs.end()) {
        result.mode = parse_shared_control_mode(mode_it->second.as_string());
        if (result.mode == SharedControlMode::UNKNOWN) {
            result.error = "unknown AGRV2K_SHARED_CONTROL_MODE token '" +
                           mode_it->second.as_string() + "'";
            return result;
        }
        if (result.mode == SharedControlMode::MALFORMED) {
            result.error = "explicit MALFORMED AGRV2K_SHARED_CONTROL_MODE";
            return result;
        }
    }

    const char *expected_port = raw_async_clear ? "R" : "ARST";
    auto reject = [&](const std::string &reason) { result.error = reason; };

    if (result.mode == SharedControlMode::NONE) {
        for (const char *port : SHARED_CONTROL_PORT_TOKENS)
            if (cell->ports.count(ctx->id(port)) != 0) {
                reject(std::string("NONE attribute disagrees with present ") + port +
                       " control port");
                return result;
            }
        return result;
    }

    if (!generic_slice && !raw_async_clear) {
        reject("ASYNC_CLEAR_POS_ZERO requires exact $_DFF_PP0_ frontend form "
               "or a packed GENERIC_SLICE");
        return result;
    }
    if (generic_slice) {
        auto ff_it = cell->params.find(ctx->id("FF_USED"));
        if (ff_it == cell->params.end()) {
            reject("ASYNC_CLEAR_POS_ZERO requires FF_USED=1 (parameter missing)");
            return result;
        }
        if (int(ff_it->second.as_int64()) != 1) {
            reject("ASYNC_CLEAR_POS_ZERO requires FF_USED=1");
            return result;
        }
    }
    for (const char *port : SHARED_CONTROL_PORT_TOKENS)
        if (std::string(port) != expected_port &&
            cell->ports.count(ctx->id(port)) != 0) {
            reject(std::string("unsupported or combined control port ") + port);
            return result;
        }
    auto control_it = cell->ports.find(ctx->id(expected_port));
    if (control_it == cell->ports.end()) {
        reject(std::string("ASYNC_CLEAR_POS_ZERO requires a ") + expected_port +
               " control port");
        return result;
    }
    if (control_it->second.net == nullptr) {
        reject(std::string(expected_port) + " control port has no bound net");
        return result;
    }
    result.polarity = SharedControlPolarity::POSITIVE;
    result.clear_value = 0;
    result.control = control_it->second.net;
    return result;
}

static const char *unsupported_shared_control_diagnostic()
{
    return "unsupported physical shared control ASYNC_CLEAR_POS_ZERO "
           "(positive polarity, clear value 0): control graph, selector codewords, "
           "and HIL qualification are absent";
}

static bool shared_control_cell_admitted(Context *ctx, const CellInfo *cell,
                                         BelId bel, bool explain_invalid)
{
    const SharedControlRequirement requirement = shared_control_requirement(ctx, cell);
    if (requirement.malformed()) {
        if (explain_invalid)
            log_info("agrv2k validity: shared-control cell '%s' at %s is malformed: %s\n",
                     ctx->nameOf(cell), ctx->nameOfBel(bel), requirement.error.c_str());
        return false;
    }
    if (!requirement.active())
        return true;
    if (explain_invalid)
        log_info("agrv2k validity: cell '%s' at %s has %s\n", ctx->nameOf(cell),
                 ctx->nameOfBel(bel), unsupported_shared_control_diagnostic());
    return false;
}

static void reject_unsupported_shared_control_ingress(Context *ctx)
{
    for (auto &entry : ctx->cells) {
        CellInfo *cell = entry.second.get();
        const std::string type = cell->type.str(ctx);
        const bool internal_ff = string_starts_with(type, "$_DFF") ||
                                 string_starts_with(type, "$_SDFF") ||
                                 string_starts_with(type, "$_ALDFF");
        if (internal_ff && type != "$_DFF_PP0_")
            log_error("agrv2k: shared-control ingress rejects unsupported frontend "
                      "register type '%s' on '%s'; expected mapped DFF or exact $_DFF_PP0_\n",
                      type.c_str(), ctx->nameOf(cell));
        if (type != "$_DFF_PP0_" && cell->type != ctx->id("DFF"))
            continue;
        const SharedControlRequirement requirement =
                shared_control_requirement(ctx, cell);
        if (requirement.malformed())
            log_error("agrv2k: shared-control ingress rejects malformed register '%s': %s\n",
                      ctx->nameOf(cell), requirement.error.c_str());
        if (requirement.active())
            log_error("agrv2k: shared-control ingress rejects register '%s': %s; "
                      "refusing packing and ordinary placement/router admission\n",
                      ctx->nameOf(cell), unsupported_shared_control_diagnostic());
    }
}

static void reject_unbound_shared_controls_before_placement(Context *ctx)
{
    for (auto &entry : ctx->cells) {
        CellInfo *cell = entry.second.get();
        if (cell->type != ctx->id("GENERIC_SLICE") || cell->bel != BelId() ||
            cell->cluster != ClusterId())
            continue;
        const SharedControlRequirement requirement =
                shared_control_requirement(ctx, cell);
        if (requirement.malformed())
            log_error("agrv2k: pre-placement shared-control DRC rejects malformed "
                      "unbound slice '%s': %s\n",
                      ctx->nameOf(cell), requirement.error.c_str());
        if (requirement.active())
            log_error("agrv2k: pre-placement shared-control DRC rejects unbound slice "
                      "'%s': %s\n", ctx->nameOf(cell),
                      unsupported_shared_control_diagnostic());
    }
}

// A fabric cell presented at an already-fixed ordinary IOB carries an explicit
// endpoint mode instead of a pack-time slice BEL.  The netlist shape supplies
// the exact slice port and IOB direction; the admitted graph is therefore the
// complete hard placement predicate.  Keep this protocol separate from
// AGRV2K_IO_PINPACKED, which remains the compatibility marker for retained
// exact input permutation, registered/synchronizer roots, left-pad, and
// qualified-corridor placements.
static const IdString native_endpoint_mode_attr(Context *ctx)
{
    return ctx->id("AGRV2K_NATIVE_ENDPOINT_MODE");
}

enum class NativeEndpointMode
{
    NONE,
    IOB_OUTPUT,
    IOB_INPUT,
    UNKNOWN,
    MALFORMED,
};

static constexpr const char *NATIVE_ENDPOINT_MODE_TOKENS[] = {
        "NONE",
        "IOB_OUTPUT",
        "IOB_INPUT",
        "UNKNOWN",
        "MALFORMED",
};

static const char *native_endpoint_mode_name(NativeEndpointMode mode)
{
    return NATIVE_ENDPOINT_MODE_TOKENS[int(mode)];
}

static NativeEndpointMode parse_native_endpoint_mode(const std::string &token)
{
    for (int i = 0; i < int(sizeof(NATIVE_ENDPOINT_MODE_TOKENS) /
                            sizeof(NATIVE_ENDPOINT_MODE_TOKENS[0])); ++i)
        if (token == NATIVE_ENDPOINT_MODE_TOKENS[i])
            return NativeEndpointMode(i);
    return NativeEndpointMode::UNKNOWN;
}

static void set_native_endpoint_mode(Context *ctx, CellInfo *cell,
                                     NativeEndpointMode mode)
{
    cell->attrs[native_endpoint_mode_attr(ctx)] =
            Property(native_endpoint_mode_name(mode));
}

struct NativeEndpointRequirement
{
    NativeEndpointMode mode = NativeEndpointMode::NONE;
    int fixed_output_endpoints = 0;
    int fixed_input_endpoints = 0;
    std::string error;

    bool active() const
    {
        return mode == NativeEndpointMode::IOB_OUTPUT ||
               mode == NativeEndpointMode::IOB_INPUT;
    }
    bool allows_odd_slice() const { return mode == NativeEndpointMode::IOB_OUTPUT; }
    bool malformed() const { return !error.empty(); }
};

// The multi-pad splitter below creates one deliberately tiny identity LUT per
// fixed input pad.  The marker is emitted into routed JSON, so it is not a
// trust boundary by itself: both the placer and bitstream emitter must prove
// the complete generated shape before granting native placement freedom.
static std::string pad_input_identity_shape_error(Context *ctx,
                                                  const CellInfo *cell)
{
    auto marker = cell->attrs.find(ctx->id("AGRV2K_PAD_INPUT_IDENTITY"));
    if (marker == cell->attrs.end())
        return "missing AGRV2K_PAD_INPUT_IDENTITY marker";
    if (marker->second.is_string || marker->second.as_int64() != 1)
        return "AGRV2K_PAD_INPUT_IDENTITY marker is not numeric 1";
    if (cell->type != ctx->id("GENERIC_SLICE"))
        return "pad identity requires a GENERIC_SLICE cell";
    auto init = cell->params.find(ctx->id("INIT"));
    if (init == cell->params.end() || init->second.is_string ||
        uint64_t(init->second.as_int64()) != 0xaaaa)
        return "pad identity requires exact INIT=0xAAAA";
    auto k = cell->params.find(ctx->id("K"));
    if (k == cell->params.end() || k->second.is_string ||
        int(k->second.as_int64()) != 4)
        return "pad identity requires exact K=4";
    auto ff = cell->params.find(ctx->id("FF_USED"));
    if (ff == cell->params.end() || ff->second.is_string ||
        int(ff->second.as_int64()) != 0)
        return "pad identity requires explicit FF_USED=0";

    auto connected_port = [&](const char *name, PortType type) -> NetInfo * {
        auto port = cell->ports.find(ctx->id(name));
        if (port == cell->ports.end() || port->second.type != type)
            return nullptr;
        return port->second.net;
    };
    NetInfo *input = connected_port("I[0]", PORT_IN);
    NetInfo *output = connected_port("F", PORT_OUT);
    auto q = cell->ports.find(ctx->id("Q"));
    if (input == nullptr)
        return "pad identity requires exactly one live I[0] input";
    for (int i = 1; i < 4; ++i) {
        auto port = cell->ports.find(ctx->id("I[" + std::to_string(i) + "]"));
        if (port == cell->ports.end() || port->second.type != PORT_IN ||
            port->second.net != nullptr)
            return "pad identity requires I[1:3] disconnected";
    }
    if (output == nullptr)
        return "pad identity requires a live F output";
    if (q != cell->ports.end() &&
        (q->second.type != PORT_OUT || q->second.net != nullptr))
        return "pad identity requires Q disconnected";
    if (cell->ports.count(ctx->id("CIN")) ||
        cell->ports.count(ctx->id("COUT")))
        return "pad identity cannot carry dedicated carry ports";
    for (auto &port : cell->ports) {
        if (port.second.net == nullptr || port.first == ctx->id("I[0]") ||
            port.first == ctx->id("F"))
            continue;
        return "pad identity has an unexpected live port '" +
               port.first.str(ctx) + "'";
    }

    CellInfo *driver = input->driver.cell;
    if (driver == nullptr || driver->type != ctx->id("GENERIC_IOB") ||
        driver->bel == BelId() || input->driver.port != ctx->id("O"))
        return "pad identity I[0] requires one genuine fixed GENERIC_IOB.O endpoint";
    auto driver_port = driver->ports.find(ctx->id("O"));
    if (driver_port == driver->ports.end() || driver_port->second.type != PORT_OUT)
        return "pad identity I[0] endpoint port O is not declared output";
    int fixed_inputs = 0;
    for (auto &port : cell->ports) {
        if (port.second.type != PORT_IN || port.second.net == nullptr)
            continue;
        CellInfo *source = port.second.net->driver.cell;
        if (source != nullptr && source->type == ctx->id("GENERIC_IOB") &&
            source->bel != BelId())
            ++fixed_inputs;
    }
    if (fixed_inputs != 1)
        return "pad identity requires exactly one fixed GENERIC_IOB.O endpoint";

    bool ordinary_fabric_consumer = false;
    for (auto &user : output->users) {
        if (user.cell == nullptr || user.cell == cell ||
            user.cell->type != ctx->id("GENERIC_SLICE"))
            return "pad identity F may drive only ordinary fabric consumers";
        auto user_port = user.cell->ports.find(user.port);
        if (user_port == user.cell->ports.end() || user_port->second.type != PORT_IN)
            return "pad identity F consumer port is not declared input";
        ordinary_fabric_consumer = true;
    }
    if (!ordinary_fabric_consumer)
        return "pad identity F requires at least one ordinary fabric consumer";

    for (const char *attribute : {
             "agamemnon_pad_sync_stage", "agamemnon_pad_sync_group",
             "agamemnon_direct_d_feedback", "AGRV2K_ROUTE_THROUGH",
             "AGRV2K_IO_PINPACKED", "AGRV2K_BRAM_PINPACKED",
             "AGRV2K_MCU_PINPACKED", "NEXTPNR_CLUSTER"})
        if (cell->attrs.count(ctx->id(attribute)))
            return std::string("pad identity cannot carry special attribute '") +
                   attribute + "'";
    auto register_mode = cell->attrs.find(ctx->id("AGRV2K_REGISTER_INPUT_MODE"));
    if (register_mode != cell->attrs.end() &&
        (!register_mode->second.is_string ||
         register_mode->second.as_string() != "NONE"))
        return "pad identity requires AGRV2K_REGISTER_INPUT_MODE=NONE";
    if (cell->cluster != ClusterId() || !cell->constr_children.empty())
        return "pad identity cannot participate in a relative cluster";
    return "";
}

static NativeEndpointRequirement native_endpoint_requirement(Context *ctx,
                                                              const CellInfo *cell)
{
    NativeEndpointRequirement result;
    if (cell == nullptr)
        return result;
    auto mode_it = cell->attrs.find(native_endpoint_mode_attr(ctx));
    if (mode_it == cell->attrs.end())
        return result;
    result.mode = parse_native_endpoint_mode(mode_it->second.as_string());
    if (result.mode == NativeEndpointMode::UNKNOWN) {
        result.error = "unknown AGRV2K_NATIVE_ENDPOINT_MODE token '" +
                       mode_it->second.as_string() + "'";
        return result;
    }
    if (result.mode == NativeEndpointMode::MALFORMED) {
        result.error = "explicit MALFORMED AGRV2K_NATIVE_ENDPOINT_MODE";
        return result;
    }
    if (cell->type != ctx->id("GENERIC_SLICE")) {
        result.error = "AGRV2K_NATIVE_ENDPOINT_MODE requires a GENERIC_SLICE cell";
        return result;
    }
    for (auto &port : cell->ports) {
        if (port.second.net == nullptr)
            continue;
        if (port.second.type == PORT_OUT) {
            for (auto &user : port.second.net->users) {
                if (user.cell == nullptr || user.cell->type != ctx->id("GENERIC_IOB"))
                    continue;
                auto endpoint_port = user.cell->ports.find(user.port);
                if (user.cell->bel == BelId() || user.port != ctx->id("I") ||
                    endpoint_port == user.cell->ports.end() ||
                    endpoint_port->second.type != PORT_IN) {
                    result.error = "fixed GENERIC_IOB output endpoint has a malformed mixed "
                                   "type/placement/port claim";
                    return result;
                }
                ++result.fixed_output_endpoints;
            }
        } else if (port.second.type == PORT_IN) {
            CellInfo *driver = port.second.net->driver.cell;
            if (driver == nullptr || driver->type != ctx->id("GENERIC_IOB"))
                continue;
            auto endpoint_port = driver->ports.find(port.second.net->driver.port);
            if (driver->bel == BelId() ||
                port.second.net->driver.port != ctx->id("O") ||
                endpoint_port == driver->ports.end() ||
                endpoint_port->second.type != PORT_OUT) {
                result.error = "fixed GENERIC_IOB input endpoint has a malformed mixed "
                               "type/placement/port claim";
                return result;
            }
            ++result.fixed_input_endpoints;
        }
    }
    if (result.mode == NativeEndpointMode::NONE) {
        if (result.fixed_output_endpoints != 0 || result.fixed_input_endpoints != 0)
            result.error = "NONE attribute disagrees with a fixed GENERIC_IOB endpoint shape";
        return result;
    }
    if (result.mode == NativeEndpointMode::IOB_OUTPUT) {
        if (result.fixed_output_endpoints == 0)
            result.error = "IOB_OUTPUT requires a connected, fixed GENERIC_IOB.I endpoint";
        return result;
    }
    if (result.fixed_input_endpoints == 0) {
        result.error = "IOB_INPUT requires a connected, fixed GENERIC_IOB.O endpoint";
        return result;
    }
    if (result.fixed_output_endpoints != 0) {
        result.error = "IOB_INPUT cannot also claim a GENERIC_IOB.I output endpoint";
        return result;
    }
    auto ff_it = cell->params.find(ctx->id("FF_USED"));
    if (ff_it == cell->params.end() || int(ff_it->second.as_int64()) != 0)
        result.error = "IOB_INPUT requires an explicit combinational FF_USED=0 slice";
    else if (cell->attrs.count(ctx->id("agamemnon_pad_sync_stage")) ||
             cell->attrs.count(ctx->id("agamemnon_pad_sync_group")))
        result.error = "IOB_INPUT cannot claim a synchronizer root";
    else if (cell->attrs.count(ctx->id("AGRV2K_PAD_INPUT_IDENTITY")))
        result.error = pad_input_identity_shape_error(ctx, cell);
    return result;
}

static bool native_endpoint_cell_admitted(Context *ctx, const CellInfo *cell,
                                          BelId bel, bool explain_invalid)
{
    const NativeEndpointRequirement requirement =
            native_endpoint_requirement(ctx, cell);
    if (requirement.malformed()) {
        if (explain_invalid)
            log_info("agrv2k validity: native endpoint for '%s' at %s is malformed: %s\n",
                     ctx->nameOf(cell), ctx->nameOfBel(bel),
                     requirement.error.c_str());
        return false;
    }
    if (!requirement.active())
        return true;
    if (ctx->getBelType(bel) != ctx->id("GENERIC_SLICE")) {
        if (explain_invalid)
            log_info("agrv2k validity: native endpoint cell '%s' requires a GENERIC_SLICE BEL, "
                     "not %s\n", ctx->nameOf(cell), ctx->nameOfBel(bel));
        return false;
    }
    if (cell->attrs.count(ctx->id("AGRV2K_PAD_INPUT_IDENTITY"))) {
        const Loc loc = ctx->getBelLocation(bel);
        if (loc.z == 0 || (loc.z & 1) != 0 ||
            (loc.x == 1 && loc.y == 4 && loc.z == 4)) {
            if (explain_invalid)
                log_info("agrv2k validity: pad identity '%s' at %s requires a "
                         "nonzero even slice other than X1Y4_SLICE4\n",
                         ctx->nameOf(cell), ctx->nameOfBel(bel));
            return false;
        }
    }
    return true;
}

static void reject_malformed_native_endpoints_before_placement(Context *ctx)
{
    for (auto &entry : ctx->cells) {
        CellInfo *cell = entry.second.get();
        if (cell->bel != BelId())
            continue;
        const NativeEndpointRequirement requirement =
                native_endpoint_requirement(ctx, cell);
        if (requirement.malformed())
            log_error("agrv2k: pre-placement native-endpoint DRC rejects '%s': %s\n",
                      ctx->nameOf(cell), requirement.error.c_str());
    }
}

// N5.8A admits exactly one rename-invariant MCU-to-fabric semantic identity.
// Physical resource authority remains in mcu_endpoint_capabilities.csv; these
// four attributes are the complete design-side intent protocol.  Seeing only
// part of it, or any tuple other than HWDATA25 v1 direct input, is malformed.
static const IdString mcu_endpoint_interface_attr(Context *ctx)
{
    return ctx->id("AGRV2K_MCU_ENDPOINT_INTERFACE");
}
static const IdString mcu_endpoint_lane_attr(Context *ctx)
{
    return ctx->id("AGRV2K_MCU_ENDPOINT_LANE");
}
static const IdString mcu_endpoint_mode_attr(Context *ctx)
{
    return ctx->id("AGRV2K_MCU_ENDPOINT_MODE");
}
static const IdString mcu_endpoint_version_attr(Context *ctx)
{
    return ctx->id("AGRV2K_MCU_ENDPOINT_VERSION");
}

struct McuEndpointIntent
{
    bool present = false;
    bool active = false;
    std::string interface;
    std::string mode;
    int lane = -1;
    int version = -1;
    NetInfo *net = nullptr;
    std::string error;

    bool malformed() const { return !error.empty(); }
};

static McuEndpointIntent mcu_endpoint_intent(Context *ctx, const CellInfo *cell)
{
    McuEndpointIntent result;
    if (cell == nullptr)
        return result;
    const IdString attrs[] = {
        mcu_endpoint_interface_attr(ctx), mcu_endpoint_lane_attr(ctx),
        mcu_endpoint_mode_attr(ctx), mcu_endpoint_version_attr(ctx),
    };
    int present = 0;
    for (IdString attr : attrs)
        present += cell->attrs.count(attr) != 0;
    if (present == 0)
        return result;
    result.present = true;
    if (present != 4) {
        result.error = "partial typed MCU endpoint intent metadata";
        return result;
    }
    auto interface = cell->attrs.find(attrs[0]);
    auto lane = cell->attrs.find(attrs[1]);
    auto mode = cell->attrs.find(attrs[2]);
    auto version = cell->attrs.find(attrs[3]);
    if (!interface->second.is_string || lane->second.is_string ||
        !mode->second.is_string || version->second.is_string) {
        result.error = "typed MCU endpoint intent has malformed field types";
        return result;
    }
    result.interface = interface->second.as_string();
    result.lane = int(lane->second.as_int64());
    result.mode = mode->second.as_string();
    result.version = int(version->second.as_int64());
    if (result.interface != "HWDATA" || result.lane != 25 ||
        result.mode != "DIRECT_FABRIC_INPUT" || result.version != 1) {
        result.error = "typed MCU endpoint tuple has no exact capability; "
                       "HWDATA24/26 and other lanes are not generalized";
        return result;
    }
    if (cell->type != ctx->id("MCU_DIN")) {
        result.error = "typed HWDATA25 endpoint requires an MCU_DIN cell";
        return result;
    }
    auto port = cell->ports.find(ctx->id("DIN"));
    if (port == cell->ports.end() || port->second.type != PORT_OUT) {
        result.error = "typed HWDATA25 endpoint requires output port DIN";
        return result;
    }
    result.net = port->second.net;
    if (result.net == nullptr)
        return result; // kept but unused boundary cell; no route authority
    int users = 0;
    for (auto &user : result.net->users)
        if (user.cell != nullptr) {
            ++users;
            if (user.cell->type != ctx->id("GENERIC_SLICE")) {
                result.error = "typed HWDATA25 endpoint drives a non-slice consumer";
                return result;
            }
            auto sink_port = user.cell->ports.find(user.port);
            if (sink_port == user.cell->ports.end() ||
                sink_port->second.type != PORT_IN ||
                user.port.str(ctx).rfind("I[", 0) != 0) {
                result.error = "typed HWDATA25 endpoint requires ordinary slice I[n] sinks";
                return result;
            }
        }
    result.active = users != 0;
    return result;
}

struct McuEndpointRequirement
{
    bool active = false;
    CellInfo *endpoint = nullptr;
    NetInfo *net = nullptr;
    std::vector<IdString> input_ports;
    std::string error;

    bool malformed() const { return !error.empty(); }
};

// Derive a consumer requirement exclusively from the connected typed hard
// endpoint.  Cell names, hierarchy tokens, and legacy MCU footprint tokens
// have no authority in this path.
static McuEndpointRequirement mcu_endpoint_requirement(Context *ctx,
                                                       const CellInfo *cell)
{
    McuEndpointRequirement result;
    if (cell == nullptr)
        return result;
    for (auto &port : cell->ports) {
        if (port.second.type != PORT_IN || port.second.net == nullptr ||
            port.second.net->driver.cell == nullptr)
            continue;
        CellInfo *driver = port.second.net->driver.cell;
        McuEndpointIntent intent = mcu_endpoint_intent(ctx, driver);
        if (!intent.present)
            continue;
        if (intent.malformed()) {
            result.error = "connected typed endpoint is malformed: " + intent.error;
            return result;
        }
        if (!intent.active)
            continue;
        if (port.second.net->driver.port != ctx->id("DIN")) {
            result.error = "typed endpoint signal is not driven through MCU_DIN.DIN";
            return result;
        }
        if (result.endpoint != nullptr && result.endpoint != driver) {
            result.error = "consumer has conflicting typed MCU endpoints";
            return result;
        }
        result.endpoint = driver;
        result.net = port.second.net;
        result.input_ports.push_back(port.first);
    }
    result.active = result.endpoint != nullptr;
    if (result.active && cell->type != ctx->id("GENERIC_SLICE"))
        result.error = "typed HWDATA25 consumer is not a GENERIC_SLICE";
    if (result.active && result.input_ports.empty())
        result.error = "typed HWDATA25 consumer has no slice input pin";
    return result;
}

// A packed registered slice carries one explicit semantic description of the
// physical path feeding its FF.  This attribute is written into routed JSON,
// so the placer DRC and strict Python emitter validate the same fact rather
// than guessing from cell names or a site allowlist.
static const IdString register_input_mode_attr(Context *ctx)
{
    return ctx->id("AGRV2K_REGISTER_INPUT_MODE");
}

enum class RegisterInputMode
{
    NONE,
    LUT_COMPUTE_TO_FF,
    LUT_FEEDTHROUGH_I0,
    REGISTERED_PAD_I3,
    DIRECT_D_I3,
    CARRY_SUM_TO_FF,
    UNKNOWN,
    MALFORMED,
};

// Keep every protocol spelling in this one table.  Python's conformance test
// reads this table and compares it with its strict-emitter token set.
static constexpr const char *REGISTER_INPUT_MODE_TOKENS[] = {
        "NONE",
        "LUT_COMPUTE_TO_FF",
        "LUT_FEEDTHROUGH_I0",
        "REGISTERED_PAD_I3",
        "DIRECT_D_I3",
        "CARRY_SUM_TO_FF",
        "UNKNOWN",
        "MALFORMED",
};

static const char *register_input_mode_name(RegisterInputMode mode)
{
    return REGISTER_INPUT_MODE_TOKENS[int(mode)];
}

static RegisterInputMode parse_register_input_mode(const std::string &token)
{
    for (int i = 0; i < int(sizeof(REGISTER_INPUT_MODE_TOKENS) /
                            sizeof(REGISTER_INPUT_MODE_TOKENS[0])); ++i)
        if (token == REGISTER_INPUT_MODE_TOKENS[i])
            return RegisterInputMode(i);
    return RegisterInputMode::UNKNOWN;
}

static void set_register_input_mode(Context *ctx, CellInfo *cell, RegisterInputMode mode)
{
    cell->attrs[register_input_mode_attr(ctx)] = Property(register_input_mode_name(mode));
}

static bool port_has_net(Context *ctx, const CellInfo *cell, const std::string &port)
{
    auto found = cell->ports.find(ctx->id(port));
    return found != cell->ports.end() && found->second.net != nullptr;
}

static bool init_depends_on(uint64_t init, int input)
{
    for (int row = 0; row < 16; ++row) {
        if ((row & (1 << input)) != 0)
            continue;
        if (((init >> row) & 1) != ((init >> (row | (1 << input))) & 1))
            return true;
    }
    return false;
}

static bool direct_d_q_is_local_only(Context *ctx, const CellInfo *cell)
{
    auto q_port = cell->ports.find(ctx->id("Q"));
    if (q_port == cell->ports.end() || q_port->second.net == nullptr ||
        q_port->second.type != PORT_OUT)
        return false;
    NetInfo *q = q_port->second.net;
    if (q->driver.cell != cell || q->driver.port != ctx->id("Q") ||
        q->users.entries() != 1)
        return false;
    for (auto &user : q->users)
        return user.cell == cell && user.port == ctx->id("I[3]");
    return false;
}

struct RegisterInputRequirement
{
    RegisterInputMode mode = RegisterInputMode::UNKNOWN;
    std::string error;

    bool malformed() const { return !error.empty(); }
};

static RegisterInputRequirement register_input_requirement(Context *ctx, const CellInfo *cell)
{
    RegisterInputRequirement result;
    if (cell == nullptr || cell->type != ctx->id("GENERIC_SLICE")) {
        result.mode = RegisterInputMode::NONE;
        return result;
    }

    auto ff_it = cell->params.find(ctx->id("FF_USED"));
    auto init_it = cell->params.find(ctx->id("INIT"));
    if (ff_it == cell->params.end()) {
        result.error = "missing FF_USED parameter";
        result.mode = RegisterInputMode::MALFORMED;
        return result;
    }
    const int ff_used = int(ff_it->second.as_int64());
    if (ff_used != 0 && ff_used != 1) {
        result.error = "FF_USED is neither 0 nor 1";
        result.mode = RegisterInputMode::MALFORMED;
        return result;
    }
    if (init_it == cell->params.end()) {
        result.error = "missing INIT parameter";
        result.mode = RegisterInputMode::MALFORMED;
        return result;
    }
    const uint64_t init = uint64_t(init_it->second.as_int64()) & 0xffff;
    const bool tagged_pad = cell->attrs.count(ctx->id("agamemnon_registered_pad_input")) != 0;
    const bool tagged_direct = cell->attrs.count(ctx->id("agamemnon_direct_d_feedback")) != 0;
    const bool carry_shape = cell->ports.count(ctx->id("CIN")) != 0 ||
                             cell->ports.count(ctx->id("COUT")) != 0;
    const int special_shapes = int(tagged_pad) + int(tagged_direct) + int(carry_shape);
    if (special_shapes > 1) {
        result.error = "conflicting registered-pad, direct-D, and carry shapes";
        result.mode = RegisterInputMode::MALFORMED;
        return result;
    }

    auto mode_it = cell->attrs.find(register_input_mode_attr(ctx));
    const bool legacy_derived = mode_it == cell->attrs.end();
    if (mode_it != cell->attrs.end()) {
        result.mode = parse_register_input_mode(mode_it->second.as_string());
        if (result.mode == RegisterInputMode::UNKNOWN) {
            result.error = "unknown AGRV2K_REGISTER_INPUT_MODE token '" +
                           mode_it->second.as_string() + "'";
            return result;
        }
        if (result.mode == RegisterInputMode::MALFORMED) {
            result.error = "explicit MALFORMED AGRV2K_REGISTER_INPUT_MODE";
            return result;
        }
    } else if (ff_used == 0) {
        // Retained routed artifacts predate the semantic attribute.  Only
        // derive a legacy mode from a shape that is physically unambiguous.
        result.mode = RegisterInputMode::NONE;
    } else if (tagged_pad) {
        result.mode = RegisterInputMode::REGISTERED_PAD_I3;
    } else if (tagged_direct) {
        result.mode = RegisterInputMode::DIRECT_D_I3;
    } else if (carry_shape) {
        result.mode = RegisterInputMode::CARRY_SUM_TO_FF;
    } else if (init == 0xaaaa && port_has_net(ctx, cell, "I[0]") &&
               !port_has_net(ctx, cell, "I[1]") && !port_has_net(ctx, cell, "I[2]") &&
               !port_has_net(ctx, cell, "I[3]")) {
        result.mode = RegisterInputMode::LUT_FEEDTHROUGH_I0;
    } else {
        result.mode = RegisterInputMode::LUT_COMPUTE_TO_FF;
    }

    auto reject = [&](const std::string &reason) {
        result.error = std::string(register_input_mode_name(result.mode)) + ": " + reason;
    };
    const bool has_clk = port_has_net(ctx, cell, "CLK");
    const bool has_q = port_has_net(ctx, cell, "Q");
    const bool has_f = port_has_net(ctx, cell, "F");
    if (result.mode == RegisterInputMode::NONE) {
        if (ff_used != 0)
            reject("requires FF_USED=0");
        else if (tagged_pad || tagged_direct)
            reject("special registered tag requires an active FF mode");
        return result;
    }
    if (result.mode == RegisterInputMode::UNKNOWN) {
        reject("explicit UNKNOWN mode is fail-closed");
        return result;
    }
    if (ff_used != 1) {
        reject("requires FF_USED=1");
        return result;
    }
    if (!has_clk || !has_q) {
        reject("requires connected CLK/Q");
        return result;
    }
    if (has_f && result.mode != RegisterInputMode::DIRECT_D_I3 &&
        result.mode != RegisterInputMode::LUT_COMPUTE_TO_FF) {
        reject("requires unused F");
        return result;
    }

    if (result.mode == RegisterInputMode::LUT_FEEDTHROUGH_I0) {
        if (init != 0xaaaa)
            reject("requires INIT=0xAAAA");
        else if (!port_has_net(ctx, cell, "I[0]") || port_has_net(ctx, cell, "I[1]") ||
                 port_has_net(ctx, cell, "I[2]") || port_has_net(ctx, cell, "I[3]"))
            reject("requires the data net on I[0] only");
        else if (special_shapes != 0)
            reject("cannot inherit registered-pad, direct-D, or carry support");
    } else if (result.mode == RegisterInputMode::REGISTERED_PAD_I3) {
        if (!tagged_pad || tagged_direct || carry_shape)
            reject("requires only the existing agamemnon_registered_pad_input tag");
        else if (init != 0xff00)
            reject("requires the qualified I[3] identity INIT=0xFF00");
        else if (port_has_net(ctx, cell, "I[0]") || port_has_net(ctx, cell, "I[1]") ||
                 port_has_net(ctx, cell, "I[2]") || !port_has_net(ctx, cell, "I[3]"))
            reject("requires the registered pad data net on I[3] only");
    } else if (result.mode == RegisterInputMode::DIRECT_D_I3) {
        if ((!tagged_direct && legacy_derived) || tagged_pad || carry_shape)
            reject("requires an explicit DIRECT_D_I3 mode or the existing direct-D tag");
        else if (!port_has_net(ctx, cell, "I[3]") ||
                 cell->ports.at(ctx->id("I[3]")).net != cell->ports.at(ctx->id("Q")).net)
            reject("requires own-Q feedback on I[3]");
        else if (!direct_d_q_is_local_only(ctx, cell))
            reject("requires registered Q to be local-only on the same cell's I[3]");
        else if (!init_depends_on(init, 3))
            reject("INIT does not depend on the tagged I[3] feedback input");
    } else if (result.mode == RegisterInputMode::CARRY_SUM_TO_FF) {
        if (!carry_shape || tagged_pad || tagged_direct)
            reject("requires only the dedicated carry resource shape");
        else if (!port_has_net(ctx, cell, "I[3]"))
            reject("requires the carry I[3] sum selector");
    } else if (result.mode == RegisterInputMode::LUT_COMPUTE_TO_FF) {
        if (special_shapes != 0)
            reject("cannot inherit registered-pad, direct-D, or carry support");
        else
            for (int input = 0; input < 4; ++input)
                if (init_depends_on(init, input) &&
                    !port_has_net(ctx, cell, "I[" + std::to_string(input) + "]")) {
                    reject("INIT depends on an unconnected LUT input");
                    break;
                }
    }
    return result;
}

static bool qualified_direct_d_site(Context *ctx, BelId bel)
{
    const Loc loc = ctx->getBelLocation(bel);
    bool qualified = loc.x == 14 && loc.y == 11 && loc.z >= 4 && loc.z <= 7;
    if (std::getenv("AGAMEMNON_DIRECT_D_X15Y8_S12_EXPERIMENT") != nullptr)
        qualified = qualified || (loc.x == 15 && loc.y == 8 && loc.z == 12);
    if (std::getenv("AGRV2K_DIRECT_D_X14Y11_S8_EXPERIMENT") != nullptr)
        qualified = qualified || (loc.x == 14 && loc.y == 11 && loc.z == 8);
    // Experimental site broadening is parsed once because this predicate is
    // shared by both the hot placer-validity path and final pre-route DRC.
    static const std::unordered_set<std::string> extra_sites = [] {
        std::unordered_set<std::string> sites;
        const char *raw = std::getenv("AGAMEMNON_DIRECT_D_EXTRA_SITES");
        if (raw != nullptr) {
            std::string token;
            std::istringstream stream((std::string(raw)));
            while (std::getline(stream, token, ';'))
                if (!token.empty())
                    sites.insert(token);
        }
        return sites;
    }();
    return qualified || extra_sites.count(std::string(ctx->nameOfBel(bel))) != 0;
}

static const char *native_direct_d_pool_token = "X14Y11_SLICE4_7_V1";

static bool native_direct_d_pool_cell(Context *ctx, const CellInfo *cell)
{
    return cell != nullptr &&
           (cell->attrs.count(ctx->id("AGRV2K_NATIVE_DIRECT_D_POOL")) != 0 ||
            cell->attrs.count(ctx->id("AGRV2K_NATIVE_DIRECT_D_COUNT")) != 0);
}

static bool native_direct_d_pool_site(Context *ctx, BelId bel)
{
    if (bel == BelId())
        return false;
    const Loc loc = ctx->getBelLocation(bel);
    return loc.x == 14 && loc.y == 11 && loc.z >= 4 && loc.z <= 7;
}

static int native_direct_d_pool_count(Context *ctx, const CellInfo *cell,
                                      std::string &error)
{
    const auto pool = cell->attrs.find(ctx->id("AGRV2K_NATIVE_DIRECT_D_POOL"));
    const auto count = cell->attrs.find(ctx->id("AGRV2K_NATIVE_DIRECT_D_COUNT"));
    if (pool == cell->attrs.end() || count == cell->attrs.end()) {
        error = "requires both AGRV2K_NATIVE_DIRECT_D_POOL and "
                "AGRV2K_NATIVE_DIRECT_D_COUNT";
        return -1;
    }
    if (!pool->second.is_string ||
        pool->second.as_string() != native_direct_d_pool_token) {
        error = "unknown AGRV2K_NATIVE_DIRECT_D_POOL capability token '" +
                pool->second.to_string() + "'";
        return -1;
    }
    int value = -1;
    if (count->second.is_string) {
        const std::string token = count->second.as_string();
        if (token == "1" || token == "2" || token == "3")
            value = token[0] - '0';
    } else if (count->second.is_fully_def()) {
        value = int(count->second.as_int64());
    }
    if (value < 1 || value > 3) {
        error = "AGRV2K_NATIVE_DIRECT_D_COUNT must be exactly 1, 2, or 3";
        return -1;
    }
    return value;
}

static bool register_input_bel_valid(Context *ctx, const CellInfo *cell, BelId bel,
                                     bool explain_invalid)
{
    const RegisterInputRequirement requirement = register_input_requirement(ctx, cell);
    if (requirement.malformed()) {
        if (explain_invalid)
            log_info("agrv2k validity: registered input for '%s' at %s is malformed: %s\n",
                     ctx->nameOf(cell), ctx->nameOfBel(bel), requirement.error.c_str());
        return false;
    }
    auto has_bel_pin = [&](const char *pin) {
        return ctx->getBelPinWire(bel, ctx->id(pin)) != WireId();
    };
    if (ctx->getBelType(bel) != ctx->id("GENERIC_SLICE"))
        return false;
    if (native_direct_d_pool_cell(ctx, cell)) {
        std::string pool_error;
        const int count = native_direct_d_pool_count(ctx, cell, pool_error);
        auto origin = cell->attrs.find(ctx->id("agamemnon_direct_d_origin"));
        if (count < 0 || requirement.mode != RegisterInputMode::DIRECT_D_I3 ||
            origin == cell->attrs.end() ||
            !origin->second.is_string ||
            origin->second.as_string() != "qin-pack-inferred-own-q") {
            if (explain_invalid)
                log_info("agrv2k validity: native direct-D pool metadata on '%s' at %s "
                         "is malformed: %s\n", ctx->nameOf(cell), ctx->nameOfBel(bel),
                         count < 0 ? pool_error.c_str() :
                         "requires inferred own-Q DIRECT_D_I3 provenance");
            return false;
        }
        if (!native_direct_d_pool_site(ctx, bel)) {
            if (explain_invalid)
                log_info("agrv2k validity: native direct-D cell '%s' at %s is outside "
                         "X14Y11_SLICE4..7\n", ctx->nameOf(cell), ctx->nameOfBel(bel));
            return false;
        }
    }
    if (requirement.mode == RegisterInputMode::DIRECT_D_I3 &&
        !qualified_direct_d_site(ctx, bel)) {
        if (explain_invalid)
            log_info("agrv2k validity: DIRECT_D_I3 cell '%s' at %s is outside the "
                     "qualified direct-D site/presentation pool\n",
                     ctx->nameOf(cell), ctx->nameOfBel(bel));
        return false;
    }
    std::vector<const char *> pins;
    switch (requirement.mode) {
    case RegisterInputMode::NONE:
        return true;
    case RegisterInputMode::LUT_FEEDTHROUGH_I0:
        pins = {"I[0]", "CLK", "Q"};
        break;
    case RegisterInputMode::REGISTERED_PAD_I3:
    case RegisterInputMode::DIRECT_D_I3:
        pins = {"I[3]", "CLK", "Q"};
        break;
    case RegisterInputMode::CARRY_SUM_TO_FF:
        pins = {"I[3]", "CIN", "COUT", "CLK", "Q"};
        break;
    case RegisterInputMode::LUT_COMPUTE_TO_FF:
        pins = {"CLK", "Q"};
        for (int input = 0; input < 4; ++input)
            if (port_has_net(ctx, cell, "I[" + std::to_string(input) + "]") &&
                !has_bel_pin(("I[" + std::to_string(input) + "]").c_str())) {
                if (explain_invalid)
                    log_info("agrv2k validity: compute FF '%s' requires absent BEL input I[%d] at %s\n",
                             ctx->nameOf(cell), input, ctx->nameOfBel(bel));
                return false;
            }
        break;
    case RegisterInputMode::UNKNOWN:
    case RegisterInputMode::MALFORMED:
        NPNR_ASSERT(false);
    }
    for (const char *pin : pins)
        if (!has_bel_pin(pin)) {
            if (explain_invalid)
                log_info("agrv2k validity: %s cell '%s' requires absent BEL pin %s at %s\n",
                         register_input_mode_name(requirement.mode), ctx->nameOf(cell), pin,
                         ctx->nameOfBel(bel));
            return false;
        }
    return true;
}

// Record one structured footprint as a native nextpnr cluster.  The supplied
// locations describe the already-qualified physical shape, not an absolute
// placement: x/y are converted to offsets from the root so the placer may
// translate the structure as a unit.  Carry seams require exact slice slots,
// hence the optional absolute-z constraint; x/y always remain relative.
static void make_relative_cluster(Context *ctx,
                                  const std::vector<std::pair<CellInfo *, Loc>> &members,
                                  bool absolute_z)
{
    NPNR_ASSERT(!members.empty());
    require_cluster_shared_clock_compatibility(ctx, members);
    for (const auto &member : members) {
        const SharedControlRequirement control =
                shared_control_requirement(ctx, member.first);
        if (control.malformed())
            log_error("agrv2k: relative cluster rejects malformed shared control on '%s' "
                      "at tile offset X%dY%dZ%d: %s\n",
                      ctx->nameOf(member.first), member.second.x, member.second.y,
                      member.second.z, control.error.c_str());
        if (control.active())
            log_error("agrv2k: relative cluster rejects shared control on '%s' at tile "
                      "offset X%dY%dZ%d: %s\n",
                      ctx->nameOf(member.first), member.second.x, member.second.y,
                      member.second.z, unsupported_shared_control_diagnostic());
        const RegisterInputRequirement requirement =
                register_input_requirement(ctx, member.first);
        if (requirement.malformed())
            log_error("agrv2k: relative cluster rejects malformed register input on '%s' "
                      "at tile offset X%dY%dZ%d: %s\n",
                      ctx->nameOf(member.first), member.second.x, member.second.y,
                      member.second.z, requirement.error.c_str());
    }
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
                    const bool registered_pad =
                            packed->attrs.count(ctx->id("agamemnon_registered_pad_input")) != 0;
                    const bool direct_d =
                            packed->attrs.count(ctx->id("agamemnon_direct_d_feedback")) != 0;
                    if (registered_pad && direct_d)
                        log_error("agrv2k: LUT '%s' has conflicting registered-pad and direct-D tags\n",
                                  ctx->nameOf(ci));
                    set_register_input_mode(
                            ctx, packed.get(),
                            registered_pad ? RegisterInputMode::REGISTERED_PAD_I3
                                           : direct_d ? RegisterInputMode::DIRECT_D_I3
                                                      : RegisterInputMode::LUT_COMPUTE_TO_FF);
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
                set_register_input_mode(ctx, packed.get(), RegisterInputMode::NONE);
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
            // The generic helper implements a physical LUT identity path:
            // INIT=0xAAAA, D on I[0], CLK/Q connected, and F unused.
            set_register_input_mode(ctx, packed.get(), RegisterInputMode::LUT_FEEDTHROUGH_I0);
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

static void cofactor_disconnected_zero_lut_input(const Context *ctx, CellInfo *cell,
                                                 IdString port)
{
    const std::string port_name = port.str(ctx);
    if (port_name.size() != 4 || port_name[0] != 'I' || port_name[1] != '[' ||
        port_name[3] != ']' || port_name[2] < '0' || port_name[2] > '9')
        return;
    const int input = port_name[2] - '0';
    if (input < 0 || input >= ctx->args.K)
        return;

    auto init_it = cell->params.find(ctx->id("INIT"));
    if (init_it == cell->params.end())
        return; // Preserve malformed imported cells for the existing fail-closed validator.

    const int width = 1 << ctx->args.K;
    uint64_t init = uint64_t(init_it->second.as_int64());
    for (int row = 0; row < width; ++row) {
        if ((row & (1 << input)) == 0)
            continue;
        const int zero_row = row & ~(1 << input);
        const uint64_t bit = (init >> zero_row) & 1;
        if (bit)
            init |= uint64_t(1) << row;
        else
            init &= ~(uint64_t(1) << row);
    }
    cell->params[ctx->id("INIT")] = Property(int64_t(init), width);
}

static void set_net_constant(const Context *ctx, NetInfo *orig, NetInfo *constnet, bool constval)
{
    // AGRV2K_LOCAL_CONSTANTS (opt-in): also fold the spurious constant tied to the CLK pin of
    // combinational GENERIC_SLICE cells (FF_USED=0). Structural primitives write `.CLK(1'b0)` on
    // combinational slices; an unused clock needs no routed constant, but the default flow routes it to
    // the tile ClkMUX -- a non-conducting arc that becomes the universal routing barrier once local-
    // constant replication removes the X14Y11 placement starvation. Disconnecting it (like the LUT-input
    // GND fold below) removes the dead arc. Gated, so the default remains byte-identical.
    static const bool local_constants_enabled =
            std::getenv("AGRV2K_LOCAL_CONSTANTS") != nullptr;
    const IdString clk_id = ctx->id("CLK");
    const IdString gslice_id = ctx->id("GENERIC_SLICE");
    const IdString ffused_id = ctx->id("FF_USED");
    orig->driver.cell = nullptr;
    for (auto user : orig->users) {
        if (user.cell != nullptr) {
            CellInfo *uc = user.cell;
            if (ctx->verbose)
                log_info("%s user %s\n", orig->name.c_str(ctx), uc->name.c_str(ctx));
            bool comb_clk_fold = false;
            if (local_constants_enabled && user.port == clk_id && uc->type == gslice_id) {
                auto ff = uc->params.find(ffused_id);
                comb_clk_fold = (ff != uc->params.end() && ff->second.is_fully_def() &&
                                 ff->second.as_int64() == 0);
            }
            if ((((is_lut(ctx, uc) || is_lc(ctx, uc)) && (user.port.str(ctx).at(0) == 'I') && !constval)) ||
                comb_clk_fold) {
                if (local_constants_enabled && !comb_clk_fold) {
                    // Disconnecting a defined-zero LUT input is safe only after
                    // INIT is canonicalized to that input's zero cofactor.
                    // Otherwise the packed LUT can silently depend on an input
                    // that no longer exists. Keep this correction inside the
                    // silicon-witnessed opt-in combination; with the flag off,
                    // the existing validator rejects such imported slices.
                    // VCC stays connected and needs no equivalent rewrite.
                    cofactor_disconnected_zero_lut_input(ctx, uc, user.port);
                }
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

// AGRV2K_LOCAL_CONSTANTS (opt-in): the default flow drives every constant consumer from ONE shared
// $PACKER_GND/$PACKER_VCC cell, which the placer pins far (the MCU-boundary X14Y11), so fabric-wide
// constant fan-in becomes long cross-fabric routes -- silicon-wrong for carry-heavy designs and a
// placement-starvation source for ~half the routability gaps. This splits the shared constant net so
// all-but-the-first consumer gets its OWN local driver cell+net (params copied verbatim from the
// prototype), letting HPWL placement keep each constant source adjacent to its single user. Reached
// ONLY under the env flag, so the default remains byte-identical.
static void replicate_local_constants(Context *ctx, IdString net_name, IdString cell_name)
{
    auto net_it = ctx->nets.find(net_name);
    auto cell_it = ctx->cells.find(cell_name);
    if (net_it == ctx->nets.end() || cell_it == ctx->cells.end())
        return;
    NetInfo *shared = net_it->second.get();
    CellInfo *proto = cell_it->second.get();
    std::vector<PortRef> users;
    for (auto &u : shared->users)
        users.push_back(u);
    if (users.size() <= 1)
        return;
    shared->users.clear();
    std::vector<std::unique_ptr<CellInfo>> new_cells;
    std::vector<std::unique_ptr<NetInfo>> new_nets;
    int idx = 0;
    for (auto &u : users) {
        if (u.cell == nullptr)
            continue;
        if (idx++ == 0) {
            // keep the first consumer on the original shared cell/net (also preserves
            // $PACKER_GND/$PACKER_VCC for any downstream by-name use).
            u.cell->ports[u.port].net = shared;
            u.cell->ports[u.port].user_idx = shared->users.add(u);
            continue;
        }
        std::string base = cell_name.str(ctx) + "_LOCAL_" + std::to_string(idx);
        std::unique_ptr<CellInfo> cell =
                create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), base);
        for (auto &p : proto->params)
            cell->params[p.first] = p.second;
        std::unique_ptr<NetInfo> net = std::make_unique<NetInfo>(ctx->id(base + "_NET"));
        net->driver.cell = cell.get();
        net->driver.port = ctx->id("F");
        cell->ports.at(ctx->id("F")).net = net.get();
        u.cell->ports[u.port].net = net.get();
        u.cell->ports[u.port].user_idx = net->users.add(u);
        new_cells.push_back(std::move(cell));
        new_nets.push_back(std::move(net));
    }
    for (auto &c : new_cells)
        ctx->cells[c->name] = std::move(c);
    for (auto &n : new_nets)
        ctx->nets[n->name] = std::move(n);
    log_info("agrv2k: AGRV2K_LOCAL_CONSTANTS replicated %d local drivers off %s\n",
             int(new_cells.size()), cell_name.c_str(ctx));
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

    if (std::getenv("AGRV2K_LOCAL_CONSTANTS") != nullptr) {
        replicate_local_constants(ctx, ctx->id("$PACKER_GND_NET"), ctx->id("$PACKER_GND"));
        replicate_local_constants(ctx, ctx->id("$PACKER_VCC_NET"), ctx->id("$PACKER_VCC"));
    }
}

// A GENERIC_SLICE with FF_USED=0 has no physical clocked state, so its CLK
// port is semantically absent.  Direct structural and retained-overlay
// netlists can nevertheless leave that unused port connected.  N5.7A makes
// every GCLK0 leaf an exact typed claim; keeping an inactive user would either
// manufacture an extra leaf or ask router2 to route a sink which bitgen does
// not emit.  Canonicalize every inactive slice CLK before placement.  Active
// clocks and every non-clock user of the net remain untouched.
static void pack_inactive_constant_slice_clocks(Context *ctx)
{
    const IdString slice = ctx->id("GENERIC_SLICE");
    const IdString clk = ctx->id("CLK");
    const IdString ff_used = ctx->id("FF_USED");
    int disconnected = 0;

    for (auto &item : ctx->cells) {
        CellInfo *cell = item.second.get();
        if (cell->type != slice || int_or_default(cell->params, ff_used, 0) != 0)
            continue;
        NetInfo *clock = cell->getPort(clk);
        if (clock == nullptr)
            continue;
        cell->disconnectPort(clk);
        ++disconnected;
    }
    if (disconnected)
        log_info("agrv2k: canonicalized %d inactive slice clock connection(s)\n",
                  disconnected);
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
    IdString cin_port = ctx->id("CIN");
    IdString cout_port = ctx->id("COUT");
    IdString sum_port = ctx->id("SUM");
    bool any = false;
    for (auto &cell : ctx->cells)
        if (cell.second->type == fa_type) { any = true; break; }
    if (!any)
        return;
    log_info("Packing carry chains..\n");

    // Inventory and validate the complete logical graph before mutating it. A
    // dedicated carry COUT may have one following AG32_FA.CIN, or it may be a
    // terminal value routed into ordinary logic. It may not do both: the
    // characterized dedicated resource has no admitted interior fanout.
    struct CarrySite { int x, y, z; };
    struct CarryChain {
        std::vector<CellInfo *> fa;
        std::vector<CarrySite> sites; // seed first, then one site per FA
        BelId root_constraint;
        std::vector<BelId> fixed_bels;
    };
    std::vector<CellInfo *> fa_cells;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type == fa_type)
            fa_cells.push_back(ci);
    }
    std::sort(fa_cells.begin(), fa_cells.end(), [&](CellInfo *a, CellInfo *b) {
        return a->name.str(ctx) < b->name.str(ctx);
    });

    std::unordered_map<CellInfo *, CellInfo *> successor;
    std::unordered_map<CellInfo *, CellInfo *> predecessor;
    for (CellInfo *ci : fa_cells) {
        auto require_port = [&](IdString port, PortType type, bool require_net) -> NetInfo * {
            auto found = ci->ports.find(port);
            if (found == ci->ports.end() || found->second.type != type ||
                    (require_net && found->second.net == nullptr))
                log_error("agrv2k: dedicated carry cell '%s' has malformed or disconnected %s port\n",
                          ctx->nameOf(ci), ctx->nameOf(port));
            return found == ci->ports.end() ? nullptr : found->second.net;
        };
        require_port(ctx->id("A"), PORT_IN, false);
        require_port(ctx->id("B"), PORT_IN, false);
        NetInfo *cin = require_port(cin_port, PORT_IN, false);
        require_port(sum_port, PORT_OUT, true);
        NetInfo *cout = require_port(cout_port, PORT_OUT, true);
        if (cout->driver.cell != ci || cout->driver.port != cout_port)
            log_error("agrv2k: dedicated carry cell '%s' does not exclusively drive its COUT net '%s'\n",
                      ctx->nameOf(ci), ctx->nameOf(cout));

        CellInfo *next = nullptr;
        bool has_external_user = false;
        for (const PortRef &user : cout->users) {
            if (user.cell == nullptr)
                continue;
            if (user.cell->type == fa_type && user.port == cin_port) {
                if (next != nullptr && next != user.cell)
                    log_error("agrv2k: dedicated carry COUT net '%s' branches to multiple AG32_FA.CIN users\n",
                              ctx->nameOf(cout));
                next = user.cell;
            } else {
                has_external_user = true;
                if (user.cell->type == fa_type)
                    log_error("agrv2k: dedicated carry COUT net '%s' drives AG32_FA '%s' through non-CIN port %s\n",
                              ctx->nameOf(cout), ctx->nameOf(user.cell), ctx->nameOf(user.port));
            }
        }
        if (next != nullptr && has_external_user)
            log_error("agrv2k: dedicated carry COUT net '%s' has unsupported interior non-carry fanout\n",
                      ctx->nameOf(cout));
        successor[ci] = next;

        if (cin != nullptr && cin->driver.cell != nullptr && cin->driver.cell->type == fa_type) {
            if (cin->driver.port != cout_port)
                log_error("agrv2k: dedicated carry cell '%s' CIN is driven by AG32_FA '%s' through non-COUT port %s\n",
                          ctx->nameOf(ci), ctx->nameOf(cin->driver.cell), ctx->nameOf(cin->driver.port));
            predecessor[ci] = cin->driver.cell;
        } else {
            predecessor[ci] = nullptr;
        }
    }

    std::vector<CarryChain> chains;
    std::unordered_set<CellInfo *> seen;
    for (CellInfo *head : fa_cells) {
        if (predecessor.at(head) != nullptr)
            continue;
        CarryChain chain;
        for (CellInfo *cur = head; cur != nullptr; cur = successor.at(cur)) {
            if (!seen.insert(cur).second)
                log_error("agrv2k: dedicated carry graph merges or cycles at cell '%s'\n",
                          ctx->nameOf(cur));
            chain.fa.push_back(cur);
        }
        chains.push_back(std::move(chain));
    }
    if (chains.empty())
        log_error("agrv2k: dedicated carry contains no chain head (cycle or malformed netlist)\n");
    if (seen.size() != fa_cells.size())
        log_error("agrv2k: dedicated carry graph contains %ld untraced cell(s) (headless cycle or merged interior)\n",
                  long(fa_cells.size() - seen.size()));
    std::sort(chains.begin(), chains.end(), [&](const CarryChain &a, const CarryChain &b) {
        if (a.fa.size() != b.fa.size())
            return a.fa.size() > b.fa.size();
        return a.fa.front()->name.str(ctx) < b.fa.front()->name.str(ctx);
    });

    // A capture DFF is semantically one physical member with its FA.  Its
    // fixed placement is therefore whole-chain intent too; preflight both
    // surfaces before any packing mutation and reject disagreement.
    std::unordered_map<CellInfo *, CellInfo *> capture_dff;
    for (CellInfo *fa : fa_cells) {
        NetInfo *sum = fa->getPort(sum_port);
        CellInfo *dff = sum ? net_only_drives(ctx, sum, is_ff, ctx->id("D"), true)
                            : nullptr;
        if (dff != nullptr)
            capture_dff.emplace(fa, dff);
    }

    // Admit only the already-qualified physical templates. Template selection
    // also happens before mutation, so an unsupported topology cannot leave a
    // half-packed design behind.
    std::vector<CarrySite> sites;
    auto append_tile = [&](int x, int y, int limit = 16) {
        for (int z = 0; z < limit; ++z)
            sites.push_back({x, y, z});
    };
    size_t total = chains.size(); // one seed per chain
    for (const CarryChain &chain : chains)
        total += chain.fa.size();
    const bool native_short_profile = total <= 9;
    if (!native_short_profile && chains.size() == 1 && total <= 25) {
        append_tile(20, 12);
        append_tile(20, 11, 9);
    } else if (!native_short_profile && chains.size() == 1 && total <= 33) {
        append_tile(20, 11);
        append_tile(20, 12);
        append_tile(20, 10, 1);
    } else if (!native_short_profile) {
        log_error("agrv2k: dedicated carry requires %ld slices across %ld chain(s), but the "
                  "qualified vendor-observed corridor supports one chain through 33 stages or "
                  "multiple same-tile chains through nine stages (including seeds)\n",
                  long(total), long(chains.size()));
    }
    size_t next_site = 0;
    for (CarryChain &chain : chains) {
        const size_t stages = chain.fa.size() + 1;
        if (native_short_profile) {
            // N5.6A: each bounded chain is an independent same-tile shape.
            // Its seed is relative z=0 and every arithmetic member advances
            // by one exact local CARRY edge.  The placer may choose any graph-
            // legal root whose complete footprint fits; unrelated chains no
            // longer inherit disjoint absolute slots from X15Y1.
            for (size_t z = 0; z < stages; ++z)
                chain.sites.push_back({0, 0, int(z)});
        } else {
            chain.sites.assign(sites.begin() + next_site,
                               sites.begin() + next_site + stages);
            next_site += stages;
        }

        // nextpnr constrains a relative cluster through its root. Convert any
        // explicit member BEL to the equivalent seed/root BEL now, reject
        // conflicting constraints, and prove every translated carry hop is an
        // exact direct pip before any cell or net is rewritten.
        const CarrySite first = chain.sites.front();
        for (size_t index = 0; index < chain.fa.size(); ++index) {
            CellInfo *fa = chain.fa.at(index);
            std::vector<std::pair<CellInfo *, Property>> requests;
            auto requested_fa = fa->attrs.find(ctx->id("BEL"));
            if (requested_fa != fa->attrs.end())
                requests.push_back({fa, requested_fa->second});
            auto capture = capture_dff.find(fa);
            if (capture != capture_dff.end()) {
                auto requested_dff = capture->second->attrs.find(ctx->id("BEL"));
                if (requested_dff != capture->second->attrs.end())
                    requests.push_back({capture->second, requested_dff->second});
            }
            if (requests.empty())
                continue;
            const CarrySite site = chain.sites.at(index + 1);
            for (const auto &request : requests) {
                const std::string requested_name = request.second.as_string();
                // GenericArch's getBelByName() asserts on an unknown name.
                // BEL attributes are untrusted imported/user input, so parse
                // the exact slice spelling and use the non-asserting location
                // lookup before consulting any physical carry resource.
                int requested_x = -1, requested_y = -1, requested_z = -1;
                int consumed = 0;
                const bool exact_slice_name =
                        std::sscanf(requested_name.c_str(),
                                    "X%dY%d_SLICE%d%n", &requested_x,
                                    &requested_y, &requested_z, &consumed) == 3 &&
                        consumed == int(requested_name.size()) &&
                        requested_x >= 0 && requested_y >= 0 &&
                        requested_z >= 0;
                BelId requested_bel = exact_slice_name
                        ? ctx->getBelByLocation(
                                  Loc(requested_x, requested_y, requested_z))
                        : BelId();
                if (requested_bel == BelId() ||
                    ctx->getBelType(requested_bel) != ctx->id("GENERIC_SLICE") ||
                    ctx->getBelName(requested_bel).str(ctx) != requested_name)
                    log_error("agrv2k: carry member '%s' requests invalid slice BEL '%s'\n",
                              ctx->nameOf(request.first), requested_name.c_str());
                const Loc requested_loc = ctx->getBelLocation(requested_bel);
                if (!native_short_profile && requested_loc.z != site.z)
                    log_error("agrv2k: carry member '%s' requests BEL '%s' at slice %d, but its "
                              "qualified chain position requires absolute slice %d\n",
                              ctx->nameOf(request.first), requested_name.c_str(),
                              requested_loc.z, site.z);
                const Loc implied_root(
                        requested_loc.x - (site.x - first.x),
                        requested_loc.y - (site.y - first.y),
                        native_short_profile
                                ? requested_loc.z - (site.z - first.z)
                                : first.z);
                BelId implied_root_bel = ctx->getBelByLocation(implied_root);
                if (implied_root_bel == BelId() ||
                    ctx->getBelType(implied_root_bel) != ctx->id("GENERIC_SLICE"))
                    log_error("agrv2k: carry member '%s' BEL '%s' implies an unavailable "
                              "cluster root\n", ctx->nameOf(request.first),
                              requested_name.c_str());
                if (chain.root_constraint != BelId() &&
                    chain.root_constraint != implied_root_bel)
                    log_error("agrv2k: carry chain has mutually inconsistent BEL constraints\n");
                chain.root_constraint = implied_root_bel;
            }
        }
        if (chain.root_constraint != BelId()) {
            const Loc root_loc = ctx->getBelLocation(chain.root_constraint);
            auto has_direct_pip = [&](WireId source, WireId target,
                                      bool local_only) {
                if (source == WireId() || target == WireId())
                    return false;
                for (PipId pip : ctx->getPipsDownhill(source)) {
                    if (ctx->getPipDstWire(pip) != target)
                        continue;
                    const IdString type = ctx->getPipType(pip);
                    if (type == ctx->id("CARRY") ||
                        (!local_only && type == ctx->id("CARRY_SEAM")))
                        return true;
                }
                return false;
            };
            for (const CarrySite &site : chain.sites) {
                BelId bel = ctx->getBelByLocation(
                        Loc(root_loc.x + site.x - first.x,
                            root_loc.y + site.y - first.y,
                            native_short_profile
                                    ? root_loc.z + site.z - first.z
                                    : site.z));
                if (bel == BelId() ||
                    ctx->getBelType(bel) != ctx->id("GENERIC_SLICE"))
                    log_error("agrv2k: fixed carry footprint rooted at %s contains an "
                              "unavailable member\n",
                              ctx->getBelName(chain.root_constraint).str(ctx).c_str());
                chain.fixed_bels.push_back(bel);
            }
            for (size_t index = 1; index < chain.fixed_bels.size(); ++index) {
                const CarrySite before = chain.sites.at(index - 1);
                const CarrySite after = chain.sites.at(index);
                BelId before_bel = chain.fixed_bels.at(index - 1);
                BelId after_bel = chain.fixed_bels.at(index);
                if (!has_direct_pip(ctx->getBelPinWire(before_bel, cout_port),
                                    ctx->getBelPinWire(after_bel, cin_port),
                                    native_short_profile))
                    log_error("agrv2k: constrained carry translation from X%dY%d_SLICE%d to "
                              "X%dY%d_SLICE%d has no dedicated COUT->CIN pip\n",
                              root_loc.x + before.x - first.x,
                              root_loc.y + before.y - first.y, before.z,
                              root_loc.x + after.x - first.x,
                              root_loc.y + after.y - first.y, after.z);
            }

            std::unordered_set<CellInfo *> own_cells(chain.fa.begin(), chain.fa.end());
            for (const auto &capture : capture_dff)
                if (own_cells.count(capture.first))
                    own_cells.insert(capture.second);
            std::unordered_set<int> footprint;
            for (BelId bel : chain.fixed_bels)
                footprint.insert(bel.index);
            for (auto &entry : ctx->cells) {
                CellInfo *other = entry.second.get();
                if (own_cells.count(other))
                    continue;
                auto requested = other->attrs.find(ctx->id("BEL"));
                if (requested == other->attrs.end())
                    continue;
                BelId reserved = ctx->getBelByName(
                        IdStringList(ctx->id(requested->second.as_string())));
                if (reserved != BelId() && footprint.count(reserved.index))
                    log_error("agrv2k: fixed carry footprint overlaps foreign fixed cell '%s' "
                              "at %s\n", ctx->nameOf(other), ctx->nameOfBel(reserved));
            }
        }
    }

    // The physical chain has no defined external Cin at slice 0. The vendor
    // therefore places a combinational seed slice ahead of every arithmetic
    // bit and drives the first real Cin from that slice's Cout.
    std::vector<CellInfo *> fa_heads;
    for (const CarryChain &chain : chains)
        fa_heads.push_back(chain.fa.front());

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
        CellInfo *packed;
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
        set_register_input_mode(ctx, seed.get(), RegisterInputMode::NONE);
        if (input_const < 0)
            seed->addInput(ctx->id("I[0]"));
        auto seed_net = std::make_unique<NetInfo>(ctx->id("$CARRY_SEED_NET" + suffix));
        seed->connectPort(ctx->id("COUT"), seed_net.get());
        head_seed[head] = seeds.size();
        CellInfo *packed = seed.get();
        seeds.push_back({head, input_const, packed, std::move(seed), std::move(seed_net)});
    }

    // one shared VCC slice fans out to every carry cell's D input (I[3]=1)
    std::unique_ptr<CellInfo> vcc_cell = create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), "$CARRY_VCC");
    vcc_cell->params[ctx->id("INIT")] = Property(Property::S1).extract(0, (1 << ctx->args.K), Property::S1);
    vcc_cell->params[ctx->id("FF_USED")] = 0;
    set_register_input_mode(ctx, vcc_cell.get(), RegisterInputMode::NONE);
    auto vcc_net_uptr = std::make_unique<NetInfo>(ctx->id("$CARRY_VCC_NET"));
    NetInfo *vcc_net = vcc_net_uptr.get();
    vcc_cell->connectPort(ctx->id("F"), vcc_net);

    pool<IdString> packed_cells;
    std::vector<std::unique_ptr<CellInfo>> new_cells;
    std::unordered_map<CellInfo *, CellInfo *> packed_fa;
    long n_fa = 0, n_ffused = 0;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type != fa_type)
            continue;
        std::unique_ptr<CellInfo> lc =
                create_generic_cell(ctx, ctx->id("GENERIC_SLICE"), ci->name.str(ctx) + "_CARRY");
        // Preserve ordinary placement/user metadata across the legalization
        // boundary, just as the generic LUT/FF packer does. In particular,
        // an explicit BEL remains a hard constraint on the packed slice.
        lc->attrs = ci->attrs;
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
            set_register_input_mode(ctx, lc.get(), RegisterInputMode::CARRY_SUM_TO_FF);
            dff->movePortTo(ctx->id("CLK"), lc.get(), ctx->id("CLK"));
            dff->movePortTo(ctx->id("Q"), lc.get(), ctx->id("Q"));
            ctx->nets.erase(sum->name); // internal LUT->FF net; F stays unconnected
            packed_cells.insert(dff->name);
            ++n_ffused;
        } else {
            lc->params[ctx->id("FF_USED")] = 0;
            set_register_input_mode(ctx, lc.get(), RegisterInputMode::NONE);
            ci->movePortTo(ctx->id("SUM"), lc.get(), ctx->id("F"));
        }
        packed_cells.insert(ci->name);
        packed_fa[ci] = lc.get();
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

    // ---- constructive placement: each logical chain is now an independent
    // relative cluster. This preserves its exact qualified internal geometry
    // while allowing unrelated short chains to translate independently.
    size_t carry_chain_index = 0;
    for (const CarryChain &chain : chains) {
        std::vector<std::pair<CellInfo *, Loc>> clustered;
        CarrySeed &seed = seeds.at(head_seed.at(chain.fa.front()));
        // A fixed member expresses one whole-chain root.  Keep exactly that
        // root constraint on the synthetic seed and erase member-local BEL
        // attributes so nextpnr cannot interpret a consistent partial-fixed
        // request as several independent placement commands.
        for (CellInfo *fa : chain.fa)
            packed_fa.at(fa)->attrs.erase(ctx->id("BEL"));
        if (chain.root_constraint != BelId())
            seed.packed->attrs[ctx->id("BEL")] =
                    Property(ctx->getBelName(chain.root_constraint).str(ctx));
        const CarrySite first = chain.sites.front();
        clustered.push_back({seed.packed, Loc(first.x, first.y, first.z)});
        for (size_t index = 0; index < chain.fa.size(); ++index) {
            const CarrySite site = chain.sites.at(index + 1);
            CellInfo *packed = packed_fa.at(chain.fa.at(index));
            clustered.push_back({packed, Loc(site.x, site.y, site.z)});
        }
        const CarrySite last = chain.sites.back();
        log_info("  carry chain: independent relative cluster of %ld cells in shape "
                 "X%dY%d_SLICE%d to X%dY%d_SLICE%d\n",
                 long(clustered.size()), first.x, first.y, first.z, last.x, last.y, last.z);
        make_relative_cluster(ctx, clustered, !native_short_profile);
        const std::string profile = native_short_profile ? "SHORT_LOCAL" :
                (clustered.size() <= 25 ? "LEGACY_25" : "LEGACY_33");
        for (size_t index = 0; index < clustered.size(); ++index) {
            CellInfo *member = clustered.at(index).first;
            const std::string role = index == 0 ? "SEED" :
                    (clustered.size() == 2 ? "FIRST_TAIL" :
                     (index == 1 ? "FIRST" :
                      (index + 1 == clustered.size() ? "TAIL" : "INTERIOR")));
            member->attrs[ctx->id("AGRV2K_CARRY_SCHEMA")] = Property(1);
            member->attrs[ctx->id("AGRV2K_CARRY_PROFILE")] = Property(profile);
            member->attrs[ctx->id("AGRV2K_CARRY_CHAIN")] = Property(int64_t(carry_chain_index));
            member->attrs[ctx->id("AGRV2K_CARRY_POSITION")] = Property(int64_t(index));
            member->attrs[ctx->id("AGRV2K_CARRY_LENGTH")] = Property(int64_t(clustered.size()));
            member->attrs[ctx->id("AGRV2K_CARRY_ROLE")] = Property(role);
        }
        if (!chain.fixed_bels.empty()) {
            NPNR_ASSERT(chain.fixed_bels.size() == clustered.size());
            // HeAP seeds a fixed cluster root as an individual BEL and can
            // otherwise leave its children unplaced.  Validate the complete
            // fixed footprint first, then bind every member as one user-
            // strength transaction so partial/whole fixed intent is retained
            // without relying on placement order.
            for (size_t index = 0; index < clustered.size(); ++index) {
                CellInfo *occupant = ctx->getBoundBelCell(chain.fixed_bels.at(index));
                if (occupant != nullptr && occupant != clustered.at(index).first)
                    log_error("agrv2k: fixed carry member '%s' requires occupied BEL %s\n",
                              ctx->nameOf(clustered.at(index).first),
                              ctx->nameOfBel(chain.fixed_bels.at(index)));
            }
            for (size_t index = 0; index < clustered.size(); ++index) {
                CellInfo *member = clustered.at(index).first;
                BelId bel = chain.fixed_bels.at(index);
                member->attrs.erase(ctx->id("BEL"));
                if (ctx->getBoundBelCell(bel) == nullptr)
                    ctx->bindBel(bel, member, STRENGTH_USER);
            }
            log_info("  carry chain: atomically retained fixed root %s across %ld members\n",
                     ctx->nameOfBel(chain.fixed_bels.front()), long(clustered.size()));
        }
        ++carry_chain_index;
    }
    log_info("  carry placement: %ld chain(s), %ld cells clustered in qualified relative shape\n",
             long(chains.size()), long(total));
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

// One complete independent-control composition is retained from the
// register-source oracle.  Thirteen routed builds independently exercised all
// eleven sinks; this table selects one exact, simultaneous placement rather
// than inferring that arbitrary source placements compose.
static const char *fabric_ahb_independent_source_bel(Context *ctx, const CellInfo *ci)
{
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HSEL"))
        return "X14Y7_SLICE14";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HREADY"))
        return "X14Y10_SLICE9";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HTRANS0"))
        return "X14Y7_SLICE11";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HTRANS1"))
        return "X16Y7_SLICE12";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HSIZE0"))
        return "X16Y10_SLICE14";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HSIZE1"))
        return "X17Y8_SLICE0";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HSIZE2"))
        return "X14Y10_SLICE10";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HBURST0"))
        return "X14Y7_SLICE12";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HBURST1"))
        return "X14Y10_SLICE14";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HBURST2"))
        return "X17Y8_SLICE2";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HWRITE"))
        return "X17Y8_SLICE12";
    return nullptr;
}

static const char *fabric_ahb_request_signal(Context *ctx, const CellInfo *ci)
{
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HSEL"))
        return "slave_ahb_hsel";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HREADY"))
        return "slave_ahb_hready";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HTRANS0"))
        return "slave_ahb_htrans[0]";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HTRANS1"))
        return "slave_ahb_htrans[1]";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HSIZE0"))
        return "slave_ahb_hsize[0]";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HSIZE1"))
        return "slave_ahb_hsize[1]";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HSIZE2"))
        return "slave_ahb_hsize[2]";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HBURST0"))
        return "slave_ahb_hburst[0]";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HBURST1"))
        return "slave_ahb_hburst[1]";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HBURST2"))
        return "slave_ahb_hburst[2]";
    if (ci->type == ctx->id("MCU_SLAVE_AHB_HWRITE"))
        return "slave_ahb_hwrite";
    return nullptr;
}

static bool is_exact_fabric_ahb_independent_ff(Context *ctx, CellInfo *control,
                                                NetInfo *net)
{
    if (net == nullptr || net->driver.cell == nullptr || net->driver.port != ctx->id("Q"))
        return false;
    CellInfo *driver = net->driver.cell;
    const char *expected_bel = fabric_ahb_independent_source_bel(ctx, control);
    if (expected_bel == nullptr || driver->type != ctx->id("GENERIC_SLICE") ||
        int_or_default(driver->params, ctx->id("FF_USED"), 0) != 1)
        return false;
    auto requested = driver->attrs.find(ctx->id("BEL"));
    if (requested != driver->attrs.end())
        return requested->second.as_string() == expected_bel;
    return driver->bel != BelId() &&
           ctx->getBelName(driver->bel).str(ctx) == expected_bel;
}

static bool is_exact_fabric_ahb_independent_source_at(Context *ctx, CellInfo *driver,
                                                       BelId candidate)
{
    if (driver->type != ctx->id("GENERIC_SLICE") ||
        int_or_default(driver->params, ctx->id("FF_USED"), 0) != 1)
        return false;
    const std::string candidate_name = ctx->getBelName(candidate).str(ctx);
    auto requested = driver->attrs.find(ctx->id("BEL"));
    if (requested != driver->attrs.end() &&
            requested->second.as_string() != candidate_name)
        return false;
    // During pack the exact source is bound and its consumed BEL attribute is
    // removed before nextpnr's generic constraint pass.  Accept that already-
    // established state, but never an unbound attribute-free cell or a cell
    // bound somewhere else.
    if (requested == driver->attrs.end() && driver->bel != candidate)
        return false;
    NetInfo *q = driver->getPort(ctx->id("Q"));
    if (q == nullptr)
        return false;
    for (auto &user : q->users) {
        if (user.cell == nullptr || !is_fabric_ahb_request_control(ctx, user.cell))
            continue;
        const char *expected_bel = fabric_ahb_independent_source_bel(ctx, user.cell);
        if (expected_bel != nullptr && candidate_name == expected_bel)
            return true;
    }
    return false;
}

static bool is_exact_fabric_ahb_haddr2_register(Context *ctx, NetInfo *net)
{
    if (net == nullptr || net->driver.cell == nullptr || net->driver.port != ctx->id("Q"))
        return false;
    CellInfo *driver = net->driver.cell;
    if (driver->type != ctx->id("GENERIC_SLICE") ||
        int_or_default(driver->params, ctx->id("FF_USED"), 0) != 1)
        return false;
    auto requested = driver->attrs.find(ctx->id("BEL"));
    return requested != driver->attrs.end() &&
           requested->second.as_string() == "X18Y9_SLICE15";
}

static bool is_exact_fabric_ahb_haddr2_source_at(Context *ctx, CellInfo *driver,
                                                  BelId candidate)
{
    if (driver->type != ctx->id("GENERIC_SLICE") ||
        int_or_default(driver->params, ctx->id("FF_USED"), 0) != 1 ||
        ctx->getBelName(candidate).str(ctx) != "X18Y9_SLICE15")
        return false;
    auto requested = driver->attrs.find(ctx->id("BEL"));
    if (requested != driver->attrs.end())
        return requested->second.as_string() == "X18Y9_SLICE15";
    return driver->bel == candidate;
}

static bool is_exact_fabric_ahb_haddr29_hsel_register(Context *ctx, NetInfo *net)
{
    if (net == nullptr || net->driver.cell == nullptr || net->driver.port != ctx->id("Q"))
        return false;
    CellInfo *driver = net->driver.cell;
    if (driver->type != ctx->id("GENERIC_SLICE") ||
        int_or_default(driver->params, ctx->id("FF_USED"), 0) != 1)
        return false;
    auto requested = driver->attrs.find(ctx->id("BEL"));
    bool exact_bel = requested != driver->attrs.end() ?
            requested->second.as_string() == "X14Y7_SLICE14" :
            driver->bel != BelId() &&
                    ctx->getBelName(driver->bel).str(ctx) == "X14Y7_SLICE14";
    if (!exact_bel)
        return false;
    bool has_hsel = false, has_haddr29 = false;
    for (auto &user : net->users) {
        if (user.cell == nullptr)
            continue;
        has_hsel |= user.cell->type == ctx->id("MCU_SLAVE_AHB_HSEL");
        if (user.cell->type == ctx->id("MCU_DOUT")) {
            int bit = -1;
            has_haddr29 |= mcu_dout_lane(user.cell->name.str(ctx), bit) == LANE_SHADDR &&
                           bit == 29;
        }
    }
    return has_hsel && has_haddr29;
}

static bool is_exact_fabric_ahb_payload_safe_low(Context *ctx, NetInfo *net,
                                                  CellInfo *&source)
{
    if (net == nullptr || net->driver.cell == nullptr ||
        (net->driver.port != ctx->id("F0") && net->driver.port != ctx->id("F2")))
        return false;
    CellInfo *driver = net->driver.cell;
    if (driver->type != ctx->id("AGRV2K_DUAL_LUT_CONST") ||
        int_or_default(driver->params, ctx->id("VALUE"), 1) != 0)
        return false;
    auto requested = driver->attrs.find(ctx->id("BEL"));
    if (requested == driver->attrs.end() ||
        requested->second.as_string() != "X14Y12_DUAL_SLICE0")
        return false;
    if (source != nullptr && source != driver)
        return false;
    source = driver;
    return true;
}

static void guard_fabric_ahb_dynamic_payload(Context *ctx)
{
    struct Payload {
        McuDoutLane lane;
        int bit;
        NetInfo *net;
    };
    std::vector<Payload> payload;
    NetInfo *haddr2 = nullptr;
    NetInfo *haddr29 = nullptr;
    NetInfo *hsel = nullptr;
    NetInfo *hsize0 = nullptr;
    NetInfo *hsize2 = nullptr;
    CellInfo *hsize0_cell = nullptr;
    CellInfo *hsize2_cell = nullptr;
    for (auto &item : ctx->cells) {
        CellInfo *cell = item.second.get();
        if (cell->type == ctx->id("MCU_SLAVE_AHB_HSEL"))
            hsel = cell->getPort(ctx->id("DOUT"));
        if (cell->type == ctx->id("MCU_SLAVE_AHB_HSIZE0")) {
            hsize0 = cell->getPort(ctx->id("DOUT"));
            hsize0_cell = cell;
        }
        if (cell->type == ctx->id("MCU_SLAVE_AHB_HSIZE2")) {
            hsize2 = cell->getPort(ctx->id("DOUT"));
            hsize2_cell = cell;
        }
        if (cell->type != ctx->id("MCU_DOUT"))
            continue;
        int bit = -1;
        McuDoutLane lane = mcu_dout_lane(cell->name.str(ctx), bit);
        if (lane != LANE_SHADDR && lane != LANE_SHWDATA)
            continue;
        NetInfo *net = cell->getPort(ctx->id("DOUT"));
        payload.push_back({lane, bit, net});
        if (lane == LANE_SHADDR && bit == 2)
            haddr2 = net;
        if (lane == LANE_SHADDR && bit == 29)
            haddr29 = net;
    }
    if (haddr2 == nullptr)
        return;

    std::set<std::pair<int, int>> safe_lanes;
    CellInfo *complete_safe_source = nullptr;
    bool complete_safe_low = payload.size() == 64;
    for (const Payload &item : payload) {
        complete_safe_low &= item.bit >= 0 && item.bit < 32;
        complete_safe_low &= safe_lanes.insert({int(item.lane), item.bit}).second;
        complete_safe_low &=
                is_exact_fabric_ahb_payload_safe_low(ctx, item.net, complete_safe_source);
    }
    complete_safe_low &= safe_lanes.size() == 64 && complete_safe_source != nullptr;
    if (complete_safe_low)
        return; // the existing complete shared-safe-low composition is unchanged

    if (!is_exact_fabric_ahb_haddr2_register(ctx, haddr2))
        log_error("agrv2k: fabric AHB request payload matches neither the complete exact "
                  "shared safe-low tree nor a qualified HADDR[2] dynamic profile; arbitrary "
                  "dynamic payload topologies fail closed\n");

    bool haddr29_safe_low = false, haddr29_shared_hsel = false;
    CellInfo *safe_source = nullptr;
    if (haddr29 != nullptr) {
        haddr29_safe_low =
                is_exact_fabric_ahb_payload_safe_low(ctx, haddr29, safe_source);
        haddr29_shared_hsel = haddr29 == hsel &&
                is_exact_fabric_ahb_haddr29_hsel_register(ctx, haddr29);
    }
    if (!haddr29_safe_low && !haddr29_shared_hsel)
        log_error("agrv2k: dynamic fabric AHB HADDR[29] is admitted only on the exact "
                  "X14Y7_SLICE14 registered HSEL net; arbitrary SRAM-base payload "
                  "topologies fail closed\n");

    // CLAIM: mcu-ahb-haddr2-independent-register-oracle (agamemnon.engine.gate_claims)
    // CLAIM: mcu-ahb-haddr29-hsel-shared-register-oracle (agamemnon.engine.gate_claims)
    // The first profile has only exact HADDR[2] dynamic and 63 safe-low lanes.
    // The SRAM-base profile additionally shares HADDR[29] with the exact HSEL
    // register/net and branches HADDR[0]/HADDR[1] from the exact HSIZE[0]/
    // HSIZE[2] registered nets at backbone wires common to the retained route
    // tables; its other 60 payload endpoints stay on the qualified dual-output
    // safe-low tree. All route edges are directly decoded and byte-checked;
    // this is still a request routing vehicle, not a transaction or silicon
    // claim.
    bool haddr01_hsize_branches = haddr29_shared_hsel &&
            hsize0_cell != nullptr && hsize2_cell != nullptr &&
            is_exact_fabric_ahb_independent_ff(ctx, hsize0_cell, hsize0) &&
            is_exact_fabric_ahb_independent_ff(ctx, hsize2_cell, hsize2);
    std::set<std::pair<int, int>> lanes;
    bool exact = payload.size() == 64;
    for (const Payload &item : payload) {
        exact &= item.bit >= 0 && item.bit < 32;
        exact &= lanes.insert({int(item.lane), item.bit}).second;
        if (item.lane == LANE_SHADDR && item.bit == 2)
            exact &= item.net == haddr2;
        else if (item.lane == LANE_SHADDR && item.bit == 0 &&
                haddr01_hsize_branches)
            exact &= item.net == hsize0;
        else if (item.lane == LANE_SHADDR && item.bit == 1 &&
                haddr01_hsize_branches)
            exact &= item.net == hsize2;
        else if (item.lane == LANE_SHADDR && item.bit == 29)
            exact &= haddr29_safe_low ?
                    is_exact_fabric_ahb_payload_safe_low(ctx, item.net, safe_source) :
                    item.net == hsel;
        else
            exact &= is_exact_fabric_ahb_payload_safe_low(ctx, item.net, safe_source);
    }
    exact &= lanes.size() == 64 && safe_source != nullptr;
    if (!exact)
        log_error("agrv2k: qualified dynamic fabric AHB payload requires exact HADDR[2], "
                  "optional SRAM-base HADDR[29]/HSEL plus HADDR[0:1]/HSIZE branches, "
                  "all 64 endpoints, and every remaining lane on the X14Y12 safe-low "
                  "oracle\n");
    if (haddr29_shared_hsel)
        log_info("agrv2k: admitted exact HADDR[2], HADDR[29]/HSEL, and "
                 "HADDR[0:1]/HSIZE shared-source fabric AHB payload profile with 60 "
                 "safe-low lanes\n");
    else
        log_info("agrv2k: admitted one exact registered HADDR[2] source with 63 safe-low "
                 "fabric AHB payload lanes\n");
}

static void guard_fabric_ahb_request_controls(Context *ctx)
{
    std::vector<std::pair<CellInfo *, NetInfo *>> request_controls;
    NetInfo *shared = nullptr;
    bool shared_safe_low = true;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (!is_fabric_ahb_request_control(ctx, ci))
            continue;
        auto dout = ci->ports.find(ctx->id("DOUT"));
        NetInfo *net = dout == ci->ports.end() ? nullptr : dout->second.net;
        request_controls.push_back({ci, net});
        // CLAIM: mcu-ahb-request-control-shared-source-oracle (agamemnon.engine.gate_claims)
        // Only the pinned combinational safe-low source has a complete exact
        // simultaneous shared route.
        if (!is_exact_fabric_ahb_safe_low(ctx, net))
            shared_safe_low = false;
        if (shared != nullptr && shared != net)
            shared_safe_low = false;
        shared = net;
    }

    if (request_controls.empty())
        return;
    if (shared_safe_low) {
        log_info("agrv2k: admitted %d fabric AHB request control(s) on the exact shared safe-low "
                 "oracle\n", int(request_controls.size()));
        return;
    }

    // CLAIM: mcu-ahb-request-control-independent-ff-oracle (agamemnon.engine.gate_claims)
    // The only independently driven composition admitted here is the exact
    // eleven-register source placement whose simultaneous boundary selections
    // were directly decoded and byte-checked.  Requiring all eleven controls,
    // their Q ports, unique nets/cells, and the exact BEL map keeps partial or
    // generalized dynamic topologies fail-closed.
    std::set<NetInfo *> independent_nets;
    std::set<CellInfo *> independent_drivers;
    bool independent_ok = request_controls.size() == 11;
    for (auto &item : request_controls) {
        independent_ok &= is_exact_fabric_ahb_independent_ff(ctx, item.first, item.second);
        if (item.second != nullptr) {
            independent_nets.insert(item.second);
            if (item.second->driver.cell != nullptr)
                independent_drivers.insert(item.second->driver.cell);
        }
    }
    independent_ok &= independent_nets.size() == 11 && independent_drivers.size() == 11;
    if (!independent_ok)
        log_error("agrv2k: fabric AHB master request controls match neither the exact shared "
                  "safe-low oracle nor the exact eleven-source independent-FF oracle; dynamic "
                  "request topology is unqualified and fails closed\n");
    log_info("agrv2k: admitted all 11 fabric AHB request controls on the exact independent-FF "
             "oracle\n");
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
    guard_fabric_ahb_dynamic_payload(ctx);
    long nout = 0, nin = 0, nresp = 0, nrequest = 0, nslave = 0, npinned = 0;
    int typed_h25 = 0;
    std::vector<std::string> skipped_dout;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        std::string name = ci->name.str(ctx);
        std::string bn;
        bool is_slave_lane = false;
        const McuEndpointIntent typed_intent = mcu_endpoint_intent(ctx, ci);
        if (typed_intent.malformed())
            log_error("agrv2k: typed MCU endpoint intent on '%s' is malformed: %s\n",
                      name.c_str(), typed_intent.error.c_str());
        if (typed_intent.present)
            ++typed_h25;
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
            if (typed_intent.present) {
                // The exact semantic tuple, not the instance name, owns this
                // one capability. The loaded profile later proves that DIN69
                // really presents BufMUX07 and the mandatory InputMUX06 hop.
                lane = 69;
            } else {
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
            }
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
        } else if (is_fabric_ahb_request_control(ctx, ci)) {
            // Fabric-master request controls are also one-to-one typed hard
            // endpoints.  Bind them during pack so the exact independent
            // route can be reserved before the generic placer runs.
            BelId tb;
            int matches = 0;
            for (BelId cand : ctx->getBels())
                if (ctx->getBelType(cand) == ci->type) {
                    tb = cand;
                    ++matches;
                }
            if (matches != 1)
                log_error("agrv2k: expected one bel of type '%s' for request control '%s', got %d\n",
                          ci->type.c_str(ctx), name.c_str(), matches);
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
            else if (is_fabric_ahb_request_control(ctx, ci))
                ++nrequest;
            else
                ++nresp;
        } else {
            log_error("agrv2k: fixed MCU bus bel '%s' is unavailable for cell '%s'\n",
                      bn.c_str(), name.c_str());
        }
    }
    if (typed_h25 > 1)
        log_error("agrv2k: duplicate typed HWDATA25 endpoint intents are forbidden\n");
    if (nout)
        log_info("agrv2k: bound %ld MCU_DOUT exit cell(s) to hrdata lanes by name\n", nout);
    if (nslave)
        log_info("agrv2k: bound %ld MCU_DOUT cell(s) to slave_ahb haddr/hwdata boundary lanes "
                 "by name\n", nslave);
    if (npinned)
        log_info("agrv2k: %ld MCU_DOUT cell(s) carry an explicit BEL constraint\n", npinned);
    if (nin)
        log_info("agrv2k: bound %ld MCU_DIN entry cell(s) to AHB lanes by name\n", nin);
    if (typed_h25)
        log_info("agrv2k: bound one typed HWDATA25 endpoint by semantic identity\n");
    if (nresp)
        log_info("agrv2k: bound %ld AHB response control cell(s) to typed bels\n", nresp);
    if (nrequest)
        log_info("agrv2k: bound %ld fabric-master request control cell(s) to typed bels\n",
                 nrequest);
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

// ---- pack: bind the one logical external clock owner to the dedicated CLKIN
// BEL.  Source/profile admission is completed by AgrvImpl after this helper;
// this early step only resolves the generic-I/O bucket before placement.  Do
// not bind an arbitrary IOB merely because it reaches an inactive CLK port,
// and never override an explicit non-CLKIN BEL constraint.
static void pack_clk(Context *ctx)
{
    if (std::getenv("AGRV2K_NO_PACKCLK") != nullptr)
        return;
    std::set<NetInfo *> clk_nets;
    for (auto &cell : ctx->cells) {
        CellInfo *ci = cell.second.get();
        if (ci->type == ctx->id("GENERIC_SLICE")) {
            SharedClockRequirement requirement = shared_clock_requirement(ctx, ci);
            if (requirement.active())
                clk_nets.insert(requirement.clock);
        } else if (ci->type == ctx->id("ALTA_BRAM9K")) {
            for (const char *pn : {"Clk0", "Clk1"}) {
                NetInfo *net = ci->getPort(ctx->id(pn));
                if (net != nullptr)
                    clk_nets.insert(net);
            }
        }
    }
    // A later typed audit supplies the precise multi-owner diagnostic.  Avoid
    // making a source placement decision while the design is already invalid.
    if (clk_nets.size() != 1)
        return;
    NetInfo *owner = *clk_nets.begin();
    BelId clkin = ctx->getBelByName(IdStringList(ctx->id("CLKIN")));
    if (clkin == BelId() || !ctx->checkBelAvail(clkin))
        return;
    CellInfo *driver = owner->driver.cell;
    if (driver == nullptr || driver->type != ctx->id("GENERIC_IOB") ||
        owner->driver.port != ctx->id("O") || driver->bel != BelId())
        return;
    for (const char *key : {"BEL", "NEXTPNR_BEL"}) {
        auto fixed = driver->attrs.find(ctx->id(key));
        if (fixed != driver->attrs.end() && fixed->second.as_string() != "CLKIN")
            return;
    }
    ctx->bindBel(clkin, driver, STRENGTH_LOCKED);
    log_info("agrv2k: bound typed external clock owner '%s' to CLKIN\n",
             driver->name.c_str(ctx));
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

// Preserve the exact left-pad placements/corridors, but carry ordinary fixed
// output-pad intent into native placement.  For the ordinary family the
// already-fixed IOB, actual driver port, and admitted graph fully determine
// hard legality; selecting the nearest reachable slice here would discard
// other legal BELs and bypass the normal placer.
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
    int exact_bound = 0;
    std::set<CellInfo *> native_drivers;
    for (auto &c : ctx->cells) {
        CellInfo *io = c.second.get();
        if (io->type != ctx->id("GENERIC_IOB") || io->bel == BelId())
            continue;
        NetInfo *net = io->getPort(ctx->id("I"));
        if (net == nullptr || net->driver.cell == nullptr)
            continue;
        CellInfo *drv = net->driver.cell;
        if (drv->type != ctx->id("GENERIC_SLICE"))
            continue;
        const bool driver_preplaced = drv->bel != BelId();
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
        // The silicon-positive pintest2 vendor oracle supplies one complete
        // conducting corridor per left pad.  N5.5 keeps the exact source BEL
        // and Q endpoint, but router2 now negotiates the typed 36-PIP class.
        int left_z = -1;
        std::string target_name = ctx->getWireName(target).str(ctx);
        if (std::sscanf(target_name.c_str(), "X0Y4_IOMUX%d", &left_z) == 1 &&
                left_z >= 0 && left_z <= 3 && left_corridor.count(left_z)) {
            if (driver_preplaced)
                continue; // preserve the legacy fixed-left behavior unchanged
            static const char *source_bels[4] = {
                "X14Y11_SLICE4", "X14Y11_SLICE5", "X14Y11_SLICE6", "X14Y11_SLICE7"
            };
            BelId exact_bel = ctx->getBelByName(IdStringList(ctx->id(source_bels[left_z])));
            if (exact_bel == BelId() || !ctx->checkBelAvail(exact_bel))
                log_error("agrv2k: left-pad source BEL %s is unavailable\n", source_bels[left_z]);
            if (net->driver.port != ctx->id("Q"))
                log_error("agrv2k: PIN_%d typed left output requires exact %s.Q driver\n",
                          25 + left_z, source_bels[left_z]);
            ctx->bindBel(exact_bel, drv, STRENGTH_LOCKED);
            drv->attrs[ctx->id("AGRV2K_IO_PINPACKED")] = Property(1);
            ++exact_bound;
            log_info("agrv2k: fixed PIN_%d driver '%s' to %s.Q; typed corridor deferred to router2\n",
                     25 + left_z, drv->name.c_str(ctx), source_bels[left_z]);
            continue;
        }
        set_native_endpoint_mode(ctx, drv, NativeEndpointMode::IOB_OUTPUT);
        native_drivers.insert(drv);
        log_info("agrv2k: native IOB_OUTPUT endpoint records driver '%s' for pad '%s' "
                 "for %s legality\n", drv->name.c_str(ctx), io->name.c_str(ctx),
                 driver_preplaced ? "user-fixed" : "ordinary-placement");
    }
    log_info("agrv2k: output endpoints retained %d exact left-pad driver(s) and "
             "deferred %d native driver(s)\n", exact_bound, int(native_drivers.size()));
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
                    u.port != ctx->id("Clk0") && u.port != ctx->id("Clk1") &&
                    !native_direct_d_pool_cell(ctx, u.cell))
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
    std::set<CellInfo *> native_consumers;
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
            if (sink == nullptr || sink->type != ctx->id("GENERIC_SLICE"))
                continue;
            if (native_direct_d_pool_cell(ctx, sink))
                continue; // HeAP owns native direct-D placement; router2 owns this ingress
            const bool direct_native_input =
                    int_or_default(sink->params, ctx->id("FF_USED"), 0) == 0 &&
                    !sink->attrs.count(ctx->id("AGRV2K_PAD_INPUT_IDENTITY")) &&
                    !sink->attrs.count(ctx->id("agamemnon_pad_sync_stage")) &&
                    !sink->attrs.count(ctx->id("agamemnon_pad_sync_group")) &&
                    !sink->attrs.count(ctx->id("AGRV2K_IO_PINPACKED")) &&
                    !sink->attrs.count(native_endpoint_mode_attr(ctx));
            const bool native_pad_identity =
                    sink->attrs.count(ctx->id("AGRV2K_PAD_INPUT_IDENTITY")) &&
                    std::getenv("AGRV2K_INPUT_SLICE") == nullptr &&
                    std::getenv("AGRV2K_INPUT_TILE") == nullptr &&
                    !sink->attrs.count(native_endpoint_mode_attr(ctx)) &&
                    pad_input_identity_shape_error(ctx, sink).empty();
            if (sink->bel != BelId()) {
                if (direct_native_input) {
                    set_native_endpoint_mode(ctx, sink, NativeEndpointMode::IOB_INPUT);
                    native_consumers.insert(sink);
                    log_info("agrv2k: native IOB_INPUT endpoint records consumer '%s'.%s "
                             "for pad '%s' for user-fixed legality\n",
                             sink->name.c_str(ctx), u.port.c_str(ctx), io->name.c_str(ctx));
                }
                continue; // retain every legacy preplaced special-input behavior
            }
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
                    // Odd sites remain outside the live conservative
                    // xbar-conduction-even-slot-shape claim.  The exact
                    // registered/identity residual also excludes slot 0 for
                    // its separately isolated Qin-feedback failure; a direct
                    // combinational native consumer does not inherit that
                    // registered-only slot-0 restriction.
                    if ((bloc.z & 1) != 0 ||
                        (!direct_native_input && bloc.z == 0))
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

            // The existing input pin already reaches at least one admissible
            // combinational slice.  Record that fixed IOB.O relation and let
            // the ordinary placer choose among every reachable even-slot BEL.
            // Permuted LUT inputs and registered or synchronizer roots remain
            // in the exact legacy family below.  An exact generated pad
            // identity uses the same typed IOB_INPUT contract as an ordinary
            // direct consumer, but keeps its stricter nonzero/site exclusions.
            if (chosen != BelId() &&
                (direct_native_input || native_pad_identity)) {
                set_native_endpoint_mode(ctx, sink, NativeEndpointMode::IOB_INPUT);
                native_consumers.insert(sink);
                if (native_pad_identity)
                    log_info("agrv2k: native IOB_INPUT endpoint records pad-isolation "
                             "consumer '%s'.%s for pad '%s' for placement legality\n",
                             sink->name.c_str(ctx), u.port.c_str(ctx),
                             io->name.c_str(ctx));
                else
                    log_info("agrv2k: native IOB_INPUT endpoint records consumer '%s'.%s "
                             "for pad '%s' for ordinary-placement legality\n",
                             sink->name.c_str(ctx), u.port.c_str(ctx),
                             io->name.c_str(ctx));
                continue;
            }

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
    log_info("agrv2k: input endpoints retained %d exact consumer(s) and deferred "
             "%d native consumer(s)\n", bound, int(native_consumers.size()));
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
            !native_direct_d_pool_cell(ctx, ci) &&
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

struct SoftRippleRegionWitness {
    bool loaded = false;
    int min_x = 0, max_x = 0, min_y = 0, max_y = 0;
    int decoded_builds = 0, chain_stages = 0, max_slices_per_tile = 0;
};

// Recognize a decomposed soft-ripple vector entirely from packed connectivity.
// Each stage is exactly two combinational slices with identical input nets and
// two or three bounded registered inputs. One member's output must feed both
// members of the unique successor stage, producing one unbranched directed
// chain of the decoded length. Names, hierarchy, source paths, and net labels
// do not participate. Pair adjacent stages into one movable even-slot cluster
// so every other ripple seam is guaranteed to remain on a local crossbar.
static void pack_shared_fanin_clusters(Context *ctx, const SoftRippleRegionWitness &witness)
{
    if (std::getenv("AGRV2K_SOFT_RIPPLE_LEGACY") != nullptr) {
        log_info("agrv2k: soft-ripple clustering disabled for legacy A/B control\n");
        return;
    }
    if (!witness.loaded)
        log_error("agrv2k: soft-ripple clustering requires witnessed placement bounds\n");

    const IdString slice = ctx->id("GENERIC_SLICE");
    const IdString ff_used = ctx->id("FF_USED");
    const IdString init = ctx->id("INIT");
    auto eligible = [&](CellInfo *cell) {
        return cell != nullptr && cell->type == slice && cell->bel == BelId() &&
               cell->cluster == ClusterId() && !cell->attrs.count(ctx->id("BEL")) &&
               !native_direct_d_pool_cell(ctx, cell) &&
               !cell->ports.count(ctx->id("CIN")) && !cell->ports.count(ctx->id("COUT"));
    };
    auto registered = [&](CellInfo *cell) {
        return eligible(cell) && int_or_default(cell->params, ff_used, 0) != 0;
    };
    auto combinational = [&](CellInfo *cell) {
        return eligible(cell) && int_or_default(cell->params, ff_used, 0) == 0;
    };
    auto constant_slice = [&](CellInfo *cell) {
        if (!combinational(cell))
            return false;
        int value = int_or_default(cell->params, init, 0);
        return value == 0 || value == 0xffff;
    };
    auto fabric_users = [&](NetInfo *net) {
        std::set<CellInfo *> users;
        if (net != nullptr)
            for (auto &user : net->users)
                if (user.cell != nullptr && user.cell != net->driver.cell &&
                    user.cell->type == slice)
                    users.insert(user.cell);
        return users;
    };
    auto fabric_fanout = [&](NetInfo *net) { return int(fabric_users(net).size()); };
    auto input_nets = [&](CellInfo *cell) {
        std::set<NetInfo *> nets;
        for (auto &port : cell->ports)
            if (port.second.type == PORT_IN && port.second.net != nullptr &&
                port.first != ctx->id("CLK"))
                nets.insert(port.second.net);
        return nets;
    };

    std::map<std::set<NetInfo *>, std::vector<CellInfo *>> identical_inputs;
    for (auto &entry : ctx->cells) {
        CellInfo *cell = entry.second.get();
        if (!combinational(cell) || constant_slice(cell))
            continue;
        std::set<NetInfo *> nets = input_nets(cell);
        if (!nets.empty())
            identical_inputs[nets].push_back(cell);
    }

    struct Stage {
        CellInfo *first;
        CellInfo *second;
        std::set<CellInfo *> registered_inputs;
    };
    std::vector<Stage> stages;
    for (auto &group : identical_inputs) {
        if (group.second.size() != 2)
            continue;
        std::set<CellInfo *> drivers;
        for (NetInfo *net : group.first)
            if (registered(net->driver.cell) && fabric_fanout(net) >= 2 &&
                fabric_fanout(net) <= 3)
                drivers.insert(net->driver.cell);
        if (drivers.size() < 2 || drivers.size() > 3)
            continue;
        stages.push_back({group.second[0], group.second[1], std::move(drivers)});
    }
    if (stages.empty())
        return;

    std::unordered_map<CellInfo *, int> stage_by_cell;
    for (size_t i = 0; i < stages.size(); ++i) {
        stage_by_cell[stages[i].first] = int(i);
        stage_by_cell[stages[i].second] = int(i);
    }
    std::vector<std::set<int>> successors(stages.size()), predecessors(stages.size());
    for (size_t source = 0; source < stages.size(); ++source) {
        for (CellInfo *cell : {stages[source].first, stages[source].second}) {
            std::set<NetInfo *> outputs;
            for (auto &port : cell->ports) {
                NetInfo *net = port.second.net;
                if (port.second.type != PORT_OUT || net == nullptr ||
                    !outputs.insert(net).second)
                    continue;
                std::map<int, std::set<CellInfo *>> reached;
                for (auto &user : net->users) {
                    auto target = stage_by_cell.find(user.cell);
                    if (target != stage_by_cell.end() && target->second != int(source))
                        reached[target->second].insert(user.cell);
                }
                for (auto &target : reached)
                    if (target.second.size() == 2) {
                        successors[source].insert(target.first);
                        predecessors[target.first].insert(int(source));
                    }
            }
        }
    }

    std::vector<int> capture;
    std::set<int> visited;
    for (size_t origin = 0; origin < stages.size(); ++origin) {
        if (!visited.insert(int(origin)).second)
            continue;
        std::vector<int> component;
        std::deque<int> queue{int(origin)};
        while (!queue.empty()) {
            int current = queue.front();
            queue.pop_front();
            component.push_back(current);
            std::set<int> neighbors = successors[current];
            neighbors.insert(predecessors[current].begin(), predecessors[current].end());
            for (int neighbor : neighbors)
                if (visited.insert(neighbor).second)
                    queue.push_back(neighbor);
        }

        int edges = 0, source = -1, sources = 0, sinks = 0;
        bool simple = true;
        std::set<int> component_set(component.begin(), component.end());
        for (int current : component) {
            int outgoing = 0, incoming = 0;
            for (int target : successors[current])
                outgoing += component_set.count(target) != 0;
            for (int parent : predecessors[current])
                incoming += component_set.count(parent) != 0;
            edges += outgoing;
            if (incoming == 0) {
                source = current;
                ++sources;
            }
            sinks += outgoing == 0;
            simple = simple && incoming <= 1 && outgoing <= 1;
        }
        simple = simple && edges == int(component.size()) - 1 && sources == 1 && sinks == 1;
        if (!simple || int(component.size()) != witness.chain_stages)
            continue;

        std::vector<int> ordered;
        int current = source;
        while (current >= 0) {
            ordered.push_back(current);
            int next = -1;
            for (int target : successors[current])
                if (component_set.count(target)) {
                    next = target;
                    break;
                }
            current = next;
        }
        if (int(ordered.size()) != witness.chain_stages || !capture.empty()) {
            log_info("agrv2k: ambiguous soft-ripple topology; leaving placement unchanged\n");
            return;
        }
        capture = std::move(ordered);
    }
    if (capture.empty())
        return;

    // Orient the two same-input cells by a rename-invariant structural key.
    // A true tie is physically and logically ambiguous, so fail closed rather
    // than allowing cell-map iteration order to choose a different footprint.
    auto cell_key = [&](CellInfo *cell) {
        int fanout = 0, registered_users = 0;
        std::set<NetInfo *> outputs;
        for (auto &port : cell->ports) {
            NetInfo *net = port.second.net;
            if (port.second.type != PORT_OUT || net == nullptr || !outputs.insert(net).second)
                continue;
            fanout += fabric_fanout(net);
            for (CellInfo *user : fabric_users(net))
                registered_users += registered(user);
        }
        return std::make_tuple(fanout, registered_users,
                               int_or_default(cell->params, init, 0));
    };
    std::vector<std::pair<CellInfo *, CellInfo *>> oriented;
    for (int stage_index : capture) {
        CellInfo *first = stages[stage_index].first;
        CellInfo *second = stages[stage_index].second;
        auto first_key = cell_key(first), second_key = cell_key(second);
        if (first_key == second_key) {
            log_info("agrv2k: symmetric soft-ripple stage; leaving placement unchanged\n");
            return;
        }
        if (first_key < second_key)
            std::swap(first, second);
        oriented.push_back({first, second});
    }

    // The decoded envelope describes the ripple consumers and their direct
    // registered producers. Do not expand it transitively: second-order data
    // neighbors were not witnessed inside this placement envelope.
    auto region_eligible = [&](CellInfo *cell) {
        return eligible(cell) && !constant_slice(cell) && cell->region == nullptr;
    };
    std::set<CellInfo *> region_cells;
    auto add_region_cell = [&](CellInfo *cell) -> bool {
        if (!region_eligible(cell))
            return false;
        region_cells.insert(cell);
        return true;
    };
    for (int stage_index : capture) {
        if (!add_region_cell(stages[stage_index].first) ||
            !add_region_cell(stages[stage_index].second)) {
            log_info("agrv2k: soft-ripple consumer already constrained; "
                     "leaving placement unchanged\n");
            return;
        }
        for (CellInfo *driver : stages[stage_index].registered_inputs) {
            if (!add_region_cell(driver)) {
                log_info("agrv2k: soft-ripple direct producer already constrained; "
                         "leaving placement unchanged\n");
                return;
            }
        }
    }
    const int capacity = (witness.max_x - witness.min_x + 1) *
                         (witness.max_y - witness.min_y + 1) *
                         witness.max_slices_per_tile;
    if (int(region_cells.size()) > capacity) {
        log_info("agrv2k: soft-ripple semantic target exceeds witnessed capacity; "
                 "leaving placement unchanged\n");
        return;
    }

    const IdString region = ctx->id("AGRV2K_SOFT_RIPPLE_REGION");
    ctx->createRectangularRegion(region, witness.min_x, witness.min_y,
                                 witness.max_x, witness.max_y);
    int clusters = 0;
    for (int first_stage = 0; first_stage < witness.chain_stages; first_stage += 2) {
        std::vector<std::pair<CellInfo *, Loc>> shape{
                {oriented[first_stage].first, Loc(0, 0, 0)},
                {oriented[first_stage].second, Loc(0, 0, 2)},
                {oriented[first_stage + 1].first, Loc(0, 0, 4)},
                {oriented[first_stage + 1].second, Loc(0, 0, 6)},
        };
        make_relative_cluster(ctx, shape, false);
        ++clusters;
    }
    for (CellInfo *cell : region_cells)
        ctx->constrainCellToRegion(cell->name, region);
    const int consumers = witness.chain_stages * 2;
    log_info("agrv2k: captured %d-stage soft-ripple topology as %d paired-stage "
             "cluster(s) in witnessed Region X%d..%d Y%d..%d "
             "(%d semantic cells: %d consumers, %d direct registered producers)\n",
             witness.chain_stages, clusters, witness.min_x, witness.max_x,
             witness.min_y, witness.max_y, int(region_cells.size()), consumers,
             int(region_cells.size()) - consumers);
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
            native_direct_d_pool_cell(ctx, cell) ||
            cell->ports.count(ctx->id("CIN")) || cell->ports.count(ctx->id("COUT")))
            return false;
        const McuEndpointRequirement endpoint =
                mcu_endpoint_requirement(ctx, cell);
        if (endpoint.malformed())
            log_error("agrv2k: MCU relative clustering rejects malformed typed endpoint "
                      "consumer '%s': %s\n", ctx->nameOf(cell), endpoint.error.c_str());
        if (endpoint.active)
            return false; // retire only the typed HWDATA25 one-cell sentinel cluster
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
        make_relative_cluster(ctx, shape, false);
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
        const NativeEndpointRequirement endpoint =
                native_endpoint_requirement(ctx, ci);
        if (endpoint.malformed())
            log_error("agrv2k: DENSE placement rejects malformed native endpoint on '%s': %s\n",
                      ctx->nameOf(ci), endpoint.error.c_str());
        if (endpoint.active())
            continue; // diagnostic dense packing must not consume native endpoint placement
        const McuEndpointRequirement mcu_endpoint =
                mcu_endpoint_requirement(ctx, ci);
        if (mcu_endpoint.malformed())
            log_error("agrv2k: DENSE placement rejects malformed typed MCU endpoint on '%s': %s\n",
                      ctx->nameOf(ci), mcu_endpoint.error.c_str());
        if (mcu_endpoint.active)
            continue; // typed HWDATA25 direct consumer belongs to native placement
        if (native_direct_d_pool_cell(ctx, ci))
            continue; // native direct-D allocation belongs to HeAP
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
        auto it = placements.find(ci->name.str(ctx));
        if (it == placements.end())
            continue;
        if (native_direct_d_pool_cell(ctx, ci))
            log_error("agrv2k: replay BEL map names native direct-D member '%s'; "
                      "native members must be allocated only by HeAP\n",
                      ci->name.c_str(ctx));
        if (ci->type != ctx->id("GENERIC_SLICE") || ci->bel != BelId())
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
        if (native_direct_d_pool_cell(ctx, ci))
            log_error("agrv2k: replay BEL map names native direct-D member '%s'; "
                      "native members must be allocated only by HeAP\n",
                      ci->name.c_str(ctx));
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

// Validate the whole native direct-D allocation, not merely each cell.  The
// four sites are individually qualified, but only one-, two-, and three-cell
// compositions are admitted; the observed four-cell composition set an extra
// static bit.  Once any inferred member opts into the native pool, every
// direct-D cell in the design participates in this exact composition.
static void validate_native_direct_d_pool(Context *ctx, bool require_bound)
{
    std::vector<CellInfo *> native_members;
    std::vector<CellInfo *> direct_members;
    int expected = -1;
    for (auto &entry : ctx->cells) {
        CellInfo *cell = entry.second.get();
        if (cell->type != ctx->id("GENERIC_SLICE"))
            continue;
        const RegisterInputRequirement input = register_input_requirement(ctx, cell);
        if (input.mode == RegisterInputMode::DIRECT_D_I3)
            direct_members.push_back(cell);
        if (!native_direct_d_pool_cell(ctx, cell))
            continue;
        native_members.push_back(cell);
        if (input.malformed() || input.mode != RegisterInputMode::DIRECT_D_I3)
            log_error("agrv2k: native direct-D pool member '%s' is not a valid "
                      "DIRECT_D_I3 cell: %s\n", ctx->nameOf(cell),
                      input.malformed() ? input.error.c_str() : "wrong register-input mode");
        std::string error;
        const int count = native_direct_d_pool_count(ctx, cell, error);
        if (count < 0)
            log_error("agrv2k: malformed native direct-D pool member '%s': %s\n",
                      ctx->nameOf(cell), error.c_str());
        if (expected < 0)
            expected = count;
        else if (expected != count)
            log_error("agrv2k: native direct-D pool members disagree on composition count "
                      "(%d versus %d at '%s')\n", expected, count, ctx->nameOf(cell));
        auto origin = cell->attrs.find(ctx->id("agamemnon_direct_d_origin"));
        if (origin == cell->attrs.end() ||
            !origin->second.is_string ||
            origin->second.as_string() != "qin-pack-inferred-own-q")
            log_error("agrv2k: native direct-D pool member '%s' lacks exact inferred "
                      "own-Q provenance\n", ctx->nameOf(cell));
        if (!require_bound &&
            (cell->bel != BelId() || cell->attrs.count(ctx->id("BEL"))))
            log_error("agrv2k: native direct-D pool member '%s' carries a fixed BEL; "
                      "native allocation must remain unbound for HeAP\n", ctx->nameOf(cell));
        if (!require_bound &&
            (cell->cluster != ClusterId() || cell->region != nullptr))
            log_error("agrv2k: native direct-D pool member '%s' already owns an incompatible "
                      "cluster or Region constraint\n", ctx->nameOf(cell));
    }
    if (native_members.empty())
        return; // retained explicit and legacy direct-D footprints are unchanged
    if (expected < 1 || expected > 3 || int(direct_members.size()) != expected)
        log_error("agrv2k: native direct-D composition declares %d cell(s), but the design "
                  "contains %d DIRECT_D_I3 cell(s); only exact 1..3-cell compositions are "
                  "qualified\n", expected, int(direct_members.size()));

    if (!require_bound) {
        // This coarse one-tile Region is placement convergence metadata, not
        // site admission.  The hot validity predicate below remains the hard
        // z=4..7/F/Q/I3 gate, while avoiding a device-wide HeAP search for a
        // resource with only four legal BELs.
        const IdString region = ctx->id("AGRV2K_NATIVE_DIRECT_D_REGION");
        if (ctx->region.count(region))
            log_error("agrv2k: native direct-D Region name already exists; refusing to "
                      "overwrite AGRV2K_NATIVE_DIRECT_D_REGION\n");
        ctx->createRectangularRegion(region, 14, 11, 14, 11);
        for (CellInfo *cell : native_members)
            ctx->constrainCellToRegion(cell->name, region);
        log_info("agrv2k: admitted %d-cell native direct-D composition for HeAP allocation "
                 "over X14Y11_SLICE4..7\n", expected);
        return;
    }

    std::set<int> occupied;
    for (CellInfo *cell : direct_members) {
        if (cell->bel == BelId())
            log_error("agrv2k: pre-route DRC rejects native direct-D composition: '%s' "
                      "has no bound BEL\n", ctx->nameOf(cell));
        if (!native_direct_d_pool_site(ctx, cell->bel))
            log_error("agrv2k: pre-route DRC rejects native direct-D cell '%s' at %s: "
                      "the whole composition must use X14Y11_SLICE4..7\n",
                      ctx->nameOf(cell), ctx->nameOfBel(cell->bel));
        if (!occupied.insert(cell->bel.index).second)
            log_error("agrv2k: pre-route DRC rejects duplicate native direct-D site %s\n",
                      ctx->nameOfBel(cell->bel));
    }
    log_info("agrv2k: pre-route DRC matched %d native direct-D cell(s) to distinct "
             "X14Y11_SLICE4..7 sites\n", expected);
}

// Explicit user direct-D BEL constraints remain hard.  Inferred N5.4 pool
// members carry no BEL and are therefore deliberately left to HeAP.
static void pack_direct_d_bels(Context *ctx)
{
    int bound = 0;
    for (auto &kv : ctx->cells) {
        CellInfo *ci = kv.second.get();
        if (ci->type != ctx->id("GENERIC_SLICE") ||
            ci->attrs.count(ctx->id("agamemnon_direct_d_feedback")) == 0)
            continue;
        auto requested = ci->attrs.find(ctx->id("BEL"));
        if (native_direct_d_pool_cell(ctx, ci)) {
            if (requested != ci->attrs.end() || ci->bel != BelId())
                log_error("agrv2k: native direct-D member '%s' reached the explicit "
                          "direct-D BEL binder; replay and explicit BEL metadata are forbidden\n",
                          ci->name.c_str(ctx));
            continue;
        }
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
        log_info("agrv2k: bound %d explicit direct-D cell(s) to qualified BELs\n", bound);
}

// ---- pack: CONDUCTION-AWARE placer (AGRV2K_CONDPLACE). Backtracking-embed the post-pack cell graph onto
// the silicon-conducting tile graph so EVERY driver->consumer edge is same-tile or a proven directed
// inter-tile RMUX->RMUX hop (tile_adj from master_conduction). This is the OTHER half of the solve: with the
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
    auto conduct = [&](int source, int sink) -> bool {
        if (source == sink)
            return true;
        auto it = tile_adj.find(source);
        return it != tile_adj.end() && it->second.count(sink);
    };
    std::unordered_map<int, std::unordered_set<int>> tile_pred;
    for (auto &edge : tile_adj)
        for (int sink : edge.second)
            tile_pred[sink].insert(edge.first);
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
        const NativeEndpointRequirement endpoint =
                native_endpoint_requirement(ctx, ci);
        if (endpoint.malformed())
            log_error("agrv2k: CONDPLACE rejects malformed native endpoint on '%s': %s\n",
                      ctx->nameOf(ci), endpoint.error.c_str());
        if (endpoint.active())
            continue; // this family is deliberately owned by the ordinary placer
        const McuEndpointRequirement mcu_endpoint =
                mcu_endpoint_requirement(ctx, ci);
        if (mcu_endpoint.malformed())
            log_error("agrv2k: CONDPLACE rejects malformed typed MCU endpoint on '%s': %s\n",
                      ctx->nameOf(ci), mcu_endpoint.error.c_str());
        if (mcu_endpoint.active)
            continue; // typed HWDATA25 consumer is deliberately native-placed
        if (native_direct_d_pool_cell(ctx, ci))
            continue; // this family is deliberately owned by the ordinary placer
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
    // the small exact-embedding regime, select a compact capacity-complete region around the BRAM
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

        // Regional placement needs a capacity-complete candidate set. Do not
        // turn the directed routing graph into an undirected graph merely to
        // order it: the physical-distance order below is deterministic, while
        // actual producer->consumer preferences retain edge direction.
        std::vector<int> region = cand;

        // Sort by physical distance and expose only the minimum number of CAP-sized tiles;
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
                    score += (assign[nb] == t) ? 10000 : (conduct(t, assign[nb]) ? 1000 : 0);
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
            if (assign.count(d)) {
                addpref(assign[d]);
                auto it = tile_pred.find(assign[d]);
                if (it != tile_pred.end()) for (int n : it->second) addpref(n);
            }
        for (auto dr : indeps[ci])
            if (assign.count(dr)) {
                addpref(assign[dr]);
                auto it = tile_adj.find(assign[dr]);
                if (it != tile_adj.end()) for (int n : it->second) addpref(n);
            }
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
        // corresponding check back to this cell, so every local pair is covered.
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

    // N5.7A typed single-GCLK0 authority.  The generated catalogs bind exact
    // source identities and exact graph topology; the mutable design state
    // below is frozen after placement and used by router2's net-aware gate.
    struct ClockSourceProfile {
        std::string profile, source_class, cell_type, bel, port, root_wire;
        std::string entry_src, entry_dst, rate_policy, evidence;
        bool admitted = false;
        BelId bel_id;
        WireId root;
        PipId entry;
    };
    std::vector<ClockSourceProfile> clock_sources;
    std::string clock_source_catalog_digest, clock_topology_digest;
    WireId global_clock_spine;
    PipId global_clock_bram_root;
    std::vector<PipId> global_clock_bram_branches;
    std::unordered_map<int, PipId> global_clock_leaf_by_bel;
    std::unordered_set<int> global_clock_protected_pips;
    std::unordered_set<int> global_clock_protected_wires;
    std::unordered_set<int> global_clock_expected_pips;
    std::unordered_set<int> global_clock_expected_wires;
    std::vector<PipId> global_clock_expected_order;
    NetInfo *global_clock_owner = nullptr;
    const ClockSourceProfile *global_clock_source = nullptr;
    bool global_clock_owner_prepared = false;
    bool global_clock_resources_frozen = false;

    // N5.5 typed L48 left-output pilot.  These are existing graph resources,
    // not a new resource-key or selector claim.  Active lanes gain one exact
    // owner; inactive lane resources remain ordinary router2 resources.
    struct SpecialRouteLane {
        int index = -1;
        std::string pin, source_bel, source_port, sink_bel, sink_port;
        std::vector<PipId> pips;
        std::vector<WireId> wires;
        std::unordered_set<int> wire_indices;
        std::unordered_map<int, int> predecessor_by_dst;
        NetInfo *owner = nullptr;
    };
    bool special_routes_enabled = false;
    bool special_route_owners_frozen = false;
    std::string special_route_digest;
    std::vector<SpecialRouteLane> special_route_lanes;
    std::unordered_map<int, int> special_route_pip_lane;
    std::unordered_map<int, int> special_route_wire_lane;

    // N5.8A one-lane MCU endpoint profile. The exact source and first hop are
    // loaded from the runtime-fingerprinted capability table; router2 may
    // negotiate only the ordinary downstream tree for its semantic owner.
    struct McuEndpointProfile {
        bool loaded = false;
        std::string hard_bel, source_root, first_hop_dst;
        BelId bel;
        WireId root, after_first_hop;
        PipId first_hop;
        CellInfo *endpoint = nullptr;
        NetInfo *owner = nullptr;
    } mcu_endpoint_profile;
    bool mcu_endpoint_owner_frozen = false;

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
    // Router2 queries estimateDelay() from several worker threads. Protect the
    // shared LRU and consume cached vectors while the same lock is held so an
    // eviction cannot invalidate a returned reference in another worker.
    mutable std::mutex timing_cache_mutex;
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
    SoftRippleRegionWitness soft_ripple_region_witness;
    // K-hop conducting closure (directed BFS over tile_adj, K = AGRV2K_CONDPAIR_HOPS). The data mesh
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
    bool tiles_conduct(int source_x, int source_y, int sink_x, int sink_y) const
    {
        if (source_x == sink_x && source_y == sink_y)
            return true; // same tile: intra-tile crossbar (even-slot invariant guarantees the pair conducts)
        int source = tkey(source_x, source_y), sink = tkey(sink_x, sink_y);
        if (!tile_reach.empty()) {
            auto it = tile_reach.find(source);
            return it != tile_reach.end() && it->second.count(sink);
        }
        auto it = tile_adj.find(source);
        return it != tile_adj.end() && it->second.count(sink);
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

    void refresh_mcu_endpoint_owner(const char *phase, bool require_placement,
                                    bool freeze = false)
    {
        CellInfo *endpoint = nullptr;
        NetInfo *owner = nullptr;
        int typed = 0, active_sinks = 0;
        for (auto &entry : ctx->cells) {
            CellInfo *cell = entry.second.get();
            const McuEndpointIntent intent = mcu_endpoint_intent(ctx, cell);
            if (!intent.present)
                continue;
            ++typed;
            if (intent.malformed())
                log_error("agrv2k: %s rejects malformed typed MCU endpoint '%s': %s\n",
                          phase, ctx->nameOf(cell), intent.error.c_str());
            if (endpoint != nullptr && endpoint != cell)
                log_error("agrv2k: %s rejects duplicate typed HWDATA25 endpoints\n", phase);
            endpoint = cell;
            if (cell->bel != BelId() && cell->bel != mcu_endpoint_profile.bel)
                log_error("agrv2k: %s typed HWDATA25 endpoint '%s' is at %s, not %s\n",
                          phase, ctx->nameOf(cell), ctx->nameOfBel(cell->bel),
                          mcu_endpoint_profile.hard_bel.c_str());
            if (require_placement && cell->bel == BelId())
                log_error("agrv2k: %s typed HWDATA25 endpoint '%s' has no bound hard BEL\n",
                          phase, ctx->nameOf(cell));
            if (!intent.active)
                continue;
            if (intent.net->driver.cell != cell ||
                intent.net->driver.port != ctx->id("DIN"))
                log_error("agrv2k: %s typed HWDATA25 signal has a contradictory driver\n",
                          phase);
            owner = intent.net;
            for (auto &user : owner->users) {
                if (user.cell == nullptr)
                    continue;
                const McuEndpointRequirement requirement =
                        mcu_endpoint_requirement(ctx, user.cell);
                if (requirement.malformed() || !requirement.active ||
                    requirement.endpoint != cell || requirement.net != owner)
                    log_error("agrv2k: %s typed HWDATA25 sink '%s.%s' is malformed: %s\n",
                              phase, ctx->nameOf(user.cell), user.port.c_str(ctx),
                              requirement.error.c_str());
                ++active_sinks;
            }
        }
        if (typed > 1)
            log_error("agrv2k: %s found more than one typed HWDATA25 endpoint\n", phase);
        if (mcu_endpoint_owner_frozen &&
            (endpoint != mcu_endpoint_profile.endpoint ||
             owner != mcu_endpoint_profile.owner))
            log_error("agrv2k: %s changed the frozen typed HWDATA25 owner identity\n", phase);
        mcu_endpoint_profile.endpoint = endpoint;
        mcu_endpoint_profile.owner = owner;
        if (freeze)
            mcu_endpoint_owner_frozen = true;
        if (owner != nullptr)
            log_info("agrv2k: %s typed HWDATA25 owner '%s' has %d exact sink(s)%s\n",
                     phase, ctx->nameOf(owner), active_sinks,
                     freeze ? " and is frozen" : "");
    }

    bool mcu_endpoint_cell_admitted(CellInfo *cell, BelId candidate,
                                    bool explain_invalid) const
    {
        const McuEndpointRequirement requirement =
                mcu_endpoint_requirement(ctx, cell);
        if (requirement.malformed()) {
            if (explain_invalid)
                log_info("agrv2k validity: typed MCU endpoint consumer '%s' is malformed: %s\n",
                         ctx->nameOf(cell), requirement.error.c_str());
            return false;
        }
        if (!requirement.active)
            return true;
        if (!mcu_endpoint_profile.loaded ||
            ctx->getBelType(candidate) != ctx->id("GENERIC_SLICE") ||
            requirement.endpoint->bel != mcu_endpoint_profile.bel ||
            requirement.net != mcu_endpoint_profile.owner) {
            if (explain_invalid)
                log_info("agrv2k validity: typed HWDATA25 consumer '%s' lacks its exact "
                         "profile, source BEL, or net owner\n", ctx->nameOf(cell));
            return false;
        }
        for (IdString port : requirement.input_ports) {
            const std::string name = port.str(ctx);
            if (name.size() != 4 || name.rfind("I[", 0) != 0 ||
                name[2] < '0' || name[2] > '3' || name[3] != ']') {
                if (explain_invalid)
                    log_info("agrv2k validity: typed HWDATA25 consumer '%s' uses "
                             "incompatible port %s\n", ctx->nameOf(cell), name.c_str());
                return false;
            }
            WireId target = ctx->getBelPinWire(candidate, port);
            if (target == WireId() ||
                !reachable_from(mcu_endpoint_profile.after_first_hop).count(target.index)) {
                if (explain_invalid)
                    log_info("agrv2k validity: typed HWDATA25 first-hop class cannot reach "
                             "%s.%s for '%s'\n", ctx->nameOfBel(candidate), name.c_str(),
                             ctx->nameOf(cell));
                return false;
            }
        }
        return true;
    }

    bool mcu_endpoint_pip_legal(PipId pip, const NetInfo *net) const
    {
        if (!mcu_endpoint_profile.loaded || mcu_endpoint_profile.owner == nullptr)
            return true;
        WireId src = ctx->getPipSrcWire(pip);
        WireId dst = ctx->getPipDstWire(pip);
        if (pip == mcu_endpoint_profile.first_hop)
            return net == mcu_endpoint_profile.owner;
        if (src == mcu_endpoint_profile.root)
            return false; // the owner and every foreign net get only the exact first hop
        if (dst == mcu_endpoint_profile.after_first_hop ||
            src == mcu_endpoint_profile.after_first_hop ||
            dst == mcu_endpoint_profile.root)
            return net == mcu_endpoint_profile.owner;
        return true;
    }

    void audit_mcu_endpoint_routes(const char *phase, bool require_complete)
    {
        refresh_mcu_endpoint_owner(phase, require_complete, require_complete);
        NetInfo *owner = mcu_endpoint_profile.owner;
        if (owner == nullptr)
            return;
        NetInfo *first_owner = ctx->getBoundPipNet(mcu_endpoint_profile.first_hop);
        if (first_owner != nullptr && first_owner != owner)
            log_error("agrv2k: %s typed HWDATA25 first hop is owned by foreign net '%s'\n",
                      phase, ctx->nameOf(first_owner));
        if (require_complete && first_owner != owner)
            log_error("agrv2k: %s typed HWDATA25 route omits its mandatory first hop\n", phase);
        for (PipId pip : ctx->getPipsDownhill(mcu_endpoint_profile.root)) {
            NetInfo *bound = ctx->getBoundPipNet(pip);
            if (bound == owner && pip != mcu_endpoint_profile.first_hop)
                log_error("agrv2k: %s typed HWDATA25 owner uses a wrong/additional first hop %s\n",
                          phase, ctx->getPipName(pip).str(ctx).c_str());
            if (bound != nullptr && !mcu_endpoint_pip_legal(pip, bound))
                log_error("agrv2k: %s typed HWDATA25 protected first-hop class has a "
                          "foreign binding\n", phase);
        }
        if (!require_complete)
            return;
        int roots = 0, sinks = 0;
        for (const auto &wire : owner->wires)
            if (wire.second.pip == PipId()) {
                ++roots;
                if (wire.first != mcu_endpoint_profile.root)
                    log_error("agrv2k: %s typed HWDATA25 route has an extra/wrong root %s\n",
                              phase, ctx->getWireName(wire.first).str(ctx).c_str());
            }
        if (roots != 1)
            log_error("agrv2k: %s typed HWDATA25 route requires exactly one source root\n",
                      phase);
        for (auto &user : owner->users) {
            if (user.cell == nullptr)
                continue;
            ++sinks;
            if (user.cell->bel == BelId() ||
                !mcu_endpoint_cell_admitted(user.cell, user.cell->bel, true))
                log_error("agrv2k: %s typed HWDATA25 sink '%s' lacks an admitted BEL/input\n",
                          phase, ctx->nameOf(user.cell));
            WireId target = ctx->getBelPinWire(user.cell->bel, user.port);
            if (target == WireId() || ctx->getBoundWireNet(target) != owner)
                log_error("agrv2k: %s typed HWDATA25 route does not reach '%s.%s'\n",
                          phase, ctx->nameOf(user.cell), user.port.c_str(ctx));
        }
        if (sinks == 0)
            log_error("agrv2k: %s active typed HWDATA25 route has no sinks\n", phase);
        log_info("agrv2k: %s typed HWDATA25 route audit verified mandatory first hop, "
                 "one root, and %d sink(s)\n", phase, sinks);
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

    bool typed_carry_pip_exists(WireId source, WireId target,
                                bool local_only) const
    {
        if (source == WireId() || target == WireId())
            return false;
        for (PipId pip : ctx->getPipsDownhill(source)) {
            if (ctx->getPipDstWire(pip) != target)
                continue;
            const IdString type = ctx->getPipType(pip);
            if (type == ctx->id("CARRY") ||
                (!local_only && type == ctx->id("CARRY_SEAM")))
                return true;
        }
        return false;
    }

    // Validate a relative carry cluster as one prospective placement.  HeAP
    // may ask about any member first, so consulting only currently bound
    // neighbours makes legality placement-order dependent.  Derive the root
    // from the candidate member, materialise every expected member BEL, check
    // occupancy atomically, then prove each logical CIN edge on that complete
    // footprint.  N5.6A relative-z clusters admit only local typed CARRY PIPs;
    // legacy absolute-z long profiles retain their exact CARRY_SEAM edges.
    bool carry_cluster_footprint_valid(CellInfo *cell, BelId candidate,
                                       bool explain_invalid) const
    {
        if (cell->cluster == ClusterId())
            return true;
        std::vector<CellInfo *> members;
        CellInfo *root = nullptr;
        for (auto &entry : ctx->cells) {
            CellInfo *member = entry.second.get();
            if (member->cluster != cell->cluster)
                continue;
            members.push_back(member);
            if (member->name == cell->cluster)
                root = member;
        }
        if (root == nullptr || members.empty()) {
            if (explain_invalid)
                log_info("agrv2k validity: carry cell '%s' has an incomplete cluster identity\n",
                         ctx->nameOf(cell));
            return false;
        }
        const bool absolute_z = root->constr_abs_z;
        const Loc candidate_loc = ctx->getBelLocation(candidate);
        if (cell->constr_abs_z != absolute_z ||
            (absolute_z && candidate_loc.z != cell->constr_z)) {
            if (explain_invalid)
                log_info("agrv2k validity: carry cell '%s' at %s violates its cluster z mode\n",
                         ctx->nameOf(cell), ctx->nameOfBel(candidate));
            return false;
        }
        const Loc root_loc(candidate_loc.x - cell->constr_x,
                           candidate_loc.y - cell->constr_y,
                           absolute_z ? root->constr_z
                                      : candidate_loc.z - cell->constr_z);
        std::unordered_map<CellInfo *, BelId> expected;
        std::unordered_set<int> occupied_locations;
        std::set<int> relative_z;
        for (CellInfo *member : members) {
            if (member->constr_abs_z != absolute_z)
                return false;
            const Loc loc(root_loc.x + member->constr_x,
                          root_loc.y + member->constr_y,
                          absolute_z ? member->constr_z
                                     : root_loc.z + member->constr_z);
            BelId bel = ctx->getBelByLocation(loc);
            if (bel == BelId() ||
                ctx->getBelType(bel) != ctx->id("GENERIC_SLICE") ||
                !occupied_locations.insert(bel.index).second) {
                if (explain_invalid)
                    log_info("agrv2k validity: carry cluster rooted at X%dY%dZ%d has an "
                             "unavailable or duplicate member X%dY%dZ%d\n",
                             root_loc.x, root_loc.y, root_loc.z,
                             loc.x, loc.y, loc.z);
                return false;
            }
            CellInfo *occupant = ctx->getBoundBelCell(bel);
            if (occupant != nullptr && occupant != member) {
                if (explain_invalid)
                    log_info("agrv2k validity: carry cluster member '%s' requires occupied %s\n",
                             ctx->nameOf(member), ctx->nameOfBel(bel));
                return false;
            }
            for (auto &reservation_entry : ctx->cells) {
                CellInfo *reserved_by = reservation_entry.second.get();
                if (reserved_by->cluster == cell->cluster)
                    continue;
                auto requested = reserved_by->attrs.find(ctx->id("BEL"));
                if (requested == reserved_by->attrs.end())
                    continue;
                BelId reserved = ctx->getBelByName(
                        IdStringList(ctx->id(requested->second.as_string())));
                if (reserved == bel) {
                    if (explain_invalid)
                        log_info("agrv2k validity: carry cluster member '%s' requires %s, "
                                 "reserved by fixed cell '%s'\n",
                                 ctx->nameOf(member), ctx->nameOfBel(bel),
                                 ctx->nameOf(reserved_by));
                    return false;
                }
            }
            expected.emplace(member, bel);
            if (!absolute_z) {
                if (member->constr_x != 0 || member->constr_y != 0)
                    return false;
                relative_z.insert(member->constr_z);
            }
        }
        if (!absolute_z) {
            if (members.size() > 9 || relative_z.size() != members.size())
                return false;
            int position = 0;
            for (int z : relative_z)
                if (z != position++)
                    return false;
        }
        for (CellInfo *member : members) {
            NetInfo *cin = member->getPort(ctx->id("CIN"));
            if (cin == nullptr)
                continue;
            CellInfo *driver = cin->driver.cell;
            auto source = expected.find(driver);
            if (driver == nullptr || cin->driver.port != ctx->id("COUT") ||
                source == expected.end() ||
                !typed_carry_pip_exists(
                        ctx->getBelPinWire(source->second, ctx->id("COUT")),
                        ctx->getBelPinWire(expected.at(member), ctx->id("CIN")),
                        !absolute_z)) {
                if (explain_invalid)
                    log_info("agrv2k validity: carry cluster member '%s' lacks its exact "
                             "typed COUT-to-CIN predecessor\n", ctx->nameOf(member));
                return false;
            }
        }
        return true;
    }

    // Relative constraints preserve a carry footprint's geometry, but not
    // every translation of a characterized seam has a dedicated carry pip.
    // Reject a translated cluster unless each already-placed CIN/COUT
    // neighbour is joined by the exact admitted one-hop resource.
    bool dedicated_carry_pins_reachable(CellInfo *cell, BelId candidate,
                                        bool explain_invalid) const
    {
        if (cell->cluster != ClusterId() &&
            !carry_cluster_footprint_valid(cell, candidate, explain_invalid))
            return false;
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
            // Terminal COUT is an ordinary routable design value. Only the
            // admitted carry neighbour must be joined by the exact one-hop
            // dedicated resource.
            if (user.cell == nullptr || user.cell->bel == BelId() ||
                user.cell->type != ctx->id("GENERIC_SLICE") || user.port != ctx->id("CIN"))
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
            if (native_direct_d_pool_cell(ctx, drv))
                continue; // HeAP chooses the pool site; router2 negotiates the exit
            const NativeEndpointRequirement endpoint =
                    native_endpoint_requirement(ctx, drv);
            if (endpoint.malformed())
                log_error("agrv2k: exit anchor rejects malformed native endpoint on '%s': %s\n",
                          ctx->nameOf(drv), endpoint.error.c_str());
            if (endpoint.active())
                continue; // all of its fixed hard endpoints are native legality constraints
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
            if (native_direct_d_pool_cell(ctx, ci))
                continue; // HeAP chooses the pool site; router2 negotiates the ingress
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
            if (native_direct_d_pool_cell(ctx, ci))
                continue; // HeAP chooses the pool site; router2 negotiates the ingress
            const McuEndpointRequirement typed_endpoint =
                    mcu_endpoint_requirement(ctx, ci);
            if (typed_endpoint.malformed())
                log_error("agrv2k: entry anchor rejects malformed typed MCU endpoint on "
                          "'%s': %s\n", ctx->nameOf(ci),
                          typed_endpoint.error.c_str());
            if (typed_endpoint.active)
                continue; // native placer owns this exact one-lane consumer
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
            const McuEndpointIntent typed_endpoint =
                    mcu_endpoint_intent(ctx, din);
            if (typed_endpoint.malformed())
                log_error("agrv2k: MCU input locker rejects malformed typed endpoint '%s': %s\n",
                          ctx->nameOf(din), typed_endpoint.error.c_str());
            if (typed_endpoint.active)
                continue; // router2 owns HWDATA25 after its mandatory first hop
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
        std::lock_guard<std::mutex> lock(timing_cache_mutex);
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

    BelBucketId getBelBucketForCellType(IdString cell_type) const override
    {
        // The packer canonicalises these source-level aliases before HeAP,
        // but advertising their shared physical bucket keeps availability,
        // spreading, and legality accounting coherent at every API boundary.
        if (cell_type.in(ctx->id("LUT"), ctx->id("DFF"), ctx->id("AG32_FA"),
                         ctx->id("GENERIC_SLICE")))
            return ctx->id("GENERIC_SLICE");
        if (cell_type.in(ctx->id("$nextpnr_ibuf"), ctx->id("$nextpnr_obuf"),
                         ctx->id("$nextpnr_iobuf"), ctx->id("GENERIC_IOB")))
            return ctx->id("GENERIC_IOB");
        return cell_type;
    }

    bool isValidBelForCellType(IdString cell_type, BelId bel) const override
    {
        return ctx->getBelType(bel) == getBelBucketForCellType(cell_type);
    }

    void init(Context *ctx) override
    {
        ViaductAPI::init(ctx);
        h.init(ctx);
        load_db();
        load_mcu_endpoint_profile();
        load_clock_resources();
        load_special_routes();
        load_mcu_region_witness();
        load_soft_ripple_region_witness();
        load_conduction();
    }

    void load_mcu_endpoint_profile()
    {
        Csv capability(path("mcu_endpoint_capabilities.csv"));
        const std::vector<std::string> header = {
            "schema_version", "interface", "lane", "cell_type", "cell_port",
            "hard_pin", "hard_bel", "source_root", "first_hop_dst", "mode",
            "selector_owner", "selector_field", "selector_selection",
            "evidence_tier", "evidence",
        };
        if (!capability.next() || capability.fields != header)
            log_error("agrv2k: malformed mcu_endpoint_capabilities.csv schema\n");
        if (!capability.next())
            log_error("agrv2k: mcu_endpoint_capabilities.csv has no HWDATA25 row\n");
        const std::vector<std::string> exact = {
            "1", "HWDATA", "25", "MCU_DIN", "DIN", "MCU_DIN69",
            "X10Y5_MCU_DIN69", "X13Y9_BufMUX07", "X13Y9_InputMUX06",
            "DIRECT_FABRIC_INPUT", "mcu", "InputMUX6", "0",
            "silicon_lane_identity",
            "group6-hwdata25-lane-identity-and-vendor-ahbrwide32-route",
        };
        if (capability.fields != exact || capability.next())
            log_error("agrv2k: endpoint capability must be exactly the one bounded HWDATA25 row\n");

        int lane_matches = 0;
        {
            Csv lanes(path("mcu_hwdata_lanes.csv"));
            if (!lanes.next() || lanes.at(0) != "logical_bit" ||
                lanes.at(1) != "bel_bit" || lanes.at(2) != "entry_x" ||
                lanes.at(3) != "entry_y" || lanes.at(4) != "entry_res" ||
                lanes.at(5) != "next_res" || lanes.at(6) != "evidence")
                log_error("agrv2k: malformed mcu_hwdata_lanes.csv schema\n");
            while (lanes.next())
                if (lanes.at(0) == "25") {
                    ++lane_matches;
                    if (lanes.fields != std::vector<std::string>({
                            "25", "69", "13", "9", "BufMUX07",
                            "InputMUX06", "vendor-ahbrwide32"}))
                        log_error("agrv2k: HWDATA25 lane mapping contradicts endpoint capability\n");
                }
        }
        if (lane_matches != 1)
            log_error("agrv2k: endpoint capability requires one exact HWDATA25 lane mapping\n");

        int selector_matches = 0;
        {
            Csv selectors(path("mcu_ahb32_pip_cfg.csv"));
            if (!selectors.next() || selectors.at(0) != "src_wire" ||
                selectors.at(1) != "dst_wire" || selectors.at(2) != "cell_table" ||
                selectors.at(5) != "cfg_group" || selectors.at(6) != "clear_selectors" ||
                selectors.at(7) != "set_selectors")
                log_error("agrv2k: malformed mcu_ahb32_pip_cfg.csv schema\n");
            while (selectors.next())
                if (selectors.at(0) == exact.at(7) && selectors.at(1) == exact.at(8)) {
                    ++selector_matches;
                    if (selectors.at(2) != "mcu" || selectors.at(3) != "13" ||
                        selectors.at(4) != "9" || selectors.at(5) != "InputMUX6" ||
                        selectors.at(6) != "0" || selectors.at(7) != "0")
                        log_error("agrv2k: HWDATA25 first-hop selector contradicts capability\n");
                }
        }
        if (selector_matches != 1)
            log_error("agrv2k: endpoint capability requires one exact first-hop selector row\n");

        mcu_endpoint_profile.hard_bel = exact.at(6);
        mcu_endpoint_profile.source_root = exact.at(7);
        mcu_endpoint_profile.first_hop_dst = exact.at(8);
        mcu_endpoint_profile.bel = ctx->getBelByNameStr(mcu_endpoint_profile.hard_bel);
        auto root = wire_by_name.find(ctx->id(mcu_endpoint_profile.source_root));
        auto first_dst = wire_by_name.find(ctx->id(mcu_endpoint_profile.first_hop_dst));
        mcu_endpoint_profile.first_hop = ctx->getPipByNameStr(
            mcu_endpoint_profile.source_root + "." +
            mcu_endpoint_profile.first_hop_dst);
        if (mcu_endpoint_profile.bel == BelId() || root == wire_by_name.end() ||
            first_dst == wire_by_name.end() ||
            mcu_endpoint_profile.first_hop == PipId())
            log_error("agrv2k: HWDATA25 capability references an absent BEL/wire/PIP\n");
        mcu_endpoint_profile.root = root->second;
        mcu_endpoint_profile.after_first_hop = first_dst->second;
        if (ctx->getBelType(mcu_endpoint_profile.bel) != ctx->id("MCU_DIN") ||
            ctx->getBelPinWire(mcu_endpoint_profile.bel, ctx->id("DIN")) !=
                    mcu_endpoint_profile.root ||
            ctx->getPipSrcWire(mcu_endpoint_profile.first_hop) !=
                    mcu_endpoint_profile.root ||
            ctx->getPipDstWire(mcu_endpoint_profile.first_hop) !=
                    mcu_endpoint_profile.after_first_hop)
            log_error("agrv2k: HWDATA25 capability fails BEL-pin/graph referential integrity\n");
        mcu_endpoint_profile.loaded = true;
        log_info("agrv2k: loaded one typed HWDATA25 endpoint at %s with mandatory %s -> %s\n",
                 mcu_endpoint_profile.hard_bel.c_str(),
                 mcu_endpoint_profile.source_root.c_str(),
                 mcu_endpoint_profile.first_hop_dst.c_str());
    }

    void load_clock_resources()
    {
        std::map<std::string, std::string> meta;
        {
            Csv c(path("dev_clock_meta.csv"));
            if (!c.next() || c.fields.size() != 2 ||
                c.at(0) != "key" || c.at(1) != "value")
                log_error("agrv2k: malformed dev_clock_meta.csv header\n");
            while (c.next()) {
                if (c.fields.size() != 2 || c.at(0).empty() ||
                    !meta.emplace(c.at(0), c.at(1)).second)
                    log_error("agrv2k: malformed/duplicate clock metadata key\n");
            }
        }
        const std::map<std::string, std::string> required = {
            {"schema", "1"}, {"class", "GCLK0"}, {"version", "1"},
            {"device", "AGRV2KL48"}, {"package", "L48"}, {"spine", "GCLK0"},
            {"wire_type", "GCLK0_SPINE"}, {"entry_type", "GCLK0_ENTRY"},
            {"slice_leaf_type", "GCLK0_SLICE_LEAF"},
            {"bram_root_type", "GCLK0_BRAM_ROOT"},
            {"bram_branch_type", "GCLK0_BRAM_BRANCH"},
            {"source_count", "3"}, {"admitted_source_count", "2"},
            {"entry_count", "46"}, {"slice_leaf_count", "2112"},
            {"bram_root_count", "1"}, {"bram_branch_count", "2"},
        };
        if (meta.size() != required.size() + 2)
            log_error("agrv2k: dev_clock_meta.csv has an unexpected key set\n");
        for (const auto &item : required)
            if (meta[item.first] != item.second)
                log_error("agrv2k: typed clock metadata drift at %s\n", item.first.c_str());
        auto valid_digest = [](const std::string &value) {
            return value.size() == 64 &&
                   std::all_of(value.begin(), value.end(), [](unsigned char ch) {
                       return std::isdigit(ch) || (ch >= 'a' && ch <= 'f');
                   });
        };
        clock_source_catalog_digest = meta["source_catalog_sha256"];
        clock_topology_digest = meta["topology_sha256"];
        if (!valid_digest(clock_source_catalog_digest) || !valid_digest(clock_topology_digest))
            log_error("agrv2k: typed clock metadata contains a malformed digest\n");
        static const char *exact_source_digest =
            "0166c3d2eaec1bc7e2832b33d6e7d9afcfb79d23c5d4f185762bf6356d53b1cd";
        static const char *exact_topology_digest =
            "57c7c819bf1ccddbe16243f2349597620743f047b6f2ccbc133378d44043f26d";
        if (clock_source_catalog_digest != exact_source_digest ||
            clock_topology_digest != exact_topology_digest)
            log_error("agrv2k: typed clock authority is not exact reviewed N5.7A content\n");

        std::map<std::string, std::string> dev_meta;
        {
            Csv c(path("dev_meta.csv"));
            if (!c.next() || c.fields.size() != 2 ||
                c.at(0) != "key" || c.at(1) != "value")
                log_error("agrv2k: malformed dev_meta.csv header\n");
            while (c.next()) {
                if (c.fields.size() != 2)
                    log_error("agrv2k: malformed dev_meta.csv row\n");
                if (c.at(0).empty() || !dev_meta.emplace(c.at(0), c.at(1)).second)
                    log_error("agrv2k: malformed/duplicate dev_meta key\n");
            }
        }
        if (dev_meta["clock_class"] != "GCLK0" ||
            dev_meta["clock_source_catalog_sha256"] != clock_source_catalog_digest ||
            dev_meta["clock_topology_sha256"] != clock_topology_digest)
            log_error("agrv2k: typed clock dev_meta/cache binding drift\n");

        // Verify the one global wire's generated type directly from the flat
        // database; Viaduct exposes wire identity but not a wire-type query.
        int spine_rows = 0;
        {
            Csv c(path("dev_wires.csv"));
            if (!c.next() || c.fields.size() != 4 || c.at(0) != "name" ||
                c.at(1) != "type" || c.at(2) != "x" || c.at(3) != "y")
                log_error("agrv2k: malformed dev_wires.csv header\n");
            while (c.next())
                if (c.at(0) == "GCLK0") {
                    ++spine_rows;
                    if (c.fields.size() != 4 || c.at(1) != "GCLK0_SPINE" ||
                        c.at(2) != "0" || c.at(3) != "0")
                        log_error("agrv2k: GCLK0 wire/type/location drift\n");
                }
        }
        auto spine_it = wire_by_name.find(ctx->id("GCLK0"));
        if (spine_rows != 1 || spine_it == wire_by_name.end())
            log_error("agrv2k: typed clock database requires exactly one GCLK0 spine\n");
        global_clock_spine = spine_it->second;
        global_clock_protected_wires.insert(global_clock_spine.index);

        int entries = 0, leaves = 0, roots = 0, branches = 0;
        std::unordered_set<int> entry_sources;
        std::unordered_map<int, unsigned> leaf_masks;
        for (PipId pip : ctx->getPips()) {
            const IdString type = ctx->getPipType(pip);
            WireId src = ctx->getPipSrcWire(pip), dst = ctx->getPipDstWire(pip);
            const std::string source = ctx->getWireName(src).str(ctx);
            const std::string target = ctx->getWireName(dst).str(ctx);
            if (type == ctx->id("GCLK0_ENTRY")) {
                ++entries;
                if (dst != global_clock_spine || source.find("_InputMUX") == std::string::npos ||
                    !entry_sources.insert(src.index).second)
                    log_error("agrv2k: malformed or duplicate GCLK0 entry PIP %s\n",
                              ctx->getPipName(pip).str(ctx).c_str());
                global_clock_protected_pips.insert(pip.index);
            } else if (type == ctx->id("GCLK0_SLICE_LEAF")) {
                ++leaves;
                int x = -1, y = -1, z = -1;
                char tail = 0;
                if (src != global_clock_spine ||
                    std::sscanf(target.c_str(), "X%dY%d_ClkMUX%d%c", &x, &y, &z, &tail) != 3 ||
                    z < 0 || z >= 16)
                    log_error("agrv2k: malformed GCLK0 slice leaf PIP %s\n",
                              ctx->getPipName(pip).str(ctx).c_str());
                const std::string bel_name = "X" + std::to_string(x) + "Y" +
                        std::to_string(y) + "_SLICE" + std::to_string(z);
                BelId bel = ctx->getBelByNameStr(bel_name);
                if (bel == BelId() || ctx->getBelType(bel) != ctx->id("GENERIC_SLICE") ||
                    ctx->getBelPinWire(bel, ctx->id("CLK")) != dst ||
                    !global_clock_leaf_by_bel.emplace(bel.index, pip).second)
                    log_error("agrv2k: GCLK0 leaf/BEL-pin mapping drift at %s\n",
                              bel_name.c_str());
                const int tile = tkey(x, y);
                if ((leaf_masks[tile] & (1u << unsigned(z))) != 0)
                    log_error("agrv2k: duplicate GCLK0 leaf at %s\n", bel_name.c_str());
                leaf_masks[tile] |= 1u << unsigned(z);
                global_clock_protected_pips.insert(pip.index);
                global_clock_protected_wires.insert(dst.index);
            } else if (type == ctx->id("GCLK0_BRAM_ROOT")) {
                ++roots;
                if (src != global_clock_spine || target != "X13Y0_BufMUX05" ||
                    global_clock_bram_root != PipId())
                    log_error("agrv2k: malformed or duplicate GCLK0 BRAM root\n");
                global_clock_bram_root = pip;
                global_clock_protected_pips.insert(pip.index);
                global_clock_protected_wires.insert(dst.index);
            } else if (type == ctx->id("GCLK0_BRAM_BRANCH")) {
                ++branches;
                const bool first = source == "X13Y0_BufMUX05" &&
                                   target == "X13Y4_SeamMUX01";
                const bool second = source == "X13Y4_SeamMUX01" &&
                                    target == "X13Y4_TileClkMUX01";
                if ((!first && !second) ||
                    std::any_of(global_clock_bram_branches.begin(),
                                global_clock_bram_branches.end(),
                                [&](PipId old) {
                                    return ctx->getPipSrcWire(old) == src &&
                                           ctx->getPipDstWire(old) == dst;
                                }))
                    log_error("agrv2k: malformed or duplicate GCLK0 BRAM branch\n");
                global_clock_bram_branches.push_back(pip);
                global_clock_protected_pips.insert(pip.index);
                global_clock_protected_wires.insert(src.index);
                global_clock_protected_wires.insert(dst.index);
            } else if (src == global_clock_spine || dst == global_clock_spine) {
                log_error("agrv2k: untyped PIP enters or leaves the GCLK0 spine: %s\n",
                          ctx->getPipName(pip).str(ctx).c_str());
            }
        }
        if (entries != 46 || leaves != 2112 || roots != 1 || branches != 2 ||
            leaf_masks.size() != 132)
            log_error("agrv2k: typed GCLK0 topology count drift (%d/%d/%d/%d, %d tiles)\n",
                      entries, leaves, roots, branches, int(leaf_masks.size()));
        for (const auto &tile : leaf_masks)
            if (tile.second != 0xffffu)
                log_error("agrv2k: GCLK0 slice-leaf completeness drift at tile key %d\n",
                          tile.first);
        std::sort(global_clock_bram_branches.begin(), global_clock_bram_branches.end(),
                  [&](PipId a, PipId b) {
                      return ctx->getWireName(ctx->getPipSrcWire(a)).str(ctx) <
                             ctx->getWireName(ctx->getPipSrcWire(b)).str(ctx);
                  });
        // Lexical order is SeamMUX first; restore physical root-to-leaf order.
        if (ctx->getWireName(ctx->getPipSrcWire(global_clock_bram_branches.front())).str(ctx) !=
            "X13Y0_BufMUX05")
            std::reverse(global_clock_bram_branches.begin(), global_clock_bram_branches.end());

        {
            Csv c(path("dev_clock_sources.csv"));
            if (!c.next() || c.fields.size() != 15 || c.at(0) != "schema" ||
                c.at(1) != "device" || c.at(2) != "package" || c.at(3) != "profile" ||
                c.at(4) != "source_class" || c.at(5) != "version" ||
                c.at(6) != "admitted" || c.at(7) != "cell_type" || c.at(8) != "bel" ||
                c.at(9) != "port" || c.at(10) != "root_wire" ||
                c.at(11) != "entry_src" || c.at(12) != "entry_dst" ||
                c.at(13) != "rate_policy" || c.at(14) != "evidence")
                log_error("agrv2k: malformed dev_clock_sources.csv header\n");
            while (c.next()) {
                if (c.fields.size() != 15 || c.at(0) != "1" ||
                    c.at(1) != "AGRV2KL48" || c.at(2) != "L48" || c.at(5) != "1" ||
                    (c.at(6) != "0" && c.at(6) != "1") || c.at(3).empty() ||
                    c.at(4).empty() || c.at(13).empty() || c.at(14).empty())
                    log_error("agrv2k: malformed typed clock source row\n");
                ClockSourceProfile row;
                row.profile = c.at(3); row.source_class = c.at(4);
                row.admitted = c.at(6) == "1"; row.cell_type = c.at(7);
                row.bel = c.at(8); row.port = c.at(9); row.root_wire = c.at(10);
                row.entry_src = c.at(11); row.entry_dst = c.at(12);
                row.rate_policy = c.at(13); row.evidence = c.at(14);
                clock_sources.push_back(row);
            }
        }
        if (clock_sources.size() != 3)
            log_error("agrv2k: typed clock source catalog must contain exactly three rows\n");
        // The metadata carries the reviewed canonical digest, but direct
        // nextpnr must also bind that digest to the bytes it actually parsed.
        // Every semantic field and row position is frozen here, so a changed
        // profile/class/rate/evidence value or a pure row permutation cannot
        // retain the old metadata digest and acquire runtime authority.
        const std::vector<ClockSourceProfile> exact_sources = {
            {"HSE_PLL_CLKIN_V1", "HSE_PLL", "GENERIC_IOB", "CLKIN", "O",
             "X14Y13_InputMUX01", "X14Y13_InputMUX01", "GCLK0",
             "SUPPORTED_PLL_RATIOS", "qualification/timing_evidence.jsonl", true},
            {"MCU_BUS_DEFAULT_V1", "MCU_BUS", "MCU_BUS_CLOCK",
             "X10Y5_MCU_BUS_CLOCK", "CLK", "GCLK0", "", "",
             "DEFAULT_SYS_GCK",
             "qualification/mcu_bus_clock_evidence.jsonl#bus-clock-lfsr16-mtime-rate-20260803",
             true},
            {"MCU_SYS_UNSUPPORTED_V1", "MCU_SYS", "MCU_SYS_CLOCK",
             "X10Y5_MCU_SYS_CLOCK", "CLK", "GCLK0", "", "", "UNSUPPORTED",
             "qualification/pack_regression.json#no-MCU_SYS_CLOCK-source", false},
        };
        for (size_t index = 0; index < exact_sources.size(); ++index) {
            const ClockSourceProfile &actual = clock_sources.at(index);
            const ClockSourceProfile &exact = exact_sources.at(index);
            if (actual.profile != exact.profile ||
                actual.source_class != exact.source_class ||
                actual.cell_type != exact.cell_type || actual.bel != exact.bel ||
                actual.port != exact.port || actual.root_wire != exact.root_wire ||
                actual.entry_src != exact.entry_src || actual.entry_dst != exact.entry_dst ||
                actual.rate_policy != exact.rate_policy || actual.evidence != exact.evidence ||
                actual.admitted != exact.admitted)
                log_error("agrv2k: typed clock source canonical row/digest drift at row %d\n",
                          int(index));
        }
        int admitted = 0, hse = 0, bus = 0, sys = 0;
        std::unordered_set<std::string> classes;
        for (ClockSourceProfile &row : clock_sources) {
            if (!classes.insert(row.source_class).second)
                log_error("agrv2k: duplicate typed clock source class\n");
            row.bel_id = ctx->getBelByNameStr(row.bel);
            auto root_it = wire_by_name.find(ctx->id(row.root_wire));
            if (row.bel_id == BelId() || root_it == wire_by_name.end() ||
                ctx->getBelType(row.bel_id) != ctx->id(row.cell_type) ||
                ctx->getBelPinWire(row.bel_id, ctx->id(row.port)) != root_it->second ||
                ctx->getBelPinType(row.bel_id, ctx->id(row.port)) != PORT_OUT)
                log_error("agrv2k: typed clock source BEL/port/root drift for %s\n",
                          row.source_class.c_str());
            row.root = root_it->second;
            if (row.cell_type == "GENERIC_IOB" && row.bel == "CLKIN" && row.port == "O") {
                ++hse;
                if (!row.admitted || row.root_wire != "X14Y13_InputMUX01" ||
                    row.entry_src != row.root_wire || row.entry_dst != "GCLK0")
                    log_error("agrv2k: exact HSE/CLKIN source profile drift\n");
                row.entry = ctx->getPipByNameStr(row.entry_src + "." + row.entry_dst);
                if (row.entry == PipId() ||
                    ctx->getPipType(row.entry) != ctx->id("GCLK0_ENTRY"))
                    log_error("agrv2k: exact HSE/CLKIN entry is absent or mistyped\n");
            } else if (row.cell_type == "MCU_BUS_CLOCK" &&
                       row.bel == "X10Y5_MCU_BUS_CLOCK" && row.port == "CLK") {
                ++bus;
                if (!row.admitted || row.root_wire != "GCLK0" ||
                    !row.entry_src.empty() || !row.entry_dst.empty())
                    log_error("agrv2k: exact MCU_BUS source profile drift\n");
            } else if (row.cell_type == "MCU_SYS_CLOCK" &&
                       row.bel == "X10Y5_MCU_SYS_CLOCK" && row.port == "CLK") {
                ++sys;
                if (row.admitted || row.root_wire != "GCLK0" ||
                    !row.entry_src.empty() || !row.entry_dst.empty())
                    log_error("agrv2k: exact unsupported MCU_SYS source profile drift\n");
            } else {
                log_error("agrv2k: unrecognized typed clock source identity for %s\n",
                          row.source_class.c_str());
            }
            admitted += row.admitted ? 1 : 0;
        }
        if (admitted != 2 || hse != 1 || bus != 1 || sys != 1)
            log_error("agrv2k: typed clock source role/count drift\n");

        ctx->attrs[ctx->id("AGAMEMNON_CLOCK_SCHEMA")] = Property(1);
        ctx->attrs[ctx->id("AGAMEMNON_CLOCK_CLASS")] = Property("GCLK0");
        ctx->attrs[ctx->id("AGAMEMNON_CLOCK_SOURCE_CATALOG_SHA256")] =
                Property(clock_source_catalog_digest);
        ctx->attrs[ctx->id("AGAMEMNON_CLOCK_TOPOLOGY_SHA256")] =
                Property(clock_topology_digest);
        log_info("agrv2k: loaded typed GCLK0 authority (3 sources, 46 entries, "
                 "2112 slice leaves, 1+2 BRAM tree; %.12s.../%.12s...)\n",
                 clock_source_catalog_digest.c_str(), clock_topology_digest.c_str());
    }

    void add_global_clock_net(NetInfo *net, const char *phase, const char *consumer)
    {
        if (net == nullptr)
            log_error("agrv2k: %s clock closure rejects unbound %s clock\n",
                      phase, consumer);
        if (global_clock_owner != nullptr && global_clock_owner != net)
            log_error("agrv2k: %s clock closure rejects multiple whole-device clocks "
                      "('%s' and '%s')\n", phase, ctx->nameOf(global_clock_owner),
                      ctx->nameOf(net));
        global_clock_owner = net;
    }

    void refresh_global_clock_owner(const char *phase, bool require_placement)
    {
        NetInfo *old_owner = global_clock_owner_prepared ? global_clock_owner : nullptr;
        global_clock_owner = nullptr;
        global_clock_source = nullptr;
        for (const auto &entry : ctx->cells) {
            CellInfo *cell = entry.second.get();
            const SharedClockRequirement requirement = shared_clock_requirement(ctx, cell);
            if (requirement.malformed())
                log_error("agrv2k: %s clock closure rejects active slice '%s': %s\n",
                          phase, ctx->nameOf(cell), requirement.malformed_reason());
            if (requirement.active()) {
                if (require_placement && cell->bel == BelId())
                    log_error("agrv2k: %s clock closure rejects unplaced active slice '%s'\n",
                              phase, ctx->nameOf(cell));
                add_global_clock_net(requirement.clock, phase, "slice");
            }
            if (cell->type != ctx->id("ALTA_BRAM9K"))
                continue;
            int declared = 0, connected = 0, unbound = 0;
            for (const char *port : {"Clk0", "Clk1"}) {
                auto clock = cell->ports.find(ctx->id(port));
                if (clock == cell->ports.end())
                    continue; // an unused sibling BRAM port consumes no clock resource
                ++declared;
                if (clock->second.net == nullptr) {
                    ++unbound;
                    continue; // a disconnected sibling beside one live port is inert
                }
                ++connected;
                add_global_clock_net(clock->second.net, phase, port);
            }
            if (declared == 0)
                log_error("agrv2k: %s clock closure rejects BRAM '%s': no declared "
                          "clock port\n", phase, ctx->nameOf(cell));
            if (unbound && connected == 0)
                log_error("agrv2k: %s clock closure rejects BRAM '%s': declared clock "
                          "ports have no bound clock\n", phase, ctx->nameOf(cell));
            if (connected && require_placement && cell->bel == BelId())
                log_error("agrv2k: %s clock closure rejects unplaced clocked BRAM '%s'\n",
                          phase, ctx->nameOf(cell));
        }
        if (global_clock_owner_prepared && old_owner != global_clock_owner)
            log_error("agrv2k: %s clock closure owner changed after initial preparation\n", phase);
        global_clock_owner_prepared = true;
        if (global_clock_owner == nullptr)
            return;

        CellInfo *driver = global_clock_owner->driver.cell;
        if (driver == nullptr)
            log_error("agrv2k: %s clock closure owner '%s' has no cell driver\n",
                      phase, ctx->nameOf(global_clock_owner));
        std::vector<ClockSourceProfile *> matches;
        for (ClockSourceProfile &source : clock_sources)
            if (driver->type == ctx->id(source.cell_type) &&
                global_clock_owner->driver.port == ctx->id(source.port))
                matches.push_back(&source);
        if (matches.size() != 1)
            log_error("agrv2k: %s clock closure rejects unclassified source '%s'.%s\n",
                      phase, ctx->nameOf(driver),
                      global_clock_owner->driver.port.str(ctx).c_str());
        ClockSourceProfile *source = matches.front();
        if (!source->admitted)
            log_error("agrv2k: %s clock closure rejects unsupported source class %s\n",
                      phase, source->source_class.c_str());

        if (driver->bel == BelId() && !require_placement) {
            for (const char *key : {"BEL", "NEXTPNR_BEL"}) {
                auto fixed = driver->attrs.find(ctx->id(key));
                if (fixed != driver->attrs.end() && fixed->second.as_string() != source->bel)
                    log_error("agrv2k: %s clock source '%s' has conflicting %s constraint '%s'\n",
                              phase, ctx->nameOf(driver), key,
                              fixed->second.as_string().c_str());
            }
            if (!ctx->checkBelAvail(source->bel_id))
                log_error("agrv2k: %s clock source BEL %s is unavailable\n",
                          phase, source->bel.c_str());
            ctx->bindBel(source->bel_id, driver, STRENGTH_LOCKED);
        }
        if (driver->bel == BelId())
            log_error("agrv2k: %s clock closure rejects unplaced source '%s'\n",
                      phase, ctx->nameOf(driver));
        if (driver->bel != source->bel_id ||
            ctx->getBelPinWire(driver->bel, global_clock_owner->driver.port) != source->root)
            log_error("agrv2k: %s clock closure rejects source '%s' at wrong BEL/port/root\n",
                      phase, ctx->nameOf(driver));
        global_clock_source = source;
        ctx->attrs[ctx->id("AGAMEMNON_CLOCK_SOURCE_CLASS")] =
                Property(source->source_class);
        ctx->attrs[ctx->id("AGAMEMNON_CLOCK_SOURCE_PROFILE")] =
                Property(source->profile);
        ctx->attrs[ctx->id("AGAMEMNON_CLOCK_OWNER_NET")] =
                Property(global_clock_owner->name.str(ctx));
    }

    void append_expected_clock_pip(PipId pip)
    {
        if (pip == PipId() || !global_clock_expected_pips.insert(pip.index).second)
            return;
        global_clock_expected_order.push_back(pip);
        global_clock_expected_wires.insert(ctx->getPipSrcWire(pip).index);
        global_clock_expected_wires.insert(ctx->getPipDstWire(pip).index);
    }

    void refresh_global_clock_resources(const char *phase, bool require_placement)
    {
        refresh_global_clock_owner(phase, require_placement);
        global_clock_expected_pips.clear();
        global_clock_expected_wires.clear();
        global_clock_expected_order.clear();
        if (global_clock_owner == nullptr) {
            global_clock_resources_frozen = true;
            return;
        }
        global_clock_expected_wires.insert(global_clock_spine.index);
        if (global_clock_source->entry != PipId())
            append_expected_clock_pip(global_clock_source->entry);

        bool bram_clocked = false;
        std::vector<PipId> leaves;
        for (const auto &entry : ctx->cells) {
            CellInfo *cell = entry.second.get();
            const SharedClockRequirement requirement = shared_clock_requirement(ctx, cell);
            if (requirement.active()) {
                if (cell->bel == BelId())
                    log_error("agrv2k: %s clock topology cannot resolve unplaced active slice '%s'\n",
                              phase, ctx->nameOf(cell));
                auto leaf = global_clock_leaf_by_bel.find(cell->bel.index);
                if (leaf == global_clock_leaf_by_bel.end() ||
                    ctx->getBelPinWire(cell->bel, ctx->id("CLK")) !=
                            ctx->getPipDstWire(leaf->second))
                    log_error("agrv2k: %s clock topology lacks exact typed leaf for '%s' at %s\n",
                              phase, ctx->nameOf(cell), ctx->nameOfBel(cell->bel));
                leaves.push_back(leaf->second);
            }
            if (cell->type != ctx->id("ALTA_BRAM9K"))
                continue;
            bool cell_clocked = false;
            for (const char *port : {"Clk0", "Clk1"})
                if (cell->getPort(ctx->id(port)) != nullptr)
                    cell_clocked = true;
            if (!cell_clocked)
                continue;
            bram_clocked = true;
            if (cell->bel == BelId() ||
                ctx->getBelName(cell->bel).str(ctx) != "X13Y4_BRAM")
                log_error("agrv2k: %s clock topology admits BRAM clocking only at X13Y4_BRAM\n",
                          phase);
            for (const char *port : {"Clk0", "Clk1"})
                if (ctx->getBelPinWire(cell->bel, ctx->id(port)) !=
                    wire_by_name.at(ctx->id("X13Y4_TileClkMUX01")))
                    log_error("agrv2k: %s BRAM %s endpoint is not the typed X13Y4 clock leaf\n",
                              phase, port);
        }
        if (bram_clocked) {
            append_expected_clock_pip(global_clock_bram_root);
            for (PipId pip : global_clock_bram_branches)
                append_expected_clock_pip(pip);
        }
        std::sort(leaves.begin(), leaves.end(),
                  [](PipId a, PipId b) { return a.index < b.index; });
        for (PipId pip : leaves)
            append_expected_clock_pip(pip);
        global_clock_resources_frozen = true;
    }

    bool global_clock_consumers_placed() const
    {
        for (const auto &entry : ctx->cells) {
            const CellInfo *cell = entry.second.get();
            const SharedClockRequirement requirement =
                    shared_clock_requirement(ctx, cell);
            if (requirement.active() && cell->bel == BelId())
                return false;
            if (cell->type != ctx->id("ALTA_BRAM9K") || cell->bel != BelId())
                continue;
            for (const char *port : {"Clk0", "Clk1"})
                if (cell->getPort(ctx->id(port)) != nullptr)
                    return false;
        }
        return true;
    }

    bool global_clock_pip_legal(PipId pip, const NetInfo *net) const
    {
        if (!global_clock_protected_pips.count(pip.index))
            return true;
        // JSON import notifications occur before pack has reconstructed the
        // logical owner.  The mandatory end-pack aggregate audit closes that
        // boundary; once frozen, router2 receives the exact O(1) predicate.
        if (!global_clock_resources_frozen)
            return true;
        return net != nullptr && net == global_clock_owner &&
               global_clock_expected_pips.count(pip.index);
    }

    void audit_global_clock_routes(const char *phase, bool require_complete)
    {
        int bound_expected = 0, bound_any = 0;
        for (PipId pip : ctx->getPips()) {
            if (!global_clock_protected_pips.count(pip.index))
                continue;
            NetInfo *bound = ctx->getBoundPipNet(pip);
            if (bound == nullptr)
                continue;
            ++bound_any;
            if (bound != global_clock_owner ||
                !global_clock_expected_pips.count(pip.index))
                log_error("agrv2k: %s clock audit rejects extra/foreign/wrong-class PIP %s "
                          "on net '%s'\n", phase,
                          ctx->getPipName(pip).str(ctx).c_str(), ctx->nameOf(bound));
            ++bound_expected;
        }
        for (int wire_index : global_clock_protected_wires) {
            WireId wire(wire_index);
            NetInfo *bound = ctx->getBoundWireNet(wire);
            if (bound == nullptr)
                continue;
            if (bound != global_clock_owner ||
                !global_clock_expected_wires.count(wire_index))
                log_error("agrv2k: %s clock audit rejects protected wire %s on foreign/extra net\n",
                          phase, ctx->getWireName(wire).str(ctx).c_str());
        }
        const int expected = int(global_clock_expected_pips.size());
        if (global_clock_owner == nullptr) {
            if (bound_any != 0)
                log_error("agrv2k: %s clock audit finds protected resources without an owner\n",
                          phase);
            return;
        }
        if ((!require_complete && bound_expected != 0 && bound_expected != expected) ||
            (require_complete && bound_expected != expected))
            log_error("agrv2k: %s clock audit requires %d exact tree PIPs, found %d%s\n",
                      phase, expected, bound_expected,
                      require_complete ? "" : " (partial imported tree)");
    }

    void lock_global_clock_tree(const char *phase)
    {
        if (global_clock_owner == nullptr)
            return;
        int locked = 0;
        for (PipId pip : global_clock_expected_order) {
            NetInfo *bound = ctx->getBoundPipNet(pip);
            if (bound == global_clock_owner)
                continue;
            if (bound != nullptr || !ctx->checkPipAvailForNet(pip, global_clock_owner))
                log_error("agrv2k: %s clock tree cannot bind exact PIP %s\n", phase,
                          ctx->getPipName(pip).str(ctx).c_str());
            NetInfo *source_owner = ctx->getBoundWireNet(ctx->getPipSrcWire(pip));
            if (source_owner != nullptr && source_owner != global_clock_owner)
                log_error("agrv2k: %s clock tree source wire for %s has a foreign owner\n",
                          phase, ctx->getPipName(pip).str(ctx).c_str());
            ctx->bindPip(pip, global_clock_owner, STRENGTH_LOCKED);
            ++locked;
        }
        if (locked)
            log_info("agrv2k: %s atomically bound %d typed GCLK0 tree PIP(s)\n",
                     phase, locked);
    }

    bool global_clock_cell_compatible(const CellInfo *cell, bool explain_invalid) const
    {
        const SharedClockRequirement requirement = shared_clock_requirement(ctx, cell);
        if (!requirement.active())
            return !requirement.malformed();
        // Internal pack helpers can query BEL legality before pack() reaches
        // its owner-preparation point.  The final pack audit closes that
        // boundary.  Main placement always follows prePlace(), so its queries
        // see the exact prepared owner without mutating state from this const,
        // potentially parallel callback.
        if (!global_clock_owner_prepared)
            return true;
        if (global_clock_owner_prepared && requirement.clock == global_clock_owner)
            return true;
        if (explain_invalid) {
            if (global_clock_owner_prepared && global_clock_owner != nullptr)
                log_info("agrv2k validity: registered slice '%s' uses net '%s', not "
                         "whole-device GCLK0 owner '%s'\n", ctx->nameOf(cell),
                         ctx->nameOf(requirement.clock), ctx->nameOf(global_clock_owner));
            else
                log_info("agrv2k validity: registered slice '%s' uses net '%s' before "
                         "a whole-device GCLK0 owner is prepared\n", ctx->nameOf(cell),
                         ctx->nameOf(requirement.clock));
        }
        return false;
    }

    void load_special_routes()
    {
        std::map<std::string, std::string> meta;
        {
            Csv c(path("dev_special_route_meta.csv"));
            if (!c.next() || c.fields.size() != 2 ||
                c.at(0) != "key" || c.at(1) != "value")
                log_error("agrv2k: malformed dev_special_route_meta.csv header\n");
            while (c.next()) {
                if (c.fields.size() != 2)
                    log_error("agrv2k: malformed dev_special_route_meta.csv row\n");
                if (c.at(0).empty() || !meta.emplace(c.at(0), c.at(1)).second)
                    log_error("agrv2k: duplicate/empty special-route metadata key\n");
            }
        }
        const std::map<std::string, std::string> required = {
            {"schema", "1"}, {"class", "L48_LEFT_OUTPUT"}, {"version", "1"},
            {"device", "AGRV2KL48"}, {"package", "L48"}, {"profile", "physical-io"},
            {"pip_count", "36"}, {"wire_count", "40"},
        };
        for (const auto &item : required)
            if (meta[item.first] != item.second)
                log_error("agrv2k: special-route metadata drift at %s\n", item.first.c_str());
        if (meta["enabled"] != "0" && meta["enabled"] != "1")
            log_error("agrv2k: invalid special-route enabled flag\n");
        special_routes_enabled = meta["enabled"] == "1";
        special_route_digest = meta["catalog_sha256"];
        static const char *exact_catalog_digest =
            "c900368abe07fe61e0c97a76dcb11e9e8b3d9acdfc56ada99d56de6e5bf30e8e";
        if (special_route_digest != exact_catalog_digest)
            log_error("agrv2k: special-route catalog digest is not the exact reviewed N5.5 authority\n");
        // jsonwrite carries Context attributes onto the physical top module.
        // The shared Python authority uses this exact emitted profile binding
        // to keep generic strict (27/36 edges) inert while making physical-I/O
        // routes impossible to reinterpret as an untyped generic checkpoint.
        ctx->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_SCHEMA")] = Property(1);
        ctx->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_CLASS")] = Property("L48_LEFT_OUTPUT");
        ctx->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_VERSION")] = Property("v1");
        ctx->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_DEVICE")] = Property("AGRV2KL48");
        ctx->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_PACKAGE")] = Property("L48");
        ctx->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_PROFILE")] = Property("physical-io");
        ctx->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_ENABLED")] =
                Property(special_routes_enabled ? 1 : 0);
        ctx->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_CATALOG_SHA256")] =
                Property(special_route_digest);
        {
            Csv c(path("dev_meta.csv"));
            if (!c.next() || c.fields.size() != 2 ||
                c.at(0) != "key" || c.at(1) != "value")
                log_error("agrv2k: malformed dev_meta.csv header\n");
            std::map<std::string, std::string> dev_meta;
            while (c.next()) {
                if (c.fields.size() != 2)
                    log_error("agrv2k: malformed dev_meta.csv row\n");
                if (c.at(0).empty() || !dev_meta.emplace(c.at(0), c.at(1)).second)
                    log_error("agrv2k: duplicate/empty dev_meta key\n");
            }
            if (dev_meta["special_route_class"] != "L48_LEFT_OUTPUT" ||
                dev_meta["special_route_enabled"] != meta["enabled"] ||
                dev_meta["special_route_catalog_sha256"] != special_route_digest)
                log_error("agrv2k: special-route dev_meta/cache binding drift\n");
            std::map<std::string, std::string> cached_env;
            const std::string &summary = dev_meta["agamemnon_env"];
            if (!summary.empty() && summary.back() == ';')
                log_error("agrv2k: malformed/duplicate agamemnon_env token\n");
            size_t start = 0;
            while (start < summary.size()) {
                size_t end = summary.find(';', start);
                if (end == std::string::npos)
                    end = summary.size();
                std::string token = summary.substr(start, end - start);
                size_t equals = token.find('=');
                if (token.empty() || equals == std::string::npos || equals == 0 ||
                    !cached_env.emplace(token.substr(0, equals), token.substr(equals + 1)).second)
                    log_error("agrv2k: malformed/duplicate agamemnon_env token\n");
                start = end + 1;
            }
            const bool cached_physical_profile =
                    cached_env["AGAMEMNON_PHYSICAL_IO"] == "1" &&
                    cached_env["AGAMEMNON_LEFT_PAD_OUT"] == "1";
            if (special_routes_enabled != cached_physical_profile)
                log_error("agrv2k: special-route enabled state does not match exact cached profile\n");
        }

        struct Row { int lane, step; std::string pin, sb, sp, tb, tp, src, dst, evidence; };
        std::vector<Row> rows;
        {
            Csv c(path("dev_special_routes.csv"));
            if (!c.next() || c.fields.size() != 16 ||
                c.at(0) != "schema" || c.at(1) != "device" ||
                c.at(2) != "package" || c.at(3) != "profile" || c.at(4) != "class" ||
                c.at(5) != "version" || c.at(6) != "lane" || c.at(7) != "pin" ||
                c.at(8) != "source_bel" || c.at(9) != "source_port" ||
                c.at(10) != "sink_bel" || c.at(11) != "sink_port" ||
                c.at(12) != "step" || c.at(13) != "src_wire" ||
                c.at(14) != "dst_wire" || c.at(15) != "evidence")
                log_error("agrv2k: malformed dev_special_routes.csv header\n");
            while (c.next()) {
                const int lane_value = to_int(c.at(6), -1);
                const int step_value = to_int(c.at(12), -1);
                if (c.fields.size() != 16 || c.at(0) != "1" ||
                    c.at(1) != "AGRV2KL48" || c.at(2) != "L48" ||
                    c.at(3) != "physical-io" || c.at(4) != "L48_LEFT_OUTPUT" ||
                    c.at(5) != "1" || c.at(9) != "Q" || c.at(11) != "I" || c.at(15).empty() ||
                    c.at(6) != std::to_string(lane_value) ||
                    c.at(12) != std::to_string(step_value))
                    log_error("agrv2k: malformed special-route catalog row\n");
                rows.push_back({lane_value, step_value, c.at(7), c.at(8),
                                c.at(9), c.at(10), c.at(11), c.at(13), c.at(14), c.at(15)});
            }
        }
        if (rows.size() != 36)
            log_error("agrv2k: typed L48 left-output catalog must contain 36 PIPs\n");
        static const char *pins[4] = {"PIN_25", "PIN_26", "PIN_27", "PIN_28"};
        static const char *source_bels[4] = {
            "X14Y11_SLICE4", "X14Y11_SLICE5", "X14Y11_SLICE6", "X14Y11_SLICE7"};
        static const char *sink_bels[4] = {
            "X0Y4_IOB0", "X0Y4_IOB1", "X0Y4_IOB2", "X0Y4_IOB3"};
        static const int counts[4] = {10, 9, 9, 8};
        static const char *expected_wires[4][11] = {
            {"X14Y11_OMUX13", "X14Y11_OMUX12", "X15Y11_RMUX44", "X15Y8_RMUX80",
             "X15Y4_RMUX26", "X11Y4_RMUX08", "X12Y4_RMUX26", "X8Y4_RMUX03",
             "X4Y4_RMUX20", "X0Y4_RMUX30", "X0Y4_IOMUX00"},
            {"X14Y11_OMUX16", "X14Y11_OMUX15", "X15Y11_RMUX27", "X15Y8_RMUX21",
             "X15Y4_RMUX86", "X12Y4_RMUX56", "X8Y4_RMUX43", "X4Y4_RMUX79",
             "X0Y4_RMUX06", "X0Y4_IOMUX01", nullptr},
            {"X14Y11_OMUX20", "X14Y11_RMUX44", "X14Y8_RMUX80", "X14Y4_RMUX26",
             "X11Y4_RMUX03", "X7Y4_RMUX20", "X3Y4_RMUX74", "X4Y4_RMUX13",
             "X0Y4_RMUX18", "X0Y4_IOMUX02", nullptr},
            {"X14Y11_OMUX23", "X14Y11_RMUX27", "X14Y8_RMUX21", "X14Y4_RMUX93",
             "X12Y4_RMUX86", "X8Y4_RMUX56", "X4Y4_RMUX26", "X0Y4_RMUX00",
             "X0Y4_IOMUX03", nullptr, nullptr},
        };
        static const char *exact_evidence =
            "qualification/left_edge_output_evidence.jsonl#2026-07-15-l48-pin25-28-simultaneous";
        special_route_lanes.resize(4);
        std::unordered_set<std::string> all_wires;
        for (int lane_index = 0; lane_index < 4; ++lane_index) {
            std::vector<Row> lane_rows;
            for (const Row &row : rows)
                if (row.lane == lane_index)
                    lane_rows.push_back(row);
            std::sort(lane_rows.begin(), lane_rows.end(),
                      [](const Row &a, const Row &b) { return a.step < b.step; });
            if (int(lane_rows.size()) != counts[lane_index])
                log_error("agrv2k: special-route lane %d has wrong PIP count\n", lane_index);
            SpecialRouteLane &lane = special_route_lanes.at(lane_index);
            lane.index = lane_index; lane.pin = pins[lane_index];
            lane.source_bel = source_bels[lane_index]; lane.source_port = "Q";
            lane.sink_bel = sink_bels[lane_index]; lane.sink_port = "I";
            std::string prior;
            std::unordered_set<std::string> lane_wire_names;
            for (int step = 0; step < counts[lane_index]; ++step) {
                const Row &row = lane_rows.at(step);
                if (row.step != step || row.pin != lane.pin || row.sb != lane.source_bel ||
                    row.sp != lane.source_port || row.tb != lane.sink_bel || row.tp != lane.sink_port ||
                    (step != 0 && row.src != prior))
                    log_error("agrv2k: special-route lane %d endpoint/continuity drift at step %d\n",
                              lane_index, step);
                if (row.src != expected_wires[lane_index][step] ||
                    row.dst != expected_wires[lane_index][step + 1] ||
                    row.evidence != exact_evidence)
                    log_error("agrv2k: actual special-route catalog row drift at lane %d step %d\n",
                              lane_index, step);
                prior = row.dst;
                lane_wire_names.insert(row.src);
                lane_wire_names.insert(row.dst);
                if (!special_routes_enabled)
                    continue;
                auto src_it = wire_by_name.find(ctx->id(row.src));
                auto dst_it = wire_by_name.find(ctx->id(row.dst));
                if (src_it == wire_by_name.end() || dst_it == wire_by_name.end())
                    log_error("agrv2k: enabled special-route wire absent: %s -> %s\n",
                              row.src.c_str(), row.dst.c_str());
                PipId pip = ctx->getPipByNameStr(row.src + "." + row.dst);
                if (pip == PipId())
                    log_error("agrv2k: enabled special-route PIP absent: %s -> %s\n",
                              row.src.c_str(), row.dst.c_str());
                if (ctx->getPipSrcWire(pip) != src_it->second ||
                    ctx->getPipDstWire(pip) != dst_it->second)
                    log_error("agrv2k: named special-route PIP endpoint drift: %s -> %s\n",
                              row.src.c_str(), row.dst.c_str());
                if (!special_route_pip_lane.emplace(pip.index, lane_index).second)
                    log_error("agrv2k: duplicate typed special-route PIP\n");
                lane.pips.push_back(pip);
                if (lane.wire_indices.insert(src_it->second.index).second)
                    lane.wires.push_back(src_it->second);
                if (lane.wire_indices.insert(dst_it->second.index).second)
                    lane.wires.push_back(dst_it->second);
                lane.predecessor_by_dst[dst_it->second.index] = src_it->second.index;
            }
            for (const std::string &wire_name : lane_wire_names)
                if (!all_wires.insert(wire_name).second)
                    log_error("agrv2k: special-route lanes are not wire-disjoint\n");
            if (special_routes_enabled)
                for (WireId wire : lane.wires)
                    if (!special_route_wire_lane.emplace(wire.index, lane_index).second)
                        log_error("agrv2k: typed special-route lanes share a wire\n");
            if (special_routes_enabled) {
                BelId source_bel = ctx->getBelByNameStr(lane.source_bel);
                BelId sink_bel = ctx->getBelByNameStr(lane.sink_bel);
                if (source_bel == BelId() ||
                    ctx->getBelType(source_bel) != ctx->id("GENERIC_SLICE") ||
                    ctx->getBelPinWire(source_bel, ctx->id(lane.source_port)) != lane.wires.front() ||
                    ctx->getBelPinType(source_bel, ctx->id(lane.source_port)) != PORT_OUT)
                    log_error("agrv2k: special-route source BEL-pin endpoint drift at %s.%s\n",
                              lane.source_bel.c_str(), lane.source_port.c_str());
                if (sink_bel == BelId() ||
                    ctx->getBelType(sink_bel) != ctx->id("GENERIC_IOB") ||
                    ctx->getBelPinWire(sink_bel, ctx->id(lane.sink_port)) != lane.wires.back() ||
                    ctx->getBelPinType(sink_bel, ctx->id(lane.sink_port)) != PORT_IN)
                    log_error("agrv2k: special-route sink BEL-pin endpoint drift at %s.%s\n",
                              lane.sink_bel.c_str(), lane.sink_port.c_str());
            }
        }
        // Python's catalog digest canonicalizes the parsed rows in their
        // emitted order.  Check the frozen lane content above first so a real
        // topology/evidence substitution receives its precise lane/step
        // diagnostic; then bind original row order so a pure permutation
        // cannot retain the metadata digest and enter direct nextpnr through
        // a different interpretation.
        size_t expected_position = 0;
        for (int lane_index = 0; lane_index < 4; ++lane_index) {
            for (int step = 0; step < counts[lane_index]; ++step) {
                const Row &row = rows.at(expected_position++);
                if (row.lane != lane_index || row.step != step ||
                    row.pin != pins[lane_index] || row.sb != source_bels[lane_index] ||
                    row.sp != "Q" || row.tb != sink_bels[lane_index] || row.tp != "I" ||
                    row.src != expected_wires[lane_index][step] ||
                    row.dst != expected_wires[lane_index][step + 1] ||
                    row.evidence != exact_evidence)
                    log_error("agrv2k: special-route catalog canonical row-order/digest drift at row %d\n",
                              int(expected_position - 1));
            }
        }
        if (all_wires.size() != 40)
            log_error("agrv2k: typed L48 left-output catalog must contain 40 wires\n");
        log_info("agrv2k: typed L48 left-output authority %s (36 PIPs/40 wires, digest %.12s...)\n",
                 special_routes_enabled ? "ENABLED" : "disabled for non-physical profile",
                 special_route_digest.c_str());
    }

    bool net_targets_special_lane(const NetInfo *net, const SpecialRouteLane &lane) const
    {
        if (net == nullptr || net->driver.cell == nullptr || net->driver.port != ctx->id(lane.source_port) ||
            net->driver.cell->type != ctx->id("GENERIC_SLICE") ||
            net->driver.cell->bel == BelId() ||
            ctx->getBelName(net->driver.cell->bel).str(ctx) != lane.source_bel)
            return false;
        for (const PortRef &user : net->users)
            if (user.cell != nullptr && user.cell->type == ctx->id("GENERIC_IOB") &&
                user.port == ctx->id(lane.sink_port) && user.cell->bel != BelId() &&
                ctx->getBelName(user.cell->bel).str(ctx) == lane.sink_bel)
                return true;
        return false;
    }

    bool net_matches_special_lane(const NetInfo *net, const SpecialRouteLane &lane) const
    {
        if (!net_targets_special_lane(net, lane))
            return false;
        // The qualified composition is a dedicated copy FF whose Q has one
        // physical-pad consumer.  A functional Q with any internal fanout is
        // a different, unqualified electrical composition even if router2 can
        // find ordinary graph resources for that branch.
        if (net->users.entries() != 1)
            return false;
        for (const PortRef &user : net->users)
            return user.cell != nullptr && user.cell->type == ctx->id("GENERIC_IOB") &&
                   user.port == ctx->id(lane.sink_port) && user.cell->bel != BelId() &&
                   ctx->getBelName(user.cell->bel).str(ctx) == lane.sink_bel;
        return false;
    }

    NetInfo *derive_special_lane_owner(SpecialRouteLane &lane) const
    {
        BelId sink = ctx->getBelByNameStr(lane.sink_bel);
        if (sink == BelId())
            log_error("agrv2k: typed special-route sink BEL absent: %s\n", lane.sink_bel.c_str());
        CellInfo *iob = ctx->getBoundBelCell(sink);
        if (iob == nullptr)
            return nullptr;
        if (iob->type != ctx->id("GENERIC_IOB"))
            log_error("agrv2k: typed special-route sink %s is not GENERIC_IOB\n", lane.sink_bel.c_str());
        NetInfo *net = iob->getPort(ctx->id(lane.sink_port));
        if (net == nullptr)
            return nullptr;
        if (!net_matches_special_lane(net, lane)) {
            if (net_targets_special_lane(net, lane))
                log_error("agrv2k: %s exact owner has unsupported internal fanout; only one pad sink is qualified\n",
                          lane.pin.c_str());
            log_error("agrv2k: %s requires exact %s.%s -> %s.%s ownership\n", lane.pin.c_str(),
                      lane.source_bel.c_str(), lane.source_port.c_str(),
                      lane.sink_bel.c_str(), lane.sink_port.c_str());
        }
        return net;
    }

    void refresh_special_route_owners(bool freeze)
    {
        if (!special_routes_enabled)
            return;
        for (SpecialRouteLane &lane : special_route_lanes) {
            NetInfo *owner = derive_special_lane_owner(lane);
            if (special_route_owners_frozen && lane.owner != owner)
                log_error("agrv2k: typed special-route lane %d owner changed after pre-route freeze\n",
                          lane.index);
            lane.owner = owner;
            if (owner != nullptr) {
                CellInfo *driver = owner->driver.cell;
                driver->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_CLASS")] = Property("L48_LEFT_OUTPUT");
                driver->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_VERSION")] = Property("v1");
                driver->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_LANE")] =
                        Property(lane.index);
                driver->attrs[ctx->id("AGAMEMNON_SPECIAL_ROUTE_CATALOG_SHA256")] =
                        Property(special_route_digest);
            }
        }
        if (freeze)
            special_route_owners_frozen = true;
    }

    bool special_route_pip_legal(PipId pip, const NetInfo *net) const
    {
        if (!special_routes_enabled)
            return true;
        WireId src = ctx->getPipSrcWire(pip), dst = ctx->getPipDstWire(pip);
        auto src_lane_it = special_route_wire_lane.find(src.index);
        auto dst_lane_it = special_route_wire_lane.find(dst.index);
        auto pip_lane_it = special_route_pip_lane.find(pip.index);
        auto active_owner = [&](int lane_index) -> NetInfo * {
            const SpecialRouteLane &lane = special_route_lanes.at(lane_index);
            if (lane.owner != nullptr)
                return lane.owner;
            return net_matches_special_lane(net, lane) ? const_cast<NetInfo *>(net) : nullptr;
        };
        for (const SpecialRouteLane &lane : special_route_lanes)
            if (net_targets_special_lane(net, lane) && !net_matches_special_lane(net, lane))
                return false;
        int net_owner_lane = -1;
        for (const SpecialRouteLane &lane : special_route_lanes)
            if (lane.owner == net || (lane.owner == nullptr && net_matches_special_lane(net, lane))) {
                if (net_owner_lane != -1)
                    return false;
                net_owner_lane = lane.index;
            }
        // An active L48 pad owner is qualified only for its exact catalog
        // corridor.  It may not depart to the ordinary fabric, even through a
        // graph-present and statically conducting PIP.
        if (net_owner_lane != -1)
            return pip_lane_it != special_route_pip_lane.end() &&
                   pip_lane_it->second == net_owner_lane;
        // Inactive lanes remain ordinary resources.
        if (pip_lane_it != special_route_pip_lane.end()) {
            NetInfo *owner = active_owner(pip_lane_it->second);
            return owner == nullptr || owner == net;
        }
        if (src_lane_it != special_route_wire_lane.end()) {
            NetInfo *owner = active_owner(src_lane_it->second);
            if (owner != nullptr) {
                if (owner != net)
                    return false;
                if (dst_lane_it != special_route_wire_lane.end() &&
                    dst_lane_it->second == src_lane_it->second)
                    return false; // non-catalog internal edge
            }
        }
        if (dst_lane_it != special_route_wire_lane.end()) {
            const int lane_index = dst_lane_it->second;
            NetInfo *owner = active_owner(lane_index);
            if (owner != nullptr) {
                if (owner != net)
                    return false;
                const auto &pred = special_route_lanes.at(lane_index).predecessor_by_dst;
                auto expected = pred.find(dst.index);
                if (expected == pred.end() || expected->second != src.index)
                    return false; // wrong predecessor/re-entry
            }
        }
        return true;
    }

    struct CarryIdentity {
        bool active = false;
        bool valid = false;
        std::string profile, role;
        int chain = -1, position = -1, length = -1;
    };

    CarryIdentity carry_identity(const CellInfo *cell) const
    {
        CarryIdentity result;
        if (cell == nullptr)
            return result;
        const std::array<IdString, 6> keys = {
            ctx->id("AGRV2K_CARRY_SCHEMA"), ctx->id("AGRV2K_CARRY_PROFILE"),
            ctx->id("AGRV2K_CARRY_CHAIN"), ctx->id("AGRV2K_CARRY_POSITION"),
            ctx->id("AGRV2K_CARRY_LENGTH"), ctx->id("AGRV2K_CARRY_ROLE"),
        };
        int present = 0;
        for (IdString key : keys)
            present += cell->attrs.count(key) != 0;
        if (present == 0)
            return result;
        result.active = true;
        if (present != int(keys.size()))
            return result;
        if (cell->attrs.at(keys[0]).as_int64() != 1)
            return result;
        result.profile = cell->attrs.at(keys[1]).as_string();
        result.chain = int(cell->attrs.at(keys[2]).as_int64());
        result.position = int(cell->attrs.at(keys[3]).as_int64());
        result.length = int(cell->attrs.at(keys[4]).as_int64());
        result.role = cell->attrs.at(keys[5]).as_string();
        const bool profile_valid =
                (result.profile == "SHORT_LOCAL" && result.length >= 2 && result.length <= 9) ||
                (result.profile == "LEGACY_25" && result.length >= 10 && result.length <= 25) ||
                (result.profile == "LEGACY_33" && result.length >= 26 && result.length <= 33);
        const std::string expected_role = result.position == 0 ? "SEED" :
                (result.length == 2 ? "FIRST_TAIL" :
                 (result.position == 1 ? "FIRST" :
                  (result.position + 1 == result.length ? "TAIL" : "INTERIOR")));
        result.valid = profile_valid && result.chain >= 0 &&
                result.position >= 0 && result.position < result.length &&
                result.role == expected_role;
        return result;
    }

    bool same_carry_chain(const CellInfo *a, const CellInfo *b) const
    {
        const CarryIdentity left = carry_identity(a), right = carry_identity(b);
        return left.valid && right.valid && left.profile == right.profile &&
                left.chain == right.chain && left.length == right.length;
    }

    bool carry_cluster_profile(const CellInfo *member, bool &short_local,
                               int &member_count) const
    {
        const CarryIdentity identity = carry_identity(member);
        if (identity.valid) {
            short_local = identity.profile == "SHORT_LOCAL";
            member_count = identity.length;
            return true;
        }
        if (member == nullptr || member->cluster == ClusterId())
            return false;
        const CellInfo *root = nullptr;
        member_count = 0;
        for (const auto &entry : ctx->cells) {
            const CellInfo *candidate = entry.second.get();
            if (candidate->cluster != member->cluster)
                continue;
            if (candidate->type != ctx->id("GENERIC_SLICE") ||
                candidate->constr_abs_z != member->constr_abs_z)
                return false;
            ++member_count;
            if (candidate->name == member->cluster)
                root = candidate;
        }
        if (root == nullptr)
            return false;
        short_local = !root->constr_abs_z;
        return short_local ? member_count >= 2 && member_count <= 9
                           : (member_count == 25 || member_count == 33);
    }

    // Return the one protected COUT->CIN resource owned by an internal carry
    // net.  A terminal COUT is deliberately not a carry-link net and remains
    // free to enter the ordinary mesh.  A malformed branch, foreign cluster,
    // unbound endpoint, short-profile seam, or duplicate typed edge has no
    // owner and therefore cannot acquire any routing PIP.
    PipId expected_carry_link_pip(const NetInfo *net) const
    {
        if (net == nullptr || net->driver.cell == nullptr ||
            net->driver.cell->type != ctx->id("GENERIC_SLICE") ||
            net->driver.port != ctx->id("COUT"))
            return PipId();
        CellInfo *source_cell = net->driver.cell;
        CellInfo *sink_cell = nullptr;
        int real_users = 0;
        for (const PortRef &user : net->users) {
            if (user.cell == nullptr)
                continue;
            ++real_users;
            if (user.cell->type == ctx->id("GENERIC_SLICE") &&
                user.port == ctx->id("CIN") && sink_cell == nullptr)
                sink_cell = user.cell;
            else
                return PipId();
        }
        const CarryIdentity source_identity = carry_identity(source_cell);
        const CarryIdentity sink_identity = carry_identity(sink_cell);
        if (sink_cell == nullptr || real_users != 1 ||
            (!same_carry_chain(source_cell, sink_cell) &&
             (source_cell->cluster == ClusterId() ||
              source_cell->cluster != sink_cell->cluster)) ||
            (source_identity.valid && sink_identity.valid &&
             sink_identity.position != source_identity.position + 1) ||
            source_cell->bel == BelId() || sink_cell->bel == BelId())
            return PipId();

        bool short_local = false;
        int member_count = 0;
        if (!carry_cluster_profile(source_cell, short_local, member_count))
            return PipId();
        const Loc source_loc = ctx->getBelLocation(source_cell->bel);
        const Loc sink_loc = ctx->getBelLocation(sink_cell->bel);
        if (short_local &&
            (source_loc.x != sink_loc.x || source_loc.y != sink_loc.y ||
             source_loc.z + 1 != sink_loc.z))
            return PipId();

        WireId source = ctx->getBelPinWire(source_cell->bel, ctx->id("COUT"));
        WireId target = ctx->getBelPinWire(sink_cell->bel, ctx->id("CIN"));
        PipId expected;
        for (PipId pip : ctx->getPipsDownhill(source)) {
            if (ctx->getPipDstWire(pip) != target)
                continue;
            const IdString type = ctx->getPipType(pip);
            const bool admitted = short_local ? type == ctx->id("CARRY")
                                              : (type == ctx->id("CARRY") ||
                                                 type == ctx->id("CARRY_SEAM"));
            if (!admitted)
                continue;
            if (expected != PipId())
                return PipId();
            expected = pip;
        }
        return expected;
    }

    bool is_internal_carry_net(const NetInfo *net) const
    {
        if (net == nullptr || net->driver.cell == nullptr ||
            net->driver.cell->type != ctx->id("GENERIC_SLICE") ||
            net->driver.port != ctx->id("COUT"))
            return false;
        for (const PortRef &user : net->users)
            if (user.cell != nullptr &&
                user.cell->type == ctx->id("GENERIC_SLICE") &&
                user.port == ctx->id("CIN"))
                return true;
        return false;
    }

    // A registered slice may feed its own B input through two physical
    // resources: the ordinary Q-presentation bridge and the typed local QFB
    // edge.  Retained HIL-positive ordinary slices use the same edge class as
    // carry captures, so ownership is semantic and same-site, not carry-only.
    // Other branches of that Q net remain ordinary router2 resources.
    bool expected_slice_qfb(const NetInfo *net, PipId &bridge, PipId &qfb) const
    {
        bridge = PipId();
        qfb = PipId();
        if (net == nullptr || net->driver.cell == nullptr ||
            net->driver.cell->type != ctx->id("GENERIC_SLICE") ||
            net->driver.port != ctx->id("Q"))
            return false;
        CellInfo *cell = net->driver.cell;
        if (cell->bel == BelId() ||
            int_or_default(cell->params, ctx->id("FF_USED"), 0) != 1)
            return false;
        bool self_b = false;
        for (const PortRef &user : net->users)
            if (user.cell == cell && user.port == ctx->id("I[1]"))
                self_b = true;
        if (!self_b)
            return false;
        const WireId q_wire = ctx->getBelPinWire(cell->bel, ctx->id("Q"));
        const WireId b_wire = ctx->getBelPinWire(cell->bel, ctx->id("I[1]"));
        for (PipId candidate_bridge : ctx->getPipsDownhill(q_wire)) {
            if (ctx->getPipType(candidate_bridge) != ctx->id("OMUXFB"))
                continue;
            const WireId presented_q = ctx->getPipDstWire(candidate_bridge);
            for (PipId candidate_qfb : ctx->getPipsDownhill(presented_q)) {
                if (ctx->getPipType(candidate_qfb) != ctx->id("SLICE_QFB") ||
                    ctx->getPipDstWire(candidate_qfb) != b_wire)
                    continue;
                if (bridge != PipId() || qfb != PipId())
                    return false;
                bridge = candidate_bridge;
                qfb = candidate_qfb;
            }
        }
        return bridge != PipId() && qfb != PipId();
    }

    bool short_carry_qfb_required(const NetInfo *net) const
    {
        if (net == nullptr || net->driver.cell == nullptr)
            return false;
        CellInfo *cell = net->driver.cell;
        if (!cell->ports.count(ctx->id("CIN")) ||
            !cell->ports.count(ctx->id("COUT")))
            return false;
        bool short_local = false;
        int member_count = 0;
        return carry_cluster_profile(cell, short_local, member_count) && short_local;
    }

    bool carry_pip_legal(PipId pip, const NetInfo *net) const
    {
        const IdString type = ctx->getPipType(pip);
        if (type == ctx->id("CARRY") || type == ctx->id("CARRY_SEAM"))
            return expected_carry_link_pip(net) == pip;
        if (type == ctx->id("SLICE_QFB")) {
            PipId bridge, qfb;
            return expected_slice_qfb(net, bridge, qfb) && qfb == pip;
        }
        // An interior COUT->CIN link is atomic: it may use its one protected
        // direct edge and no ordinary detour, even for the same net.
        return !is_internal_carry_net(net);
    }

    void audit_carry_routes(const char *phase, bool require_complete)
    {
        const IdString slice = ctx->id("GENERIC_SLICE");
        const bool require_placement = std::string(phase) != "end-pack";
        int chains = 0, links = 0, feedbacks = 0;
        std::map<std::string, std::vector<CellInfo *>> groups;
        for (const auto &entry : ctx->cells) {
            CellInfo *member = entry.second.get();
            const bool has_cin = member->ports.count(ctx->id("CIN"));
            const bool has_cout = member->ports.count(ctx->id("COUT"));
            const CarryIdentity identity = carry_identity(member);
            if (!has_cin && !has_cout) {
                if (identity.active)
                    log_error("agrv2k: %s carry closure rejects metadata on non-carry cell '%s'\n",
                              phase, ctx->nameOf(member));
                continue;
            }
            if (member->type != slice || !identity.valid ||
                (require_placement && member->bel == BelId()))
                log_error("agrv2k: %s carry closure rejects unbound or unauthenticated member '%s'\n",
                          phase, ctx->nameOf(member));
            const std::string key = identity.profile + ":" +
                    std::to_string(identity.chain) + ":" +
                    std::to_string(identity.length);
            auto inserted = groups.emplace(
                    key, std::vector<CellInfo *>(size_t(identity.length), nullptr));
            std::vector<CellInfo *> &ordered = inserted.first->second;
            if (ordered.at(size_t(identity.position)) != nullptr)
                log_error("agrv2k: %s carry closure rejects duplicate chain position %d\n",
                          phase, identity.position);
            ordered.at(size_t(identity.position)) = member;
        }

        for (auto &group : groups) {
            std::vector<CellInfo *> &ordered = group.second;
            if (std::find(ordered.begin(), ordered.end(), nullptr) != ordered.end())
                log_error("agrv2k: %s carry closure rejects incomplete chain metadata '%s'\n",
                          phase, group.first.c_str());
            CellInfo *root = ordered.front();
            const CarryIdentity root_identity = carry_identity(root);
            const bool short_local = root_identity.profile == "SHORT_LOCAL";
            for (size_t index = 0; index < ordered.size(); ++index) {
                CellInfo *current = ordered.at(index);
                const bool has_cin = current->ports.count(ctx->id("CIN"));
                const bool has_cout = current->ports.count(ctx->id("COUT"));
                if (!has_cout || (index == 0 && has_cin) || (index != 0 && !has_cin))
                    log_error("agrv2k: %s carry closure rejects role/port mismatch at position %ld\n",
                              phase, long(index));
                if (short_local && root->bel != BelId() && current->bel != BelId()) {
                    const Loc root_loc = ctx->getBelLocation(root->bel);
                    const Loc current_loc = ctx->getBelLocation(current->bel);
                    if (current_loc.x != root_loc.x || current_loc.y != root_loc.y ||
                        current_loc.z != root_loc.z + int(index))
                        log_error("agrv2k: %s short carry closure rejects nonconsecutive member '%s'\n",
                                  phase, ctx->nameOf(current));
                } else if (!short_local && root->bel != BelId() &&
                           current->bel != BelId()) {
                    const Loc root_loc = ctx->getBelLocation(root->bel);
                    const Loc current_loc = ctx->getBelLocation(current->bel);
                    int expected_y = root_loc.y, expected_z = int(index);
                    if (root_identity.profile == "LEGACY_25" && index >= 16) {
                        expected_y = root_loc.y - 1;
                        expected_z = int(index) - 16;
                    } else if (root_identity.profile == "LEGACY_33" && index >= 16) {
                        expected_y = index < 32 ? root_loc.y + 1 : root_loc.y - 1;
                        expected_z = index < 32 ? int(index) - 16 : 0;
                    }
                    if (root_loc.z != 0 || current_loc.x != root_loc.x ||
                        current_loc.y != expected_y || current_loc.z != expected_z)
                        log_error("agrv2k: %s retained carry closure rejects profile geometry at "
                                  "position %ld for member '%s'\n", phase, long(index),
                                  ctx->nameOf(current));
                }
                NetInfo *cout = current->getPort(ctx->id("COUT"));
                CellInfo *next = nullptr;
                int cin_users = 0;
                if (cout != nullptr)
                    for (const PortRef &user : cout->users)
                        if (user.cell != nullptr && user.cell->type == slice &&
                            user.port == ctx->id("CIN")) {
                            ++cin_users;
                            if (next != nullptr && next != user.cell)
                                log_error("agrv2k: %s carry closure rejects branched COUT\n", phase);
                            next = user.cell;
                        }
                if (index + 1 < ordered.size()) {
                    if (next != ordered.at(index + 1) || cin_users != 1 || cout == nullptr)
                        log_error("agrv2k: %s carry closure rejects a broken linear link\n", phase);
                    const bool imported = !cout->wires.empty();
                    PipId expected = expected_carry_link_pip(cout);
                    if ((require_placement || imported) && expected == PipId())
                        log_error("agrv2k: %s carry closure lacks one exact typed link\n", phase);
                    if ((imported || require_complete) &&
                        ctx->getBoundPipNet(expected) != cout)
                        log_error("agrv2k: %s carry closure lacks its exact routed PIP for net '%s'\n",
                                  phase, ctx->nameOf(cout));
                    int route_pips = 0;
                    for (const auto &wire : cout->wires)
                        if (wire.second.pip != PipId()) {
                            ++route_pips;
                            if (!carry_pip_legal(wire.second.pip, cout))
                                log_error("agrv2k: %s carry closure rejects extra/wrong PIP on net '%s'\n",
                                          phase, ctx->nameOf(cout));
                        }
                    if ((imported || require_complete) && route_pips != 1)
                        log_error("agrv2k: %s carry closure requires exactly one routed PIP on net '%s'\n",
                                  phase, ctx->nameOf(cout));
                    ++links;
                } else if (next != nullptr || cin_users != 0) {
                    log_error("agrv2k: %s carry closure contains an extra cluster successor\n", phase);
                }
            }
            ++chains;
        }

        for (const auto &entry : ctx->nets) {
            NetInfo *net = entry.second.get();
            PipId bridge, qfb;
            if (!expected_slice_qfb(net, bridge, qfb))
                continue;
            const bool imported = !net->wires.empty();
            const bool qfb_bound = ctx->getBoundPipNet(qfb) == net;
            const bool bridge_bound = ctx->getBoundPipNet(bridge) == net;
            if (qfb_bound != bridge_bound)
                log_error("agrv2k: %s slice Q-feedback closure is partial on net '%s'\n",
                          phase, ctx->nameOf(net));
            if (short_carry_qfb_required(net) && (imported || require_complete) &&
                (ctx->getBoundPipNet(bridge) != net ||
                 ctx->getBoundPipNet(qfb) != net))
                log_error("agrv2k: %s carry Q-feedback closure is incomplete on net '%s'\n",
                          phase, ctx->nameOf(net));
            if (short_carry_qfb_required(net))
                ++feedbacks;
        }
        for (PipId pip : ctx->getPips()) {
            NetInfo *bound = ctx->getBoundPipNet(pip);
            if (bound != nullptr && !carry_pip_legal(pip, bound))
                log_error("agrv2k: %s carry aggregate audit rejects PIP %s for net '%s'\n",
                          phase, ctx->getPipName(pip).str(ctx).c_str(), ctx->nameOf(bound));
        }
        if (chains)
            log_info("agrv2k: %s carry audit verified %d chain(s), %d internal link(s), "
                     "%d Q-feedback net(s)%s\n", phase, chains, links, feedbacks,
                     require_complete ? " with routed closure" : "");
    }

    void audit_special_routes(const char *phase, bool require_complete)
    {
        if (!special_routes_enabled)
            return;
        refresh_special_route_owners(false);
        for (PipId pip : ctx->getPips()) {
            NetInfo *bound = ctx->getBoundPipNet(pip);
            if (bound != nullptr && !checkPipAvailForNet(pip, bound))
                log_error("agrv2k: %s typed special-route aggregate audit rejects PIP %s\n",
                          phase, ctx->getPipName(pip).str(ctx).c_str());
        }
        int active = 0;
        for (const SpecialRouteLane &lane : special_route_lanes) {
            if (lane.owner == nullptr)
                continue;
            ++active;
            int present = 0;
            const bool imported_route_state = !lane.owner->wires.empty();
            for (WireId wire : lane.wires) {
                NetInfo *bound = ctx->getBoundWireNet(wire);
                if (bound != nullptr && bound != lane.owner)
                    log_error("agrv2k: %s typed lane %d contains a foreign wire binding\n",
                              phase, lane.index);
            }
            for (PipId pip : lane.pips) {
                NetInfo *bound = ctx->getBoundPipNet(pip);
                if (bound == lane.owner)
                    ++present;
                else if (bound != nullptr)
                    log_error("agrv2k: %s typed lane %d contains a foreign catalog binding\n",
                              phase, lane.index);
            }
            if ((imported_route_state && present != int(lane.pips.size())) ||
                (require_complete && present != int(lane.pips.size())))
                log_error("agrv2k: %s typed lane %d closure is %d/%d PIPs\n", phase,
                          lane.index, present, int(lane.pips.size()));
            if (require_complete || present == int(lane.pips.size())) {
                WireId source = lane.wires.front();
                if (ctx->getBoundWireNet(source) != lane.owner)
                    log_error("agrv2k: %s typed lane %d lacks its exact source root\n",
                              phase, lane.index);
                int roots = 0;
                for (const auto &wire : lane.owner->wires)
                    if (wire.second.pip == PipId()) {
                        ++roots;
                        if (wire.first != source)
                            log_error("agrv2k: %s typed lane %d has an extra/wrong route root\n",
                                      phase, lane.index);
                    }
                if (roots != 1)
                    log_error("agrv2k: %s typed lane %d must have exactly one route root\n",
                              phase, lane.index);
            }
        }
        log_info("agrv2k: %s typed L48 left-output audit verified %d active lane(s)%s\n",
                 phase, active, require_complete ? " with full closure" : "");
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

    void load_soft_ripple_region_witness()
    {
        Csv c(path("soft_ripple_region_witness.csv"));
        if (!c.next() || c.at(0) != "scope" || c.at(1) != "x_min" ||
            c.at(2) != "x_max" || c.at(3) != "y_min" || c.at(4) != "y_max" ||
            c.at(5) != "decoded_builds" || c.at(6) != "chain_stages" ||
            c.at(7) != "max_slices_per_tile" || c.at(8) != "provenance")
            log_error("agrv2k: malformed soft_ripple_region_witness.csv header\n");
        if (!c.next() || c.at(0) != "bounded_shared_fanin_soft_ripple")
            log_error("agrv2k: soft_ripple_region_witness.csv has no bounded ripple row\n");
        soft_ripple_region_witness.min_x = to_int(c.at(1));
        soft_ripple_region_witness.max_x = to_int(c.at(2));
        soft_ripple_region_witness.min_y = to_int(c.at(3));
        soft_ripple_region_witness.max_y = to_int(c.at(4));
        soft_ripple_region_witness.decoded_builds = to_int(c.at(5));
        soft_ripple_region_witness.chain_stages = to_int(c.at(6));
        soft_ripple_region_witness.max_slices_per_tile = to_int(c.at(7));
        if (soft_ripple_region_witness.min_x > soft_ripple_region_witness.max_x ||
            soft_ripple_region_witness.min_y > soft_ripple_region_witness.max_y ||
            soft_ripple_region_witness.decoded_builds < 1 ||
            soft_ripple_region_witness.chain_stages < 2 ||
            (soft_ripple_region_witness.chain_stages & 1) != 0 ||
            soft_ripple_region_witness.max_slices_per_tile < 4 || c.at(8).empty())
            log_error("agrv2k: invalid witnessed soft-ripple placement bounds\n");
        if (c.next())
            log_error("agrv2k: soft_ripple_region_witness.csv must contain exactly one data row\n");
        soft_ripple_region_witness.loaded = true;
        log_info("agrv2k: loaded witnessed soft-ripple placement envelope X%d..%d Y%d..%d "
                 "from %d decoded builds\n",
                 soft_ripple_region_witness.min_x, soft_ripple_region_witness.max_x,
                 soft_ripple_region_witness.min_y, soft_ripple_region_witness.max_y,
                 soft_ripple_region_witness.decoded_builds);
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
        // single-hop = unchanged). K>1 follows outgoing tile edges only: a reverse-only path is not a legal
        // producer->consumer placement, even if the physical tile pair is adjacent in the other direction.
        int K = 1;
        if (const char *e = std::getenv("AGRV2K_CONDPAIR_HOPS"))
            K = std::max(1, std::atoi(e));
        if (K > 1) {
            std::unordered_set<int> nodes;
            for (auto &kv : tile_adj) {
                nodes.insert(kv.first);
                nodes.insert(kv.second.begin(), kv.second.end());
            }
            for (int s : nodes) {
                std::unordered_set<int> seen{s};
                std::vector<int> frontier{s};
                for (int h = 0; h < K && !frontier.empty(); ++h) {
                    std::vector<int> nxt;
                    for (int x : frontier) {
                        auto it = tile_adj.find(x);
                        if (it == tile_adj.end())
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
            log_info("agrv2k: CONDPAIR K=%d directed conducting closure over %d tiles\n",
                     K, int(tile_reach.size()));
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

    // Reserve the one retained simultaneous composition in which every
    // fabric-master request qualifier has its own registered source.  Generic
    // routing can find each sink in isolation but repeatedly strands a late
    // qualifier while negotiating all eleven.  Replaying the exact decoded
    // paths removes search ambiguity without widening placement or selector
    // policy: guard_fabric_ahb_request_controls() has already required all
    // eleven exact Q drivers and every edge below has a byte-checked codeword.
    void bind_fabric_ahb_independent_control_sources()
    {
        int bound = 0;
        for (auto &entry : ctx->cells) {
            CellInfo *control = entry.second.get();
            if (!is_fabric_ahb_request_control(ctx, control))
                continue;
            NetInfo *net = control->getPort(ctx->id("DOUT"));
            if (!is_exact_fabric_ahb_independent_ff(ctx, control, net))
                continue;
            const char *signal = fabric_ahb_request_signal(ctx, control);
            const char *expected_bel = fabric_ahb_independent_source_bel(ctx, control);
            CellInfo *driver = net->driver.cell;
            BelId exact_bel = expected_bel == nullptr ? BelId() :
                    ctx->getBelByNameStr(expected_bel);
            if (exact_bel == BelId())
                log_error("agrv2k: exact fabric AHB master request control source BEL is "
                          "absent for '%s'\n", signal);
            if (driver->bel == BelId()) {
                if (!ctx->checkBelAvail(exact_bel))
                    log_error("agrv2k: exact fabric AHB master request control source BEL is "
                              "unavailable for '%s'\n", signal);
                ctx->bindBel(exact_bel, driver, STRENGTH_LOCKED);
                if (!isBelLocationValid(exact_bel, true))
                    log_error("agrv2k: exact fabric AHB master request control source BEL is "
                              "illegal for '%s'\n", signal);
            } else if (driver->bel != exact_bel) {
                log_error("agrv2k: exact fabric AHB master request control source is misplaced "
                          "for '%s'\n", signal);
            }
            // This pack-time binding supersedes the source attribute. Leaving
            // it would make generic constraint processing bind the cell again.
            driver->attrs.erase(ctx->id("BEL"));
            ++bound;
        }
        if (bound && bound != 11)
            log_error("agrv2k: exact fabric AHB master request control source binding is "
                      "incomplete (%d/11)\n", bound);
        if (bound)
            log_info("agrv2k: reserved all 11 exact independent request-control source BELs "
                     "before ordinary placement\n");
    }

    void lock_fabric_ahb_independent_controls()
    {
        struct Edge {
            int step;
            std::string src, dst;
        };
        std::map<std::string, std::vector<Edge>> routes;
        Csv csv(path("mcu_slave_ahb_request_control_independent_paths.csv"));
        csv.next();
        while (csv.next()) {
            if (csv.at(0).empty())
                continue;
            routes[csv.at(0)].push_back({to_int(csv.at(1), -1), csv.at(2), csv.at(3)});
        }
        if (routes.size() != 11)
            log_error("agrv2k: fabric AHB master request control route table has %d/11 signals\n",
                      int(routes.size()));
        for (auto &item : routes) {
            auto &edges = item.second;
            std::sort(edges.begin(), edges.end(), [](const Edge &a, const Edge &b) {
                return a.step < b.step;
            });
            for (size_t i = 0; i < edges.size(); ++i) {
                if (edges[i].step != int(i) || (i && edges[i - 1].dst != edges[i].src))
                    log_error("agrv2k: discontinuous fabric AHB master request control route for %s\n",
                              item.first.c_str());
            }
        }

        int locked = 0, locked_nets = 0;
        for (auto &entry : ctx->cells) {
            CellInfo *control = entry.second.get();
            if (!is_fabric_ahb_request_control(ctx, control))
                continue;
            NetInfo *net = control->getPort(ctx->id("DOUT"));
            if (!is_exact_fabric_ahb_independent_ff(ctx, control, net))
                continue; // shared-safe-low oracle: leave its qualified tree to router2
            const char *signal = fabric_ahb_request_signal(ctx, control);
            auto found = signal == nullptr ? routes.end() : routes.find(signal);
            if (found == routes.end() || found->second.empty())
                log_error("agrv2k: no exact independent fabric AHB master request control route for '%s'\n",
                          ctx->nameOf(control));
            CellInfo *driver = net->driver.cell;
            if (driver->bel == BelId())
                log_error("agrv2k: exact fabric AHB master request control source was not "
                          "reserved before placement for '%s'\n", signal);
            if (control->bel == BelId() || driver->bel == BelId())
                log_error("agrv2k: fabric AHB master request control '%s' is unplaced before route lock\n",
                          ctx->nameOf(control));
            WireId source = ctx->getBelPinWire(driver->bel, net->driver.port);
            WireId target = ctx->getBelPinWire(control->bel, ctx->id("DOUT"));
            auto &edges = found->second;
            if (ctx->getWireName(source).str(ctx) != edges.front().src ||
                    ctx->getWireName(target).str(ctx) != edges.back().dst)
                log_error("agrv2k: exact fabric AHB master request control route endpoints disagree for '%s'\n",
                          signal);
            NetInfo *source_owner = ctx->getBoundWireNet(source);
            if (source_owner == nullptr)
                ctx->bindWire(source, net, STRENGTH_LOCKED);
            else if (source_owner != net)
                log_error("agrv2k: exact fabric AHB master request control route source conflicts for '%s'\n",
                          signal);
            for (const Edge &edge : edges) {
                PipId pip = ctx->getPipByNameStr(edge.src + "." + edge.dst);
                if (pip == PipId())
                    log_error("agrv2k: exact fabric AHB master request control pip is absent: %s -> %s\n",
                              edge.src.c_str(), edge.dst.c_str());
                WireId dst = ctx->getPipDstWire(pip);
                NetInfo *owner = ctx->getBoundWireNet(dst);
                if (owner == net)
                    continue;
                if (owner != nullptr || !ctx->checkPipAvailForNet(pip, net))
                    log_error("agrv2k: exact fabric AHB master request control route conflicts at %s -> %s\n",
                              edge.src.c_str(), edge.dst.c_str());
                ctx->bindPip(pip, net, STRENGTH_LOCKED);
                ++locked;
            }
            ++locked_nets;
        }
        if (locked_nets && locked_nets != 11)
            log_error("agrv2k: exact fabric AHB master request control composition is incomplete (%d/11)\n",
                      locked_nets);
        if (locked_nets)
            log_info("agrv2k: pre-routed 11 exact independent request-control nets over %d pips\n",
                     locked);
    }

    void lock_fabric_ahb_haddr2_dynamic()
    {
        struct Edge {
            int step;
            std::string src, dst;
        };
        std::vector<Edge> edges;
        Csv csv(path("mcu_slave_ahb_haddr2_dynamic_paths.csv"));
        csv.next();
        while (csv.next()) {
            if (csv.at(0).empty())
                continue;
            if (csv.at(0) != "slave_ahb_haddr[2]")
                log_error("agrv2k: unexpected signal in exact dynamic HADDR[2] route table: %s\n",
                          csv.at(0).c_str());
            edges.push_back({to_int(csv.at(1), -1), csv.at(2), csv.at(3)});
        }
        std::sort(edges.begin(), edges.end(), [](const Edge &a, const Edge &b) {
            return a.step < b.step;
        });
        if (edges.size() != 5)
            log_error("agrv2k: exact dynamic HADDR[2] route table has %d/5 edges\n",
                      int(edges.size()));
        for (size_t i = 0; i < edges.size(); ++i)
            if (edges[i].step != int(i) || (i && edges[i - 1].dst != edges[i].src))
                log_error("agrv2k: discontinuous exact dynamic HADDR[2] route table\n");

        CellInfo *payload = nullptr;
        NetInfo *net = nullptr;
        for (auto &item : ctx->cells) {
            CellInfo *cell = item.second.get();
            if (cell->type != ctx->id("MCU_DOUT"))
                continue;
            int bit = -1;
            if (mcu_dout_lane(cell->name.str(ctx), bit) != LANE_SHADDR || bit != 2)
                continue;
            NetInfo *candidate = cell->getPort(ctx->id("DOUT"));
            if (is_exact_fabric_ahb_haddr2_register(ctx, candidate)) {
                if (payload != nullptr)
                    log_error("agrv2k: multiple exact dynamic HADDR[2] endpoints\n");
                payload = cell;
                net = candidate;
            }
        }
        if (payload == nullptr)
            return;

        CellInfo *driver = net->driver.cell;
        if (driver->bel == BelId()) {
            BelId exact_bel = ctx->getBelByNameStr("X18Y9_SLICE15");
            if (exact_bel == BelId() || !ctx->checkBelAvail(exact_bel))
                log_error("agrv2k: exact dynamic HADDR[2] source BEL is unavailable\n");
            ctx->bindBel(exact_bel, driver, STRENGTH_LOCKED);
            if (!isBelLocationValid(exact_bel, true))
                log_error("agrv2k: exact dynamic HADDR[2] source BEL is illegal\n");
            driver->attrs.erase(ctx->id("BEL"));
        }
        if (payload->bel == BelId() || driver->bel == BelId())
            log_error("agrv2k: exact dynamic HADDR[2] endpoints are unplaced before route lock\n");
        WireId source = ctx->getBelPinWire(driver->bel, net->driver.port);
        WireId target = ctx->getBelPinWire(payload->bel, ctx->id("DOUT"));
        if (ctx->getWireName(source).str(ctx) != edges.front().src ||
                ctx->getWireName(target).str(ctx) != edges.back().dst)
            log_error("agrv2k: exact dynamic HADDR[2] route endpoints disagree\n");
        NetInfo *source_owner = ctx->getBoundWireNet(source);
        if (source_owner == nullptr)
            ctx->bindWire(source, net, STRENGTH_LOCKED);
        else if (source_owner != net)
            log_error("agrv2k: exact dynamic HADDR[2] source wire conflicts\n");
        int locked = 0;
        for (const Edge &edge : edges) {
            PipId pip = ctx->getPipByNameStr(edge.src + "." + edge.dst);
            if (pip == PipId())
                log_error("agrv2k: exact dynamic HADDR[2] pip is absent: %s -> %s\n",
                          edge.src.c_str(), edge.dst.c_str());
            WireId dst = ctx->getPipDstWire(pip);
            NetInfo *owner = ctx->getBoundWireNet(dst);
            if (owner == net)
                continue;
            if (owner != nullptr || !ctx->checkPipAvailForNet(pip, net))
                log_error("agrv2k: exact dynamic HADDR[2] route conflicts at %s -> %s\n",
                          edge.src.c_str(), edge.dst.c_str());
            ctx->bindPip(pip, net, STRENGTH_LOCKED);
            ++locked;
        }
        log_info("agrv2k: pre-routed one exact dynamic HADDR[2] net over %d pips\n", locked);
    }

    // The retained independent HSIZE[0] and HSIZE[2] routes occupy the same
    // backbones used by the retained shared-low HADDR[0] and HADDR[1] routes.
    // The SRAM-base profile therefore extends those already-owned control nets
    // from the common witnessed wires instead of asking router2 to negotiate a
    // conflicting second owner. Only the exact retained suffixes are replayed.
    void lock_fabric_ahb_haddr01_hsize_branches()
    {
        struct Edge {
            int step;
            std::string src, dst;
        };
        std::map<int, std::vector<Edge>> routes;
        Csv csv(path("mcu_slave_ahb_request_payload_paths.csv"));
        csv.next();
        while (csv.next()) {
            int bit = csv.at(0) == "slave_ahb_haddr[0]" ? 0 :
                      csv.at(0) == "slave_ahb_haddr[1]" ? 1 : -1;
            if (bit >= 0)
                routes[bit].push_back({to_int(csv.at(1), -1), csv.at(2), csv.at(3)});
        }
        const std::array<std::string, 2> junctions = {
            "X14Y10_RMUX93", "X15Y10_RMUX56"
        };
        for (int bit = 0; bit < 2; ++bit) {
            auto &edges = routes[bit];
            std::sort(edges.begin(), edges.end(), [](const Edge &a, const Edge &b) {
                return a.step < b.step;
            });
            if (edges.size() != size_t(bit == 0 ? 4 : 5))
                log_error("agrv2k: exact HADDR[%d] branch table is incomplete\n", bit);
            for (size_t i = 0; i < edges.size(); ++i)
                if (edges[i].step != int(i) || (i && edges[i - 1].dst != edges[i].src))
                    log_error("agrv2k: discontinuous exact HADDR[%d] branch table\n", bit);
        }

        std::array<CellInfo *, 2> payload{{nullptr, nullptr}};
        std::array<CellInfo *, 2> controls{{nullptr, nullptr}};
        for (auto &item : ctx->cells) {
            CellInfo *cell = item.second.get();
            if (cell->type == ctx->id("MCU_SLAVE_AHB_HSIZE0"))
                controls[0] = cell;
            if (cell->type == ctx->id("MCU_SLAVE_AHB_HSIZE2"))
                controls[1] = cell;
            if (cell->type == ctx->id("MCU_DOUT")) {
                int lane_bit = -1;
                if (mcu_dout_lane(cell->name.str(ctx), lane_bit) == LANE_SHADDR &&
                        lane_bit >= 0 && lane_bit < 2)
                    payload[lane_bit] = cell;
            }
        }
        if (payload[0] == nullptr || payload[1] == nullptr ||
                controls[0] == nullptr || controls[1] == nullptr)
            return;
        NetInfo *net0 = payload[0]->getPort(ctx->id("DOUT"));
        NetInfo *net1 = payload[1]->getPort(ctx->id("DOUT"));
        if (net0 != controls[0]->getPort(ctx->id("DOUT")) ||
                net1 != controls[1]->getPort(ctx->id("DOUT")))
            return; // non-SRAM profiles leave these lanes to the normal router

        int locked = 0;
        for (int bit = 0; bit < 2; ++bit) {
            NetInfo *net = payload[bit]->getPort(ctx->id("DOUT"));
            if (!is_exact_fabric_ahb_independent_ff(ctx, controls[bit], net))
                log_error("agrv2k: HADDR[%d] branch is not on its exact HSIZE net\n", bit);
            WireId target = ctx->getBelPinWire(payload[bit]->bel, ctx->id("DOUT"));
            auto &edges = routes[bit];
            auto first = std::find_if(edges.begin(), edges.end(), [&](const Edge &edge) {
                return edge.src == junctions[bit];
            });
            if (first == edges.end() ||
                    ctx->getWireName(target).str(ctx) != edges.back().dst)
                log_error("agrv2k: exact HADDR[%d]/HSIZE branch endpoints disagree\n", bit);
            WireId junction = ctx->getWireByNameStr(junctions[bit]);
            if (junction == WireId() || ctx->getBoundWireNet(junction) != net)
                log_error("agrv2k: exact HADDR[%d]/HSIZE branch junction is not owned by "
                          "the control net\n", bit);
            for (auto edge = first; edge != edges.end(); ++edge) {
                PipId pip = ctx->getPipByNameStr(edge->src + "." + edge->dst);
                if (pip == PipId())
                    log_error("agrv2k: exact HADDR[%d]/HSIZE branch pip is absent: %s -> %s\n",
                              bit, edge->src.c_str(), edge->dst.c_str());
                WireId dst = ctx->getPipDstWire(pip);
                NetInfo *owner = ctx->getBoundWireNet(dst);
                if (owner == net)
                    continue;
                if (owner != nullptr || !ctx->checkPipAvailForNet(pip, net))
                    log_error("agrv2k: exact HADDR[%d]/HSIZE branch conflicts at %s -> %s\n",
                              bit, edge->src.c_str(), edge->dst.c_str());
                ctx->bindPip(pip, net, STRENGTH_LOCKED);
                ++locked;
            }
        }
        log_info("agrv2k: extended exact HSIZE[0]/HSIZE[2] nets to HADDR[0]/HADDR[1] "
                 "over %d witnessed pips\n", locked);
    }

    void lock_fabric_ahb_haddr29_sram_base()
    {
        struct Edge {
            int step;
            std::string src, dst;
        };
        std::vector<Edge> edges;
        Csv csv(path("mcu_slave_ahb_haddr29_sram_base_paths.csv"));
        csv.next();
        while (csv.next()) {
            if (csv.at(0).empty())
                continue;
            if (csv.at(0) != "slave_ahb_haddr[29]")
                log_error("agrv2k: unexpected signal in exact SRAM-base HADDR[29] route table: %s\n",
                          csv.at(0).c_str());
            edges.push_back({to_int(csv.at(1), -1), csv.at(2), csv.at(3)});
        }
        std::sort(edges.begin(), edges.end(), [](const Edge &a, const Edge &b) {
            return a.step < b.step;
        });
        if (edges.size() != 4)
            log_error("agrv2k: exact SRAM-base HADDR[29] route table has %d/4 edges\n",
                      int(edges.size()));
        for (size_t i = 0; i < edges.size(); ++i)
            if (edges[i].step != int(i) || (i && edges[i - 1].dst != edges[i].src))
                log_error("agrv2k: discontinuous exact SRAM-base HADDR[29] route table\n");

        CellInfo *payload = nullptr;
        NetInfo *net = nullptr;
        for (auto &item : ctx->cells) {
            CellInfo *cell = item.second.get();
            if (cell->type != ctx->id("MCU_DOUT"))
                continue;
            int bit = -1;
            if (mcu_dout_lane(cell->name.str(ctx), bit) != LANE_SHADDR || bit != 29)
                continue;
            NetInfo *candidate = cell->getPort(ctx->id("DOUT"));
            if (is_exact_fabric_ahb_haddr29_hsel_register(ctx, candidate)) {
                if (payload != nullptr)
                    log_error("agrv2k: multiple exact SRAM-base HADDR[29] endpoints\n");
                payload = cell;
                net = candidate;
            }
        }
        if (payload == nullptr)
            return;

        CellInfo *driver = net->driver.cell;
        if (driver->bel == BelId()) {
            BelId exact_bel = ctx->getBelByNameStr("X14Y7_SLICE14");
            if (exact_bel == BelId() || !ctx->checkBelAvail(exact_bel))
                log_error("agrv2k: exact SRAM-base HADDR[29]/HSEL source BEL is unavailable\n");
            ctx->bindBel(exact_bel, driver, STRENGTH_LOCKED);
            if (!isBelLocationValid(exact_bel, true))
                log_error("agrv2k: exact SRAM-base HADDR[29]/HSEL source BEL is illegal\n");
            driver->attrs.erase(ctx->id("BEL"));
        }
        if (payload->bel == BelId() || driver->bel == BelId())
            log_error("agrv2k: exact SRAM-base HADDR[29] endpoints are unplaced before route lock\n");
        WireId source = ctx->getBelPinWire(driver->bel, net->driver.port);
        WireId target = ctx->getBelPinWire(payload->bel, ctx->id("DOUT"));
        if (ctx->getWireName(source).str(ctx) != edges.front().src ||
                ctx->getWireName(target).str(ctx) != edges.back().dst)
            log_error("agrv2k: exact SRAM-base HADDR[29] route endpoints disagree\n");
        NetInfo *source_owner = ctx->getBoundWireNet(source);
        if (source_owner == nullptr)
            ctx->bindWire(source, net, STRENGTH_LOCKED);
        else if (source_owner != net)
            log_error("agrv2k: exact SRAM-base HADDR[29]/HSEL source wire conflicts\n");
        int locked = 0;
        for (const Edge &edge : edges) {
            PipId pip = ctx->getPipByNameStr(edge.src + "." + edge.dst);
            if (pip == PipId())
                log_error("agrv2k: exact SRAM-base HADDR[29] pip is absent: %s -> %s\n",
                          edge.src.c_str(), edge.dst.c_str());
            WireId dst = ctx->getPipDstWire(pip);
            NetInfo *owner = ctx->getBoundWireNet(dst);
            if (owner == net)
                continue; // the first HSEL/HADDR[29] edge is deliberately shared
            if (owner != nullptr || !ctx->checkPipAvailForNet(pip, net))
                log_error("agrv2k: exact SRAM-base HADDR[29] route conflicts at %s -> %s\n",
                          edge.src.c_str(), edge.dst.c_str());
            ctx->bindPip(pip, net, STRENGTH_LOCKED);
            ++locked;
        }
        log_info("agrv2k: extended exact HSEL net to SRAM-base HADDR[29] over %d new pips\n",
                 locked);
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
        // Regions that are already active at this point encode earlier,
        // stronger placement knowledge (for example a witnessed relative
        // topology). Snapshot them before creating any broad MCU Regions so
        // two heuristic cone components do not accidentally arbitrate each
        // other. The later attraction may yield, but hard endpoint/site/pin
        // legality remains in isBelLocationValid().
        std::set<Region *> prior_slice_regions;
        for (auto &item : ctx->cells) {
            CellInfo *cell = item.second.get();
            if (cell->type != slice_type)
                continue;
            Region *region = cell->region;
            if (region != nullptr && region->constr_bels)
                prior_slice_regions.insert(region);
        }
        std::set<CellInfo *> candidates;
        for (auto &item : ctx->cells) {
            CellInfo *cell = item.second.get();
            const McuEndpointRequirement typed_endpoint =
                    mcu_endpoint_requirement(ctx, cell);
            if (typed_endpoint.malformed())
                log_error("agrv2k: MCU Region rejects malformed typed endpoint on '%s': %s\n",
                          ctx->nameOf(cell), typed_endpoint.error.c_str());
            if (cell->type == slice_type && cell->bel == BelId() &&
                !cell->attrs.count(bel_attr) && cell->region == nullptr &&
                cell->cluster == ClusterId() &&
                !native_direct_d_pool_cell(ctx, cell) &&
                !typed_endpoint.active)
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
                for (auto &user : port_it->second.net->users) {
                    if (user.cell != nullptr && candidates.count(user.cell)) {
                        seeds.push_back({user.cell, row, 1});
                        ++typed_seeds;
                        continue;
                    }
                    if (user.cell == nullptr)
                        continue;
                    const McuEndpointRequirement typed_endpoint =
                            mcu_endpoint_requirement(ctx, user.cell);
                    if (!typed_endpoint.active)
                        continue;
                    // The exact direct HWDATA25 consumer is native-placed and
                    // intentionally receives no broad Region. Preserve the
                    // existing convergence guidance for its ordinary
                    // downstream cone by seeding the first fabric successors.
                    std::set<NetInfo *> outputs;
                    for (const char *output_name : {"Q", "F"}) {
                        NetInfo *output = user.cell->getPort(ctx->id(output_name));
                        if (output == nullptr || !outputs.insert(output).second)
                            continue;
                        for (auto &successor : output->users)
                            if (successor.cell != nullptr &&
                                candidates.count(successor.cell)) {
                                seeds.push_back({successor.cell, row, 1});
                                ++typed_seeds;
                            }
                    }
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

            int overlapping_prior_regions = 0;
            for (Region *prior : prior_slice_regions) {
                bool overlaps = false;
                for (BelId bel : prior->bels) {
                    if (ctx->getBelType(bel) != slice_type)
                        continue;
                    Loc loc = ctx->getBelLocation(bel);
                    if (loc.x >= x0 && loc.x <= x1 && loc.y >= y0 && loc.y <= y1) {
                        overlaps = true;
                        break;
                    }
                }
                overlapping_prior_regions += overlaps;
            }
            if (overlapping_prior_regions) {
                log_info("agrv2k: broad heuristic MCU Region yields for %d-cell cone at "
                         "X%d..%d Y%d..%d overlapping %d active prior Region(s); "
                         "hard endpoint/site/pin legality remains active\n",
                         int(component.size()), x0, x1, y0, y1,
                         overlapping_prior_regions);
                continue;
            }

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
        reject_unsupported_shared_control_ingress(ctx);
        pack_constants(ctx);
        pack_bram_trim(ctx); // drop a read-only BRAM's don't-care DataInA (avoids an unroutable GND fanout)
        pack_io(ctx);
        pack_carries(ctx);   // dedicated HW carry: fuse AG32_FA(+DFF) -> GENERIC_SLICE keeping CIN/COUT
        pack_lut_lutffs(ctx);
        pack_nonlut_ffs(ctx);
        pack_inactive_constant_slice_clocks(ctx);
        validate_native_direct_d_pool(ctx, false);
        pack_mcu_edge(ctx);  // bind MCU_DOUT exit cells AFTER fusion (binding before corrupts a readout net
                             // shared with a fusing LUT -> stale port). Names survive; bels still free.
        refresh_mcu_endpoint_owner("pack", false);
        // Reserve the witnessed request-source sites before any ordinary
        // placement can consume one. Their exact routes are locked later,
        // after placement has established the rest of the fabric topology.
        bind_fabric_ahb_independent_control_sources();
        lock_uart_tx_corridors(ctx); // exact simultaneous hard-UART0/UART1/UART2 data/OE route to PIN_10
        lock_spi0_tx_corridors(ctx); // exact simultaneous SCK/CSN/MOSI data+OE routes
        lock_spi1_tx_corridors(ctx); // independent hard-SPI1 roots to the same L48 pad triplet
        lock_i2c_corridors(ctx); // exact SCL/SDA data+OE+input open-drain composition
        pack_clk(ctx);       // bind the clock input pad to CLKIN (else the placer may drop it on an OPAD)
        refresh_global_clock_owner("pack", false);
        pack_bram_localize_const(ctx); // per-pin local constants for BRAM control (not the stranded global net)
        pack_bram_pin_drivers(ctx); // slot-exact dynamic BRAM ingress on the loaded gated graph
        tie_left_link_data_gnd(ctx); // exact alta_rio-style local zero; only OE needs a fabric route
        pack_output_pin_drivers(ctx); // slot-exact physical output-pad ingress on the gated graph
        pack_left_oe_quad(ctx); // four independent exact left-edge dynamic-OE trunks
        pack_left_link_inputs(ctx); // exact bidirectional-link input reduction corridors
        pack_distribution_root_bels(ctx); // source must exist before exact route-through prefixes lock
        pack_route_through_bels(ctx); // reserve exact complete-footprint sites first
        pack_entry_buffers(); // vendor-style identity buffer per lane for multi-entry LUTs
        pack_shared_fanin_clusters(ctx, soft_ripple_region_witness);
        pack_mcu_relative_clusters(ctx); // movable, conducting MCU boundary producer/consumer units
        reject_unbound_shared_controls_before_placement(ctx);
        reject_malformed_native_endpoints_before_placement(ctx);
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
        const bool end_pack_clock_complete = global_clock_consumers_placed();
        if (end_pack_clock_complete) {
            refresh_global_clock_resources("end-pack", true);
            audit_global_clock_routes("end-pack import", false);
            lock_global_clock_tree("end-pack");
        } else {
            // Relative clusters intentionally remain unplaced in --pack-only
            // output.  Their one logical owner/source is already hard-checked,
            // but their exact leaves do not exist until placement resolves the
            // cluster root.  Admit no imported protected resource in this
            // deferred state; postPlace/preRoute performs full tree closure.
            refresh_global_clock_owner("end-pack deferred", false);
            global_clock_expected_pips.clear();
            global_clock_expected_wires.clear();
            global_clock_expected_order.clear();
            global_clock_resources_frozen = false;
            audit_global_clock_routes("end-pack deferred import", false);
            log_info("agrv2k: end-pack deferred typed GCLK0 leaf closure for "
                     "unplaced relative cluster(s)\n");
        }
        lock_fabric_ahb_independent_controls(); // exact eleven-source request-control composition
        lock_fabric_ahb_haddr01_hsize_branches(); // shared retained backbones, exact suffixes
        lock_fabric_ahb_haddr2_dynamic(); // one exact registered address lane
        lock_fabric_ahb_haddr29_sram_base(); // HSEL also presents the 0x20000000 base bit
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
        // Imported bindings bypass the router predicate and arrived before
        // pack established exact endpoint owners.  Audit them now: an active
        // lane may be absent for router2 or already complete, never partial.
        audit_carry_routes("end-pack", false);
        audit_special_routes("end-pack", false);
        audit_global_clock_routes("end-pack", end_pack_clock_complete);
        audit_mcu_endpoint_routes("end-pack", false);
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

    bool shared_clock_tile_compatible(const CellInfo *cell, BelId candidate,
                                      bool explain_invalid) const
    {
        const SharedClockRequirement requirement = shared_clock_requirement(ctx, cell);
        if (requirement.malformed()) {
            if (explain_invalid)
                log_info("agrv2k validity: active registered slice '%s' at %s is malformed: %s\n",
                         ctx->nameOf(cell), ctx->nameOfBel(candidate),
                         requirement.malformed_reason());
            return false;
        }
        if (!requirement.active())
            return true;
        const Loc loc = ctx->getBelLocation(candidate);
        for (BelId tile_bel : ctx->getBelsByTile(loc.x, loc.y)) {
            CellInfo *occupant = ctx->getBoundBelCell(tile_bel);
            if (occupant == nullptr || occupant == cell)
                continue;
            const SharedClockRequirement occupied = shared_clock_requirement(ctx, occupant);
            if (occupied.malformed()) {
                if (explain_invalid)
                    log_info("agrv2k validity: tile occupant '%s' at %s is a malformed "
                             "active registered slice: %s\n",
                             ctx->nameOf(occupant), ctx->nameOfBel(tile_bel),
                             occupied.malformed_reason());
                return false;
            }
            if (shared_clock_requirements_compatible(requirement, occupied))
                continue;
            if (explain_invalid)
                log_info("agrv2k validity: registered slice '%s' at %s requires shared "
                         "CLOCK net '%s', but tile occupant '%s' at %s requires net '%s'\n",
                         ctx->nameOf(cell), ctx->nameOfBel(candidate),
                         ctx->nameOf(requirement.clock), ctx->nameOf(occupant),
                         ctx->nameOfBel(tile_bel), ctx->nameOf(occupied.clock));
            return false;
        }
        return true;
    }

    void prePlace() override
    {
        // This is essential for --no-pack: establish one exact admitted source
        // and logical owner before any possibly parallel placement callback.
        refresh_global_clock_owner("pre-place", false);
        refresh_mcu_endpoint_owner("pre-place", false);
    }

    void postPlace() override
    {
        refresh_mcu_endpoint_owner("post-place", true);
        refresh_global_clock_resources("post-place", true);
        audit_global_clock_routes("post-place import", false);
        lock_global_clock_tree("post-place");
        audit_global_clock_routes("post-place", true);
    }

    void preRoute() override
    {
        audit_mcu_endpoint_routes("pre-route import", false);
        refresh_mcu_endpoint_owner("pre-route", true, true);
        refresh_global_clock_resources("pre-route", true);
        audit_global_clock_routes("pre-route import", false);
        lock_global_clock_tree("pre-route");
        audit_global_clock_routes("pre-route", true);
        // Repeat the aggregate import audit after placement, then freeze the
        // four O(1) owner identities used by router2's negotiation predicate.
        audit_carry_routes("pre-route", false);
        audit_special_routes("pre-route", false);
        refresh_special_route_owners(true);
        validate_native_direct_d_pool(ctx, true);
        std::map<int, SharedClockRequirement> per_tile;
        int active = 0;
        int register_inputs = 0;
        int native_endpoints = 0;
        int typed_mcu_endpoints = 0;
        for (auto &entry : ctx->cells) {
            CellInfo *cell = entry.second.get();
            const NativeEndpointRequirement endpoint =
                    native_endpoint_requirement(ctx, cell);
            const McuEndpointRequirement mcu_endpoint =
                    mcu_endpoint_requirement(ctx, cell);
            if (mcu_endpoint.malformed())
                log_error("agrv2k: pre-route DRC rejects malformed typed MCU endpoint "
                          "consumer '%s': %s\n", ctx->nameOf(cell),
                          mcu_endpoint.error.c_str());
            if (endpoint.malformed()) {
                if (cell->bel == BelId())
                    log_error("agrv2k: pre-route DRC rejects malformed native endpoint on "
                              "unbound '%s': %s\n", ctx->nameOf(cell), endpoint.error.c_str());
                else
                    log_error("agrv2k: pre-route DRC rejects malformed native endpoint on '%s' "
                              "at %s: %s\n", ctx->nameOf(cell), ctx->nameOfBel(cell->bel),
                              endpoint.error.c_str());
            }
            // --no-place is not an alternate endpoint-placement mode.  Typed
            // endpoint intent is active hard legality, so routing may begin
            // only after a BEL has been supplied by placement or an explicit
            // fixed constraint.  Inspect the protocol before the general
            // unbound-cell skip so a hand-edited routed JSON cannot reach
            // router2 without ever satisfying endpoint admission.
            if (cell->bel == BelId()) {
                if (endpoint.active())
                    log_error("agrv2k: pre-route DRC rejects active native endpoint on '%s': "
                              "no BEL is bound before routing\n", ctx->nameOf(cell));
                if (mcu_endpoint.active)
                    log_error("agrv2k: pre-route DRC rejects typed HWDATA25 consumer '%s': "
                              "no BEL is bound before routing\n", ctx->nameOf(cell));
                continue;
            }
            if (!native_endpoint_cell_admitted(ctx, cell, cell->bel, true))
                log_error("agrv2k: pre-route DRC rejects native endpoint on '%s' at %s: "
                          "the bound BEL fails its typed physical admission\n",
                          ctx->nameOf(cell), ctx->nameOfBel(cell->bel));
            if (!mcu_endpoint_cell_admitted(cell, cell->bel, true))
                log_error("agrv2k: pre-route DRC rejects typed HWDATA25 consumer '%s' at %s: "
                          "the bound BEL/input fails exact first-hop reachability\n",
                          ctx->nameOf(cell), ctx->nameOfBel(cell->bel));
            const SharedClockRequirement requirement = shared_clock_requirement(ctx, cell);
            if (requirement.malformed())
                log_error("agrv2k: pre-route DRC rejects malformed active registered slice "
                          "'%s' at %s: %s\n",
                          ctx->nameOf(cell), ctx->nameOfBel(cell->bel),
                          requirement.malformed_reason());
            if (cell->type == ctx->id("GENERIC_SLICE")) {
                const SharedControlRequirement control =
                        shared_control_requirement(ctx, cell);
                if (control.malformed())
                    log_error("agrv2k: pre-route DRC rejects malformed shared control on "
                              "'%s' at %s: %s\n", ctx->nameOf(cell),
                              ctx->nameOfBel(cell->bel), control.error.c_str());
                if (control.active())
                    log_error("agrv2k: pre-route DRC rejects shared control on '%s' at %s: "
                              "%s\n", ctx->nameOf(cell), ctx->nameOfBel(cell->bel),
                              unsupported_shared_control_diagnostic());
                const RegisterInputRequirement input = register_input_requirement(ctx, cell);
                if (input.malformed())
                    log_error("agrv2k: pre-route DRC rejects malformed register input on '%s' "
                              "at %s: %s\n", ctx->nameOf(cell), ctx->nameOfBel(cell->bel),
                              input.error.c_str());
                if (!register_input_bel_valid(ctx, cell, cell->bel, true))
                    log_error("agrv2k: pre-route DRC rejects %s register input on '%s' at %s: "
                              "the bound BEL fails its physical resource/site admission\n",
                              register_input_mode_name(input.mode), ctx->nameOf(cell),
                              ctx->nameOfBel(cell->bel));
                // A user-supplied fixed placement must not bypass the same
                // fixed-endpoint and carry-topology checks used by normal
                // placer admission. This closes the analogous --no-place
                // boundary for registered-pad, feedthrough, compute, and
                // carry modes without inventing cell-name site policy.
                if (!fixed_endpoint_pins_reachable(cell, cell->bel, true)) {
                    if (endpoint.active())
                        log_error("agrv2k: pre-route DRC rejects native endpoint on '%s' at %s: "
                                  "fixed endpoint pins are unreachable\n",
                                  ctx->nameOf(cell), ctx->nameOfBel(cell->bel));
                    log_error("agrv2k: pre-route DRC rejects register input on '%s' at %s: "
                              "fixed endpoint pins are unreachable\n",
                              ctx->nameOf(cell), ctx->nameOfBel(cell->bel));
                }
                if (input.mode == RegisterInputMode::CARRY_SUM_TO_FF &&
                    !dedicated_carry_pins_reachable(cell, cell->bel, true))
                    log_error("agrv2k: pre-route DRC rejects carry register input on '%s' at %s: "
                              "dedicated carry pins are unreachable\n",
                              ctx->nameOf(cell), ctx->nameOfBel(cell->bel));
                if (input.mode != RegisterInputMode::NONE)
                    ++register_inputs;
                if (endpoint.active())
                    ++native_endpoints;
                if (mcu_endpoint.active)
                    ++typed_mcu_endpoints;
            }
            if (!requirement.active())
                continue;
            ++active;
            const Loc loc = ctx->getBelLocation(cell->bel);
            const int tile = tkey(loc.x, loc.y);
            auto prior = per_tile.find(tile);
            if (prior == per_tile.end()) {
                per_tile.emplace(tile, requirement);
                continue;
            }
            if (!shared_clock_requirements_compatible(prior->second, requirement))
                log_error("agrv2k: pre-route DRC rejects tile X%dY%d: registered slice "
                          "'%s' requires shared CLOCK net '%s', while '%s' requires net '%s'\n",
                          loc.x, loc.y, ctx->nameOf(prior->second.cell),
                          ctx->nameOf(prior->second.clock), ctx->nameOf(requirement.cell),
                          ctx->nameOf(requirement.clock));
        }
        if (active)
            log_info("agrv2k: pre-route DRC verified %d active shared CLOCK requirement(s) "
                     "across %d tile(s)\n", active, int(per_tile.size()));
        if (register_inputs)
            log_info("agrv2k: pre-route DRC verified %d typed register-input requirement(s)\n",
                     register_inputs);
        if (native_endpoints)
            log_info("agrv2k: pre-route DRC verified %d typed native endpoint(s)\n",
                     native_endpoints);
        if (typed_mcu_endpoints)
            log_info("agrv2k: pre-route DRC verified %d typed HWDATA25 consumer(s)\n",
                     typed_mcu_endpoints);
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

    bool checkPipAvailForNet(PipId pip, const NetInfo *net) const override
    {
        // The static architecture gate is deliberately first.  A typed owner
        // never resurrects a PIP rejected by the existing hard graph policy.
        if (!checkPipAvail(pip))
            return false;
        if (!carry_pip_legal(pip, net))
            return false;
        if (!global_clock_pip_legal(pip, net))
            return false;
        if (!mcu_endpoint_pip_legal(pip, net))
            return false;
        return special_route_pip_legal(pip, net);
    }

    void notifyPipChange(PipId pip, NetInfo *net) override
    {
        // Generic calls this before installing the binding, including JSON
        // imports which precede pack().  Validate the prospective local edge;
        // the end-pack aggregate audit then proves whole-lane closure.
        if (net != nullptr && !checkPipAvailForNet(pip, net))
            log_error("agrv2k: typed resource notification rejects PIP %s for net '%s'\n",
                      ctx->getPipName(pip).str(ctx).c_str(), ctx->nameOf(net));
    }

    void notifyWireChange(WireId wire, NetInfo *net) override
    {
        if (net != nullptr && mcu_endpoint_profile.owner != nullptr &&
            (wire == mcu_endpoint_profile.root ||
             wire == mcu_endpoint_profile.after_first_hop) &&
            net != mcu_endpoint_profile.owner)
            log_error("agrv2k: foreign net '%s' binds typed HWDATA25 protected wire %s\n",
                      ctx->nameOf(net), ctx->getWireName(wire).str(ctx).c_str());
        if (net != nullptr && global_clock_resources_frozen &&
            global_clock_protected_wires.count(wire.index) &&
            (net != global_clock_owner ||
             !global_clock_expected_wires.count(wire.index)))
            log_error("agrv2k: typed GCLK0 notification rejects wire %s for net '%s'\n",
                      ctx->getWireName(wire).str(ctx).c_str(), ctx->nameOf(net));
        if (!special_routes_enabled || net == nullptr)
            return;
        auto protected_it = special_route_wire_lane.find(wire.index);
        if (protected_it == special_route_wire_lane.end())
            return;
        const int wire_lane = protected_it->second;
        const SpecialRouteLane &lane = special_route_lanes.at(wire_lane);
        if (lane.owner != nullptr && lane.owner != net)
            log_error("agrv2k: foreign net '%s' binds active typed lane %d wire %s\n",
                      ctx->nameOf(net), wire_lane, ctx->getWireName(wire).str(ctx).c_str());
        for (const SpecialRouteLane &owner_lane : special_route_lanes)
            if ((owner_lane.owner == net ||
                 (owner_lane.owner == nullptr && net_matches_special_lane(net, owner_lane))) &&
                owner_lane.index != wire_lane)
                log_error("agrv2k: typed lane %d owner enters lane %d protected wire %s\n",
                          owner_lane.index, wire_lane, ctx->getWireName(wire).str(ctx).c_str());
    }

    void postRoute() override
    {
        audit_carry_routes("post-route", true);
        audit_special_routes("post-route", true);
        audit_global_clock_routes("post-route", true);
        audit_mcu_endpoint_routes("post-route", true);
    }

    // ---- legality: STAGE-GATED.
    //   Stage 0/1 = permissive (prove build + graph load + end-to-end pipeline on a trivial design).
    //   Stage 2   = even-slot + conducting-pair (port engine_work/pin_densepack.py).
    //   Stage 3   = exit-lane reachability (port engine_work/pin_ahb_condplace.py) — the pivotal test.
    bool isBelLocationValid(BelId bel, bool explain_invalid) const override
    {
        CellInfo *ci = ctx->getBoundBelCell(bel);
        if (ci == nullptr)
            return true;
        if (ci->type == ctx->id("ALTA_BRAM9K")) {
            std::vector<NetInfo *> clocks;
            for (const char *port : {"Clk0", "Clk1"}) {
                NetInfo *clock = ci->getPort(ctx->id(port));
                if (clock != nullptr)
                    clocks.push_back(clock);
            }
            if (clocks.empty())
                return true;
            if (ctx->getBelName(bel).str(ctx) != "X13Y4_BRAM") {
                if (explain_invalid)
                    log_info("agrv2k validity: N5.7A admits BRAM clock topology only at X13Y4_BRAM\n");
                return false;
            }
            for (NetInfo *clock : clocks) {
                if (global_clock_owner_prepared && clock != global_clock_owner) {
                    if (explain_invalid)
                        log_info("agrv2k validity: BRAM '%s' has a port which does not use "
                                 "the one GCLK0 owner\n", ctx->nameOf(ci));
                    return false;
                }
            }
            return true;
        }
        if (ci->type != ctx->id("GENERIC_SLICE"))
            return true; // ordinary IO/MCU hard BELs are not conduction-constrained

        Loc loc = ctx->getBelLocation(bel);
        if (!shared_clock_tile_compatible(ci, bel, explain_invalid))
            return false;
        if (!global_clock_cell_compatible(ci, explain_invalid))
            return false;
        if (!shared_control_cell_admitted(ctx, ci, bel, explain_invalid))
            return false;
        if (!register_input_bel_valid(ctx, ci, bel, explain_invalid))
            return false;
        const NativeEndpointRequirement endpoint =
                native_endpoint_requirement(ctx, ci);
        if (!native_endpoint_cell_admitted(ctx, ci, bel, explain_invalid))
            return false;
        if (!mcu_endpoint_cell_admitted(ci, bel, explain_invalid))
            return false;
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
                            ci->attrs.count(ctx->id("AGRV2K_MCU_PINPACKED")) != 0 ||
                            endpoint.allows_odd_slice();
        const bool direct_d_site = qualified_direct_d_site(ctx, bel);
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
                ci->attrs.count(ctx->id("AGRV2K_DENSE_MCU_ODD_OK")) != 0 ||
                is_exact_fabric_ahb_independent_source_at(ctx, ci, bel) ||
                is_exact_fabric_ahb_haddr2_source_at(ctx, ci, bel);
        if (!is_carry && !is_pinpacked && !direct_d_site &&
                !(route_through_cell && route_through_site) &&
                !strict_allows_odd && (loc.z & 1) != 0) {
            if (explain_invalid)
                log_info("agrv2k validity: ordinary cell '%s' at %s uses an unqualified odd slice\n",
                         ctx->nameOf(ci), ctx->nameOfBel(bel));
            return false;
        }

        // CONDUCTING-PAIR: every already-placed DATA neighbour must sit on a tile that conducts in the
        // net's driver->user direction (same tile via crossbar, or a proven directed inter-tile RMUX path).
        // Skip the clock (global tree, not the mesh), constants, and high-fanout nets.
        // NOTE: as a HARD reject this is too tight for nextpnr's SA placer to satisfy on the sparse
        // conducting tile-graph (large chains fail to find a legal placement). Gated behind
        // AGRV2K_CONDPAIR=1 while we evaluate router-side conduction gating + clustering as the
        // convergent path; even-slot alone (above) is the always-on intra-tile guarantee.
        if (tile_adj.empty() || std::getenv("AGRV2K_CONDPAIR") == nullptr)
            return true;
        auto conducts_from = [&](CellInfo *driver) -> bool {
            if (driver == nullptr || driver == ci || driver->type != ctx->id("GENERIC_SLICE"))
                return true;
            if (driver->bel == BelId())
                return true; // neighbour not placed yet
            Loc driver_loc = ctx->getBelLocation(driver->bel);
            return tiles_conduct(driver_loc.x, driver_loc.y, loc.x, loc.y);
        };
        auto conducts_to = [&](CellInfo *user) -> bool {
            if (user == nullptr || user == ci || user->type != ctx->id("GENERIC_SLICE"))
                return true;
            if (user->bel == BelId())
                return true; // neighbour not placed yet
            Loc user_loc = ctx->getBelLocation(user->bel);
            return tiles_conduct(loc.x, loc.y, user_loc.x, user_loc.y);
        };
        for (auto &pe : ci->ports) {
            if (pe.first == ctx->id("CLK"))
                continue; // clock rides the global tree, not the RMUX mesh
            NetInfo *net = pe.second.net;
            if (net == nullptr)
                continue;
            if (net->users.entries() > 24)
                continue; // global/high-fanout (reset, enable, const); not a point-to-point data hop
            if (!conducts_from(net->driver.cell)) {
                if (explain_invalid)
                    log_info("agrv2k validity: cell '%s' at %s cannot conduct net '%s' from placed driver '%s'\n",
                             ctx->nameOf(ci), ctx->nameOfBel(bel), ctx->nameOf(net),
                             ctx->nameOf(net->driver.cell));
                return false;
            }
            for (auto &u : net->users)
                if (!conducts_to(u.cell)) {
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
