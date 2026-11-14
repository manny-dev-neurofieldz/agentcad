"""``agentcad plugin export``: the skills and the reviewer agent as a plugin for an agent harness;
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
    print(f"{args.target} plugin {plugin.NAME} {plugin.manifest()['version']}: {len(written)} files in {args.output}")
    for path in written:
        print(f"  {path}")
    if args.target == "claude-code":
        print(f"\nCheck it: claude plugin validate --strict {args.output}/.claude-plugin/plugin.json")
        print(f"Use it:   claude --plugin-dir {args.output}  (the agentcad command must be installed there too)")
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

    pe = sub.add_parser("export", help="Write the plugin into a folder (empty, new, or an earlier export)")
    pe.add_argument("--target", required=True, choices=TARGETS, help="The harness the plugin is for")
    pe.add_argument("-o", "--output", required=True, help="Folder to write the plugin into")
    pe.add_argument("--marketplace", action="store_true",
                    help="Also write a local marketplace manifest offering the plugin from the same folder")
    pe.set_defaults(func=cmd_plugin_export)

    ph = sub.add_parser("hook", help="Run one of the plugin's hooks on the harness's JSON payload (stdin)")
    ph.add_argument("event", choices=EVENTS, help="The hook to run")
    ph.add_argument("--plugin-version", default=None,
                    help="The agentcad version the plugin was exported from (session-start compares it)")
    ph.set_defaults(func=cmd_plugin_hook)
