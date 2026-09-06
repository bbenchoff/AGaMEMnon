# Inferred AHB RAM development interface

`agamemnon/rtl/mcu_ahb_ram.v` provides a synchronous inferred 32-bit RAM with
an AHB-Lite protocol core and a separate full-width AG32 hard-port wrapper.
This interface is under development and has not been qualified on silicon.

The default memory contains 512 words at `0x60000000`. The core captures the
address phase, inserts one wait cycle, and consumes registered HWDATA in the
completing data phase. Reads use the synchronous memory result. Aligned word
transfers are supported; subword, unaligned and out-of-window transfers receive
a two-cycle error response and cannot write storage. Reset cancels a pending
transfer and retains memory contents. `BASE_ADDR` must be word-aligned.

The protocol tests cover every default address, distinct full-word values,
walking-one/zero data, overlapping transfers, global stalls, error responses
and cancellation by reset. They run with zero and nonzero initialization.
These simulations do not establish mapped bitstream or silicon correctness.

The hard-port wrapper does not discard upper HWDATA or HADDR lanes. Full-width
routing, multi-block control emission, nonzero initialized-writable admission,
byte enables and repeatable silicon qualification remain work to complete.
