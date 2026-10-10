"""Command modules: each adds commands to the CLI without editing cli.py.

A module in this package defines ``register(subparsers, groups)``. ``subparsers``
is the top-level subparsers action; ``groups`` maps a command group's name
(``probe``, ``gcode``, ``gallery``, ``session``, and any group a module adds)
to that group's subparsers action, so a module can add a subcommand under an
existing group. Modules are imported in name order when the parser is built.
A module that fails to import or register is reported on stderr and skipped;
the other commands keep working.
"""
