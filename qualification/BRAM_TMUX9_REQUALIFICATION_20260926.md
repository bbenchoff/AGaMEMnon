# Requalified retained BRAM checkpoints

The registered-output repair changes X14Y8 CFG_OMUX2[2] from F to Q in the two
packable zero-INIT TMUX9 checkpoints. Their corrected images were independently
compared and measured in paired hardware runs, recorded in
`registered_bram_tmux9_requalification_20260926.json` under `checkpoint`.

The public checkpoint CLI, legacy clock admission and installed-wheel check now
require those exact measured raw and compressed hashes. Both checkpoints must
reproduce them. Their sources, routes, clock topology and admission restrictions
are unchanged; initialized historical checkpoints remain refused.

The record also preserves source-profile experiments from the separate release
integration branch. This public update does not import those source-profile pins
or qualify fresh source builds, general BRAM modes, other sites or collisions.
