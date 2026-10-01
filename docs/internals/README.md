# Implementation notes

Design notes for individual packer, router, bitgen and RTL mechanisms,
including opt-in experiments. User-facing behaviour is described in
[STATUS](../STATUS.md) and [USAGE](../USAGE.md); these notes explain how a
mechanism works and how it was qualified.

- [Experimental ABC9 LUT4 mapping](ABC9_EXPERIMENTAL.md)
- [BRAM control selector encoding](BRAM_CONTROL_ENCODING.md)
- [Register fanout from BRAM pin packing](BRAM_REGISTER_FANOUT.md)
- [Long carry corridor correction](CARRY_CORRIDOR_CORRECTION.md)
- [Registered carry local inputs](CARRY_LOCAL_INPUTS.md)
- [Synchronous reset in carry SUM slices](CARRY_RESET_FUSION.md)
- [Control-sharing selection](CONTROL_SHARING_SELECTION.md)
- [Ordinary routing-aware placement](DEFAULT_TILE_PACKING.md)
- [Fabric AHB read-master core](FABRIC_AHB_READ_MASTER.md)
- [HIL campaign work lists](HIL_CAMPAIGN.md)
- [Local clock sharing: supported scope and qualification](LOCAL_CLOCK_SHARING.md)
- [Local constant replication (`AGRV2K_LOCAL_CONSTANTS`) — opt-in, experimental](LOCAL_CONSTANT_RECOVERY.md)
- [Internal registered feedback candidate](LOCAL_QIN_CANDIDATE.md)
- [Native clock-enable plus local Qin experiment](LOCAL_QIN_NATIVE_ENABLE_EXPERIMENT.md)
- [MCU External-AHB soft UART](MCU_AHB_SOFT_UART.md)
- [High-address logic ingress](mcu_haddr_region_logic.md)
- [Native-enable packing audit](NATIVE_ENABLE_PACKING_AUDIT.md)
- [Typed register-input legality](REGISTER_INPUT_LEGALITY.md)
- [Shared register-control legality](SHARED_CONTROL_LEGALITY.md)
- [Unused generated constants](UNUSED_CONSTANT_RECOVERY.md)
- [Source-typed crossbar experiment](XBAR_SOURCE_TYPED_EXPERIMENT.md)
