"""``agentcad targets``: the registered output targets and what each can do."""

import json


def cmd_targets(args):
    from agentcad import targets

    described = targets.describe()
    if args.json:
        print(json.dumps(described, indent=2))
        return 0
    for t in described:
        caps = ", ".join(t["capabilities"]) or "no capabilities"
        state = "" if t["available"] else " (not available here)"
        version = f" {t['version']}" if t["version"] else ""
        print(f"{t['name']:<12}{version}{state}: {caps}")
    return 0


def register(subparsers, groups):
    p = subparsers.add_parser("targets", help="Registered output targets and the capabilities each declares")
    p.add_argument("--json", action="store_true", help="Print the targets as JSON")
    p.set_defaults(func=cmd_targets)
