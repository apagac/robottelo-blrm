# -*- encoding: utf-8 -*-
# vim: ts=4 sw=4 expandtab ai
"""
task: https://github.com/omaciel/robottelo/issues/47
task: <more to follow>
"""

from lib.cli.subnet import Subnet
from lib.common.helpers import generate_name
from nose.plugins.attrib import attr
from tests.cli.basecli import BaseCLI


class TestSubnet(BaseCLI):
    """
    Subnet related tests.
    """

    @attr('cli', 'subnet')  # TODO makes nose to run group of tests
    def test_create_minimal_required_params(self):
        """
        create basic operation of subnet with minimal parameters required.
        """
        subnet = Subnet(self.conn)
        options = {}
        options['name'] = generate_name(8, 8)
        options['network'] = '192.168.104.0'  # TODO - needs random unique
        options['mask'] = '255.255.255.0'
        self.assertTrue(len(subnet.create(options)[1]) == 0, 'Subnet created')

    @attr('cli', 'subnet')
    def test_info(self):
        """
        basic `info` operation test.
        TODO - FOR DEMO ONLY, NEEDS TO BE REWORKED [gkhachik].
        """
        subnet_name = 'xnzwk4'
        subnet = Subnet(self.conn)
        _ret = subnet.info({'name': subnet_name})
        self.assertEquals(len(_ret), 1,
            "Subnet info - returns 1 record")
        self.assertEquals(_ret[0]['Name'], subnet_name,
            "Subnet info - check name")

    @attr('cli', 'subnet')
    def test_list(self):
        """
        basic `list` operation test.
        TODO - FOR DEMO ONLY, NEEDS TO BE REWORKED [gkhachik].
        """
        subnet = Subnet(self.conn)
        _ret = subnet.list({'per-page': '10'})
        self.assertGreater(len(_ret), 0,
            "Subnet list - returns >0 records")