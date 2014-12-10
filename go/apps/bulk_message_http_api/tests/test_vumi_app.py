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

from go.apps.bulk_message_http_api.vumi_app import (
    ConcurrencyLimitManager, BulkHTTPWorker)
from go.apps.bulk_message_http_api.resource import ApiResource
from go.apps.tests.helpers import AppWorkerHelper
class TestBulkHTTPWorkerBase(VumiTestCase):

    def setUp(self):
        self.app_helper = self.add_helper(
            AppWorkerHelper(BulkHTTPWorker))

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


        self.auth_headers = {
            'Authorization': ['Basic ' + base64.b64encode('%s:%s' % (
                'admin', 'aaa'))],
        }

        self._setup_wait_for_request()
        self.add_cleanup(self._wait_for_requests)

    def get_message_url(self):
        return self.mock_push_server.url

    def get_event_url(self):
        return self.mock_push_server.url

   

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


class TestBulkHTTPWorker(TestBulkHTTPWorkerBase):

    @inlineCallbacks
    def test_missing_auth(self):
        yield self.start_app_worker()
        url = '%s/%s/messages.json' % (self.url, 'conversation10')
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
        url = '%s/%s/messages.json' % (self.url, 'conversation10')
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

        url = '%s/%s/messages.json' % (self.url, 'conversation10')
        response = yield http_request_full(url, json.dumps(msg),
                                           self.auth_headers, method='PUT')
        print "delivery body"
        print response.delivered_body

        self.assertEqual(response.code, http.OK)
        self.assertEqual(
            response.headers.getRawHeaders('content-type'),
            ['application/json; charset=utf-8'])
        put_msg = json.loads(response.delivered_body)

        # We do not respect the message_id that's been given.
        self.assertEqual(msg['message_id'], put_msg['message_id'])
        self.assertEqual(put_msg['to_addr'], msg['to_addr'])

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

        url = '%s/%s/messages.json' % (self.url, 'conversation10')
        d = http_request_full(
            url, json.dumps(msg), self.auth_headers, method='PUT',
            timeout=0.2)

        yield self.assertFailure(d, HttpTimeoutError)

    @inlineCallbacks
    def test_in_send_to_with_evil_content(self):
        yield self.start_app_worker()
        msg = {
            'content': 0xBAD,
            'to_addr': '+1234',
        }

        url = '%s/%s/messages.json' % (self.url, 'conversation10')
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

        url = '%s/%s/messages.json' % (self.url, 'conversation10')
        response = yield http_request_full(url, json.dumps(msg),
                                           self.auth_headers, method='PUT')
        self.assert_bad_request(
            response, "Invalid or missing value for payload key 'to_addr'")


   


