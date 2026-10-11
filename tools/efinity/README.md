# Efinity toolchain container

Efinix only ships Efinity for Linux and Windows. On macOS the FPGA builds run
it inside an [Apple Container](https://github.com/apple/container) image
(linux/amd64, run under Rosetta on Apple silicon).

## One-time setup

Download the Linux x64 base release and the matching patch from the Efinix
support portal, then run:

```sh
tools/efinity/setup-container.sh \
    ~/Downloads/efinity-2026.1.132-linux-x64.tar.bz2 \
    ~/Downloads/efinity-2026.1.132.5.14-linux-x64-patch.zip
```

This builds `nuboard-efinity:<version>` and `nuboard-efinity:latest`. The patch
is optional. Run it again with newer archives to upgrade. `--tag NAME` picks a
different image name.

## Use

The `fpga/*/build.sh` scripts and `fpga/Makefile` pick the environment
automatically:

```sh
make -C fpga                 # route every image
make -C fpga heartbeat       # one image
./fpga/template/build.sh     # same thing, directly
```

To run any other Efinity tool, use `efinity-run`:

```sh
tools/efinity/efinity-run efx_run --help
tools/efinity/efinity-run                  # interactive shell
make -C fpga efx CMD="efx_pgm --help"
```

`efinity-run` mounts the repository at the same path inside the container and
keeps the current directory, so paths don't change. If the current directory
is outside the repository, it is mounted as well. On Linux with a native
install (`EFINITY_HOME` pointing at it), `efinity-run` skips the container.

| Variable                   | Default                  |
|----------------------------|--------------------------|
| `EFINITY_IMAGE`            | `nuboard-efinity:latest` |
| `EFINITY_CONTAINER_MEMORY` | `8G`                     |
| `EFINITY_CONTAINER_CPUS`   | all host CPUs            |
| `EFINITY_USE_CONTAINER=1`  | force the container on Linux |

The container has no USB access, so use a native install to program hardware
with `efx_pgm`.
