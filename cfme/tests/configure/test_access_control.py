# -*- coding: utf-8 -*-
import traceback

import fauxfactory
import pytest

from cfme import test_requirements
from cfme.base.credential import Credential
from cfme.common.provider import base_types
from cfme.configure.access_control import AddUserView
from cfme.configure.tasks import TasksView
from cfme.exceptions import RBACOperationBlocked
from cfme.infrastructure import virtual_machines as vms
from cfme.infrastructure.provider.virtualcenter import VMwareProvider
from cfme.services.myservice import MyService
from cfme.utils import error
from cfme.utils.appliance.implementations.ui import navigate_to
from cfme.utils.blockers import BZ
from cfme.utils.log import logger
from cfme.utils.providers import ProviderFilter
from cfme.utils.update import update
from fixtures.provider import setup_one_or_skip

pytestmark = test_requirements.rbac


@pytest.fixture(scope='module')
def group_collection(appliance):
    return appliance.collections.groups


@pytest.fixture(scope='module')
def a_provider(request):
    prov_filter = ProviderFilter(classes=[VMwareProvider])
    return setup_one_or_skip(request, filters=[prov_filter])


def new_credential():
    if BZ(1487199, forced_streams=['5.8']).blocks:
        return Credential(principal='uid{}'.format(fauxfactory.gen_alphanumeric().lower()),
                          secret='redhat')
    else:
        return Credential(principal='uid{}'.format(fauxfactory.gen_alphanumeric()),
                          secret='redhat')


def new_user(appliance, group, name=None, credential=None):
    from fixtures.blockers import bug

    uppercase_username_bug = bug(1487199)

    name = name or 'user{}'.format(fauxfactory.gen_alphanumeric())
    credential = credential or new_credential()

    user = appliance.collections.users.create(
        name=name,
        credential=credential,
        email='xyz@redhat.com',
        group=group,
        cost_center='Workload',
        value_assign='Database')

    # Version 5.8.2 has a regression blocking logins for usernames w/ uppercase chars
    if '5.8.2' <= user.appliance.version < '5.9' and uppercase_username_bug:
        user.credential.principal = user.credential.principal.lower()

    return user


def new_role(appliance, name=None):
    name = name or 'rol{}'.format(fauxfactory.gen_alphanumeric())
    return appliance.collections.roles.create(
        name=name,
        vm_restriction='None')


@pytest.fixture(scope='function')
def check_item_visibility(tag):
    def _check_item_visibility(item, user_restricted):
        category_name = ' '.join((tag.category.display_name, '*'))
        item.edit_tags(category_name, tag.display_name)
        with user_restricted:
            assert item.exists
        item.remove_tag(category_name, tag.display_name)
        with user_restricted:
            assert not item.exists

    return _check_item_visibility


# User test cases
@pytest.mark.sauce
@pytest.mark.tier(2)
def test_user_crud(appliance, group_collection):
    group_name = 'EvmGroup-user'
    group = group_collection.instantiate(description=group_name)

    user = new_user(appliance, group)
    with update(user):
        user.name = "{}edited".format(user.name)
    copied_user = user.copy()
    copied_user.delete()
    user.delete()


# @pytest.mark.meta(blockers=[1035399]) # work around instead of skip
@pytest.mark.tier(2)
def test_user_login(appliance, group_collection):
    group_name = 'EvmGroup-user'
    group = group_collection.instantiate(description=group_name)

    user = new_user(appliance, group)
    try:
        with user:
            navigate_to(appliance.server, 'Dashboard')
    finally:
        user.appliance.server.login_admin()


@pytest.mark.tier(3)
def test_user_duplicate_username(appliance, group_collection):
    """ Tests that creating user with existing username is forbidden.

    Steps:
        * Generate some credential
        * Create a user with this credential
        * Create another user with same credential
    """
    group_name = 'EvmGroup-user'
    group = group_collection.instantiate(description=group_name)

    credential = new_credential()

    nu = new_user(appliance, group, credential=credential)
    with pytest.raises(RBACOperationBlocked):
        nu = new_user(appliance, group, credential=credential)

    # Navigating away from this page will create an "Abandon Changes" alert
    # Since group creation failed we need to reset the state of the page
    navigate_to(nu.appliance.server, 'Dashboard')


@pytest.mark.tier(3)
def test_user_allow_duplicate_name(appliance, group_collection):
    """ Tests that creating user with existing full name is allowed.

    Steps:
        * Generate full name
        * Create a user with this full name
        * Create another user with same full name
    """
    group_name = 'EvmGroup-user'
    group = group_collection.instantiate(description=group_name)

    name = 'user{}'.format(fauxfactory.gen_alphanumeric())

    # Create first user
    new_user(appliance, group, name=name)
    # Create second user with same full name
    nu = new_user(appliance, group, name=name)

    assert nu.exists


@pytest.mark.tier(3)
def test_username_required_error_validation(appliance, group_collection):
    group_name = 'EvmGroup-user'
    group = group_collection.instantiate(description=group_name)

    with error.expected("Name can't be blank"):
        appliance.collections.users.create(
            name="",
            credential=new_credential(),
            email='xyz@redhat.com',
            group=group
        )


@pytest.mark.tier(3)
def test_userid_required_error_validation(appliance, group_collection):
    group_name = 'EvmGroup-user'
    group = group_collection.instantiate(description=group_name)

    with error.expected("Userid can't be blank"):
        appliance.collections.users.create(
            name='user{}'.format(fauxfactory.gen_alphanumeric()),
            credential=Credential(principal='', secret='redhat'),
            email='xyz@redhat.com',
            group=group
        )
    # Navigating away from this page will create an "Abandon Changes" alert
    # Since group creation failed we need to reset the state of the page
    navigate_to(appliance.server, 'Dashboard')


@pytest.mark.tier(3)
def test_user_password_required_error_validation(appliance, group_collection):
    group_name = 'EvmGroup-user'
    group = group_collection.instantiate(description=group_name)

    check = "Password can't be blank"

    with error.expected(check):
        appliance.collections.users.create(
            name='user{}'.format(fauxfactory.gen_alphanumeric()),
            credential=Credential(
                principal='uid{}'.format(fauxfactory.gen_alphanumeric()), secret=None),
            email='xyz@redhat.com',
            group=group)
    # Navigating away from this page will create an "Abandon Changes" alert
    # Since group creation failed we need to reset the state of the page
    navigate_to(appliance.server, 'Dashboard')


@pytest.mark.tier(3)
def test_user_group_error_validation(appliance):
    with error.expected("A User must be assigned to a Group"):
        appliance.collections.users.create(
            name='user{}'.format(fauxfactory.gen_alphanumeric()),
            credential=new_credential(),
            email='xyz@redhat.com',
            group='')


@pytest.mark.tier(3)
def test_user_email_error_validation(appliance, group_collection):
    group = group_collection.instantiate(description='EvmGroup-user')

    with error.expected("Email must be a valid email address"):
        appliance.collections.users.create(
            name='user{}'.format(fauxfactory.gen_alphanumeric()),
            credential=new_credential(),
            email='xyzdhat.com',
            group=group)


@pytest.mark.tier(2)
def test_user_edit_tag(appliance, group_collection):
    group_name = 'EvmGroup-user'
    group = group_collection.instantiate(description=group_name)

    user = new_user(appliance, group)
    user.edit_tags("Cost Center *", "Cost Center 001")
    assert ('Cost Center *', 'Cost Center 001') in user.get_tags(), "User edit tag failed"
    user.delete()


@pytest.mark.tier(3)
def test_user_remove_tag(appliance, group_collection):
    group_name = 'EvmGroup-user'
    group = group_collection.instantiate(description=group_name)

    user = new_user(appliance, group)
    user.edit_tags("Department", "Engineering")
    user.remove_tag("Department", "Engineering")
    navigate_to(user, 'Details')
    assert ('Department', 'Engineering') not in user.get_tags(), "Remove User tag failed"
    user.delete()


@pytest.mark.tier(3)
def test_delete_default_user(appliance):
    """Test for deleting default user Administrator.

    Steps:
        * Login as Administrator user
        * Try deleting the user
    """
    user = appliance.collections.users.instantiate(name='Administrator')
    with pytest.raises(RBACOperationBlocked):
        user.delete()


@pytest.mark.tier(3)
@pytest.mark.meta(automates=[BZ(1090877)])
@pytest.mark.meta(blockers=[BZ(1408479)], forced_streams=["5.7", "upstream"])
def test_current_user_login_delete(appliance, request):
    """Test for deleting current user login.

    Steps:
        * Login as Admin user
        * Create a new user
        * Login with the new user
        * Try deleting the user
    """
    group_name = "EvmGroup-super_administrator"
    group = group_collection(appliance).instantiate(description=group_name)

    user = new_user(appliance, group)
    request.addfinalizer(user.delete)
    request.addfinalizer(user.appliance.server.login_admin)
    with user:
        with pytest.raises(RBACOperationBlocked):
            user.delete()


@pytest.mark.tier(3)
def test_tagvis_user(user_restricted, check_item_visibility):
    """ Tests if group honour tag visibility feature
    Prerequirement:
        Catalog, tag, role, group and restricted user should be created

    Steps:
        1. As admin add tag to group
        2. Login as restricted user, group is visible for user
        3. As admin remove tag from group
        4. Login as restricted user, group is not visible for user
    """
    check_item_visibility(user_restricted, user_restricted)


@pytest.mark.sauce
@pytest.mark.tier(2)
# Group test cases
def test_group_crud(group_collection):
    role = 'EvmRole-administrator'
    group = group_collection.create(
        description='grp{}'.format(fauxfactory.gen_alphanumeric()), role=role)
    with update(group):
        group.description = "{}edited".format(group.description)
    group.delete()


@pytest.mark.sauce
@pytest.mark.tier(2)
def test_group_crud_with_tag(a_provider, category, tag, group_collection):
    """Test for verifying group create with tag defined

    Steps:
        * Login as Admin user
        * Navigate to add group page
        * Fill all fields
        * Set tag
        * Save group
    """
    group = group_collection.create(
        description='grp{}'.format(fauxfactory.gen_alphanumeric()),
        role='EvmRole-approver',
        tag=([category.display_name, tag.display_name], True),
        host_cluster=([a_provider.data['name']], True),
        vm_template=([a_provider.data['name'], a_provider.data['datacenters'][0],
                     'Discovered virtual machine'], True)
    )
    with update(group):
        group.tag = ([tag.category.display_name, tag.display_name], False)
        group.host_cluster = ([a_provider.data['name']], False)
        group.vm_template = ([a_provider.data['name'], a_provider.data['datacenters'][0],
                             'Discovered virtual machine'], False)
    group.delete()


@pytest.mark.tier(3)
def test_group_duplicate_name(group_collection):
    """ Verify that two groups can't have the same name """
    role = 'EvmRole-approver'
    group_description = 'grp{}'.format(fauxfactory.gen_alphanumeric())
    group = group_collection.create(description=group_description, role=role)

    with pytest.raises(RBACOperationBlocked):
        group = group_collection.create(
            description=group_description, role=role)

    # Navigating away from this page will create an "Abandon Changes" alert
    # Since group creation failed we need to reset the state of the page
    navigate_to(group.appliance.server, 'Dashboard')


@pytest.mark.tier(2)
def test_group_edit_tag(group_collection):
    role = 'EvmRole-approver'
    group_description = 'grp{}'.format(fauxfactory.gen_alphanumeric())
    group = group_collection.create(description=group_description, role=role)

    group.edit_tags("Cost Center *", "Cost Center 001")
    assert ('Cost Center *', 'Cost Center 001') in group.get_tags(), "Group edit tag failed"
    group.delete()


@pytest.mark.tier(2)
def test_group_remove_tag(group_collection):
    role = 'EvmRole-approver'
    group_description = 'grp{}'.format(fauxfactory.gen_alphanumeric())
    group = group_collection.create(description=group_description, role=role)

    navigate_to(group, 'Edit')
    group.edit_tags("Department", "Engineering")
    group.remove_tag("Department", "Engineering")
    assert ('Department', 'Engineering') not in group.get_tags(), "Group User tag failed"
    group.delete()


@pytest.mark.tier(3)
def test_group_description_required_error_validation(group_collection):
    error_text = "Description can't be blank"

    with error.expected(error_text):
        group_collection.create(description=None, role='EvmRole-approver')

    # Navigating away from this page will create an "Abandon Changes" alert
    # Since group creation failed we need to reset the state of the page
    navigate_to(group_collection.parent.server, 'Dashboard')


@pytest.mark.tier(3)
def test_delete_default_group(group_collection):
    """Test for deleting default group EvmGroup-administrator.

    Steps:
        * Login as Administrator user
        * Try deleting the group EvmGroup-adminstrator
    """
    group = group_collection.instantiate(description='EvmGroup-administrator')

    with pytest.raises(RBACOperationBlocked):
        group.delete()


@pytest.mark.tier(3)
def test_delete_group_with_assigned_user(appliance, group_collection):
    """Test that CFME prevents deletion of a group that has users assigned
    """
    role = 'EvmRole-approver'
    group_description = 'grp{}'.format(fauxfactory.gen_alphanumeric())
    group = group_collection.create(description=group_description, role=role)
    new_user(appliance, group=group)
    with pytest.raises(RBACOperationBlocked):
        group.delete()


@pytest.mark.tier(3)
def test_edit_default_group(group_collection):
    """Test that CFME prevents a user from editing a default group

    Steps:
        * Login as Administrator user
        * Try editing the group EvmGroup-adminstrator
    """
    group = group_collection.instantiate(description='EvmGroup-approver')

    group_updates = {}
    with pytest.raises(RBACOperationBlocked):
        group.update(group_updates)


@pytest.mark.tier(3)
def test_edit_sequence_usergroups(request, group_collection):
    """Test for editing the sequence of user groups for LDAP lookup.

    Steps:
        * Login as Administrator user
        * create a new group
        * Edit the sequence of the new group
        * Verify the changed sequence
    """
    role_name = 'EvmRole-approver'
    group_description = 'grp{}'.format(fauxfactory.gen_alphanumeric())
    group = group_collection.create(description=group_description, role=role_name)
    request.addfinalizer(group.delete)

    group.set_group_order(group.description)


@pytest.mark.tier(3)
def test_tagvis_group(user_restricted, group_with_tag, check_item_visibility):
    """ Tests if group honour tag visibility feature
    Prerequirement:
        Catalog, tag, role, group and restricted user should be created

    Steps:
        1. As admin add tag to group
        2. Login as restricted user, group is visible for user
        3. As admin remove tag from group
        4. Login as restricted user, group is not visible for user
    """
    check_item_visibility(group_with_tag, user_restricted)


# Role test cases
@pytest.mark.sauce
@pytest.mark.tier(2)
def test_role_crud(appliance):
    role = new_role(appliance)
    with update(role):
        role.name = "{}edited".format(role.name)
    copied_role = role.copy()
    copied_role.delete()
    role.delete()


@pytest.mark.tier(3)
def test_rolename_required_error_validation(appliance):
    with error.expected("Name can't be blank"):
        appliance.collections.roles.create(
            name=None,
            vm_restriction='Only User Owned'
        )


@pytest.mark.tier(3)
def test_rolename_duplicate_validation(appliance):
    name = 'rol{}'.format(fauxfactory.gen_alphanumeric())
    role = new_role(appliance, name=name)
    with pytest.raises(RBACOperationBlocked):
        new_role(appliance, name=name)

    # Navigating away from this page will create an "Abandon Changes" alert
    # Since group creation failed we need to reset the state of the page
    navigate_to(role.appliance.server, 'Dashboard')


@pytest.mark.tier(3)
def test_delete_default_roles(appliance):
    """Test that CFME prevents a user from deleting a default role
    when selecting it from the Access Control EVM Role checklist

    Steps:
        * Login as Administrator user
        * Navigate to Configuration -> Role
        * Try editing the group EvmRole-approver
    """
    role = appliance.collections.roles.instantiate(name='EvmRole-approver')
    with pytest.raises(RBACOperationBlocked):
        role.delete()


@pytest.mark.tier(3)
def test_edit_default_roles(appliance):
    """Test that CFME prevents a user from editing a default role
    when selecting it from the Access Control EVM Role checklist

    Steps:
        * Login as Administrator user
        * Navigate to Configuration -> Role
        * Try editing the group EvmRole-auditor
    """
    role = appliance.collections.roles.instantiate(name='EvmRole-auditor')
    newrole_name = "{}-{}".format(role.name, fauxfactory.gen_alphanumeric())
    role_updates = {'name': newrole_name}

    with pytest.raises(RBACOperationBlocked):
        role.update(role_updates)


@pytest.mark.tier(3)
def test_delete_roles_with_assigned_group(appliance, group_collection):
    role = new_role(appliance)
    group_description = 'grp{}'.format(fauxfactory.gen_alphanumeric())
    group_collection.create(description=group_description, role=role.name)

    with pytest.raises(RBACOperationBlocked):
        role.delete()


@pytest.mark.tier(3)
def test_assign_user_to_new_group(appliance, group_collection):
    role = new_role(appliance)  # call function to get role

    group_description = 'grp{}'.format(fauxfactory.gen_alphanumeric())
    group = group_collection.create(description=group_description, role=role.name)

    new_user(appliance, group=group)


def _test_vm_provision(appliance):
    logger.info("Checking for provision access")
    view = navigate_to(vms.Vm, 'VMsOnly')
    view.toolbar.lifecycle.item_enabled('Provision VMs')

# this fixture is used in disabled tests. it should be updated along with tests
# def _test_vm_power_on():
#     """Ensures power button is shown for a VM"""
#     logger.info("Checking for power button")
#     vm_name = vms.Vm.get_first_vm()
#     logger.debug("VM " + vm_name + " selected")
#     if not vms.is_pwr_option_visible(vm_name, option=vms.Vm.POWER_ON):
#         raise OptionNotAvailable("Power button does not exist")


def _test_vm_removal():
    logger.info("Testing for VM removal permission")
    vm_name = vms.get_first_vm()
    logger.debug("VM {} selected".format(vm_name))
    vms.remove(vm_name, cancel=True)


@pytest.mark.tier(3)
@pytest.mark.parametrize(
    'product_features', [
        [['Everything', 'Access Rules for all Virtual Machines', 'VM Access Rules', 'View'],
         ['Everything', 'Compute', 'Infrastructure', 'Virtual Machines', 'Accordions']]])
def test_permission_edit(appliance, request, product_features):
    """
    Ensures that changes in permissions are enforced on next login
    Args:
        appliance: cfme appliance fixture
        request: pytest request fixture
        product_features: product features to set for test role
        action: reference to a function to execute under the test user context
    """
    role_name = fauxfactory.gen_alphanumeric()
    role = appliance.collections.roles.create(name=role_name,
                vm_restriction=None,
                product_features=[(['Everything'], False)] +  # role_features
                                 [(k, True) for k in product_features])
    group_description = 'grp{}'.format(fauxfactory.gen_alphanumeric())
    group = group_collection(appliance).create(description=group_description, role=role.name)
    user = new_user(appliance, group=group)
    with user:
        try:
            navigate_to(vms.Vm, 'VMsOnly')
        except Exception:
            pytest.fail('Incorrect permissions set')
    appliance.server.login_admin()
    role.update({'product_features': [(['Everything'], True)] +
                                     [(k, False) for k in product_features]
                 })
    with user:
        try:
            with error.expected(Exception):
                navigate_to(vms.Vm, 'VMsOnly')
        except error.UnexpectedSuccessException:
            pytest.fail('Permissions have not been updated')

    @request.addfinalizer
    def _delete_user_group_role():
        for item in [user, group, role]:
            item.delete()


def _mk_role(appliance, name=None, vm_restriction=None, product_features=None):
    """Create a thunk that returns a Role object to be used for perm
       testing.  name=None will generate a random name

    """
    name = name or fauxfactory.gen_alphanumeric()
    return appliance.collections.roles.create(
        name=name,
        vm_restriction=vm_restriction,
        product_features=product_features
    )


def _go_to(cls_or_obj, dest='All'):
    """Create a thunk that navigates to the given destination"""
    def nav(appliance):
        if cls_or_obj == 'server':
            navigate_to(appliance.server, dest)
        else:
            navigate_to(cls_or_obj, dest)
    return nav


@pytest.mark.tier(3)
@pytest.mark.parametrize(
    'product_features,allowed_actions,disallowed_actions',
    [
        [  # Param Set 1
            [  # product_features
                [['Everything'], False],  # minimal permission
                [['Everything', 'Settings', 'Tasks'], True]
            ],
            {  # allowed_actions
                'tasks':
                    lambda appliance: appliance.browser.create_view(TasksView).tabs.default.click()
            },
            {  # disallowed actions
                'my services': _go_to(MyService),
                'chargeback': _go_to('server', 'Chargeback'),
                'clouds providers': _go_to(base_types()['cloud']),
                'infrastructure providers': _go_to(base_types()['infra']),
                'control explorer': _go_to('server', 'ControlExplorer'),
                'automate explorer': _go_to('server', 'AutomateExplorer')
            }
        ],
        [  # Param Set 2
            [  # product_features
                [['Everything'], True]  # full permissions
            ],
            {  # allowed_actions
                'my services': _go_to(MyService),
                'chargeback': _go_to('server', 'Chargeback'),
                'clouds providers': _go_to(base_types()['cloud']),
                'infrastructure providers': _go_to(base_types()['infra']),
                'control explorer': _go_to('server', 'ControlExplorer'),
                'automate explorer': _go_to('server', 'AutomateExplorer')
            },
            {}  # disallowed_actions
        ]
    ]
)
@pytest.mark.meta(blockers=[1262759])
def test_permissions(appliance, product_features, allowed_actions, disallowed_actions):
    """ Test that that under the specified role the allowed acctions succeed
        and the disallowed actions fail

        Args:
            appliance: cfme_test appliance fixture
            role: reference to a function that will create a role object
            allowed_actions: Action(s) that should succeed under given roles
                             permission
            disallowed_actions: Action(s) that should fail under given roles
                                permission

        *_actions are a list of actions with each item consisting of a dictionary
            object: [ { "Action Name": function_reference_action }, ...]
    """
    # create a user and role
    role = _mk_role(appliance, product_features=product_features)
    group_description = 'grp{}'.format(fauxfactory.gen_alphanumeric())
    group = group_collection(appliance).create(description=group_description, role=role.name)
    user = new_user(appliance, group=group)
    fails = {}
    try:
        with user:
            appliance.server.login(user)

            for name, action_thunk in sorted(allowed_actions.items()):
                try:
                    action_thunk(appliance)
                except Exception:
                    fails[name] = "{}: {}".format(name, traceback.format_exc())

            for name, action_thunk in sorted(disallowed_actions.items()):
                try:
                    with error.expected(Exception):
                        action_thunk(appliance)
                except error.UnexpectedSuccessException:
                    fails[name] = "{}: {}".format(name, traceback.format_exc())

            if fails:
                message = ''
                for failure in fails.values():
                    message = "{}\n\n{}".format(message, failure)
                raise Exception(message)
    finally:
        appliance.server.login_admin()


def single_task_permission_test(appliance, product_features, actions):
    """Tests that action succeeds when product_features are enabled, and
       fail when everything but product_features are enabled"""
    # Enable only specified product features
    test_prod_features = [(['Everything'], False)] + [(f, True) for f in product_features]
    test_permissions(appliance, test_prod_features, actions, {})

    # Enable everything except product features
    test_prod_features = [(['Everything'], True)] + [(f, False) for f in product_features]
    test_permissions(appliance, test_prod_features, {}, actions)


@pytest.mark.tier(3)
@pytest.mark.meta(blockers=[1262764])
def test_permissions_role_crud(appliance):
    single_task_permission_test(appliance,
                                [['Everything', 'Settings', 'Configuration'],
                                 ['Everything', 'Services', 'Catalogs Explorer']],
                                {'Role CRUD': test_role_crud})


@pytest.mark.tier(3)
def test_permissions_vm_provisioning(appliance, a_provider):
    features = [
        ['Everything', 'Compute', 'Infrastructure', 'Virtual Machines', 'Accordions'],
        ['Everything', 'Access Rules for all Virtual Machines', 'VM Access Rules', 'Modify',
         'Provision VMs']
    ]

    single_task_permission_test(
        appliance,
        features,
        {'Provision VM': _test_vm_provision}
    )


# This test is disabled until it has been rewritten
# def test_permissions_vm_power_on_access(appliance):
#    # Ensure VMs exist
#    if not vms.get_number_of_vms():
#        logger.debug("Setting up providers")
#        infra_provider
#        logger.debug("Providers setup")
#    single_task_permission_test(
#        appliance,
#        [
#            ['Infrastructure', 'Virtual Machines', 'Accordions'],
#            ['Infrastructure', 'Virtual Machines', 'VM Access Rules', 'Operate', 'Power On']
#        ],
#        {'VM Power On': _test_vm_power_on}
#    )


# This test is disabled until it has been rewritten
# def test_permissions_vm_remove(appliance):
#    # Ensure VMs exist
#    if not vms.get_number_of_vms():
#        logger.debug("Setting up providers")
#        setup_infrastructure_providers()
#        logger.debug("Providers setup")
#    single_task_permission_test(
#        appliance,
#        [
#            ['Infrastructure', 'Virtual Machines', 'Accordions'],
#            ['Infrastructure', 'Virtual Machines', 'VM Access Rules', 'Modify', 'Remove']
#        ],
#        {'Remove VM': _test_vm_removal}
#    )


@pytest.mark.tier(2)
def test_user_change_password(appliance, request):
    group_name = 'EvmGroup-user'
    group = group_collection(appliance).instantiate(description=group_name)

    user = new_user(appliance, group=group)

    request.addfinalizer(user.delete)
    request.addfinalizer(appliance.server.login_admin)
    with user:
        appliance.server.logout()
        appliance.server.login(user)
        assert appliance.server.current_full_name() == user.name
    appliance.server.login_admin()
    with update(user):
        user.credential = Credential(
            principal=user.credential.principal,
            secret="another_very_secret",
            verify_secret="another_very_secret",
        )
    with user:
        appliance.server.logout()
        appliance.server.login(user)
        assert appliance.server.current_full_name() == user.name


# Tenant/Project test cases

@pytest.mark.tier(3)
def test_superadmin_tenant_crud(request, appliance):
    """Test suppose to verify CRUD operations for CFME tenants

    Prerequisities:
        * This test is not depending on any other test and can be executed against fresh appliance.

    Steps:
        * Create tenant
        * Update description of tenant
        * Update name of tenant
        * Delete tenant
    """
    tenant_collection = appliance.collections.tenants
    tenant = tenant_collection.create(
        name='tenant1{}'.format(fauxfactory.gen_alphanumeric()),
        description='tenant1 description',
        parent=tenant_collection.get_root_tenant()
    )

    @request.addfinalizer
    def _delete_tenant():
        if tenant.exists:
            tenant.delete()

    with update(tenant):
        tenant.description = "{}edited".format(tenant.description)
    with update(tenant):
        tenant.name = "{}edited".format(tenant.name)
    tenant.delete()


@pytest.mark.tier(3)
def test_superadmin_tenant_project_crud(request, appliance):
    """Test suppose to verify CRUD operations for CFME projects

    Prerequisities:
        * This test is not depending on any other test and can be executed against fresh appliance.

    Steps:
        * Create tenant
        * Create project as child to tenant
        * Update description of project
        * Update name of project
        * Delete project
        * Delete tenant
    """
    tenant_collection = appliance.collections.tenants
    project_collection = appliance.collections.projects
    tenant = tenant_collection.create(
        name='tenant1{}'.format(fauxfactory.gen_alphanumeric()),
        description='tenant1 description',
        parent=tenant_collection.get_root_tenant())

    project = project_collection.create(
        name='project1{}'.format(fauxfactory.gen_alphanumeric()),
        description='project1 description',
        parent=project_collection.get_root_tenant())

    @request.addfinalizer
    def _delete_tenant_and_project():
        for item in [project, tenant]:
            if item.exists:
                item.delete()

    with update(project):
        project.description = "{}edited".format(project.description)
    with update(project):
        project.name = "{}_edited".format(project.name)
    project.delete()
    tenant.delete()


@pytest.mark.tier(3)
@pytest.mark.parametrize('number_of_childrens', [5])
def test_superadmin_child_tenant_crud(request, appliance, number_of_childrens):
    """Test CRUD operations for CFME child tenants, where several levels of tenants are created.

    Prerequisities:
        * This test is not depending on any other test and can be executed against fresh appliance.

    Steps:
        * Create 5 tenants where the next tenant is always child to the previous one
        * Update description of tenant(N-1)_* in the tree
        * Update name of tenant(N-1)_*
        * Delete all created tenants in reversed order
    """
    tenant_collection = appliance.collections.tenants
    tenant_list = []

    @request.addfinalizer
    def _delete_tenants():
        # reversed because we need to go from the last one
        for tenant in reversed(tenant_list):
            if tenant.exists:
                tenant.delete()

    tenant = tenant_collection.get_root_tenant()
    for i in range(1, number_of_childrens + 1):
        new_tenant = tenant_collection.create(
            name="tenant{}_{}".format(i, fauxfactory.gen_alpha(4)),
            description=fauxfactory.gen_alphanumeric(16),
            parent=tenant)
        tenant_list.append(new_tenant)
        tenant = new_tenant

    tenant_update = tenant.parent_tenant
    with update(tenant_update):
        tenant_update.description = "{}edited".format(tenant_update.description)
    with update(tenant_update):
        tenant_update.name = "{}edited".format(tenant_update.name)


def tenant_unique_tenant_project_name_on_parent_level(request, appliance, object_type):
    """Tenant or Project has always unique name on parent level. Same name cannot be used twice.

    Prerequisities:
        * This test is not depending on any other test and can be executed against fresh appliance.

    Steps:
        * Create tenant or project
        * Create another tenant or project with the same name
        * Creation will fail because object with the same name exists
        * Delete created objects
    """

    name_of_tenant = fauxfactory.gen_alphanumeric()
    tenant_description = 'description'

    tenant = object_type.create(
        name=name_of_tenant,
        description=tenant_description,
        parent=object_type.get_root_tenant())
    if appliance.version < '5.9':
        msg = 'Error when adding a new tenant: Validation failed: Name should be unique per parent'
    else:
        msg = 'Failed to add a new tenant resource - Name should be unique per parent'
    with error.expected(msg):
        tenant2 = object_type.create(
            name=name_of_tenant,
            description=tenant_description,
            parent=object_type.get_root_tenant())

    tenant.delete()

    @request.addfinalizer
    def _delete_tenant():
        if tenant.exists:
            tenant.delete()
        try:
            if tenant2.exists:
                tenant2.delete()
        except NameError:
            pass


@pytest.mark.tier(3)
def test_unique_tenant_name_on_parent_level(request, appliance):
    tenant_unique_tenant_project_name_on_parent_level(request, appliance,
                                                      appliance.collections.tenants)


@pytest.mark.tier(3)
def test_unique_project_name_on_parent_level(request, appliance):
    tenant_unique_tenant_project_name_on_parent_level(request, appliance,
                                                      appliance.collections.projects)


def test_tenant_quota_input_validate(appliance):
    roottenant = appliance.collections.tenants.get_root_tenant()
    fields = [('cpu', 2.5), ('storage', '1.x'), ('memory', '2.x'), ('vm', 1.5)]

    for field in fields:
        view = navigate_to(roottenant, 'ManageQuotas', wait_for_view=True)
        view.form.fill({'{}_cb'.format(field[0]): True, '{}_txt'.format(field[0]): field[1]})
        assert view.save_button.disabled
        view.form.fill({'{}_cb'.format(field[0]): False})


def test_delete_default_tenant(appliance):
    roottenant = appliance.collections.tenants.get_root_tenant()
    view = navigate_to(appliance.collections.tenants, 'All')
    for row in view.table.rows():
        if row.name.text == roottenant.name:
            row[0].check()
    with error.handler('Default Tenant "{}" can not be deleted'.format(roottenant.name)):
        view.toolbar.configuration.item_select('Delete selected items', handle_alert=True)


def test_copied_user_password_inheritance(appliance, group_collection, request):
    """Test to verify that dialog for copied user should appear and password field should be
    empty
    """
    group_name = 'EvmGroup-user'
    group = group_collection.instantiate(description=group_name)
    user = new_user(appliance, group)
    request.addfinalizer(user.delete)
    view = navigate_to(user, 'Details')
    view.toolbar.configuration.item_select('Copy this User to a new User')
    view = user.create_view(AddUserView)
    assert view.password_txt.value == '' and view.password_verify_txt.value == ''
    view.cancel_button.click()
