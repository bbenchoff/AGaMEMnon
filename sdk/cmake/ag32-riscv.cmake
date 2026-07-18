set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR riscv32)

if(DEFINED ENV{RISCV_PREFIX})
  set(_AG32_PREFIX "$ENV{RISCV_PREFIX}")
  set(_AG32_GCC "${_AG32_PREFIX}gcc")
  set(_AG32_OBJCOPY "${_AG32_PREFIX}objcopy")
else()
  find_program(_AG32_GCC NAMES riscv64-unknown-elf-gcc riscv-none-elf-gcc REQUIRED)
  find_program(_AG32_OBJCOPY NAMES riscv64-unknown-elf-objcopy riscv-none-elf-objcopy REQUIRED)
endif()

set(CMAKE_C_COMPILER "${_AG32_GCC}")
set(CMAKE_ASM_COMPILER "${_AG32_GCC}")
set(CMAKE_OBJCOPY "${_AG32_OBJCOPY}")
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

execute_process(
  COMMAND "${_AG32_GCC}" -dumpversion
  OUTPUT_VARIABLE _AG32_GCC_VERSION
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(_AG32_GCC_VERSION VERSION_GREATER_EQUAL 12)
  set(_AG32_MARCH "rv32imac_zicsr")
else()
  set(_AG32_MARCH "rv32imac")
endif()

set(CMAKE_C_FLAGS_INIT "-march=${_AG32_MARCH} -mabi=ilp32 -ffreestanding -fno-builtin -ffunction-sections -fdata-sections")
set(CMAKE_ASM_FLAGS_INIT "-march=${_AG32_MARCH} -mabi=ilp32")
