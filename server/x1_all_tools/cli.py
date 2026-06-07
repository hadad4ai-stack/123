from __future__ import annotations
import argparse, json, sys
from .dispatcher import ToolDispatcher
from .runtime import ToolRuntime
from .tools import build_registry

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="x1-all-tools")
    p.add_argument("--workspace", default="workspace")
    p.add_argument("--verbose-errors", action="store_true")
    p.add_argument("--shell-timeout", type=int, default=30)
    p.add_argument("--max-output-chars", type=int, default=30000)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    call = sub.add_parser("call")
    call.add_argument("tool")
    call.add_argument("arguments", nargs="?", default="{}")
    args = p.parse_args(argv)

    rt = ToolRuntime.create(args.workspace, verbose_errors=args.verbose_errors, shell_timeout=args.shell_timeout, max_output_chars=args.max_output_chars)
    disp = ToolDispatcher(build_registry(), rt)
    if args.command == "list":
        print(json.dumps(disp.manifest(), ensure_ascii=False, indent=2))
        return 0
    try:
        payload = json.loads(args.arguments)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"invalid JSON: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    result = disp.call(args.tool, payload).to_dict()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
