set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR riscv32)

if(DEFINED ENV{RISCV_PREFIX})
  set(_AG32_PREFIX "$ENV{RISCV_PREFIX}")
else()
  set(_AG32_PREFIX "riscv64-unknown-elf-")
endif()

set(CMAKE_C_COMPILER "${_AG32_PREFIX}gcc")
set(CMAKE_ASM_COMPILER "${_AG32_PREFIX}gcc")
set(CMAKE_OBJCOPY "${_AG32_PREFIX}objcopy")
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

set(CMAKE_C_FLAGS_INIT "-march=rv32imac -mabi=ilp32 -ffreestanding -fno-builtin -ffunction-sections -fdata-sections")
set(CMAKE_ASM_FLAGS_INIT "-march=rv32imac -mabi=ilp32")
