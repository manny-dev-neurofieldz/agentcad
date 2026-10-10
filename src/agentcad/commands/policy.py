"""``agentcad policy``: list, navigate and read the policies that ship with each capability."""

import json
import sys

from agentcad import policy as pol


def cmd_policy_list(args):
    policies = pol.all_policies()
    if args.json:
        print(json.dumps([{"name": p.name, "title": p.title, "type": p.header.get("Type", ""),
                           "status": p.header.get("Status", ""),
                           "commands": [" ".join(("agentcad",) + c) for c in p.commands]}
                          for p in policies], indent=2))
        return 0
    if not policies:
        print("No policies are installed with this agentcad.")
        return 0
    width = max(len(p.name) for p in policies)
    for p in policies:
        governs = ", ".join(" ".join(c) for c in p.commands) or "(practice; no command)"
        print(f"{p.name:<{width}}  {p.title}")
        print(f"{'':<{width}}  governs: {governs}")
    print("\nNext: agentcad policy navigate NAME (its questions), then agentcad policy read NAME --section N")
    return 0


def cmd_policy_navigate(args):
    try:
        p = pol.get_policy(args.name)
    except pol.PolicyError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    lines, note = pol.navigation(p.text)
    print(f"=== {p.name}: navigation guide ===")
    print(pol.numbered(1, lines))
    if note:
        print(f"\n({note})")
    print(f"\nRead a section: agentcad policy read {p.name} --section N")
    return 0


def cmd_policy_read(args):
    try:
        p = pol.get_policy(args.name)
        if args.section:
            first, lines = pol.section(p.text, args.section)
        elif args.lines:
            first, lines = pol.line_range(p.text, args.lines)
        elif args.from_nav_boundary:
            first, lines = pol.after_boundary(p.text)
        else:
            first, lines = 1, p.text.split("\n")
    except pol.PolicyError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"=== {p.name} ===")
    print(pol.numbered(first, lines))
    return 0


def register(subparsers, groups):
    p_policy = subparsers.add_parser("policy", help="The policies that ship with each capability: list, navigate, read")
    sub = p_policy.add_subparsers(dest="policy_cmd", required=True)
    groups["policy"] = sub

    pl = sub.add_parser("list", help="Installed policies and the commands each governs")
    pl.add_argument("--json", action="store_true", help="Print the list as JSON")
    pl.set_defaults(func=cmd_policy_list)

    pn = sub.add_parser("navigate", help="A policy's navigation guide: its numbered topics and questions")
    pn.add_argument("name", help="Policy name, with or without the agentcad- prefix")
    pn.set_defaults(func=cmd_policy_navigate)

    pr = sub.add_parser("read", help="Read a policy, a section of it (with subsections), or a line range")
    pr.add_argument("name", help="Policy name, with or without the agentcad- prefix")
    which = pr.add_mutually_exclusive_group()
    which.add_argument("--section", default=None, help="Section number, e.g. 2 or 2.1 (subsections included)")
    which.add_argument("--lines", default=None, help="Line range START:END, 1-indexed and inclusive")
    which.add_argument("--from-nav-boundary", action="store_true",
                       help="Everything after the navigation guide")
    pr.set_defaults(func=cmd_policy_read)
