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

Run the fake-transport tests with:

```sh
PYTHONPATH=host/src python3 -m unittest discover -s host/tests -v
```
