import json

from twisted.python import log
from twisted.internet import defer
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET

import string, random

from go.billing.utils import JSONEncoder, JSONDecoder,

class BaseResource(Resource):
    """Base class for the APIs ``Resource``s"""

    _connection_pool = None  # The txpostgres connection pool

    def __init__(self, connection_pool):
        Resource.__init__(self)
        self._connection_pool = connection_pool
    def _handle_error(self, error, request, *args, **kwargs):
        """Log the error and return an HTTP 500 response"""
        log.err(error)
        request.setResponseCode(500)  # Internal Server Error
        request.write(error.getErrorMessage())
        request.finish()

    def _handle_bad_request(self, request, *args, **kwargs):
        """Handle a bad request"""
        request.setResponseCode(400)  # Bad Request
        request.finish()

    def _render_to_json(self, result, request, *args, **kwargs):
        """Render the ``result`` as a JSON string.

        If the result is ``None`` return an HTTP 404 response.

        """
        if result is not None:
            data = json.dumps(result, cls=JSONEncoder)
            request.setResponseCode(200)  # OK
            request.setHeader('Content-Type', 'application/json')
            request.write(data)
        else:
            request.setResponseCode(404)  # Not Found
        request.finish()

    def _parse_json(self, request):
        """Return the POSTed data as a JSON object.

        If the *Content-Type* is anything other than *application/json*
        return ``None``.

        """
        content_type = request.getHeader('Content-Type')
        if request.method == 'POST' and content_type == 'application/json':
            content = request.content.read()
            return json.loads(content, cls=JSONDecoder)
        return None


class VoucherResource(Resource):
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
    def render_POST(self, request):
        """Handle an HTTP POST request"""
        data = self._parse_json(request)
        if data:
            phone_number = data.get('phone_number', None)
            if phone_number:
                d = self.create_voucher(phone_number)
                d.addCallbacks(self._render_to_json, self._handle_error,
                               callbackArgs=[request], errbackArgs=[request])

            else:
                self._handle_bad_request(request)
        else:
            self._handle_bad_request(request)
        return NOT_DONE_YET
class Root(BaseResource):
    """The root resource"""

    def __init__(self, connection_pool):
        BaseResource.__init__(self, connection_pool)
        self.putChild('voucher', VoucherResource(connection_pool))

    def getChild(self, name, request):
        if name == '':
            return self
        return Resource.getChild(self, name, request)

    def render_GET(self, request):
        request.setResponseCode(200)  # OK
        return ''