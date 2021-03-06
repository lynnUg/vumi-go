import sys

from twisted.python import log
from twisted.internet import reactor
from twisted.internet.endpoints import serverFromString

from django.core.management.base import BaseCommand

from go.voucherapp import settings as app_settings
from go.voucherapp.utils import DictRowConnectionPool
from go.voucherapp import api


class Command(BaseCommand):
    """Custom Django management command to start the billing server"""

    help = "Starts the voucher server"

    def handle(self, *args, **options):
        """Run the voucher server"""

        def connection_established(connection_pool):
            from twisted.web.server import Site
            root = api.Root(connection_pool)
            site = Site(root)
            endpoint = serverFromString(
                reactor, app_settings.ENDPOINT_DESCRIPTION_STRING)

            endpoint.listen(site)
            reactor.callWhenRunning(
                lambda _: _.stdout.write(
                    "Vocuher server is running on %s\n" %
                    app_settings.ENDPOINT_DESCRIPTION_STRING), self)

        def connection_error(err):
            self.stderr.write(err)

        log.startLogging(sys.stdout)
        self.stdout.write("we are here")
        connection_string = app_settings.get_connection_string()
        connection_pool = DictRowConnectionPool(
            None, connection_string, min=app_settings.API_MIN_CONNECTIONS)

        self.stdout.write("Connecting to database %s..." %
                          (connection_string,))

        d = connection_pool.start()
        d.addCallbacks(connection_established, connection_error)
        reactor.run()
