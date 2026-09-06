# TMUX09 source-image ground-route qualification

The current ordinary source flow emits a changed ground route for the two
fixed-address TMUX09 write profiles. Both hold-profile images remain identical.
The changed write images passed comparison against the previously witnessed
source images on AGRV2KL48 at HSE 8 MHz / SYSCLK 10 MHz.

All 16 reference/candidate captures passed across two repetitions and four
write/hold cases, with 500/500 expected output samples in each capture. Three
known-good controls passed; final reset succeeded, custody was released and
there were no flash writes. Exact identities, capture results and the immutable
evidence reference are in
`qualification/registered_bram_tmux9_ground_route_silicon.json`.

The CLI source-build identity guard now uses these newly witnessed images.
The original checkpoint identities and the prior source-image qualification
record remain intact. This does not broaden admission to arbitrary RAM designs.

This evidence covers one fixed address and one observed data lane in each
profile. General writes, independent addresses, full-word storage, masks,
dual-port behavior, other sites and clocks, capacity, timing closure and complete
installed SDK validation remain separate requirements.
