# BRAM control selector encoding

TMUX and KMUX use flat configuration arrays, but each destination owns its
own field: eight bits per TMUX and nine per KMUX. A routed source replaces
that field's baseline; it must not OR a whole-family control snapshot into it.

`bram_control_codewords.csv` contains 26 recovered source/destination/displacement
keys. These extracted data associations were checked against nine retained
reference records in AG32-Docs research commit `4570fdecb`. They are selector
encoding evidence, not qualification of arbitrary BRAM writes or dual-port
behavior. Unknown sources are not represented by a destination-only fallback.

The emitter checks physical field cells and rejects two different sources
requesting the same control field. Known scoped checkpoint replacements retain
precedence over ordinary entries; their established image-hash gates remain.
Both ordinary and dual-R/W control routes require source-specific resolution.
The old `bram_resolver.json` CTRL section is retained as historical data but is
not used to emit TMUX/KMUX routes.

Do not infer complete memory-mode support from successful selector mapping.
Source compilation, simultaneous ownership, read/write sequencing and stored
state still require behavioral qualification.
