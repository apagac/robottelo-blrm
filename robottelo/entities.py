# -*- encoding: utf-8 -*-
"""This module defines all entities which Foreman exposes.

Each class in this module allows you to work with a certain set of logically
related API paths exposed by the server. For example,
:class:`robottelo.entities.Host` lets you work with the ``/api/v2/hosts`` API
path and sub-paths. Each class attribute corresponds an attribute of that
entity. For example, the ``Host.name`` class attribute represents the name of a
host. These class attributes are used by the various mixins, such as
``nailgun.entity_mixins.EntityCreateMixin``.

Each class contains an inner class named ``Meta``. This inner class contains
any information about an entity that is not encoded in the JSON payload when
creating an entity. That is, the inner class contains non-field information.

"""
from datetime import datetime
from fauxfactory import gen_alpha, gen_alphanumeric, gen_url
from nailgun import client, entity_fields
from nailgun.entity_mixins import (
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    _poll_task,
)
from robottelo.common.constants import (
    FAKE_1_YUM_REPO,
    OPERATING_SYSTEMS,
    VALID_GPG_KEY_FILE,
)
from robottelo.common.decorators import bz_bug_is_open, rm_bug_is_open
from robottelo.common.helpers import (
    escape_search,
    get_data_file,
    get_external_docker_url,
    get_internal_docker_url,
)
from time import sleep
import httplib
import random
# pylint:disable=too-few-public-methods
# pylint:disable=too-many-lines


# This has the same effect as passing `module='robottelo.entities'` to every
# single OneToOneField and OneToManyField.
entity_fields.ENTITIES_MODULE = 'robottelo.entities'


class APIResponseError(Exception):
    """Indicates an error if response returns unexpected result."""


class HostCreateMissingError(Exception):
    """Indicates that ``Host.create_missing`` was unable to execute."""


class ActivationKey(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Activtion Key entity."""
    organization = entity_fields.OneToOneField('Organization', required=True)
    name = entity_fields.StringField(required=True)
    description = entity_fields.StringField()
    environment = entity_fields.OneToOneField('Environment')
    content_view = entity_fields.OneToOneField('ContentView')
    unlimited_content_hosts = entity_fields.BooleanField()
    max_content_hosts = entity_fields.IntegerField()
    host_collection = entity_fields.OneToManyField('HostCollection')
    auto_attach = entity_fields.BooleanField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/activation_keys'
        server_modes = ('sat', 'sam')

    def read_raw(self):
        """Poll the server several times upon receiving a 404.

        Poll the server several times upon receiving a 404, just to be _really_
        sure that the requested activation key is non-existent. Do this because
        elasticsearch can be slow about indexing newly created activation keys,
        especially when the server is under load.

        """
        super_read_raw = super(ActivationKey, self).read_raw
        response = super_read_raw()
        if rm_bug_is_open(4638):
            for _ in range(5):
                if response.status_code == 404:
                    sleep(5)
                    response = super_read_raw()
        return response

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        releases
            /activation_keys/<id>/releases
        add_subscriptions
            /activation_keys/<id>/add_subscriptions
        remove_subscriptions
            /activation_keys/<id>/remove_subscriptions

        ``super`` is called otherwise.

        """
        if which in ('releases', 'add_subscriptions', 'remove_subscriptions'):
            return '{0}/{1}'.format(
                super(ActivationKey, self).path(which='self'),
                which
            )
        return super(ActivationKey, self).path(which)

    def add_subscriptions(self, params):
        """Helper for adding subscriptions to activation key.

        :param dict params: Parameters that are encoded to JSON and passed in
            with the request. See the API documentation page for a list of
            parameters and their descriptions.
        :returns: The server's response, with all JSON decoded.
        :rtype: dict
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        response = client.put(
            self.path('add_subscriptions'),
            params,
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()

class Architecture(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Architecture entity."""
    name = entity_fields.StringField(required=True)
    operatingsystem = entity_fields.OneToManyField('OperatingSystem', null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/architectures'
        server_modes = ('sat')

    # NOTE: See BZ 1151220
    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {u'architecture': super(Architecture, self).create_payload()}


class AuthSourceLDAP(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a AuthSourceLDAP entity."""
    account = entity_fields.StringField(null=True)
    attr_photo = entity_fields.StringField(null=True)
    base_dn = entity_fields.StringField(null=True)
    host = entity_fields.StringField(required=True, length=(1, 60))
    name = entity_fields.StringField(required=True, length=(1, 60))
    onthefly_register = entity_fields.BooleanField(null=True)
    port = entity_fields.IntegerField(null=True)  # default: 389
    tls = entity_fields.BooleanField(null=True)

    # required if onthefly_register is true
    account_password = entity_fields.StringField(null=True)
    attr_firstname = entity_fields.StringField(null=True)
    attr_lastname = entity_fields.StringField(null=True)
    attr_login = entity_fields.StringField(null=True)
    attr_mail = entity_fields.EmailField(null=True)

    def create_missing(self):
        """Possibly set several extra instance attributes.

        If ``onthefly_register`` is set and is true, set the following instance
        attributes:

        * account_password
        * account_firstname
        * account_lastname
        * attr_login
        * attr_mail

        """
        super(AuthSourceLDAP, self).create_missing()
        cls = type(self)
        if vars(self).get('onthefly_register', False) is True:
            self.account_password = cls.account_password.gen_value()
            self.attr_firstname = cls.attr_firstname.gen_value()
            self.attr_lastname = cls.attr_lastname.gen_value()
            self.attr_login = cls.attr_login.gen_value()
            self.attr_mail = cls.attr_mail.gen_value()

    def read(self, entity=None, attrs=None, ignore=('account_password',)):
        """Do not read the ``account_password`` attribute from the server."""
        return super(AuthSourceLDAP, self).read(entity, attrs, ignore)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/auth_source_ldaps'
        server_modes = ('sat')


class Bookmark(Entity):
    """A representation of a Bookmark entity."""
    name = entity_fields.StringField(required=True)
    controller = entity_fields.StringField(required=True)
    query = entity_fields.StringField(required=True)
    public = entity_fields.BooleanField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/bookmarks'
        server_modes = ('sat')


class CommonParameter(Entity):
    """A representation of a Common Parameter entity."""
    name = entity_fields.StringField(required=True)
    value = entity_fields.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/common_parameters'
        server_modes = ('sat')


class ComputeAttribute(Entity):
    """A representation of a Compute Attribute entity."""
    compute_profile = entity_fields.OneToOneField('ComputeProfile', required=True)
    compute_resource = entity_fields.OneToOneField('ComputeResource', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/compute_attributes'
        # Alternative paths:
        #
        # '/api/v2/compute_resources/:compute_resource_id/compute_profiles/'
        # ':compute_profile_id/compute_attributes',
        #
        # '/api/v2/compute_profiles/:compute_profile_id/compute_resources/'
        # ':compute_resource_id/compute_attributes',
        #
        # '/api/v2/compute_resources/:compute_resource_id/'
        # 'compute_attributes',
        #
        # '/api/v2/compute_profiles/:compute_profile_id/compute_attributes',
        server_modes = ('sat')


class ComputeProfile(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Compute Profile entity."""
    name = entity_fields.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/compute_profiles'
        server_modes = ('sat')


class ComputeResource(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Compute Resource entity."""
    description = entity_fields.StringField(null=True)
    location = entity_fields.OneToManyField('Location')
    name = entity_fields.StringField(
        required=True,
        str_type=('alphanumeric', 'cjk'),  # name cannot contain whitespace
    )
    organization = entity_fields.OneToManyField('Organization')
    password = entity_fields.StringField(null=True)
    provider = entity_fields.StringField(
        choices=(
            'Docker',
            'EC2',
            'GCE',
            'Libvirt',
            'Openstack',
            'Ovirt',
            'Rackspace',
            'Vmware',
        ),
        null=True,
        required=True,
    )
    region = entity_fields.StringField(null=True)
    server = entity_fields.StringField(null=True)
    set_console_password = entity_fields.BooleanField(null=True)
    tenant = entity_fields.StringField(null=True)
    url = entity_fields.URLField(required=True)
    user = entity_fields.StringField(null=True)
    uuid = entity_fields.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/compute_resources'
        server_modes = ('sat')

    def create_missing(self):
        """Customize the process of auto-generating instance attributes.

        Depending upon the value of ``self.provider``, various other fields are
        filled in with values too.

        """
        cls = type(self)
        provider = vars(self).get('provider')
        if provider is None:
            self.provider = provider = cls.provider.gen_value()

        # Deal with docker provider before calling super create_missing in
        # order to check if an URL is provided by the user and, if not,
        # generate an URL pointing to a docker server
        if provider.lower() == 'docker':
            if 'url' not in vars(self):
                self.url = random.choice((
                    get_internal_docker_url(), get_external_docker_url()))

        # Now is good to call super create_missing
        super(ComputeResource, self).create_missing()

        # Generate required fields according to the provider. First check if
        # the field is already set by the user, if not generate a random value
        if provider == 'EC2' or provider == 'Ovirt' or provider == 'Openstack':
            for field in ('password', 'user'):
                if field not in vars(self):
                    setattr(self, field, getattr(cls, field).gen_value())
        elif provider == 'GCE':
            # self.email = cls.email.gen_value()
            # self.key_path = cls.key_path.gen_value()
            # self.project = cls.project.gen_value()
            #
            # FIXME: These three pieces of data are required. However, the API
            # docs don't even mention their existence!
            #
            # 1. Figure out valid values for these three fields.
            # 2. Uncomment the above.
            # 3. File an issue on bugzilla asking for the docs to be expanded.
            pass
        elif provider == 'Rackspace':
            # FIXME: Foreman always returns this error:
            #
            #     undefined method `upcase' for nil:NilClass
            #
            # 1. File a bugzilla issue asking for a fix.
            # 2. Figure out what data is necessary and add it here.
            pass
        elif provider == 'Vmware':
            for field in ('password', 'user', 'uuid'):
                if field not in vars(self):
                    setattr(self, field, getattr(cls, field).gen_value())


class ConfigGroup(Entity):
    """A representation of a Config Group entity."""
    name = entity_fields.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/config_groups'
        server_modes = ('sat')


class ConfigTemplate(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Config Template entity."""
    audit_comment = entity_fields.StringField(null=True)
    locked = entity_fields.BooleanField(null=True)
    name = entity_fields.StringField(required=True)
    operatingsystem = entity_fields.OneToManyField('OperatingSystem', null=True)
    snippet = entity_fields.BooleanField(null=True, required=True)
    # "Array of template combinations (hostgroup_id, environment_id)"
    template_combinations = entity_fields.ListField(null=True)  # flake8:noqa pylint:disable=C0103
    template_kind = entity_fields.OneToOneField('TemplateKind', null=True)
    template = entity_fields.StringField(required=True)
    organization = entity_fields.OneToManyField('Organization', null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/config_templates'
        server_modes = ('sat')

    def create_missing(self):
        """Customize the process of auto-generating instance attributes.

        Populate ``template_kind`` if:

        * this template is not a snippet, and
        * the ``template_kind`` instance attribute is unset.

        """
        super(ConfigTemplate, self).create_missing()
        if (vars(self).get('snippet') is False and
                'template_kind' not in vars(self)):
            # A server is pre-populated with exactly eight template kinds. We
            # use one of those instead of creating a new one on the fly.
            self.template_kind = TemplateKind(
                self._server_config,
                id=random.randint(1, TemplateKind.Meta.NUM_CREATED_BY_DEFAULT)
            )

    # NOTE: See BZ 1151220
    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {
            u'config_template': super(ConfigTemplate, self).create_payload()
        }

    def read(self, entity=None, attrs=None, ignore=()):
        """Deal with unusually structured data returned by the server."""
        if attrs is None:
            attrs = self.read_json()
        template_kind_id = attrs.pop('template_kind_id')
        if template_kind_id  is None:
            attrs['template_kind'] = None
        else:
            attrs['template_kind'] = {'id': template_kind_id}
        return super(ConfigTemplate, self).read(entity, attrs, ignore)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        revision
            /config_templates/revision
        build_pxe_default
            /config_templates/build_pxe_default

        ``super`` is called otherwise.

        """
        if which in ('revision', 'build_pxe_default'):
            return '{0}/{1}'.format(
                super(ConfigTemplate, self).path(which='base'),
                which
            )
        return super(ConfigTemplate, self).path(which)


class AbstractDockerContainer(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a docker container.

    This class is abstract because all containers must come from somewhere, but
    this class does not have attributes for specifying that information.

    .. WARNING:: A docker compute resource must be specified when creating a
        docker container.

    """
    attach_stderr = entity_fields.BooleanField(null=True)
    attach_stdin = entity_fields.BooleanField(null=True)
    attach_stdout = entity_fields.BooleanField(null=True)
    command = entity_fields.StringField(required=True, str_type='latin1')
    compute_resource = entity_fields.OneToOneField('ComputeResource')
    cpu_set = entity_fields.StringField(null=True)
    cpu_shares = entity_fields.StringField(null=True)
    entrypoint = entity_fields.StringField(null=True)
    location = entity_fields.OneToManyField('Location', null=True)
    memory = entity_fields.StringField(null=True)
    # "alphanumeric" is a subset of the legal chars for "name": a-zA-Z0-9_.-
    name = entity_fields.StringField(required=True, str_type='alphanumeric')
    organization = entity_fields.OneToManyField('Organization', null=True)
    tty = entity_fields.BooleanField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'docker/api/v2/containers'
        server_modes = ('sat')

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        logs
            /containers/<id>/logs
        power
            /containers/<id>/power

        ``super`` is called otherwise.

        """
        if which in ('logs', 'power'):
            return '{0}/{1}'.format(
                super(AbstractDockerContainer, self).path(which='self'),
                which
            )
        return super(AbstractDockerContainer, self).path(which)

    # NOTE: See BZ 1151220
    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {
            u'container': super(AbstractDockerContainer, self).create_payload()
        }

    def read(self, entity=None, attrs=None, ignore=()):
        """Compensate for the unusual format of responses from the server.

        The server returns an ID and a list of IDs for the ``compute_resource``
        field. Compensate for this unusual design trait. Typically, the server
        returns a hash or a list of hashes for ``OneToOneField`` and
        ``OneToManyField`` fields.

        """
        if attrs is None:
            attrs = self.read_json()
        compute_resource_id = attrs.pop('compute_resource_id')
        if compute_resource_id is None:
            attrs['compute_resource'] = None
        else:
            attrs['compute_resource'] = {'id': compute_resource_id}
        return super(AbstractDockerContainer, self).read(entity, attrs, ignore)

    def power(self, power_action):
        """Run a power operation on a container.

        :param str power_action: One of 'start', 'stop' or 'status'.
        :returns: Information about the current state of the container.
        :rtype: dict

        """
        power_actions = ('start', 'stop', 'status')
        if power_action not in power_actions:
            raise ValueError('Received {0} but expected one of {1}'.format(
                power_action, power_actions
            ))
        response = client.put(
            self.path(which='power'),
            {u'power_action': power_action},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()

    def logs(self, stdout=None, stderr=None, tail=None):
        """Get logs from this container.

        :param bool stdout: ???
        :param bool stderr: ???
        :param int tail: How many lines should be tailed? Server does 100 by
            default.
        :returns:
        :rtype: dict

        """
        data = {}
        if stdout is not None:
            data['stdout'] = stdout
        if stderr is not None:
            data['stderr'] = stderr
        if tail is not None:
            data['tail'] = tail
        response = client.get(
            self.path(which='logs'),
            auth=self._server_config.auth,
            data=data,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()


class DockerHubContainer(AbstractDockerContainer):
    """A docker container that comes from Docker Hub."""
    repository_name = entity_fields.StringField(
        default='busybox',
        required=True,
    )
    tag = entity_fields.StringField(required=True, default='latest')


class ContentUpload(Entity):
    """A representation of a Content Upload entity."""
    repository = entity_fields.OneToOneField('Repository', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/repositories/:repository_id/'
                    'content_uploads')
        server_modes = ('sat')


class ContentViewVersion(Entity, EntityReadMixin):
    """A representation of a Content View Version non-entity."""

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/content_view_versions'
        server_modes = ('sat')

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        promote
            /content_view_versions/<id>/promote

        ``super`` is called otherwise.

        """
        if which == 'promote':
            return '{0}/promote'.format(
                super(ContentViewVersion, self).path(which='self')
            )
        return super(ContentViewVersion, self).path(which)

    def promote(self, environment_id, synchronous=True):
        """Helper for promoting an existing published content view.

        :param str environment_id: The environment Id to promote to.
        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :return: Return information about the completed foreman task if an HTTP
            202 response is received and ``synchronous`` is true. Return the
            JSON response otherwise.
        :rtype: dict

        """
        response = client.post(
            self.path('promote'),
            {u'environment_id': environment_id},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()

        # Poll a task if necessary, then return the JSON response.
        if synchronous is True and response.status_code == httplib.ACCEPTED:
            return ForemanTask(
                self._server_config,
                id=response.json()['id']
            ).poll()
        return response.json()


class ContentViewFilterRule(Entity):
    """A representation of a Content View Filter Rule entity."""
    content_view_filter = entity_fields.OneToOneField('ContentViewFilter', required=True)
    # package or package group: name
    name = entity_fields.StringField()
    # package: version
    version = entity_fields.StringField()
    # package: minimum version
    min_version = entity_fields.StringField()
    # package: maximum version
    max_version = entity_fields.StringField()
    # erratum: id
    errata = entity_fields.OneToOneField('Errata')
    # erratum: start date (YYYY-MM-DD)
    start_date = entity_fields.DateField()
    # erratum: end date (YYYY-MM-DD)
    end_date = entity_fields.DateField()
    # erratum: types (enhancement, bugfix, security)
    types = entity_fields.ListField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/content_view_filters/'
                    ':content_view_filter_id/rules')
        server_modes = ('sat')


class ContentViewFilter(Entity):
    """A representation of a Content View Filter entity."""
    content_view = entity_fields.OneToOneField('ContentView', required=True)
    name = entity_fields.StringField(required=True)
    # type of filter (e.g. rpm, package_group, erratum)
    filter_type = entity_fields.StringField(required=True)
    # Add all packages without Errata to the included/excluded list. (Package
    # Filter only)
    original_packages = entity_fields.BooleanField()
    # specifies if content should be included or excluded, default: false
    inclusion = entity_fields.BooleanField()
    repositories = entity_fields.OneToManyField('Repository')

    class Meta(object):
        """Non-field information about this entity."""
        api_names = {'filter_type': 'type'}
        api_path = 'katello/api/v2/content_view_filters'
        # Alternative path
        #
        # '/katello/api/v2/content_views/:content_view_id/filters',
        server_modes = ('sat')


class ContentViewPuppetModule(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Content View Puppet Module entity."""
    author = entity_fields.StringField()
    content_view = entity_fields.OneToOneField('ContentView', required=True)
    name = entity_fields.StringField()
    puppet_module = entity_fields.OneToOneField('PuppetModule')

    class Meta(object):
        """Non-field information about this entity."""
        server_modes = ('sat')

    def __init__(self, server_config=None, **kwargs):
        """Ensure ``content_view`` is passed in and set ``self.Meta.api_path``.

        :raises TypeError: If ``content_view`` is not passed in.

        """
        if 'content_view' not in kwargs:
            raise TypeError(
                'The "content_view" parameter must be provided.'
            )
        super(ContentViewPuppetModule, self).__init__(server_config, **kwargs)
        self.Meta.api_path = '{0}/content_view_puppet_modules'.format(
            self.content_view.path('self')  # pylint:disable=no-member
        )

    def read(self, entity=None, attrs=None, ignore=('content_view',)):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`OperatingSystemParameter` requires that an
        ``operatingsystem`` be provided, so this technique will not work. Do
        this instead::

            entity = type(self)(content_view=self.content_view.id)

        Also, deal with the weirdly named "uuid" parameter.

        """
        # `entity = self` also succeeds. However, the attributes of the object
        # passed in will be clobbered. Passing in a new object allows this one
        # to avoid changing state. The default implementation of `read` follows
        # the same principle.
        if entity is None:
            # pylint:disable=no-member
            entity = type(self)(content_view=self.content_view.id)
        if attrs is None:
            attrs = self.read_json()
        uuid = attrs.pop('uuid')
        if uuid is None:
            attrs['puppet_module'] = None
        else:
            attrs['puppet_module'] = {'id': uuid}
        return super(ContentViewPuppetModule, self).read(entity, attrs, ignore)

    def create_payload(self):
        """Rename the ``puppet_module_id`` field to ``uuid``."""
        payload = super(ContentViewPuppetModule, self).create_payload()
        payload['uuid'] = payload.pop('puppet_module_id')
        return payload

class ContentView(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Content View entity."""
    organization = entity_fields.OneToOneField('Organization', required=True)
    name = entity_fields.StringField(required=True)
    label = entity_fields.StringField()
    composite = entity_fields.BooleanField()
    description = entity_fields.StringField()
    repository = entity_fields.OneToManyField('Repository')
    # List of component content view version ids for composite views
    component = entity_fields.OneToManyField('ContentView')

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/content_views'
        # Alternative paths
        #
        # '/katello/api/v2/organizations/:organization_id/content_views',
        server_modes = ('sat')

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        content_view_puppet_modules
            /content_views/<id>/content_view_puppet_modules
        content_view_versions
            /content_views/<id>/content_view_versions
        publish
            /content_views/<id>/publish
        available_puppet_module_names
            /content_views/<id>/available_puppet_module_names

        ``super`` is called otherwise.

        """
        if which in (
                'available_puppet_module_names',
                'available_puppet_modules',
                'content_view_puppet_modules',
                'content_view_versions',
                'copy',
                'publish'):
            return '{0}/{1}'.format(
                super(ContentView, self).path(which='self'),
                which
            )
        return super(ContentView, self).path(which)

    def read(self, entity=None, attrs=None, ignore=()):
        """Compensate for the pluralization of the ``repository`` field."""
        if attrs is None:
            attrs = self.read_json()
        attrs['repositorys'] = attrs.pop('repositories')
        return super(ContentView, self).read(entity, attrs, ignore)

    def publish(self, synchronous=True):
        """Helper for publishing an existing content view.

        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :return: Return information about the completed foreman task if an HTTP
            202 response is received and ``synchronous`` is true. Return the
            JSON response otherwise.
        :rtype: dict

        """
        response = client.post(
            self.path('publish'),
            {u'id': self.id},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()

        # Poll a task if necessary, then return the JSON response.
        if synchronous is True and response.status_code == httplib.ACCEPTED:
            return ForemanTask(
                self._server_config,
                id=response.json()['id']
            ).poll()
        return response.json()

    def set_repository_ids(self, repo_ids):
        """Give this content view some repositories.

        :param repo_ids: A list of repository IDs.
        :rtype: dict
        :returns: The server's response, with all JSON decoded.

        """
        response = client.put(
            self.path(which='self'),
            {u'repository_ids': repo_ids},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()

    def available_puppet_modules(self):
        """Get puppet modules available to be added to the content view.

        :rtype: dict
        :returns: The server's response, with all JSON decoded.

        """
        response = client.get(
            self.path('available_puppet_modules'),
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()

    def add_puppet_module(self, author, name):
        """Add a puppet module to the content view.

        :param str author: The author of the puppet module.
        :param str name: The name of the puppet module.
        :rtype: dict
        :returns: The server's response, with all JSON decoded.

        """
        response = client.post(
            self.path('content_view_puppet_modules'),
            {u'author': author, u'name': name},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()

    def copy(self, name):
        """Clone provided content view.

        :param str name: The name for new cloned content view.
        :rtype: dict
        :returns: The server's response, with all JSON decoded.

        """
        response = client.post(
            self.path('copy'),
            {u'id': self.id, u'name': name},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()


class CustomInfo(Entity):
    """A representation of a Custom Info entity."""
    # name of the resource
    informable_type = entity_fields.StringField(required=True)
    # resource identifier
    # FIXME figure out related resource
    # informable = entity_fields.OneToOneField(required=True)
    keyname = entity_fields.StringField(required=True)
    value = entity_fields.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/custom_info/:informable_type/'
                    ':informable_id')
        server_modes = ('sat')


class Domain(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Domain entity."""
    domain_parameters_attributes = entity_fields.ListField(null=True)
    fullname = entity_fields.StringField(null=True)
    location = entity_fields.OneToManyField('Location', null=True)
    name = entity_fields.StringField(required=True)
    organization = entity_fields.OneToManyField('Organization', null=True)
    # DNS Proxy to use within this domain
    # FIXME figure out related resource
    # dns = entity_fields.OneToOneField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/domains'
        server_modes = ('sat')

    def create_missing(self):
        """Customize the process of auto-generating instance attributes.

        By default, entity_fields.:meth:`robottelo.URLField.gen_value` does not return
        especially unique values. This is problematic, as all domain names must
        be unique.

        """
        if 'name' not in vars(self):
            self.name = gen_alphanumeric().lower()
        super(Domain, self).create_missing()

    # NOTE: See BZ 1151220
    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {u'domain': super(Domain, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=()):
        """Deal with weirdly named data returned frmo the server.

        When creating a domain, the server accepts a list named
        ``domain_parameters_attributes``. When reading a domain, the server
        returns a list named ``parameters``. These appear to be the same data.
        Deal with this naming weirdness.

        """
        if attrs is None:
            attrs = self.read_json()
        attrs['domain_parameters_attributes'] = attrs.pop('parameters')
        return super(Domain, self).read(entity, attrs, ignore)


class Environment(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Environment entity."""
    name = entity_fields.StringField(
        required=True,
        str_type=('alpha', 'numeric', 'alphanumeric'),
    )

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/environments'
        server_modes = ('sat')


class Errata(Entity):
    """A representation of an Errata entity."""
    # You cannot create an errata. Instead, errata are a read-only entity.

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/errata'
        server_modes = ('sat')


class Filter(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Filter entity."""
    role = entity_fields.OneToOneField('Role', required=True)
    search = entity_fields.StringField(null=True)
    permission = entity_fields.OneToManyField('Permission', null=True)
    organization = entity_fields.OneToManyField('Organization', null=True)
    location = entity_fields.OneToManyField('Location', null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/filters'
        server_modes = ('sat')


class ForemanTask(Entity, EntityReadMixin):
    """A representation of a Foreman task."""

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'foreman_tasks/api/tasks'
        server_modes = ('sat')

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        bulk_search
            /foreman_tasks/api/tasks/bulk_search

        ``super(which='self')`` is called otherwise. There is no path available
        for fetching all tasks.

        """
        if which == 'bulk_search':
            return '{0}/bulk_search'.format(
                super(ForemanTask, self).path(which='base')
            )
        return super(ForemanTask, self).path(which='self')

    def poll(self, poll_rate=None, timeout=None):
        """Return the status of a task or timeout.

        There are several API calls that trigger asynchronous tasks, such as
        synchronizing a repository, or publishing or promoting a content view.
        It is possible to check on the status of a task if you know its UUID.
        This method polls a task once every ``poll_rate`` seconds and, upon
        task completion, returns information about that task.

        :param int poll_rate: Delay between the end of one task check-up and
            the start of the next check-up. Defaults to
            ``nailgun.entity_mixins.TASK_POLL_RATE``.
        :param int timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :returns: Information about the asynchronous task.
        :rtype: dict
        :raises: ``nailgun.entity_mixins.TaskTimedOutError`` if the task
            completes with any result other than "success".
        :raises: ``nailgun.entity_mixins.TaskFailedError`` if the task finishes
            with any result other than "success".
        :raises: ``requests.exceptions.HTTPError`` If the API returns a message
            with an HTTP 4XX or 5XX status code.

        """
        # pylint:disable=protected-access
        # See nailgun.entity_mixins._poll_task for an explanation of why a
        # private method is called.
        return _poll_task(self.id, self._server_config, poll_rate, timeout)


def _gpgkey_content():
    """Return default content for a GPG key.

    :returns: The contents of a GPG key.
    :rtype: str

    """
    with open(get_data_file(VALID_GPG_KEY_FILE)) as handle:
        return handle.read()


class GPGKey(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a GPG Key entity."""
    # public key block in DER encoding
    content = entity_fields.StringField(required=True, default=_gpgkey_content())
    name = entity_fields.StringField(required=True)
    organization = entity_fields.OneToOneField('Organization', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/gpg_keys'
        server_modes = ('sat')


class HostClasses(Entity):
    """A representation of a Host Class entity."""
    host = entity_fields.OneToOneField('Host', required=True)
    puppetclass = entity_fields.OneToOneField('PuppetClass', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/hosts/:host_id/puppetclass_ids'
        server_modes = ('sat')


class HostCollectionErrata(Entity):
    """A representation of a Host Collection Errata entity."""
    errata = entity_fields.OneToManyField('Errata', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/organizations/:organization_id/'
                    'host_collections/:host_collection_id/errata')
        server_modes = ('sat')


class HostCollectionPackage(Entity):
    """A representation of a Host Collection Package entity."""
    packages = entity_fields.ListField()
    groups = entity_fields.ListField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/organizations/:organization_id/'
                    'host_collections/:host_collection_id/packages')
        server_modes = ('sat')


class HostCollection(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Host Collection entity."""
    description = entity_fields.StringField()
    max_content_hosts = entity_fields.IntegerField()
    name = entity_fields.StringField(required=True)
    organization = entity_fields.OneToOneField('Organization', required=True)
    system = entity_fields.OneToManyField('System')
    unlimited_content_hosts = entity_fields.BooleanField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/host_collections'
        server_modes = ('sat', 'sam')

    def read(self, entity=None, attrs=None, ignore=()):
        """Compensate for the unusual format of responses from the server.

        The server returns an ID and a list of IDs for the ``organization`` and
        ``system`` fields, respectively. Compensate for this unusual design
        trait. Typically, the server returns a hash or a list of hashes for
        ``OneToOneField`` and ``OneToManyField`` fields.

        """
        if attrs is None:
            attrs = self.read_json()
        org_id = attrs.pop('organization_id')
        if org_id is None:
            attrs['organization'] = None
        else:
            attrs['organization'] = {'id': org_id}
        attrs['systems'] = [
            {'id': system_id} for system_id in attrs.pop('system_ids')
        ]
        return super(HostCollection, self).read(entity, attrs, ignore)

    def create_payload(self):
        """Rename ``system_ids`` to ``system_uuids``."""
        payload = super(HostCollection, self).create_payload()
        if 'system_ids' in payload:
            payload['system_uuids'] = payload.pop('system_ids')
        return payload

class HostGroupClasses(Entity):
    """A representation of a Host Group Classes entity."""
    hostgroup = entity_fields.OneToOneField('HostGroup', required=True)
    puppetclass = entity_fields.OneToOneField('PuppetClass', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/hostgroups/:hostgroup_id/puppetclass_ids'
        server_modes = ('sat')


class HostGroup(Entity, EntityCreateMixin):
    """A representation of a Host Group entity."""
    name = entity_fields.StringField(required=True)
    parent = entity_fields.OneToOneField('HostGroup', null=True)
    environment = entity_fields.OneToOneField('Environment', null=True)
    operatingsystem = entity_fields.OneToOneField('OperatingSystem', null=True)
    architecture = entity_fields.OneToOneField('Architecture', null=True)
    medium = entity_fields.OneToOneField('Media', null=True)
    ptable = entity_fields.OneToOneField('PartitionTable', null=True)
    # FIXME figure out related resource
    # puppet_ca_proxy = entity_fields.OneToOneField(null=True)
    subnet = entity_fields.OneToOneField('Subnet', null=True)
    domain = entity_fields.OneToOneField('Domain', null=True)
    realm = entity_fields.OneToOneField('Realm', null=True)
    # FIXME figure out related resource
    # puppet_proxy = entity_fields.OneToOneField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/hostgroups'
        server_modes = ('sat')


class Host(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Host entity."""
    architecture = entity_fields.OneToOneField('Architecture', null=True)
    build_ = entity_fields.BooleanField(null=True)
    capabilities = entity_fields.StringField(null=True)
    compute_profile = entity_fields.OneToOneField('ComputeProfile', null=True)
    compute_resource = entity_fields.OneToOneField('ComputeResource', null=True)
    domain = entity_fields.OneToOneField('Domain', null=True)
    enabled = entity_fields.BooleanField(null=True)
    environment = entity_fields.OneToOneField('Environment', null=True)
    hostgroup = entity_fields.OneToOneField('HostGroup', null=True)
    host_parameters_attributes = entity_fields.ListField(null=True)
    image = entity_fields.OneToOneField('Image', null=True)
    ip = entity_fields.StringField(null=True)  # pylint:disable=invalid-name
    location = entity_fields.OneToOneField('Location', required=True)
    mac = entity_fields.MACAddressField(null=True)
    managed = entity_fields.BooleanField(null=True)
    medium = entity_fields.OneToOneField('Media', null=True)
    model = entity_fields.OneToOneField('Model', null=True)
    name = entity_fields.StringField(required=True, str_type='alpha')
    operatingsystem = entity_fields.OneToOneField('OperatingSystem', null=True)
    organization = entity_fields.OneToOneField('Organization', required=True)
    owner = entity_fields.OneToOneField('User', null=True)
    owner_type = entity_fields.StringField(
        choices=('User', 'Usergroup'),
        null=True,
    )
    provision_method = entity_fields.StringField(null=True)
    ptable = entity_fields.OneToOneField('PartitionTable', null=True)
    puppet_classes = entity_fields.OneToManyField('PuppetClass', null=True)
    puppet_proxy = entity_fields.OneToOneField('SmartProxy', null=True)
    realm = entity_fields.OneToOneField('Realm', null=True)
    root_pass = entity_fields.StringField(length=(8, 30))
    sp_subnet = entity_fields.OneToOneField('Subnet', null=True)
    subnet = entity_fields.OneToOneField('Subnet', null=True)

    # FIXME figure out these related resources
    # progress_report = entity_fields.OneToOneField(null=True)
    # puppet_ca_proxy = entity_fields.OneToOneField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_names = {'build_': 'build'}
        api_path = 'api/v2/hosts'
        server_modes = ('sat')

    def create_missing(self):
        """Create a bogus managed host.

        The exact set of attributes that are required varies depending on
        whether the host is managed or inherits values from a host group and
        other factors. Unfortunately, the rules for determining which
        attributes should be filled in are mildly complex, and it is hard to
        know which scenario a user is aiming for.

        Populate the values necessary to create a bogus managed host. However,
        _only_ do so if no instance attributes are present. Raise an exception
        if any instance attributes are present. Assuming that this method
        executes in full, the resultant dependency graph will look, in part,
        like this::

                 .-> medium --------.
                 |-> architecture <-V--.
            host --> operating system -|
                 |-> partition table <-'
                 |-> domain
                 '-> environment

        :raises robottelo.entities.HostCreateMissingError: If any instance
            attributes are present.

        """
        if len(self.get_values()) != 0:
            raise HostCreateMissingError(
                'Found instance attributes: {0}'.format(self.get_values())
            )
        super(Host, self).create_missing()
        self.mac = self.mac.gen_value()
        self.root_pass = self.root_pass.gen_value()

        # Flesh out the dependency graph shown in the docstring.
        self.domain = Domain(
            self._server_config,
            id=Domain(self._server_config).create_json()['id']
        )
        self.environment = Environment(
            self._server_config,
            id=Environment(self._server_config).create_json()['id']
        )
        self.architecture = Architecture(
            self._server_config,
            id=Architecture(self._server_config).create_json()['id']
        )
        self.ptable = PartitionTable(
            self._server_config,
            id=PartitionTable(self._server_config).create_json()['id']
        )
        self.operatingsystem = OperatingSystem(
            self._server_config,
            id=OperatingSystem(
                self._server_config,
                architecture=[self.architecture],
                ptable=[self.ptable],
            ).create_json()['id']
        )
        self.medium = Media(
            self._server_config,
            id=Media(
                self._server_config,
                operatingsystem=[self.operatingsystem]
            ).create_json()['id']
        )

    # NOTE: See BZ 1151220
    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {u'host': super(Host, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=('root_pass',)):
        """Deal with oddly named and structured data returned by the server."""
        if attrs is None:
            attrs = self.read_json()

        # POST accepts `host_parameters_attributes`, GET returns `parameters`
        attrs['host_parameters_attributes'] = attrs.pop('parameters')
        # The server returns a list of IDs for all OneToOneFields except
        # `puppet_classes`.
        attrs['puppet_classess'] = attrs.pop('puppetclasses')
        for field_name, field in self.get_fields().items():
            if field_name == 'puppet_classes':
                continue
            if isinstance(field, entity_fields.OneToOneField):
                field_id = attrs.pop(field_name + '_id')
                if field_id  is None:
                    attrs[field_name] = None
                else:
                    attrs[field_name] = {'id': field_id}

        return super(Host, self).read(entity, attrs, ignore)


class Image(Entity):
    """A representation of a Image entity."""
    compute_resource = entity_fields.OneToOneField('ComputeResource', required=True)
    name = entity_fields.StringField(required=True)
    username = entity_fields.StringField(required=True)
    uuid = entity_fields.StringField(required=True)
    architecture = entity_fields.OneToOneField('Architecture', required=True)
    operatingsystem = entity_fields.OneToOneField('OperatingSystem', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/compute_resources/:compute_resource_id/images'
        server_modes = ('sat')


class Interface(Entity):
    """A representation of a Interface entity."""
    host = entity_fields.OneToOneField('Host', required=True)
    mac = entity_fields.MACAddressField(required=True)
    ip = entity_fields.IPAddressField(required=True)  # pylint:disable=C0103
    # Interface type, i.e: Nic::BMC
    interface_type = entity_fields.StringField(required=True)
    name = entity_fields.StringField(required=True)
    subnet = entity_fields.OneToOneField('Subnet', null=True)
    domain = entity_fields.OneToOneField('Domain', null=True)
    username = entity_fields.StringField(null=True)
    password = entity_fields.StringField(null=True)
    # Interface provider, i.e: IPMI
    provider = entity_fields.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_names = {'interface_type': 'type'}
        api_path = 'api/v2/hosts/:host_id/interfaces'
        server_modes = ('sat')


class LifecycleEnvironment(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Lifecycle Environment entity."""
    description = entity_fields.StringField()
    name = entity_fields.StringField(required=True)
    organization = entity_fields.OneToOneField('Organization', required=True)
    prior = entity_fields.OneToOneField('LifecycleEnvironment')
    # NOTE: The "prior" field is unusual. See the `create_missing` docstring.

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/environments'
        server_modes = ('sat')

    def create_payload(self):
        """Rename the payload key "prior_id" to "prior".

        A ``LifecycleEnvironment`` can be associated to another instance of a
        ``LifecycleEnvironment``. Unusually, this relationship is represented
        via the ``prior`` field, not ``prior_id``.

        """
        data = super(LifecycleEnvironment, self).create_payload()
        data['prior'] = data.pop('prior_id')
        return data

    def create_missing(self):
        """Automatically populate additional instance attributes.

        When a new lifecycle environment is created, it must either:

        * Reference a parent lifecycle environment in the tree of lifecycle
          environments via the ``prior`` field, or
        * have a name of "Library".

        Within a given organization, there can only be a single lifecycle
        environment with a name of 'Library'. This lifecycle environment is at
        the root of a tree of lifecycle environments, so its ``prior`` field is
        blank.

        This method finds the 'Library' lifecycle environment within the
        current organization and points to it via the ``prior`` field. This is
        not done if the current lifecycle environment has a name of 'Library'.

        """
        # Create self.name and self.organization if missing.
        super(LifecycleEnvironment, self).create_missing()
        if self.name != 'Library' and 'prior' not in vars(self):
            response = client.get(
                self.path('base'),
                auth=self._server_config.auth,
                data={
                    u'name': u'Library',
                    # pylint:disable=no-member
                    u'organization_id': self.organization.id,
                },
                verify=self._server_config.verify,
            )
            response.raise_for_status()
            results = response.json()['results']
            if len(results) != 1:
                raise APIResponseError(
                    'Could not find the "Library" lifecycle environment for '
                    'organization {0}. Search results: {1}'
                    .format(self.organization, results)
                )
            self.prior = LifecycleEnvironment(
                self._server_config,
                id=results[0]['id'],
            )


class Location(Entity, EntityCreateMixin):
    """A representation of a Location entity."""
    name = entity_fields.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/locations'
        server_modes = ('sat')


class Media(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Media entity."""
    media_path = entity_fields.URLField(required=True)
    name = entity_fields.StringField(required=True)
    operatingsystem = entity_fields.OneToManyField('OperatingSystem', null=True)
    organization = entity_fields.OneToManyField('Organization', null=True)
    os_family = entity_fields.StringField(choices=(
        'AIX', 'Archlinux', 'Debian', 'Freebsd', 'Gentoo', 'Junos', 'Redhat',
        'Solaris', 'Suse', 'Windows',
    ), null=True)

    def create_missing(self):
        """Give the 'media_path' instance attribute a value if it is unset.

        By default, entity_fields.:meth:`robottelo.URLField.gen_value` does not return
        especially unique values. This is problematic, as all media must have a
        unique path.

        """
        if 'media_path' not in vars(self):
            self.media_path = gen_url(subdomain=gen_alpha())
        return super(Media, self).create_missing()

    # NOTE: See BZ 1151220
    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {u'medium': super(Media, self).create_payload()}

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/media'
        api_names = {'media_path': 'path'}
        server_modes = ('sat')


class Model(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Model entity."""
    name = entity_fields.StringField(required=True)
    info = entity_fields.StringField(null=True)
    vendor_class = entity_fields.StringField(null=True)
    hardware_model = entity_fields.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/models'
        server_modes = ('sat')


class OperatingSystem(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Operating System entity.

    ``major`` is listed as a string field in the API docs, but only numeric
    values are accepted, and they may be no longer than 5 digits long. Also see
    bugzilla bug #1122261.

    The following fields are valid despite not being listed in the API docs:

    * architecture
    * medium
    * ptable

    """
    architecture = entity_fields.OneToManyField('Architecture')
    description = entity_fields.StringField(null=True)
    family = entity_fields.StringField(null=True, choices=OPERATING_SYSTEMS)
    major = entity_fields.StringField(required=True, str_type='numeric', length=(1, 5))
    media = entity_fields.OneToManyField('Media')
    minor = entity_fields.StringField(null=True, str_type='numeric', length=(1, 16))
    name = entity_fields.StringField(required=True)
    ptable = entity_fields.OneToManyField('PartitionTable')
    release_name = entity_fields.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/operatingsystems'
        server_modes = ('sat')

    # NOTE: See BZ 1151220
    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {
            u'operatingsystem': super(OperatingSystem, self).create_payload()
        }

    def read(self, entity=None, attrs=None, ignore=()):
        """Compensate for the pluralization of the ``media`` field."""
        if attrs is None:
            attrs = self.read_json()
        attrs['medias'] = attrs.pop('media')
        return super(OperatingSystem, self).read(entity, attrs, ignore)


class OperatingSystemParameter(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a parameter for an operating system."""
    name = entity_fields.StringField(required=True)
    operatingsystem = entity_fields.OneToOneField(
        'OperatingSystem',
        required=True,
    )
    value = entity_fields.StringField(required=True)

    def __init__(self, server_config=None, **kwargs):
        """Ensure ``operatingsystem`` is passed in and set
        ``self.Meta.api_path``.

        :raises TypeError: If ``content_view`` is not passed in.

        """
        if 'operatingsystem' not in kwargs:
            raise TypeError(
                'The "operatingsystem" parameter must be provided.'
            )
        super(OperatingSystemParameter, self).__init__(server_config, **kwargs)
        self.Meta.api_path = '{0}/parameters'.format(
            self.operatingsystem.path('self')  # pylint:disable=no-member
        )

    def read(self, entity=None, attrs=None, ignore=('operatingsystem',)):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`OperatingSystemParameter` requires that an
        ``operatingsystem`` be provided, so this technique will not work. Do
        this instead::

            entity = type(self)(operatingsystem=self.operatingsystem.id)

        """
        # `entity = self` also succeeds. However, the attributes of the object
        # passed in will be clobbered. Passing in a new object allows this one
        # to avoid changing state. The default implementation of
        # `read` follows the same principle.
        if entity is None:
            # pylint:disable=no-member
            entity = type(self)(operatingsystem=self.operatingsystem.id)
        return super(OperatingSystemParameter, self).read(entity, attrs, ignore)


class OrganizationDefaultInfo(Entity):
    """A representation of a Organization Default Info entity."""
    # name of the resource
    informable_type = entity_fields.StringField(required=True)
    # resource identifier
    # FIXME figure out related resource
    # informable = entity_fields.OneToOneField(required=True)
    keyname = entity_fields.StringField(required=True)
    name = entity_fields.StringField(required=True)
    info = entity_fields.StringField()
    vendor_class = entity_fields.StringField()
    hardware_model = entity_fields.StringField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/organizations/:organization_id/'
                    'default_info/:informable_type')
        server_modes = ('sat', 'sam')


class Organization(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of an Organization entity."""
    description = entity_fields.StringField()
    label = entity_fields.StringField(str_type='alpha')
    name = entity_fields.StringField(required=True)
    title = entity_fields.StringField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/organizations'
        server_modes = ('sat', 'sam')

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        subscriptions/upload
            /organizations/<id>/subscriptions/upload
        subscriptions/delete_manifest
            /organizations/<id>/subscriptions/delete_manifest
        subscriptions/refresh_manifest
            /organizations/<id>/subscriptions/refresh_manifest
        sync_plans
            /organizations/<id>/sync_plans
        products
            /organizations/<id>/products
        subscriptions
            /organizations/<id>/subscriptions

        Otherwise, call ``super``.

        """
        if which in (
                'products',
                'subscriptions/delete_manifest',
                'subscriptions/refresh_manifest',
                'subscriptions/upload',
                'sync_plans',
                'subscriptions',
        ):
            return '{0}/{1}'.format(
                super(Organization, self).path(which='self'),
                which
            )
        return super(Organization, self).path(which)

    def subscriptions(self):
        """List the organization's subscriptions.

        :returns: A list of available subscriptions.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.

        """
        response = client.get(
            self.path('subscriptions'),
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()['results']

    def upload_manifest(self, path, repository_url=None,
                        synchronous=True):
        """Helper method that uploads a subscription manifest file

        :param str path: Local path of the manifest file
        :param str repository_url: Optional repository URL
        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.
        :raises: ``nailgun.entity_mixins.TaskTimedOutError`` if an HTTP 202
            response is received, ``synchronous is True`` and the task
            completes with any result other than "success".
        :rtype: dict

        """
        data = None
        if repository_url is not None:
            data = {u'repository_url': repository_url}
        with open(path, 'rb') as manifest:
            response = client.post(
                self.path('subscriptions/upload'),
                data,
                auth=self._server_config.auth,
                files={'content': manifest},
                verify=self._server_config.verify,
            )
        response.raise_for_status()
        # Poll a task if necessary, then return the JSON response.
        if synchronous is True and response.status_code == httplib.ACCEPTED:
            return ForemanTask(
                self._server_config,
                id=response.json()['id']
            ).poll()
        return response.json()

    def delete_manifest(self, synchronous=True):
        """Helper method that deletes an organization's manifest

        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.
        :raises: ``nailgun.entity_mixins.TaskTimedOutError`` if an HTTP 202
            response is received, ``synchronous is True`` and the task
            completes with any result other than "success".
        :rtype: dict

        """
        response = client.post(
            self.path('subscriptions/delete_manifest'),
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        # Poll a task if necessary, then return the JSON response.
        if synchronous is True and response.status_code == httplib.ACCEPTED:
            return ForemanTask(
                self._server_config,
                id=response.json()['id']
            ).poll()
        return response.json()

    def refresh_manifest(self, synchronous=True):
        """Helper method that refreshes an organization's manifest

        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.
        :raises: ``nailgun.entity_mixins.TaskTimedOutError`` if an HTTP 202
            response is received, ``synchronous is True`` and the task
            completes with any result other than "success".
        :rtype: dict

        """
        response = client.put(
            self.path('subscriptions/refresh_manifest'),
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        # Poll a task if necessary, then return the JSON response.
        if synchronous is True and response.status_code == httplib.ACCEPTED:
            return ForemanTask(
                self._server_config,
                id=response.json()['id'],
            ).poll()
        return response.json()

    def sync_plan(self, name, interval):
        """Helper for creating a sync_plan.

        :returns: The server's response, with all JSON decoded.
        :rtype: dict
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        sync_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        response = client.post(
            self.path('sync_plans'),
            {u'interval': interval, u'name': name, u'sync_date': sync_date},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()

    def list_rhproducts(self, per_page=None):
        """Lists all the RedHat Products after the importing of a manifest.

        :param int per_page: The no.of results to be shown per page.

        """
        response = client.get(
            self.path('products'),
            auth=self._server_config.auth,
            data={u'per_page': per_page},
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()['results']


class OSDefaultTemplate(Entity):
    """A representation of a OS Default Template entity."""
    operatingsystem = entity_fields.OneToOneField('OperatingSystem')
    template_kind = entity_fields.OneToOneField('TemplateKind', null=True)
    config_template = entity_fields.OneToOneField('ConfigTemplate', null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('api/v2/operatingsystems/:operatingsystem_id/'
                    'os_default_templates')
        server_modes = ('sat')


class OverrideValue(Entity):
    """A representation of a Override Value entity."""
    smart_variable = entity_fields.OneToOneField('SmartVariable')
    match = entity_fields.StringField(null=True)
    value = entity_fields.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        # FIXME: This is tricky. Overriding path() may be a solution.
        api_path = (
            # Create an override value for a specific smart_variable
            '/api/v2/smart_variables/:smart_variable_id/override_values',
            # Create an override value for a specific smart class parameter
            '/api/v2/smart_class_parameters/:smart_class_parameter_id/'
            'override_values',
        )
        server_modes = ('sat')


class Permission(Entity, EntityReadMixin):
    """A representation of a Permission entity."""
    name = entity_fields.StringField(required=True)
    resource_type = entity_fields.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/permissions'
        server_modes = ('sat', 'sam')

    def search(self, per_page=10000):
        """Searches for permissions using the values for instance name and
        resource_type

        Example usage::

            >>> entities.Permission(resource_type='Domain').search()
            [
                {u'name': u'view_domains', u'resource_type': u'Domain', u'id': 39},
                {u'name': u'create_domains', u'resource_type': u'Domain', u'id': 40},
                {u'name': u'edit_domains', u'resource_type': u'Domain', u'id': 41},
                {u'name': u'destroy_domains', u'resource_type': u'Domain', u'id': 42}
            ]
            >>> entities.Permission(name='view_domains').search()
            [{u'name': u'view_domains', u'resource_type': u'Domain', u'id': 39}]

        If both ``name`` and ``resource_type`` are provided, ``name`` is
        ignored.

        :param int per_page: number of results per page to return
        :returns: A list of matching permissions.

        """
        search_terms = {u'per_page': per_page}
        if 'name' in vars(self):
            search_terms[u'name'] = self.name
        if 'resource_type' in vars(self):
            search_terms[u'resource_type'] = self.resource_type

        response = client.get(
            self.path('base'),
            auth=self._server_config.auth,
            data=search_terms,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()['results']


class Ping(Entity):
    """A representation of a Ping entity."""

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/ping'
        server_modes = ('sat', 'sam')


class Product(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Product entity."""
    description = entity_fields.StringField()
    gpg_key = entity_fields.OneToOneField('GPGKey')
    label = entity_fields.StringField()
    name = entity_fields.StringField(required=True)
    organization = entity_fields.OneToOneField('Organization', required=True)
    sync_plan = entity_fields.OneToOneField('SyncPlan', null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/products'
        server_modes = ('sat', 'sam')

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        repository_sets
            /products/<product_id>/repository_sets
        repository_sets/<id>/enable
            /products/<product_id>/repository_sets/<id>/enable
        repository_sets/<id>/disable
            /products/<product_id>/repository_sets/<id>/disable

        ``super`` is called otherwise.

        """
        if which is not None and which.startswith("repository_sets"):
            return '{0}/{1}'.format(
                super(Product, self).path(which='self'),
                which,
            )
        return super(Product, self).path(which)

    def read(self, entity=None, attrs=None, ignore=()):
        """Compensate for the weird structure of returned data."""
        if attrs is None:
            attrs = self.read_json()

        # The `organization` hash does not include an ID.
        org_label = attrs.pop('organization')['label']
        response = client.get(
            Organization(self._server_config).path(),
            auth=self._server_config.auth,
            data={'search': 'label={0}'.format(org_label)},
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        results = response.json()['results']
        if len(results) != 1:
            raise APIResponseError(
                'Could not find exactly one organization with label "{0}". '
                'Actual search results: {1}'.format(org_label, results)
            )
        attrs['organization'] = {'id': response.json()['results'][0]['id']}

        # No `gpg_key` hash is returned.
        gpg_key_id = attrs.pop('gpg_key_id')
        if gpg_key_id  is None:
            attrs['gpg_key'] = None
        else:
            attrs['gpg_key'] = {'id': gpg_key_id}

        return super(Product, self).read(entity, attrs, ignore)

    def list_repositorysets(self, per_page=None):
        """Lists all the RepositorySets in a Product.

        :param int per_page: The no.of results to be shown per page.

        """
        response = client.get(
            self.path('repository_sets'),
            auth=self._server_config.auth,
            data={u'per_page': per_page},
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        return response.json()['results']

    def fetch_rhproduct_id(self, name, org_id):
        """Fetches the RedHat Product Id for a given Product name.

        To be used for the Products created when manifest is imported.
        RedHat Product Id could vary depending upon other custom products.
        So, we use the product name to fetch the RedHat Product Id.

        :param str org_id: The Organization Id.
        :param str name: The RedHat product's name who's ID is to be fetched.
        :returns: The RedHat Product Id is returned.

        """
        response = client.get(
            self.path(which='base'),
            auth=self._server_config.auth,
            data={
                u'organization_id': org_id,
                u'search': 'name={}'.format(escape_search(name)),
            },
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        results = response.json()['results']
        if len(results) != 1:
            raise APIResponseError(
                "The length of the results is:", len(results))
        return results[0]['id']

    def fetch_reposet_id(self, name):
        """Fetches the RepositorySet Id for a given name.

        RedHat Products do not directly contain Repositories.
        Product first contains many RepositorySets and each
        RepositorySet contains many Repositories.
        RepositorySet Id could vary. So, we use the reposet name
        to fetch the RepositorySet Id.

        :param str name: The RepositorySet's name.
        :returns: The RepositorySet's Id is returned.

        """
        response = client.get(
            self.path('repository_sets'),
            auth=self._server_config.auth,
            data={u'name': name},
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        results = response.json()['results']
        if len(results) != 1:
            raise APIResponseError(
                "The length of the results is:", len(results))
        return results[0]['id']

    def enable_rhrepo(self, base_arch,
                      release_ver, reposet_id, synchronous=True):
        """Enables the RedHat Repository

        RedHat Repos needs to be enabled first, so that we can sync it.

        :param str reposet_id: The RepositorySet Id.
        :param str base_arch: The architecture type of the repo to enable.
        :param str release_ver: The release version type of the repo to enable.
        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.
        :rtype: dict

        """
        response = client.put(
            self.path('repository_sets/{0}/enable'.format(reposet_id)),
            {u'basearch': base_arch, u'releasever': release_ver},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        # Poll a task if necessary, then return the JSON response.
        if synchronous is True and response.status_code == httplib.ACCEPTED:
            return ForemanTask(
                self._server_config,
                id=response.json()['id'],
            ).poll()
        return response.json()

    def disable_rhrepo(self, base_arch,
                       release_ver, reposet_id, synchronous=True):
        """Disables the RedHat Repository

        :param str reposet_id: The RepositorySet Id.
        :param str base_arch: The architecture type of the repo to disable.
        :param str release_ver: The release version type of the repo to
            disable.
        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.
        :rtype: dict

        """
        response = client.put(
            self.path('repository_sets/{0}/disable'.format(reposet_id)),
            {u'basearch': base_arch, u'releasever': release_ver},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        # Poll a task if necessary, then return the JSON response.
        if synchronous is True and response.status_code == httplib.ACCEPTED:
            return ForemanTask(
                self._server_config,
                id=response.json()['id'],
            ).poll()
        return response.json()


class PartitionTable(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Partition Table entity."""
    name = entity_fields.StringField(required=True)
    layout = entity_fields.StringField(required=True)
    os_family = entity_fields.StringField(null=True, choices=OPERATING_SYSTEMS)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/ptables'
        server_modes = ('sat')


class PuppetClass(Entity):
    """A representation of a Puppet Class entity."""
    name = entity_fields.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/puppetclasses'
        server_modes = ('sat')


class PuppetModule(Entity, EntityReadMixin):
    """A representation of a Puppet Module entity."""
    author = entity_fields.StringField()
    checksums = entity_fields.ListField()
    dependencies = entity_fields.ListField()
    description = entity_fields.StringField()
    license = entity_fields.StringField()
    name = entity_fields.StringField()
    project_page = entity_fields.URLField()
    # repoids = entity_fields.???
    repository = entity_fields.OneToManyField('Repository')
    source = entity_fields.URLField()
    summary = entity_fields.StringField()
    # tag_list = entity_fields.???
    version = entity_fields.StringField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/puppet_modules'

    def read(self, entity=None, attrs=None, ignore=()):
        """Compensate for the pluralization of the ``repository`` field."""
        if attrs is None:
            attrs = self.read_json()
        attrs['repositorys'] = attrs.pop('repositories')
        return super(PuppetModule, self).read(entity, attrs, ignore)


class Realm(Entity):
    """A representation of a Realm entity."""
    # The realm name, e.g. EXAMPLE.COM
    name = entity_fields.StringField(required=True)
    # Proxy to use for this realm
    # FIXME figure out related resource
    # realm_proxy = entity_fields.OneToOneField(null=True)
    # Realm type, e.g. Red Hat Identity Management or Active Directory
    realm_type = entity_fields.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/realms'
        server_modes = ('sat')


class Report(Entity):
    """A representation of a Report entity."""
    # Hostname or certname
    host = entity_fields.StringField(required=True)
    # UTC time of report
    reported_at = entity_fields.DateTimeField(required=True)
    # Optional array of log hashes
    logs = entity_fields.ListField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/reports'
        server_modes = ('sat')


class Repository(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Repository entity."""
    checksum_type = entity_fields.StringField(choices=('sha1', 'sha256'))
    content_type = entity_fields.StringField(
        choices=('puppet', 'yum', 'file', 'docker'),
        default='yum',
        required=True,
    )
    # Just setting `str_type='alpha'` will fail with this error:
    # {"docker_upstream_name":["must be a valid docker name"]}}
    docker_upstream_name = entity_fields.StringField(default='busybox')
    gpg_key = entity_fields.OneToOneField('GPGKey')
    label = entity_fields.StringField()
    name = entity_fields.StringField(required=True)
    product = entity_fields.OneToOneField('Product', required=True)
    unprotected = entity_fields.BooleanField()
    url = entity_fields.URLField(required=True, default=FAKE_1_YUM_REPO)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        sync
            /repositories/<id>/sync
        upload_content
            /repositories/<id>/upload_content

        ``super`` is called otherwise.

        """
        if which in ('sync', 'upload_content'):
            return '{0}/{1}'.format(
                super(Repository, self).path(which='self'),
                which
            )
        return super(Repository, self).path(which)

    def create_missing(self):
        """Conditionally mark ``docker_upstream_name`` as required.

        Mark ``docker_upstream_name`` as required if ``content_type`` is
        "docker".

        """
        if self.content_type == 'docker':
            type(self).docker_upstream_name.required = True
        super(Repository, self).create_missing()

    def sync(self, synchronous=True):
        """Helper for syncing an existing repository.

        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.
        :rtype: dict

        """
        response = client.post(
            self.path('sync'),
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        # Poll a task if necessary, then return the JSON response.
        if synchronous is True and response.status_code == httplib.ACCEPTED:
            return ForemanTask(
                self._server_config,
                id=response.json()['id'],
            ).poll()
        return response.json()

    def fetch_repoid(self, org_id, name):
        """Fetch the repository Id.

        This is required for RedHat Repositories, as products, reposets
        and repositories get automatically populated upon the manifest import.

        :param str org_id: The org Id for which repository listing is required.
        :param str name: The repository name who's Id has to be searched.
        :return: Returns the repository Id.
        :rtype: str
        :raises: ``APIResponseError`` If the API does not return any results.

        """
        for _ in range(5 if bz_bug_is_open(1176708) else 1):
            response = client.get(
                self.path(which=None),
                auth=self._server_config.auth,
                data={u'organization_id': org_id, u'name': name},
                verify=self._server_config.verify,
            )
            response.raise_for_status()
            results = response.json()['results']
            if len(results) == 0 and bz_bug_is_open(1176708):
                sleep(5)
            else:
                break
        if len(results) != 1:
            raise APIResponseError(
                'Found {0} repositories named {1} in organization {2}: {3} '
                .format(len(results), name, org_id, results)
            )
        return results[0]['id']

    def upload_content(self, handle):
        """Upload a file to the current repository.

        :param handle: A file object, such as the one returned by
            ``open('path', 'rb')``.
        :returns: The JSON-decoded response.
        :rtype: dict
        :raises robottelo.entities.APIResponseError: If the response has a
            status other than "success".

        """
        response = client.post(
            self.path('upload_content'),
            auth=self._server_config.auth,
            files={'content': handle},
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        response_json = response.json()
        if response_json['status'] != 'success':
            raise APIResponseError(
                'Received error when uploading file {0} to repository {1}: {2}'
                .format(handle, self.id, response_json)
            )
        return response_json

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/repositories'
        server_modes = ('sat')


class RoleLDAPGroups(Entity):
    """A representation of a Role LDAP Groups entity."""
    name = entity_fields.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/roles/:role_id/ldap_groups'
        server_modes = ('sat', 'sam')


class Role(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Role entity."""
    name = entity_fields.StringField(
        required=True,
        str_type='alphanumeric',
        length=(2, 30),  # min length is 2 and max length is arbitrary
    )

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/roles'
        server_modes = ('sat', 'sam')


class SmartProxy(Entity):
    """A representation of a Smart Proxy entity."""
    name = entity_fields.StringField(required=True)
    url = entity_fields.URLField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/smart_proxies'
        server_modes = ('sat')


class SmartVariable(Entity):
    """A representation of a Smart Variable entity."""
    variable = entity_fields.StringField(required=True)
    puppetclass = entity_fields.OneToOneField('PuppetClass', null=True)
    default_value = entity_fields.StringField(null=True)
    override_value_order = entity_fields.StringField(null=True)
    description = entity_fields.StringField(null=True)
    validator_type = entity_fields.StringField(null=True)
    validator_rule = entity_fields.StringField(null=True)
    variable_type = entity_fields.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/smart_variables'
        server_modes = ('sat')


class Status(Entity):
    """A representation of a Status entity."""

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/status'
        server_modes = ('sat')


class Subnet(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Subnet entity."""
    dns_primary = entity_fields.IPAddressField(null=True)
    dns_secondary = entity_fields.IPAddressField(null=True)
    domain = entity_fields.OneToManyField('Domain', null=True)
    from_ = entity_fields.IPAddressField(null=True)
    gateway = entity_fields.StringField(null=True)
    mask = entity_fields.NetmaskField(required=True)
    name = entity_fields.StringField(required=True)
    network = entity_fields.IPAddressField(required=True)
    to = entity_fields.IPAddressField(null=True)  # pylint:disable=invalid-name
    vlanid = entity_fields.StringField(null=True)

    # FIXME: Figure out what these IDs correspond to.
    # dhcp = entity_fields.OneToOneField(null=True)
    # dns = entity_fields.OneToOneField(null=True)
    # tftp = entity_fields.OneToOneField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/subnets'
        api_names = {'from_': 'from'}
        server_modes = ('sat')


class Subscription(Entity):
    """A representation of a Subscription entity."""
    # Subscription Pool uuid
    pool_uuid = entity_fields.StringField()
    # UUID of the system
    system = entity_fields.OneToOneField('System')
    activation_key = entity_fields.OneToOneField('ActivationKey')
    # Quantity of this subscriptions to add
    quantity = entity_fields.IntegerField()
    subscriptions = entity_fields.OneToManyField('Subscription')

    class Meta(object):
        """Non-field information about this entity."""
        api_names = {'pool_uuid': 'id'}
        api_path = 'katello/api/v2/subscriptions/:id'
        # Alternative paths.
        #
        # '/katello/api/v2/systems/:system_id/subscriptions',
        # '/katello/api/v2/activation_keys/:activation_key_id/subscriptions',
        server_modes = ('sat', 'sam')


class SyncPlan(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Sync Plan entity."""
    description = entity_fields.StringField()
    enabled = entity_fields.BooleanField(required=True)
    interval = entity_fields.StringField(
        choices=('hourly', 'daily', 'weekly'),
        required=True,
    )
    name = entity_fields.StringField(required=True)
    organization = entity_fields.OneToOneField('Organization', required=True)
    sync_date = entity_fields.DateTimeField(required=True)

    def __init__(self, server_config=None, **kwargs):
        """Ensure ``organization`` has been passed in and set
        ``self.Meta.api_path``.

        """
        if 'organization' not in kwargs:
            raise TypeError('The "organization" parameter must be provided.')
        super(SyncPlan, self).__init__(server_config, **kwargs)
        self.Meta.api_path = '{0}/sync_plans'.format(
            self.organization.path()  # pylint:disable=no-member
        )

    def read(self, entity=None, attrs=None, ignore=('organization',)):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`SyncPlan` requires that an ``organization`` be
        provided, so this technique will not work. Do this instead::

            entity = type(self)(organization=self.organization.id)

        """
        # `entity = self` also succeeds. However, the attributes of the object
        # passed in will be clobbered. Passing in a new object allows this one
        # to avoid changing state. The default implementation of
        # `read` follows the same principle.
        if entity is None:
            # pylint:disable=no-member
            entity = type(self)(organization=self.organization.id)
        return super(SyncPlan, self).read(entity, attrs, ignore)

    def create_payload(self):
        """Convert ``sync_date`` to a string before sending it to the server."""
        data = super(SyncPlan, self).create_payload()
        data['sync_date'] = data['sync_date'].strftime('%Y-%m-%d %H:%M:%S')
        return data

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        add_products
            /katello/api/v2/organizations/:organization_id/sync_plans/:sync_plan_id/add_products
        remove_products
            /katello/api/v2/organizations/:organization_id/sync_plans/:sync_plan_id/remove_products

        """
        if which in ('add_products', 'remove_products'):
            return '{0}/{1}'.format(
                super(SyncPlan, self).path(which='self'),
                which
            )
        return super(SyncPlan, self).path(which)

    def add_products(self, product_ids, synchronous=True):
        """Add products to this sync plan.

        .. NOTE:: The ``synchronous`` argument has no effect in certain
            versions of Satellite. See:
            https://bugzilla.redhat.com/show_bug.cgi?id=1199150

        :param product_ids: A list of product IDs to add to this sync plan.
        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's reponse otherwise.
        :returns: The server's JSON-decoded response.
        :rtype: dict

        """
        response = client.put(
            self.path('add_products'),
            {'product_ids': product_ids},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        if synchronous is True and response.status_code == httplib.ACCEPTED:
            return ForemanTask(
                self._server_config,
                id=response.json()['id'],
            ).poll()
        return response.json()

    def remove_products(self, product_ids, synchronous=True):
        """Remove products from this sync plan.

        .. NOTE:: The ``synchronous`` argument has no effect in certain
            versions of Satellite. See:
            https://bugzilla.redhat.com/show_bug.cgi?id=1199150

        :param product_ids: A list of product IDs to remove from this syn plan.
        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's reponse otherwise.
        :returns: The server's JSON-decoded response.
        :rtype: dict

        """
        response = client.put(
            self.path('remove_products'),
            {'product_ids': product_ids},
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )
        response.raise_for_status()
        if synchronous is True and response.status_code == httplib.ACCEPTED:
            return ForemanTask(
                self._server_config,
                id=response.json()['id'],
            ).poll()
        return response.json()

class SystemPackage(Entity):
    """A representation of a System Package entity."""
    system = entity_fields.OneToOneField('System', required=True)
    # List of package names
    packages = entity_fields.ListField()
    # List of package group names
    groups = entity_fields.ListField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/systems/:system_id/packages'
        server_modes = ('sat')


class System(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a System entity."""
    content_view = entity_fields.OneToOneField('ContentView')
    description = entity_fields.StringField()
    environment = entity_fields.OneToOneField('Environment')
    facts = entity_fields.DictField(
        default={u'uname.machine': u'unknown'},
        null=True,
        required=True,
    )
    # guest = entity_fields.OneToManyField()  # FIXME What does this field point to?
    host_collection = entity_fields.OneToManyField('HostCollection')
    installed_products = entity_fields.ListField(null=True)
    last_checkin = entity_fields.DateTimeField()
    location = entity_fields.StringField()
    name = entity_fields.StringField(required=True)
    organization = entity_fields.OneToOneField('Organization', required=True)
    release_ver = entity_fields.StringField()
    service_level = entity_fields.StringField(null=True)
    uuid = entity_fields.StringField()

    # The type() builtin is still available within instance methods, class
    # methods, static methods, inner classes, and so on. However, type() is
    # *not* available at the current level of lexical scoping after this point.
    type = entity_fields.StringField(default='system', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/systems'
        # Alternative paths.
        # '/katello/api/v2/environments/:environment_id/systems'
        # '/katello/api/v2/host_collections/:host_collection_id/systems'
        server_modes = ('sat', 'sam')

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        Most entities are uniquely identified by an ID. ``System`` is a bit
        different: it has both an ID and a UUID, and the UUID is used to
        uniquely identify a ``System``.

        Return a path in the format ``katello/api/v2/systems/<uuid>`` if a UUID
        is available and:

        * ``which is None``, or
        * ``which == 'this'``.

        """
        if 'uuid' in vars(self) and (which is None or which == 'self'):
            return '{0}/{1}'.format(
                super(System, self).path(which='base'),
                self.uuid
            )
        return super(System, self).path(which)

    def read(self, entity=None, attrs=None, ignore=()):
        if attrs is None:
            attrs = self.read_json()
        if bz_bug_is_open(1202917):
            ignore = tuple(set(ignore).union(('facts', 'type')))
        attrs['last_checkin'] = attrs.pop('checkin_time')
        attrs['host_collections'] = attrs.pop('hostCollections')
        attrs['installed_products'] = attrs.pop('installedProducts')
        organization_id = attrs.pop('organization_id')
        if organization_id  is None:
            attrs['organization'] = None
        else:
            attrs['organization'] = {'id': organization_id}
        return super(System, self).read(entity, attrs, ignore)


class TemplateCombination(Entity):
    """A representation of a Template Combination entity."""
    config_template = entity_fields.OneToOneField('ConfigTemplate', required=True)
    environment = entity_fields.OneToOneField('Environment', null=True)
    hostgroup = entity_fields.OneToOneField('HostGroup', null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('api/v2/config_templates/:config_template_id/'
                    'template_combinations')
        server_modes = ('sat')


class TemplateKind(Entity, EntityReadMixin):
    """A representation of a Template Kind entity.

    Unusually, the ``/api/v2/template_kinds/:id`` path is totally unsupported.

    """

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/template_kinds'
        server_modes = ('sat')
        NUM_CREATED_BY_DEFAULT = 8


class UserGroup(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a User Group entity."""
    admin = entity_fields.BooleanField()
    name = entity_fields.StringField(required=True)
    role = entity_fields.OneToManyField('Role')
    user = entity_fields.OneToManyField('User', required=True)
    usergroup = entity_fields.OneToManyField('UserGroup')

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/usergroups'
        server_modes = ('sat')

    # NOTE: See BZ 1151220
    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {u'usergroup': super(UserGroup, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=()):
        """Work around a bug with reading the ``admin`` attribute.

        An HTTP GET request to ``path('self')`` does not return the ``admin``
        attribute, even though it should. Work around this issue. See:

        * http://projects.theforeman.org/issues/9594
        * https://bugzilla.redhat.com/show_bug.cgi?id=1197871

        """
        if attrs is None:
            attrs = self.read_json()
        if (
                'admin' not in attrs and
                'admin' not in ignore and
                rm_bug_is_open(9594)):  # BZ is private
            response = client.put(
                self.path('self'),
                {},
                auth=self._server_config.auth,
                verify=self._server_config.verify,
            )
            response.raise_for_status()
            attrs['admin'] = response.json()['admin']
        return super(UserGroup, self).read(entity, attrs, ignore)


class User(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a User entity.

    The LDAP authentication source with an ID of 1 is internal. It is nearly
    guaranteed to exist and be functioning. Thus, ``auth_source`` is set to "1"
    by default for a practical reason: it is much easier to use internal
    authentication than to spawn LDAP authentication servers for each new user.

    """
    login = entity_fields.StringField(
        length=(1, 100),
        required=True,
        str_type=('alpha', 'alphanumeric', 'cjk', 'latin1', 'utf8'),
    )
    admin = entity_fields.BooleanField(null=True)
    # See __init__
    auth_source = entity_fields.OneToOneField('AuthSourceLDAP', required=True)
    default_location = entity_fields.OneToOneField('Location', null=True)
    default_organization = entity_fields.OneToOneField('Organization', null=True)
    firstname = entity_fields.StringField(null=True, length=(1, 50))
    lastname = entity_fields.StringField(null=True, length=(1, 50))
    location = entity_fields.OneToManyField('Location', null=True)
    mail = entity_fields.EmailField(required=True)
    organization = entity_fields.OneToManyField('Organization', null=True)
    password = entity_fields.StringField(required=True)

    def __init__(self, server_config=None, **kwargs):
        """Set a default value for the ``auth_source`` field."""
        super(User, self).__init__(server_config, **kwargs)
        self.auth_source.default = AuthSourceLDAP(self._server_config, id=1)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/users'
        server_modes = ('sat', 'sam')

    # NOTE: See BZ 1151220
    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {u'user': super(User, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=('password',)):
        if attrs is None:
            attrs = self.read_json()
        auth_source_id = attrs.pop('auth_source_id')
        if auth_source_id  is None:
            attrs['auth_source'] = None
        else:
            attrs['auth_source'] = {'id': auth_source_id}
        return super(User, self).read(entity, attrs, ignore)
