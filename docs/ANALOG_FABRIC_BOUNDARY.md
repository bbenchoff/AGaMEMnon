# Analog/fabric boundary

The strict open flow currently exposes three read-only analog hard-block
routes: `AGRV2K_ADC0_DB0`, `AGRV2K_ADC0_DB1`, and `AGRV2K_ADC0_EOC`. Raw
route-bar `src_sub` values 0, 1, and 12 match the decoded grid-pin ordering and
establish distinct hard-output identities even though vendor route.tx names all
three nets by the ADC cell instance. The public graph therefore gives each pin
a private synthetic first-exit wire before joining the shared fabric topology.

The DB0 and DB1 strict smokes each route seven pips and map five configurable
fields; their vendor oracles each pass 49 selector checks. EOC routes eight
pips, maps six fields, and passes 59 checks. All have zero unmapped pips and two
fixed hard-boundary hops. Reproducible hashes are recorded in the three
`qualification/analog_adc0_*_route_evidence.jsonl` ledgers.

This is route support only. AGaMEMnon does not configure or start the ADC, does
not arbitrate MCU/fabric ownership, and makes no ADC timing, electrical, or
silicon-function claim. DB0 and DB1 both use a symbolically named `InputMUX01`
in route.tx; their raw `src_sub` identities and private public exits prevent
that lossy name from merging the hard pins. The checked smoke images must not
be treated as board qualification images.

The remaining ten ADC0 data lanes, fabric-to-ADC controls, DACs, comparators,
register drivers, and board-level analog tests remain unsupported.
