/*
 * Synthetic, satisfiable regression architecture for router2's permanent
 * constant-net reservation bug. The graph and names are invented solely for
 * this test; it contains no device data.
 */

#include "nextpnr.h"
#include "viaduct_api.h"

#define GEN_INIT_CONSTIDS
#define VIADUCT_CONSTIDS "viaduct/agamemnon_router2_probe/constids.inc"
#include "viaduct_constids.h"

NEXTPNR_NAMESPACE_BEGIN

namespace {

struct Router2ProbeImpl : ViaductAPI
{
    void init(Context *ctx) override
    {
        init_uarch_constids(ctx);
        ViaductAPI::init(ctx);
        build_graph();
    }

    BelBucketId getBelBucketForCellType(IdString cell_type) const override { return cell_type; }
    bool isValidBelForCellType(IdString cell_type, BelId bel) const override
    {
        return ctx->getBelType(bel) == cell_type;
    }

    IdString getWireConstantValue(WireId wire) const override
    {
        return wire == local_gnd ? id_GND_VALUE : IdString();
    }

    void pack() override
    {
        // Keep this net first in insertion order: stock router2 will reserve
        // PREFIX and CHOKE for it before considering SIG.
        CellInfo *gnd_driver = ctx->createCell(ctx->id("$PACKER_GND"), id_GNDDRV);
        gnd_driver->addOutput(id_F);
        NetInfo *gnd = ctx->createNet(ctx->id("$PACKER_GND_NET"));
        gnd->constant_value = id_GND_VALUE;
        gnd_driver->connectPort(id_F, gnd);
        for (int i = 0; i < 4; ++i) {
            CellInfo *sink = ctx->createCell(ctx->idf("wide%d", i), id_WIDE);
            sink->addInput(id_IN);
            sink->connectPort(id_IN, gnd);
        }

        CellInfo *sig_driver = ctx->createCell(ctx->id("sig_driver"), id_SIGDRV);
        sig_driver->addOutput(id_F);
        NetInfo *sig = ctx->createNet(ctx->id("SIG"));
        sig_driver->connectPort(id_F, sig);
        CellInfo *sig_sink = ctx->createCell(ctx->id("sig_sink"), id_SIGSINK);
        sig_sink->addInput(id_IN);
        sig_sink->connectPort(id_IN, sig);
    }

  private:
    WireId local_gnd;

    WireId add_wire(const char *name, int x)
    {
        return ctx->addWire(IdStringList(ctx->id(name)), ctx->id("ROUTE"), x, 0);
    }

    void add_pip(const char *name, WireId src, WireId dst)
    {
        ctx->addPip(IdStringList(ctx->id(name)), ctx->id("PIP"), src, dst, 0.05, Loc(0, 0, 0));
    }

    void build_graph()
    {
        WireId gnd_out = add_wire("GND_OUT", 0);
        WireId prefix = add_wire("PREFIX", 1);
        WireId choke = add_wire("CHOKE", 2);
        WireId hub = add_wire("GND_HUB", 3);
        local_gnd = add_wire("LOCAL_GND", 3);

        WireId wide_in[4];
        for (int i = 0; i < 4; ++i)
            wide_in[i] = add_wire((std::string("WIDE_IN") + std::to_string(i)).c_str(), 4 + i);

        WireId sig_out = add_wire("SIG_OUT", 8);
        WireId sig_j1 = add_wire("SIG_J1", 7);
        WireId sig_j2 = add_wire("SIG_J2", 7);
        WireId sig_m1 = add_wire("SIG_M1", 3);
        WireId sig_m2 = add_wire("SIG_M2", 3);
        WireId sig_in = add_wire("SIG_IN", 4);

        BelId gnd_bel = ctx->addBel(IdStringList(ctx->id("GND_DRIVER")), id_GNDDRV, Loc(0, 0, 0), false, false);
        ctx->addBelOutput(gnd_bel, id_F, gnd_out);
        for (int i = 0; i < 4; ++i) {
            BelId bel = ctx->addBel(IdStringList(ctx->idf("WIDE_BEL%d", i)), id_WIDE,
                                    Loc(4 + i, 0, 0), false, false);
            ctx->addBelInput(bel, id_IN, wide_in[i]);
        }
        BelId sig_drv_bel =
                ctx->addBel(IdStringList(ctx->id("SIG_DRIVER")), id_SIGDRV, Loc(8, 0, 0), false, false);
        ctx->addBelOutput(sig_drv_bel, id_F, sig_out);
        BelId sig_sink_bel =
                ctx->addBel(IdStringList(ctx->id("SIG_SINK")), id_SIGSINK, Loc(4, 0, 1), false, false);
        ctx->addBelInput(sig_sink_bel, id_IN, sig_in);

        // The driver-side reservation walk sees one usable branch until HUB
        // and therefore locks CHOKE on stock router2.
        add_pip("GND_TO_PREFIX", gnd_out, prefix);
        add_pip("PREFIX_TO_CHOKE", prefix, choke);
        add_pip("CHOKE_TO_HUB", choke, hub);
        for (int i = 0; i < 4; ++i)
            add_pip((std::string("HUB_TO_WIDE") + std::to_string(i)).c_str(), hub, wide_in[i]);

        // Actual constant routing has a disjoint local source. Patched router2
        // uses it for all four constant sinks, leaving CHOKE for SIG.
        add_pip("LOCAL_GND_TO_HUB", local_gnd, hub);

        // Two branches at each endpoint prevent SIG's own reservation walk
        // from claiming CHOKE; both legal routes still cross it.
        add_pip("SIG_TO_J1", sig_out, sig_j1);
        add_pip("SIG_TO_J2", sig_out, sig_j2);
        add_pip("J1_TO_CHOKE", sig_j1, choke);
        add_pip("J2_TO_CHOKE", sig_j2, choke);
        add_pip("CHOKE_TO_M1", choke, sig_m1);
        add_pip("CHOKE_TO_M2", choke, sig_m2);
        add_pip("M1_TO_SIG_IN", sig_m1, sig_in);
        add_pip("M2_TO_SIG_IN", sig_m2, sig_in);
    }
};

struct Router2ProbeArch : ViaductArch
{
    Router2ProbeArch() : ViaductArch("agamemnon_router2_probe") {}
    std::unique_ptr<ViaductAPI> create(const dict<std::string, std::string> &) override
    {
        return std::make_unique<Router2ProbeImpl>();
    }
} router2_probe_arch;

} // namespace

NEXTPNR_NAMESPACE_END
