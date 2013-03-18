import uuid
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from go.base.utils import vumi_api_for_user


class Command(BaseCommand):
    help = "Manage contact groups belonging to a Vumi Go account."

    LOCAL_OPTIONS = [
        make_option('--email-address',
            dest='email-address',
            help='Email address for the Vumi Go user'),
        make_option('--group',
            dest='group',
            help='The contact group to operate on'),
        make_option('--create',
            dest='create',
            action='store_true',
            default=False,
            help='Create a new group'),
        make_option('--delete',
            dest='delete',
            action='store_true',
            default=False,
            help='Delete a group'),
        make_option('--list',
            dest='list',
            action='store_true',
            default=False,
            help='List groups'),
    ]
    option_list = BaseCommand.option_list + tuple(LOCAL_OPTIONS)

    def ask_for_option(self, options, opt):
        if options.get(opt.dest) is None:
            value = raw_input("%s: " % (opt.help,))
            if value:
                options[opt.dest] = value
            else:
                raise CommandError('Please provide %s:' % (opt.dest,))

    def ask_for_options(self, options, opt_dests):
        for opt in self.LOCAL_OPTIONS:
            if opt.dest in opt_dests:
                self.ask_for_option(options, opt)

    def get_operation(self, options, operations):
        operations = [op for op in operations if options[op]]
        if len(operations) != 1:
            raise CommandError(
                "Please provide either --create, --delete or --list.")
        return operations[0]

    def handle(self, *args, **options):
        options = options.copy()
        operation = self.get_operation(options, ('create', 'delete', 'list'))

        self.ask_for_options(options, ['email-address'])
        user = User.objects.get(username=options['email-address'])
        user_api = vumi_api_for_user(user)

        if operation == 'list':
            return self.handle_list(user_api, options)
        elif operation == 'create':
            self.ask_for_options(options, ['group'])
            return self.handle_create(user_api, options)
        elif operation == 'delete':
            self.ask_for_options(options, ['group'])
            return self.handle_delete(user_api, options)

    def format_group(self, group):
        return '%s [%s] "%s"' % (
            group.key, group.created_at.strftime("%Y-%m-%d %H:%M"), group.name)

    def handle_list(self, user_api, options):
        groups = user_api.list_groups()
        for group in sorted(groups, key=lambda g: g.created_at):
            self.stdout.write(" * %s\n" % (self.format_group(group),))

    def handle_create(self, user_api, options):
        group = user_api.contact_store.new_group(
            options['group'].decode('utf-8'))
        self.stdout.write(
            "Group created:\n * %s\n" % (self.format_group(group),))

    def handle_delete(self, user_api, options):
        # NOTE: Copied from go.conversation.tasks and expanded.
        #
        # NOTE: There is a small chance that this can break when running in
        #       production if the load is high and the queues have backed up.
        #       What could happen is that while contacts are being removed from
        #       the group, new contacts could have been added before the group
        #       has been deleted. If this happens those contacts will have
        #       secondary indexes in Riak pointing to a non-existent Group.
        group = user_api.contact_store.get_group(options['group'])
        if group is None:
            raise CommandError(
                "Group '%s' not found. Please use the group key (UUID)." % (
                    options['group'],))
        self.stdout.write(
            "Deleting group:\n * %s\n" % (self.format_group(group),))
        # We do this one at a time because we're already saving them one at a
        # time and the boilerplate for fetching batches without having them all
        # sit in memory is ugly.
        for contact_key in group.backlinks.contacts():
            contact = user_api.contact_store.get_contact_by_key(contact_key)
            contact.groups.remove(group)
            contact.save()
            self.stdout.write('.')
        self.stdout.write('\nDone.\n')
        group.delete()
