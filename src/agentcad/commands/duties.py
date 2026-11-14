"""``agentcad duties``: the work a library's or a project's records say is owed, and, with ``--declare-on``, the
same work declared as duties on a role of the MacEff framework (https://github.com/cversek/MacEff)."""

import json
import sys
from datetime import date


def cmd_duties(args):
    from agentcad import duties as dutymod
    from agentcad import records as recmod

    if args.apply and not args.declare_on:
        print("Error: --apply declares duties on a role; name the role with --declare-on ROLE", file=sys.stderr)
        return 2
    try:
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    except ValueError:
        print(f"Error: --as-of {args.as_of!r} is not a date (YYYY-MM-DD)", file=sys.stderr)
        return 2
    try:
        found = recmod.load(args.path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    if not (found.parts or found.jobs or found.fits):
        print(f"Error: no part, job or fit records under {args.path}", file=sys.stderr)
        return 2
    if found.errors():
        print(f"agentcad duties: {len(found.errors())} record error(s); what is owed is read from fields that do "
              f"not all read as their contract says (agentcad records check {args.path} lists them)", file=sys.stderr)
    owed = dutymod.derive(found, as_of)
    report = dutymod.to_dict(owed, found, as_of)
    lines = dutymod.summary(owed, found, as_of)
    if args.declare_on:
        from dataclasses import asdict

        from agentcad import duty_roles
        if found.errors() and args.apply:
            print(f"Error: --apply: {len(found.errors())} record error(s): duties are not declared from records that do not "
                  f"read as their contract says; fix them (agentcad records check {args.path}) or drop --apply",
                  file=sys.stderr)
            return 2
        try:
            role_id, declared_duties = duty_roles.existing(args.declare_on)
            plan = duty_roles.plan(role_id, owed, declared_duties)
            declared = duty_roles.apply(plan) if args.apply else 0
        except duty_roles.RoleError as e:
            print(f"Error: --declare-on {args.declare_on}: {e}", file=sys.stderr)
            return 2
        report["roles"] = {"role": plan.role, "applied": bool(args.apply), "declared": declared,
                           "declare": [asdict(d) for d in plan.declare], "present": plan.present,
                           "reopened": plan.reopened, "lapsed": plan.lapsed}
        lines = lines + [""] + duty_roles.summary(plan, bool(args.apply))
    print(json.dumps(report, indent=2) if args.json else "\n".join(lines))
    return 0


def register(subparsers, groups):
    p = subparsers.add_parser("duties", help="The work the records say is owed: verdicts to record, plans past "
                                             "their day, fits to re-run")
    p.add_argument("path", help="A library or project folder, or one part.toml, job.toml or *.print.json manifest")
    p.add_argument("--as-of", default=None, metavar="DATE",
                   help="Judge planned days against this date, YYYY-MM-DD (default: today)")
    p.add_argument("--json", action="store_true", help="Print the duties as JSON (schema agentcad.duties/1)")
    p.add_argument("--declare-on", default=None, metavar="ROLE",
                   help="Compare the owed work with the duties of this MacEff role and show which are missing "
                        "(nothing is changed without --apply)")
    p.add_argument("--apply", action="store_true",
                   help="With --declare-on: declare the missing duties on the role")
    p.set_defaults(func=cmd_duties)
