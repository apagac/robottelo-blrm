# -*- encoding: utf-8 -*-
"""
Usage::

    hammer repository [OPTIONS] SUBCOMMAND [ARG] ...

Parameters::

    SUBCOMMAND                    subcommand
    [ARG] ...                     subcommand arguments

Subcommands::

    create                        Create a repository
    delete                        Destroy a repository
    info                          Show a repository
    list                          List of repositories
    synchronize                   Sync a repository
    update                        Update a repository
    upload-content                Upload content into the repository
"""

from robottelo.cli.base import Base


class Repository(Base):
    """
    Manipulates Katello engine's repository command.
    """

    command_base = 'repository'
    command_requires_org = True

    @classmethod
    def create(cls, options=None):
        cls.command_requires_org = False

        try:
            result = super(Repository, cls).create(options)
        finally:
            cls.command_requires_org = True

        return result

    @classmethod
    def info(cls, options=None):
        cls.command_requires_org = False

        try:
            result = super(Repository, cls).info(options)
        finally:
            cls.command_requires_org = True

        return result

    @classmethod
    def synchronize(cls, options):
        """
        Synchronizes a repository.
        """

        cls.command_sub = 'synchronize'

        result = cls.execute(
            cls._construct_command(options), output_format='csv')

        return result

    @classmethod
    def upload_content(cls, options):
        """Upload content to repository."""
        cls.command_sub = 'upload-content'
        result = cls.execute(
            cls._construct_command(options), output_format='csv')
        return result
