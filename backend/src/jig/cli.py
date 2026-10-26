"""Backend command line: `python -m jig.cli sample|ping|doctor`."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import platform
import shutil
import sys
import tempfile
from pathlib import Path

from jig.ai.client import AIError, ModelClient
from jig.ai.config import load_model_config
from jig.ai.cost import CostMeter
from jig.cad.builder import Builder
from jig.cad.samples import SAMPLES
from jig.fea.ccx import find_ccx
from jig.settings import Settings, get_settings


def cmd_sample(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    code = SAMPLES[args.name]
    with tempfile.TemporaryDirectory() as scratch:
        builder = Builder(Path(scratch), timeout_s=180)
        try:
            result = builder.build(code)
        finally:
            builder.close()
        if not result.ok:
            print(f"Build failed: {result.data.get('error')}", file=sys.stderr)
            return 1
        for name in ("part.step", "part.stl", "part.py"):
            shutil.copyfile(result.out_dir / name, out / f"{args.name}{Path(name).suffix}")
    stats = result.data["stats"]
    size = " x ".join(f"{v:.1f}" for v in stats["bbox"]["size"])
    print(
        f"Built {args.name} in {result.elapsed_ms} ms: valid={stats['valid']}, "
        f"solids={stats['solids']}, volume={stats['volume_mm3']:.1f} mm3, size={size} mm"
    )
    print(f"Wrote {out / (args.name + '.step')}")
    return 0 if stats["valid"] and stats["solids"] == 1 else 1


def cmd_ping(_: argparse.Namespace) -> int:
    settings = get_settings()
    config = load_model_config()
    meter = CostMeter(config=config, budget_usd=settings.budget_usd)
    client = ModelClient(config, meter, key_lookup=Settings.api_key)
    try:
        message = {"role": "user", "content": "Reply with the single word: ready"}
        result = asyncio.run(client.chat("orchestrator", [message]))
    except AIError as error:
        print(f"Meta Model API call failed: {error}", file=sys.stderr)
        return 1
    print(f"{result.model} via {result.provider} replied {result.content.strip()!r}")
    print(f"{result.latency_ms} ms, about ${result.cost_usd:.5f}")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    settings = get_settings()
    ok = True
    print(f"Python      {platform.python_version()} on {platform.system()} {platform.machine()}")
    try:
        print(f"build123d   {importlib.metadata.version('build123d')}")
        import build123d  # noqa: F401
    except Exception as error:  # report, don't crash
        ok = False
        print(f"build123d   NOT WORKING: {error}")
    ccx = find_ccx(settings.ccx_path)
    print(f"CalculiX    {ccx.message}")
    if not ccx.available:
        print(f"            {ccx.to_dict()['install_hint']}")
    for name, provider in load_model_config().providers.items():
        state = "set" if Settings.api_key(provider.api_key_env) else "not set"
        print(f"{name:<11} {provider.api_key_env} is {state}")
    print(f"Data dir    {settings.data_dir}")
    print(f"Budget      ${settings.budget_usd:.2f} per session")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jig")
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample", help="build a sample part and write STEP/STL/.py")
    sample.add_argument("--name", default="l_bracket", choices=sorted(SAMPLES))
    sample.add_argument("--out", default="build-output")
    sample.set_defaults(func=cmd_sample)
    sub.add_parser("ping", help="make one Meta Model API call").set_defaults(func=cmd_ping)
    sub.add_parser("doctor", help="check the local setup").set_defaults(func=cmd_doctor)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
