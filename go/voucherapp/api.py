import json

from twisted.python import log
from twisted.internet import defer
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET

import string, random


from go.voucherapp import settings as app_settings

from go.voucherapp import DictRowConnectionPool
class BaseResource(Resource):
    """Base class for the APIs ``Resource``s"""

    _connection_pool = None  # The txpostgres connection pool

    def __init__(self):
        Resource.__init__(self)
        connection_string = app_settings.get_connection_string()
        connection_pool = DictRowConnectionPool(
            None, connection_string, min=app_settings.API_MIN_CONNECTIONS)
        self.connection_pool = yield connection_pool.start()
    @defer.inlineCallbacks
    def get_user(self, voucher_number):
        """Fetch the user with the given ``id``"""
        query = """
            SELECT id, phone_number, voucher_number
            FROM voucherapp_voucher
            WHERE voucher_number = %%(voucher_number)s
        """ 

        params = {'voucher_number': voucher_number}
        result = yield self._connection_pool.runQuery(query, params)
        if len(result) > 0:
            defer.returnValue(result[0])
        else:
            defer.returnValue(None)
    def create_voucher_number(self):
            length=7
        	return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(length))
    @defer.inlineCallbacks
    def create_voucher_interaction(self, cursor, phone_number):
        """Create a new voucher"""
        query = """
            INSERT INTO voucherapp_voucher
                (phone_number,voucher_number,created_at)
            VALUES
                (%%(phone_number)s, %%(voucher_number)s, now())
            RETURNING id, phone_number, voucher_number
        """ 

        params = {
            'phone_number': phone_number,
            'vocuher_number': self.create_voucher_number(password)
        }

        cursor = yield cursor.execute(query, params)
        result = yield cursor.fetchone()
        defer.returnValue(result)
    @defer.inlineCallbacks
    def create_voucher(self, phone_number):
        """Create a new account"""
        result = yield self._connection_pool.runInteraction(
            self.create_voucher_interaction, phone_number)

        defer.returnValue(result)