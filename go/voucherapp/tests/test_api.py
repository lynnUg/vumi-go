import json
import decimal

import pytest

from twisted.internet.defer import inlineCallbacks, returnValue

from vumi.tests.helpers import VumiTestCase

from go.voucherapp import settings as app_settings
from go.voucherapp import api
from go.voucherapp import DummySite, DictRowConnectionPool, JSONDecoder


DB_SUPPORTED = False
try:
    app_settings.get_connection_string()
    DB_SUPPORTED = True
except ValueError:
    pass

skipif_unsupported_db = pytest.mark.skipif(
    "True" if not DB_SUPPORTED else "False",
    reason="voucherapp API requires PostGreSQL")


class ApiCallError(Exception):
    """Raised if a voucher API call fails."""

    def __init__(self, response):
        super(ApiCallError, self).__init__(response.value())
        self.response = response


@skipif_unsupported_db
@pytest.mark.django_db
class VoucherappApiTestCase(VumiTestCase):

    @inlineCallbacks
    def setUp(self):
        connection_string = app_settings.get_connection_string()
        connection_pool = DictRowConnectionPool(
            None, connection_string, min=app_settings.API_MIN_CONNECTIONS)
        self.connection_pool = yield connection_pool.start()
        root = api.Root(connection_pool)
        self.web = DummySite(root)

    @inlineCallbacks
    def tearDown(self):
        #for table in ('billing_transaction', 'billing_messagecost',
                      #'billing_tagpool', 'billing_account'):
            #yield self.connection_pool.runOperation(
                #'DELETE FROM %s' % (table,))
        self.connection_pool.close()

    @inlineCallbacks
    def call_api(self, method, path, **kw):
        headers = {'content-type': 'application/json'}
        http_method = getattr(self.web, method)
        response = yield http_method(path, headers=headers, **kw)
        if response.responseCode != 200:
            raise ApiCallError(response)
        result = json.loads(response.value(), cls=JSONDecoder)
        returnValue(result)

    def create_api_user(self):
        """
        Create a user by calling the billing API.
        """
        content = {
            'phone_number': "256781057175", 
        }
        return self.call_api('post', 'users', content=content)

    def get_api_user(self, user_id):
        """
        Retrieve a user by id.
        """
        return self.call_api('get', 'users/%s' % (user_id,))

    def get_api_user_list(self):
        """
        Retrieve a list of all users.
        """
        return self.call_api('get', 'users')

    