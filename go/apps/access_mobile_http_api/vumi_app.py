# -*- test-case-name: go.apps.http_api_nostream.tests.test_vumi_app -*-
import base64
import json ,requests
from twisted.internet.defer import inlineCallbacks, Deferred, succeed
from twisted.internet.error import DNSLookupError, ConnectionRefusedError
from twisted.web.error import SchemeNotSupported

from vumi.config import ConfigInt, ConfigText
from vumi.utils import http_request_full, HttpTimeoutError
from vumi.transports.httprpc import httprpc
from vumi import log
from go.apps.access_mobile_http_api.auth import AuthorizedResource
from go.apps.http_api_nostream.resource import ConversationResource
from go.apps.access_mobile_http_api.resource import ApiResource
from go.base.utils import extract_auth_from_url
from go.vumitools.app_worker import GoApplicationWorker
from vumi.components.window_manager import WindowManager
from voucher import Voucher

class HTTPWorkerConfig(GoApplicationWorker.CONFIG_CLASS):
    """Configuration options for AccessHTTPWorker."""

    web_path = ConfigText(
        "The path the HTTP worker should expose the API on.",
        required=True, static=True)
    web_port = ConfigInt(
        "The port the HTTP worker should open for the API.",
        required=True, static=True)
    health_path = ConfigText(
        "The path the resource should receive health checks on.",
        default='/health/', static=True)
    concurrency_limit = ConfigInt(
        "Maximum number of clients per account. A value less than "
        "zero disables the limit.",
        default=-1)
    timeout = ConfigInt(
        "How long to wait for a response from a server when posting "
        "messages or events", default=5, static=True)
    worker_concurrency_limit = ConfigInt(
        "Maximum number of clients per account per worker. A value less than "
        "zero disables the limit. (Unlike concurrency_limit, this queues "
        "requests instead of rejecting them.)",
        default=-1, static=True)


class ConcurrencyLimiterError(Exception):
    """
    Error raised by concurrency limiters.
    """


class ConcurrencyLimiter(object):
    """
    Concurrency limiter.

    Each concurrent operation should call :meth:`start` and wait for the
    deferred it returns to fire before doing any work. When it's done, it
    should call :meth:`stop` to signal completion and allow the next queued
    operation to begin.

    Internally, we track two things:
      * :attr:`_concurrents` holds the number of active operations, for which
        the deferred returned by :meth:`start` has fired, but :meth:`stop` has
        not been called.
      * :attr:`_waiters` holds a list of pending deferreds that have been
        returned by :meth:`start` but not yet fired.
    """

    def __init__(self, name, limit):
        self._name = name
        self._limit = limit
        self._concurrents = 0
        self._waiters = []

    def _inc_concurrent(self):
        self._concurrents += 1
        return self._concurrents

    def _dec_concurrent(self):
        if self._concurrents <= 0:
            raise ConcurrencyLimiterError(
                "Can't decrement key below zero: %s" % (self._name,))
        else:
            self._concurrents -= 1
        return self._concurrents

    def _make_waiter(self):
        d = Deferred()
        self._waiters.append(d)
        return d

    def _pop_waiter(self):
        if not self._waiters:
            return None
        return self._waiters.pop(0)

    def _check_concurrent(self):
        if self._concurrents >= self._limit:
            return
        d = self._pop_waiter()
        if d is not None:
            self._inc_concurrent()
            d.callback(None)

    def empty(self):
        """
        Check if this concurrency limiter is empty so it can be cleaned up.
        """
        return (not self._concurrents) and (not self._waiters)

    def start(self):
        """
        Start a concurrent operation.

        If we are below the limit, we increment the concurrency count and fire
        the deferred we return. If not, we add the deferred to the waiters list
        and return it unfired.
        """
        # While the implemetation matches the description in the docstring
        # conceptually, it always adds a new waiter and then calls
        # _check_concurrent() to handle the various cases.
        if self._limit < 0:
            # Special case for no limit, never block.
            return succeed(None)
        elif self._limit == 0:
            # Special case for limit of zero, always block forever.
            return Deferred()
        d = self._make_waiter()
        self._check_concurrent()
        return d

    def stop(self):
        """
        Stop a concurrent operation.

        If there are waiting operations, we pop and fire the first. If not, we
        decrement the concurrency count.
        """
        # While the implemetation matches the description in the docstring
        # conceptually, it always decrements the concurrency counter and then
        # calls _check_concurrent() to handle the various cases.
        if self._limit <= 0:
            # Special case for where we don't keep state.
            return
        self._dec_concurrent()
        self._check_concurrent()


class ConcurrencyLimitManager(object):
    """
    Concurrency limit manager.

    Each concurrent operation should call :meth:`start` with a key and wait for
    the deferred it returns to fire before doing any work. When it's done, it
    should call :meth:`stop` to signal completion and allow the next queued
    operation to begin.
    """

    def __init__(self, limit):
        self._limit = limit
        self._concurrency_limiters = {}

    def _get_limiter(self, key):
        if key not in self._concurrency_limiters:
            self._concurrency_limiters[key] = ConcurrencyLimiter(
                key, self._limit)
        return self._concurrency_limiters[key]

    def _cleanup_limiter(self, key):
        limiter = self._concurrency_limiters.get(key)
        if limiter and limiter.empty():
            del self._concurrency_limiters[key]

    def start(self, key):
        """
        Start a concurrent operation.

        This gets the concurrency limiter for the given key (creating it if
        necessary) and starts a concurrent operation on it.
        """
        start_d = self._get_limiter(key).start()
        self._cleanup_limiter(key)
        return start_d

    def stop(self, key):
        """
        Stop a concurrent operation.

        This gets the concurrency limiter for the given key (creating it if
        necessary) and stops a concurrent operation on it. If the concurrency
        limiter is empty, it is deleted.
        """
        self._get_limiter(key).stop()
        self._cleanup_limiter(key)

class AmHTTPWorker(GoApplicationWorker):

    worker_name = 'bulk_message_http_api_worker'
    CONFIG_CLASS = HTTPWorkerConfig
    max_ack_window = 100
    max_ack_wait = 100
    monitor_interval = 20
    monitor_window_cleanup = True

    @inlineCallbacks
    def setup_application(self):
        yield super(AmHTTPWorker, self).setup_application()
        config = self.get_static_config()
        self.web_path = config.web_path
        self.web_port = config.web_port
        self.health_path = config.health_path

        # Set these to empty dictionaries because we're not interested
        # in using any of the helper functions at this point.
        self._event_handlers = {}
        self._session_handlers = {}

        self.concurrency_limiter = ConcurrencyLimitManager(
            config.worker_concurrency_limit)
        self.webserver = self.start_web_resources([
            (self.get_conversation_resource(), self.web_path),
            (httprpc.HttpRpcHealthResource(self), self.health_path),
        ], self.web_port)
        wm_redis = self.redis.sub_manager('%s:window_manager' % (
            self.worker_name,))
        self.window_manager = WindowManager(wm_redis,
            window_size=self.max_ack_window,
            flight_lifetime=self.max_ack_wait)
        self.window_manager.monitor(self.on_window_key_ready,
            interval=self.monitor_interval,
            cleanup=self.monitor_window_cleanup,
            cleanup_callback=self.on_window_cleanup)

    def get_conversation_resource(self):
        return AuthorizedResource(self,ApiResource)

    @inlineCallbacks
    def teardown_application(self):
        yield super(AmHTTPWorker, self).teardown_application()
        yield self.webserver.loseConnection()

    def get_api_config(self, conversation, key, default=None):
        return conversation.config.get(
            'http_api', {}).get(key, default)

    def on_window_cleanup(self, window_id):
        log.info('Finished window %s, removing.' % (window_id,))

    @inlineCallbacks
    def on_window_key_ready(self, window_id, flight_key):
        log.warning("getting data")
        
        
        try:
            data = yield self.window_manager.get_data(window_id, flight_key)
            log.warning(data)
            to_addr = data['to_addr']
            message = data['message']
            #numbers=data['numbers']
            convkey = data['convkey']
            usertoken=data['usertoken']
            accesstoken=data['accesstoken']

            auth_headers = {
                'Authorization': ['Basic %s' % (base64.b64encode(usertoken+':'+accesstoken),)],
                }
         
            url='http://vumilynn.cloudapp.net/api/v1/go/http_api/%s/messages.json' % (
                convkey,)
            if "create_voucher" in data:
                    if data["create_voucher"]:
                        voc=Voucher(to_addr )
                        message= message+" "+voc.voucher_number
                        voc.save()
            payload = { "to_addr": to_addr ,"content": message }
            msg=requests.put(url, auth=(usertoken, accesstoken),
                    data=json.dumps(payload))
            #for number in numbers:
                #out_message=""
                #if "create_voucher" in data:
                    #if data["create_voucher"]:
                        #voc=Voucher(number)
                        #out_message= message+" "+voc.voucher_number
                        #voc.save()
                #payload = { "to_addr": number ,"content": out_message}
                #msg=requests.put(url, auth=(usertoken, accesstoken),
                    #data=json.dumps(payload))
            

        except Exception as e:
            log.warning(e.message)
            log.warning("execption happened in sending to http")
        
    @inlineCallbacks
    def send_message_via_window(self, **kwargs):
        yield self.window_manager.create_window(kwargs["window_id"], strict=False)
        yield self.window_manager.add(kwargs["window_id"], kwargs)

   

    

   
