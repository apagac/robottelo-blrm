# -*- encoding: utf-8 -*-
"""Usage::

    hammer role [OPTIONS] SUBCOMMAND [ARG] ...

Parameters::

    SUBCOMMAND                    subcommand
    [ARG] ...                     subcommand arguments

Subcommands::

    create                        Create an role.
    delete                        Delete an role.
    filters                       List all filters.
    list                          List all roles.
    update                        Update an role.
"""

from robottelo.cli.base import Base


class Role(Base):
    """Manipulates Katello engine's role command."""

    command_base = 'role'
