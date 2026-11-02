`timescale 1ns/1ps

// V35S core v2, stage S2: the stub decode and class tables as a package (v35_decode_stub.svh).
// S1's generated v35_pkg.sv (fmt_t, the decode and class tables) replaces this package; the
// modules import it by name only.
package v35_stub_pkg;
`include "v35_decode_stub.svh"
endpackage
