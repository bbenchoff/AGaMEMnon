# Exact Phase1C non-programming halt/read probe. No reset, run, or write.
halt
mdw 0x03000100 1
reg misa
shutdown
