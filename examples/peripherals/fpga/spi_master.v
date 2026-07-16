/* One-byte SPI mode-0 master.  The slave samples MOSI on rising SCLK. */
module ag32_spi_master #(
    parameter integer CLOCKS_PER_HALF_BIT = 4
) (
    input  wire       clock,
    input  wire       reset_n,
    input  wire       start,
    input  wire [7:0] tx_data,
    input  wire       miso,
    output reg        sclk,
    output wire       mosi,
    output reg        cs_n,
    output reg  [7:0] rx_data,
    output reg        busy,
    output reg        done
);
    reg [31:0] divider;
    reg [3:0] half_cycle;
    reg [7:0] shift_tx;

    assign mosi = shift_tx[7];

    always @(posedge clock) begin
        if (!reset_n) begin
            divider <= 0;
            half_cycle <= 0;
            shift_tx <= 0;
            rx_data <= 0;
            sclk <= 0;
            cs_n <= 1;
            busy <= 0;
            done <= 0;
        end else begin
            done <= 0;
            if (!busy) begin
                sclk <= 0;
                cs_n <= 1;
                if (start) begin
                    divider <= 0;
                    half_cycle <= 0;
                    shift_tx <= tx_data;
                    rx_data <= 0;
                    cs_n <= 0;
                    busy <= 1;
                end
            end else if (divider == CLOCKS_PER_HALF_BIT - 1) begin
                divider <= 0;
                if (!sclk) begin
                    sclk <= 1;
                    rx_data <= {rx_data[6:0], miso};
                end else begin
                    sclk <= 0;
                    shift_tx <= {shift_tx[6:0], 1'b0};
                    if (half_cycle == 15) begin
                        cs_n <= 1;
                        busy <= 0;
                        done <= 1;
                    end
                end
                half_cycle <= half_cycle + 1'b1;
            end else
                divider <= divider + 1'b1;
        end
    end
endmodule
