"""``agentcad plugin export``: agentcad's know-how written out for an agent harness (a plugin, a policy root, an
AGENTS.md, tool definitions; the policy root is for the MacEff framework, https://github.com/cversek/MacEff);
``agentcad plugin hook``: the plugin's hooks, run by the harness."""

import json
import sys


def cmd_plugin_export(args):
    from agentcad import plugin

    try:
        written = plugin.export(args.output, target=args.target, with_marketplace=args.marketplace)
    except plugin.PluginError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    import agentcad
    print(f"{args.target} export of {plugin.NAME} {agentcad.__version__}: {len(written)} files in {args.output}")
    for path in written:
        print(f"  {path}")
    if args.target == "claude-code":
        print(f"\nCheck it: claude plugin validate --strict {args.output}/.claude-plugin/plugin.json")
        print(f"Use it:   claude --plugin-dir {args.output}  (the agentcad command must be installed there too)")
    elif args.target == "maceff":
        from agentcad import policy
        print(f"\nMount the copy:       MACEFF_POLICY_ROOTS={plugin.NAME}={args.output}/policies")
        print(f"Or the installed one: MACEFF_POLICY_ROOTS={plugin.NAME}={policy.policy_dir()}  (never stale)")
    elif args.target == "agents-md":
        print(f"\nUse it: copy or link {args.output}/AGENTS.md to where the harness reads AGENTS.md")
    elif args.target == "api-tools":
        print(f"\nUse it: pass the list in {args.output}/tools.json as a model API request's tools; "
              f"{args.output}/README.md says how a call becomes a command")
    return 0


def cmd_plugin_hook(args):
    """The harness's JSON payload on stdin, the hook's answer on stdout (nothing when it has nothing to say).
    A payload that is not JSON is said on stderr with exit 1, which a harness reports without blocking."""
    from agentcad import plugin_hooks

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as e:
        print(f"agentcad plugin hook {args.event}: the payload is not JSON ({e})", file=sys.stderr)
        return 1
    answer = plugin_hooks.run(args.event, payload if isinstance(payload, dict) else {}, args.plugin_version)
    if answer:
        print(json.dumps(answer))
    return 0


def register(subparsers, groups):
    from agentcad.plugin import TARGETS
    from agentcad.plugin_hooks import EVENTS

    p_plugin = subparsers.add_parser("plugin", help="agentcad's skills and reviewer agent as a plugin for an agent harness")
    sub = p_plugin.add_subparsers(dest="plugin_cmd", required=True)
    groups["plugin"] = sub

    pe = sub.add_parser("export", help="Write agentcad's know-how for a harness into a folder (empty, new, or an "
                                       "earlier export for the same target)")
    pe.add_argument("--target", required=True, choices=TARGETS, help="What to write: a Claude Code plugin, a MacEff policy root, an AGENTS.md, or "
                                                                "tool definitions for a model API")
    pe.add_argument("-o", "--output", required=True, help="Folder to write the plugin into")
    pe.add_argument("--marketplace", action="store_true",
                    help="claude-code only: also write a local marketplace manifest offering the plugin from the same "
                         "folder")
    pe.set_defaults(func=cmd_plugin_export)

    ph = sub.add_parser("hook", help="Run one of the plugin's hooks on the harness's JSON payload (stdin)")
    ph.add_argument("event", choices=EVENTS, help="The hook to run")
    ph.add_argument("--plugin-version", default=None,
                    help="The agentcad version the plugin was exported from (session-start compares it)")
    ph.set_defaults(func=cmd_plugin_hook)
