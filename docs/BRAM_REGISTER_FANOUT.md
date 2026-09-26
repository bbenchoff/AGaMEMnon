# Register fanout from BRAM pin packing

A register driving a BRAM input can also drive ordinary fabric logic. Its
`AGRV2K_OMUX_SEL` placement hint identifies the BRAM-facing output; it does not
replace the register's other routed outputs. Bit generation now preserves all
Q-owned output selections alongside that hint. Combinational F outputs remain
separate, including slices exposing both F and Q.

The triggering completed-read test used outputs 0 and 2 from one counter
register. The old image selected Q only on output 0, so output 2 presented LUT
logic to an ordinary fabric branch. Correcting just that selector and the image
checksum restored the test in two controlled SRAM loads. The original failed
both interleaved loads; vendor and shared references and recovery checks passed.
Repacking the retained routes with this fix reproduces the corrected image
byte-for-byte. This establishes the retained implementation's repair, not
qualification of all BRAM modes or fresh placement seeds.

The independent OMUX checker now accepts fanout beyond a BRAM hint and checks
each routed output against its actual F/Q owner. A placement hint can also
differ from the router's eventual output. A missing pin-packing marker,
out-of-range hint, inactive Q, ambiguous owner, or incorrect selection bit
still fails validation.
