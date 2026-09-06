# Internal registered feedback candidate

Ordinary inferred own-Q feedback now uses LUT input C and retains external
readers on registered Q. The LOCAL_QIN_I2 protocol requires an active register,
clock, own-Q on I2, a LUT that depends on that input, and an unused F output.
A dedicated internal routing edge is usable only by that same placed slice's
registered net. Its emission selects internal feedback without programming an
ordinary D-input route. Existing direct-D checkpoint handling remains separate.

This candidate is under qualification. Python model tests do not prove physical
operation, and source-generated identities may change. No broad silicon or
release claim follows from the new protocol. Simultaneous F/Q use remains
outside this mode until both physical output presentations are modeled.
