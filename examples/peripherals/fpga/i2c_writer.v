/*
 * Minimal standard-mode I2C controller: START, 7-bit address + write, one data
 * byte, STOP.  Outputs are open-drain enables; connect them through tri-state
 * I/O cells and external pull-ups.  Clock stretching and arbitration are not
 * implemented, so this is an educational single-master block, not SMBus.
 */
module ag32_i2c_writer #(
    parameter integer CLOCKS_PER_PHASE = 125
) (
    input  wire       clock,
    input  wire       reset_n,
    input  wire       start,
    input  wire [6:0] address,
    input  wire [7:0] data,
    input  wire       sda_in,
    output reg        scl_drive_low,
    output reg        sda_drive_low,
    output reg        busy,
    output reg        done,
    output reg        ack_error
);
    localparam IDLE=0, START_A=1, START_B=2, BIT_LOW=3, BIT_HIGH=4,
               ACK_LOW=5, ACK_HIGH=6, STOP_A=7, STOP_B=8, STOP_C=9;
    reg [3:0] state;
    reg [31:0] divider;
    reg [7:0] shift;
    reg [2:0] bit_number;
    reg byte_number;
    wire phase_tick = divider == CLOCKS_PER_PHASE - 1;

    always @(posedge clock) begin
        if (!reset_n) begin
            state <= IDLE;
            divider <= 0;
            shift <= 0;
            bit_number <= 0;
            byte_number <= 0;
            scl_drive_low <= 0;
            sda_drive_low <= 0;
            busy <= 0;
            done <= 0;
            ack_error <= 0;
        end else begin
            done <= 0;
            if (state == IDLE) begin
                divider <= 0;
                scl_drive_low <= 0;
                sda_drive_low <= 0;
                busy <= 0;
                if (start) begin
                    shift <= {address, 1'b0};
                    bit_number <= 7;
                    byte_number <= 0;
                    ack_error <= 0;
                    busy <= 1;
                    state <= START_A;
                end
            end else if (phase_tick) begin
                divider <= 0;
                case (state)
                    START_A: begin
                        scl_drive_low <= 0;
                        sda_drive_low <= 1;
                        state <= START_B;
                    end
                    START_B: begin
                        scl_drive_low <= 1;
                        state <= BIT_LOW;
                    end
                    BIT_LOW: begin
                        scl_drive_low <= 1;
                        sda_drive_low <= ~shift[bit_number];
                        state <= BIT_HIGH;
                    end
                    BIT_HIGH: begin
                        scl_drive_low <= 0;
                        if (bit_number == 0)
                            state <= ACK_LOW;
                        else begin
                            bit_number <= bit_number - 1'b1;
                            state <= BIT_LOW;
                        end
                    end
                    ACK_LOW: begin
                        scl_drive_low <= 1;
                        sda_drive_low <= 0;
                        state <= ACK_HIGH;
                    end
                    ACK_HIGH: begin
                        scl_drive_low <= 0;
                        if (sda_in)
                            ack_error <= 1;
                        if (!byte_number) begin
                            byte_number <= 1;
                            shift <= data;
                            bit_number <= 7;
                            state <= BIT_LOW;
                        end else
                            state <= STOP_A;
                    end
                    STOP_A: begin
                        scl_drive_low <= 1;
                        sda_drive_low <= 1;
                        state <= STOP_B;
                    end
                    STOP_B: begin
                        scl_drive_low <= 0;
                        state <= STOP_C;
                    end
                    default: begin
                        sda_drive_low <= 0;
                        busy <= 0;
                        done <= 1;
                        state <= IDLE;
                    end
                endcase
            end else
                divider <= divider + 1'b1;
        end
    end
endmodule
