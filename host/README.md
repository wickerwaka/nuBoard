# nuBoard host tools

```sh
python3 -m pip install ./host
sudo install -m 0644 host/99-nuboard.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

Typical workflow:

```sh
nuboard info
nuboard status
nuboard configure build/fpga/template/outflow/template.hex.bin
nuboard fpga send --channel 0 --tag 1 68656c6c6f
nuboard events
nuboard fpga recv
nuboard vccb enable
nuboard vccb disable
nuboard power off
```

Place `--json` before the subcommand for machine-readable output. `events` uses
a blocking interrupt-endpoint reader thread rather than status polling.

Library users can use `NuBoard.fpga_exchange(channel, payload)` for one tagged
request/reply packet with interrupt-driven completion. It owns the event
consumer for that exchange; do not run `events()` concurrently on the same
instance. `nuboard.debug.DebugClient` adds the CPU-independent NDB1 read/write
and FPGA-local WAIT16 protocol used by the
[68000 harness](../docs/m68000-harness.md).

Run the fake-transport tests with:

```sh
PYTHONPATH=host/src python3 -m unittest discover -s host/tests -v
```
