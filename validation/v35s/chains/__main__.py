"""python -m validation.v35s.chains gen | acquire | report | facts | score | sim | fit | adopt [...]"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from .families import FAMILIES, PARITIES, WAITS, generate
from .image import build_image


def _count_table(chains) -> str:
    rows = Counter(c.family for c in chains)
    chain_counts = {f: len({c.id.rsplit("-p", 1)[0] for c in chains if c.family == f})
                    for f in rows}
    lines = [f"{'family':<7} {'variants':>8} {'runs':>6}"]
    for family in FAMILIES:
        if family in rows:
            lines.append(f"{family:<7} {chain_counts[family]:>8} {rows[family]:>6}")
    lines.append(f"{'total':<7} {sum(chain_counts.values()):>8} {len(chains):>6}")
    return "\n".join(lines)


def gen_main(args) -> int:
    chains = generate(args.family, waits=args.waits, parities=args.parity)
    if args.list or args.check:
        for chain in chains:
            built = build_image(chain)          # raises on any byte or parity mismatch
            if args.list:
                print(f"{chain.id:<40} {chain.parity:<4} w{chain.waits:<2} "
                      f"wtc={chain.wtc:04X} base={built.chain_base:05X}")
                for instr in chain.instrs:
                    tag = instr.form + (f"#{instr.marker_id}" if instr.marker_id is not None
                                        else f"[{instr.index}]" if instr.index is not None
                                        else "")
                    print(f"    +{instr.offset:03X} {built.chain_base + instr.offset:05X} "
                          f"{instr.role:<6} {tag:<22} {instr.code.hex(' ')}")
        if args.check:
            print(f"checked {len(chains)} images: catalog bytes at their offsets, parity ok")
    print(_count_table(chains))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m validation.v35s.chains")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("gen", help="generate chains, list them, check the images")
    gen.add_argument("--family", nargs="+", choices=list(FAMILIES), default=None)
    gen.add_argument("--waits", nargs="+", type=int, choices=WAITS, default=list(WAITS))
    gen.add_argument("--parity", nargs="+", choices=PARITIES, default=list(PARITIES))
    gen.add_argument("--list", action="store_true", help="print every chain's bytes")
    gen.add_argument("--check", action="store_true", help="build and verify every image")
    gen.set_defaults(func=gen_main)

    # acquire.py (WP2) may be absent; it builds its own subparser when present.
    try:
        from .acquire import build_parser as acquire_parser, main as acquire_main
    except ImportError:
        acquire_main = None
    if acquire_main is not None:
        acquire = acquire_parser(sub.add_parser("acquire", help="run chains on the board"))
        acquire.set_defaults(func=lambda args: acquire_main(args=args))

    from .report import add_arguments, facts_main, report_main
    report = add_arguments(sub.add_parser("report", help="tables and strips of recorded runs"))
    report.set_defaults(func=report_main)
    facts = add_arguments(sub.add_parser("facts", help="derived per-run facts"), json_flag=True)
    facts.set_defaults(func=facts_main)

    from .score import add_score_arguments, add_sim_arguments, adopt_main, score_main, sim_main
    score = add_score_arguments(sub.add_parser("score", help="model vs silicon exact match"))
    score.set_defaults(func=score_main)
    sim = add_sim_arguments(sub.add_parser("sim", help="model event list of one chain"))
    sim.set_defaults(func=sim_main)
    adopt = sub.add_parser("adopt", help="make a fit JSON the tracked fit (sim.config.FIT_PATH)")
    adopt.add_argument("path", help="config JSON, e.g. build/validation/v35s/chains/fit/fit.json")
    adopt.set_defaults(func=adopt_main)

    from .fit import add_arguments as fit_arguments, fit_main
    fit = fit_arguments(sub.add_parser("fit", help="staged fit of the cycle model"))
    fit.set_defaults(func=fit_main)

    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
