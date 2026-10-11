`timescale 1ns/1ps

// Byte-stream echo application. It is the template's placeholder for a
// core-specific application: every accepted byte is returned unchanged on the
// output stream. One register stage holds the byte, so a stalled output
// backpressures the input and nothing is dropped or reordered.
module nuboard_stream_echo (
    input  wire        clock,

    input  wire        input_valid,
    output wire        input_ready,
    input  wire [7:0]  input_data,
    input  wire        input_last,

    output reg         output_valid = 1'b0,
    input  wire        output_ready,
    output reg  [7:0]  output_data = 8'h00,
    output reg         output_last = 1'b0
);
    // Accept a byte whenever the stage is empty or is being emptied this cycle.
    assign input_ready = !output_valid || output_ready;

    always @(posedge clock) begin
        if (input_valid && input_ready) begin
            output_valid <= 1'b1;
            output_data <= input_data;
            output_last <= input_last;
        end else if (output_ready) begin
            output_valid <= 1'b0;
        end
    end
endmodule
