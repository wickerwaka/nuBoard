from __future__ import annotations

import argparse
import json
import sys

from .device import NuBoard, NuBoardError


def _print(value, json_mode: bool) -> None:
    if isinstance(value, bytes):
        try:
            value = json.loads(value)
        except (UnicodeDecodeError, json.JSONDecodeError):
            value = {"raw": value.hex()}
    if json_mode:
        print(
            json.dumps(
                value,
                separators=(",", ":"),
                default=lambda item: item.__dict__,
            )
        )
    elif isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}: {item}")
    else:
        print(value)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="nuboard")
    root.add_argument("--json", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("info")
    commands.add_parser("status")
    config = commands.add_parser("configure")
    config.add_argument("image")
    fpga = commands.add_parser("fpga").add_subparsers(
        dest="fpga_command",
        required=True,
    )
    send = fpga.add_parser("send")
    send.add_argument("data")
    send.add_argument("--channel", type=int, default=0)
    send.add_argument("--tag", type=int, default=0)
    fpga.add_parser("recv")
    fpga.add_parser("status")
    commands.add_parser("events")
    vccb = commands.add_parser("vccb").add_subparsers(
        dest="vccb_command",
        required=True,
    )
    vccb.add_parser("enable")
    vccb.add_parser("disable")
    power = commands.add_parser("power").add_subparsers(
        dest="power_command", required=True
    )
    power.add_parser("off")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        with NuBoard() as board:
            if args.command == "info":
                _print(board.info(), args.json)
            elif args.command == "status":
                _print(board.state(), args.json)
            elif args.command == "configure":
                progress = None
                if not args.json:
                    progress = lambda done, total: print(
                        f"\r{done}/{total}", end="", flush=True
                    )
                board.configure(args.image, progress)
                if not args.json:
                    print()
                _print({"configured": True}, args.json)
            elif args.command == "events":
                for event in board.events():
                    _print(event.__dict__, args.json)
            elif args.command == "vccb":
                if args.vccb_command == "enable":
                    board.vccb_enable()
                else:
                    board.vccb_disable()
            elif args.command == "power":
                board.power_off()
            elif args.fpga_command == "send":
                board.fpga_send(args.channel, bytes.fromhex(args.data), args.tag)
            elif args.fpga_command == "recv":
                channel, flags, tag, data = board.fpga_recv()
                _print(
                    {
                        "channel": channel,
                        "flags": flags,
                        "tag": tag,
                        "data": data.hex(),
                    },
                    args.json,
                )
            else:
                _print(board.link_status(), args.json)
        return 0
    except (NuBoardError, ValueError, OSError) as exc:
        status = getattr(getattr(exc, "status", None), "name", None)
        _print({"error": str(exc), "status": status}, args.json)
        return 2


if __name__ == "__main__":
    sys.exit(main())
