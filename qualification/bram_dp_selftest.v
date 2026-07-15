(* top *)
module bram_dp_selftest(
    input  wire clock,
    input  wire reset,
    output wire led
);
    reg [8:0] address;
    reg [1:0] expected;
    reg [1:0] state;
    reg error;
    reg done;
    wire [1:0] read_data;
    wire [1:0] pattern = address[1:0] ^ 2'b01;

    wire write_enable = state == 0;
    wire read_enable = state == 1;

    bram_dp_selftest_ram memory_i (
        .clock(clock),
        .write_address(address),
        .write_data(pattern),
        .write_enable(write_enable),
        .read_address(address),
        .read_enable(read_enable),
        .read_data(read_data)
    );

    always @(posedge clock) begin
        if (reset) begin
            address <= 0;
            expected <= 0;
            state <= 0;
            error <= 0;
            done <= 0;
        end else begin
            case (state)
                0: begin
                    if (address == 9'h1ff) begin
                        address <= 0;
                        state <= 1;
                    end else address <= address + 1'b1;
                end
                1: begin
                    if (address != 0 && read_data != expected)
                        error <= 1;
                    expected <= pattern;
                    if (address == 9'h1ff) begin
                        state <= 2;
                    end else address <= address + 1'b1;
                end
                2: begin
                    if (read_data != expected)
                        error <= 1;
                    done <= !error && (read_data == expected);
                    state <= 3;
                end
                default: state <= state;
            endcase
        end
    end

    assign led = done;
endmodule

module bram_dp_selftest_ram(
    input wire clock,
    input wire [8:0] write_address,
    input wire [1:0] write_data,
    input wire write_enable,
    input wire [8:0] read_address,
    input wire read_enable,
    output wire [1:0] read_data
);
    reg [1:0] memory [0:511];
    reg [1:0] result;
    always @(posedge clock) begin
        if (write_enable)
            memory[write_address] <= write_data;
        if (read_enable)
            result <= memory[read_address];
    end
    assign read_data = result;
endmodule
