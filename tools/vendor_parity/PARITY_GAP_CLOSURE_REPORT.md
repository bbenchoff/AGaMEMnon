# Parity-gap closure worklog

This worklog records desk-side changes against the frozen vendor-parity
frontier. A routed image is not a silicon result, and a passing unit or
byte-identity gate is not a claim of broad vendor parity.

## D0: hermetic nextpnr build and router2 reservation probe

Status: desk-qualified for commit; no board claim.

The release build now applies the Viaduct timing hooks and the two router2
reservation corrections from checked-in patch files to the pinned upstream
nextpnr revision. It also builds a synthetic microarchitecture used only for a
mandatory process-boundary capability probe. The probe deliberately creates a
satisfiable case in which a high-fanout constant net is inserted first and a
signal net needs the shared choke resource. A qualifying executable must route
the signal through that choke and the constant through its local source.

The corrections are intentionally narrow:

- consolidated packer constant nets are not given irrevocable heuristic
  pre-reservations; their actual routes still pass through normal availability
  and negotiated-congestion checks;
- when two different nets collide in heuristic pre-reservation, neither wins
  by processing order. The resource is returned to normal negotiated
  congestion for that run;
- the dead `NEXTPNR_ROUTER2_STAGNATION_LIMIT` setting was removed. There is no
  runtime claim that stock router2 honors a private stagnation-limit knob.

Reproduction and negative control:

- a linked clean checkout at pinned nextpnr revision `2b560ad0` was built
  through `agamemnon/engine/uarch/agrv2k/build.sh`;
- a second invocation was idempotent: both patches and both microarchitecture
  registrations were detected as already present;
- with both patches, the synthetic fixture routed `SIG` through `CHOKE` and
  the constant net through `LOCAL_GND`;
- after reversing only the reservation patch and rebuilding, stock router2
  failed the otherwise satisfiable signal arc; reapplying the patch restored
  the passing result.

Gates run on 2026-08-26:

| Gate | Result |
|---|---|
| Focused hermetic/probe tests | 73 passed |
| Qualified pack regression / byte-identity set | 59 passed |
| Full Python suite | 1526 passed, 46 skipped |
| `addsub16` user-form canary | Routed desk image after the existing LUT-carry fallback; timing and strict bitgen checks passed |
| `regbank16` user-form canary | No image after 40 attempts; every attempt stopped at post-placement fixed-input conduction legality before routing |

The `regbank16` result retains the already documented no-image frontier; it is
not a newly introduced failure and no routing conclusion follows from a
placement-stage rejection. The `addsub16` result is useful desk evidence but
has not been run on silicon in this change and therefore does not close a
parity item.
