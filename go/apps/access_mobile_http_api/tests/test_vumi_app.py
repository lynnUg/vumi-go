import base64
import json
import logging
from urlparse import urlparse, urlunparse

from twisted.internet.defer import inlineCallbacks, DeferredQueue, returnValue
from twisted.internet.error import DNSLookupError, ConnectionRefusedError
from twisted.web.error import SchemeNotSupported
from twisted.web import http
from twisted.web.server import NOT_DONE_YET

from vumi.utils import http_request_full, HttpTimeoutError
from vumi.message import TransportUserMessage, TransportEvent
from vumi.tests.utils import MockHttpServer, LogCatcher
from vumi.tests.helpers import VumiTestCase

from go.apps.access_mobile_http_api.vumi_app import (
    ConcurrencyLimitManager, AmHTTPWorker)
from go.apps.access_mobile_http_api.resource import ApiResource
from go.apps.tests.helpers import AppWorkerHelper

class TestConcurrencyLimitManager(VumiTestCase):
    def test_concurrency_limiter_no_limit(self):
        """
        When given a negitive limit, ConcurrencyLimitManager never blocks.
        """
        limiter = ConcurrencyLimitManager(-1)
        d1 = limiter.start("key")
        self.assertEqual(d1.called, True)
        d2 = limiter.start("key")
        self.assertEqual(d2.called, True)

        # Check that we aren't storing any state.
        self.assertEqual(limiter._concurrency_limiters, {})

        # Check that stopping doesn't explode.
        limiter.stop("key")

    def test_concurrency_limiter_zero_limit(self):
        """
        When given a limit of zero, ConcurrencyLimitManager always blocks
        forever.
        """
        limiter = ConcurrencyLimitManager(0)
        d1 = limiter.start("key")
        self.assertEqual(d1.called, False)
        d2 = limiter.start("key")
        self.assertEqual(d2.called, False)

        # Check that we aren't storing any state.
        self.assertEqual(limiter._concurrency_limiters, {})

        # Check that stopping doesn't explode.
        limiter.stop("key")

    def test_concurrency_limiter_stop_without_start(self):
        """
        ConcurrencyLimitManager raises an exception if stop() is called without
        a prior call to start().
        """
        limiter = ConcurrencyLimitManager(1)
        self.assertRaises(Exception, limiter.stop)

    def test_concurrency_limiter_one_limit(self):
        """
        ConcurrencyLimitManager fires the next deferred in the queue when stop()
        is called.
        """
        limiter = ConcurrencyLimitManager(1)
        d1 = limiter.start("key")
        self.assertEqual(d1.called, True)
        d2 = limiter.start("key")
        self.assertEqual(d2.called, False)
        d3 = limiter.start("key")
        self.assertEqual(d3.called, False)

        # Stop the first concurrent and check that the second fires.
        limiter.stop("key")
        self.assertEqual(d2.called, True)
        self.assertEqual(d3.called, False)

        # Stop the second concurrent and check that the third fires.
        limiter.stop("key")
        self.assertEqual(d3.called, True)

        # Stop the third concurrent and check that we don't hang on to state.
        limiter.stop("key")
        self.assertEqual(limiter._concurrency_limiters, {})

    def test_concurrency_limiter_two_limit(self):
        """
        ConcurrencyLimitManager fires the next deferred in the queue when stop()
        is called.
        """
        limiter = ConcurrencyLimitManager(2)
        d1 = limiter.start("key")
        self.assertEqual(d1.called, True)
        d2 = limiter.start("key")
        self.assertEqual(d2.called, True)
        d3 = limiter.start("key")
        self.assertEqual(d3.called, False)
        d4 = limiter.start("key")
        self.assertEqual(d4.called, False)

        # Stop a concurrent and check that the third fires.
        limiter.stop("key")
        self.assertEqual(d3.called, True)
        self.assertEqual(d4.called, False)

        # Stop a concurrent and check that the fourth fires.
        limiter.stop("key")
        self.assertEqual(d4.called, True)

        # Stop the last concurrents and check that we don't hang on to state.
        limiter.stop("key")
        limiter.stop("key")
        self.assertEqual(limiter._concurrency_limiters, {})

    def test_concurrency_limiter_multiple_keys(self):
        """
        ConcurrencyLimitManager handles different keys independently.
        """
        limiter = ConcurrencyLimitManager(1)
        d1a = limiter.start("key-a")
        self.assertEqual(d1a.called, True)
        d2a = limiter.start("key-a")
        self.assertEqual(d2a.called, False)
        d1b = limiter.start("key-b")
        self.assertEqual(d1b.called, True)
        d2b = limiter.start("key-b")
        self.assertEqual(d2b.called, False)

        # Stop "key-a" and check that the next "key-a" fires.
        limiter.stop("key-a")
        self.assertEqual(d2a.called, True)
        self.assertEqual(d2b.called, False)

        # Stop "key-b" and check that the next "key-b" fires.
        limiter.stop("key-b")
        self.assertEqual(d2b.called, True)

        # Stop the last concurrents and check that we don't hang on to state.
        limiter.stop("key-a")
        limiter.stop("key-b")
        self.assertEqual(limiter._concurrency_limiters, {})
class TestAmHTTPWorkerBase(VumiTestCase):

    def setUp(self):
        self.app_helper = self.add_helper(
            AppWorkerHelper(AmHTTPWorker))

    @inlineCallbacks
    def start_app_worker(self, config_overrides={}):
        self.config = {
            'health_path': '/health/',
            'web_path': '/foo',
            'web_port': 0,
            'metrics_prefix': 'metrics_prefix.',
        }
        self.config.update(config_overrides)
        self.app = yield self.app_helper.get_app_worker(self.config)
        self.addr = self.app.webserver.getHost()
        self.url = 'http://%s:%s%s' % (
            self.addr.host, self.addr.port, self.config['web_path'])

        # Mock server to test HTTP posting of inbound messages & events
        self.mock_push_server = MockHttpServer(self.handle_request)
        yield self.mock_push_server.start()
        self.add_cleanup(self.mock_push_server.stop)
        self.push_calls = DeferredQueue()
        self.conversation = yield self.create_conversation(
            self.get_message_url(), self.get_event_url(),
            ['token-1', 'token-2', 'token-3'])

        self.auth_headers = {
            'Authorization': ['Basic ' + base64.b64encode('%s:%s' % (
                self.conversation.user_account.key, 'token-1'))],
        }

        

        self._setup_wait_for_request()
        self.add_cleanup(self._wait_for_requests)

    def get_message_url(self):
        return self.mock_push_server.url

    def get_event_url(self):
        return self.mock_push_server.url
   

    @inlineCallbacks
    def create_conversation(self, message_url, event_url, tokens):

        config = {
            'http_api': {
                'api_tokens': tokens,
                'push_message_url': message_url,
                'push_event_url': event_url,
                'metric_store': 'metric_store',
            }
        }
        conv = yield self.app_helper.create_conversation(config=config)
        yield self.app_helper.start_conversation(conv)
        conversation = yield self.app_helper.get_conversation(conv.key)
        returnValue(conversation)
   

    def _setup_wait_for_request(self):
        # Hackery to wait for the request to finish
        self._req_state = {
            'queue': DeferredQueue(),
            'expected': 0,
        }
        orig_track = ApiResource.track_request
        orig_release = ApiResource.release_request

        def track_wrapper(*args, **kw):
            self._req_state['expected'] += 1
            return orig_track(*args, **kw)

        def release_wrapper(*args, **kw):
            return orig_release(*args, **kw).addCallback(
                self._req_state['queue'].put)

        self.patch(ApiResource, 'track_request', track_wrapper)
        self.patch(ApiResource, 'release_request', release_wrapper)

    @inlineCallbacks
    def _wait_for_requests(self):
        while self._req_state['expected'] > 0:
            yield self._req_state['queue'].get()
            self._req_state['expected'] -= 1

    def handle_request(self, request):
        self.push_calls.put(request)
        return NOT_DONE_YET

    def assert_bad_request(self, response, reason):
        self.assertEqual(response.code, http.BAD_REQUEST)
        self.assertEqual(
            response.headers.getRawHeaders('content-type'),
            ['application/json; charset=utf-8'])
        data = json.loads(response.delivered_body)
        self.assertEqual(data, {
            "success": False,
            "reason": reason,
        })


class TestAmHTTPWorker(TestAmHTTPWorkerBase):

    @inlineCallbacks
    def test_missing_auth(self):
        yield self.start_app_worker()
        url = '%s/%s/messages.json' % (self.url, self.conversation.key)
        msg = {
            'to_addr': '+2345',
            'content': 'foo',
            'message_id': 'evil_id',
        }
        response = yield http_request_full(url, json.dumps(msg), {},
                                           method='PUT')
        self.assertEqual(response.code, http.UNAUTHORIZED)
        self.assertEqual(response.headers.getRawHeaders('www-authenticate'), [
            'basic realm="AccessMobile Messaging Api"'])

    @inlineCallbacks
    def test_invalid_auth(self):
        yield self.start_app_worker()
        url = '%s/%s/messages.json' % (self.url, self.conversation.key)
        msg = {
            'to_addr': '+2345',
            'content': 'foo',
            'message_id': 'evil_id',
        }
        auth_headers = {
            'Authorization': ['Basic %s' % (base64.b64encode('foo:bar'),)],
        }
        response = yield http_request_full(url, json.dumps(msg), auth_headers,
                                           method='PUT')
        self.assertEqual(response.code, http.UNAUTHORIZED)
        self.assertEqual(response.headers.getRawHeaders('www-authenticate'), [
            'basic realm="AccessMobile Messaging Api"'])

    @inlineCallbacks
    def test_send_to(self):
        yield self.start_app_worker()
        msg = {
            'to_addr': '+2345',
            'content': 'foo',
            'message_id': 'evil_id',
        }

        url = '%s/%s/messages.json' % (self.url, self.conversation.key)
        response = yield http_request_full(url, json.dumps(msg),
                                           self.auth_headers, method='PUT')

        self.assertEqual(response.code, http.OK)
        self.assertEqual(
            response.headers.getRawHeaders('content-type'),
            ['application/json; charset=utf-8'])
        put_msg = json.loads(response.delivered_body)

        self.assertTrue('convkey' in put_msg)
        self.assertTrue('accesstoken' in put_msg)
        

    @inlineCallbacks
    def test_send_to_with_zero_worker_concurrency(self):
        """
        When the worker_concurrency_limit is set to zero, our requests will
        never complete.

        This is a hacky way to test that the concurrency limit is being applied
        without invasive changes to the app worker.
        """
        yield self.start_app_worker({'worker_concurrency_limit': 0})
        msg = {
            'to_addr': '+2345',
            'content': 'foo',
            'message_id': 'evil_id',
        }

        url = '%s/%s/messages.json' % (self.url, self.conversation.key)
        d = http_request_full(
            url, json.dumps(msg), self.auth_headers, method='PUT',
            timeout=0.2)
        self.assertFailure(d, HttpTimeoutError)

    @inlineCallbacks
    def test_in_send_to_with_evil_content(self):
        yield self.start_app_worker()
        msg = {
            'content': 0xBAD,
            'to_addr': '+1234',
        }

        url = '%s/%s/messages.json' % (self.url, self.conversation.key)
        response = yield http_request_full(url, json.dumps(msg),
                                           self.auth_headers, method='PUT')
        self.assert_bad_request(
            response, "Invalid or missing value for payload key 'content'")

    @inlineCallbacks
    def test_in_send_to_with_evil_to_addr(self):
        yield self.start_app_worker()
        msg = {
            'content': 'good',
            'to_addr': 1234,
        }

        url = '%s/%s/messages.json' % (self.url, self.conversation.key)
        response = yield http_request_full(url, json.dumps(msg),
                                           self.auth_headers, method='PUT')
        self.assert_bad_request(
            response, "Invalid or missing value for payload key 'to_addr'")


   


