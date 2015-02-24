import json
import copy

from twisted.web import resource, http, util
from twisted.web.server import NOT_DONE_YET
from twisted.internet.defer import Deferred, inlineCallbacks, returnValue

from vumi import errors
from vumi.errors import InvalidMessage
from vumi.config import ConfigContext
from vumi import log

from go.vumitools.utils import MessageMetadataHelper

from twisted.web import static, resource

import string , random
import base64

from time import gmtime, strftime
from vumi.utils import http_request_full
class BaseResource(resource.Resource):

    def __init__(self, worker):
        resource.Resource.__init__(self)
        self.worker = worker
        self.vumi_api = self.worker.vumi_api
        self.user_apis = {}

    def get_user_api(self, user_account):
        if user_account in self.user_apis:
            return self.user_apis[user_account]

        user_api = self.vumi_api.get_user_api(user_account)
        self.user_apis[user_account] = user_api
        return user_api

    def get_conversation(self, user_account, conversation_key=None):
        conversation_key = conversation_key
        user_api = self.get_user_api(user_account)
        return user_api.get_wrapped_conversation(conversation_key)

    def finish_response(self, request, body, code, status=None):
        request.setHeader('Content-Type', 'application/json; charset=utf-8')
        request.setResponseCode(code, status)
        request.write(body)
        request.finish()

    def client_error_response(self, request, reason, code=http.BAD_REQUEST):
        msg = json.dumps({
            "success": False,
            "reason": reason,
        })
        self.finish_response(request, msg, code=code, status=reason)

    def success_response(self, request, reason, code=http.OK):
        msg = json.dumps({
            "success": True,
            "reason": reason,
        })
        self.finish_response(request, msg, code=code, status=reason)

    def successful_send_response(self, request, msg, code=http.OK):
        self.finish_response(request, msg, code=code)


class MsgOptions(object):
    """Helper for sanitizing msg options from clients."""

    WHITELIST = {}

    def __init__(self, payload):
        self.errors = []
        for key, checker in sorted(self.WHITELIST.iteritems()):
            value = payload.get(key)
            if not checker(value):
                self.errors.append(
                    "Invalid or missing value for payload key %r" % (key,))
            else:
                setattr(self, key, value)

    @property
    def is_valid(self):
        return not bool(self.errors)

    @property
    def error_msg(self):
        if not self.errors:
            return None
        elif len(self.errors) == 1:
            return self.errors[0]
        else:
            return "Errors:\n* %s" % ("\n* ".join(self.errors))


class MsgCheckHelpers(object):
    @staticmethod
    def is_unicode_or_none(value):
        return (value is None) or (isinstance(value, unicode))



class SendToOptions(MsgOptions):
    """Payload options for messages sent with `.send_to(...)`."""

    WHITELIST = {
        'content': MsgCheckHelpers.is_unicode_or_none,
        'to_addr': MsgCheckHelpers.is_unicode_or_none,
    }
class GetStatusOptions(MsgOptions):
    """Payload options for messages sent with `.get_status(...)`."""
    WHITELIST = {
        'get_status': MsgCheckHelpers.is_unicode_or_none,
        
    }

class MessageResource(BaseResource):


    def render_PUT(self, request):
        resp_headers = request.responseHeaders
        resp_headers.addRawHeader('Content-Type', self.content_type)
        # Turn off proxy buffering, nginx will otherwise buffer our streaming
        # output which makes clients sad.
        # See #proxy_buffering at
        # http://nginx.org/en/docs/http/ngx_http_proxy_module.html
        resp_headers.addRawHeader('X-Accel-Buffering',
                                  'yes' if self.proxy_buffering else 'no')
        # Twisted's Agent has trouble closing a connection when the server has
        # sent the HTTP headers but not the body, but sometimes we need to
        # close a connection when only the headers have been received.
        # Sending an empty string as a workaround gets the body consumer
        # stuff started anyway and then we have the ability to close the
        # connection.
        request.write('')
        done = request.notifyFinish()
        done.addBoth(self.teardown_stream)
        self._callback = partial(self.publish, request)
        self.stream_ready.callback(request)
        return NOT_DONE_YET

    def get_load_balancer_metadata(self, payload):
        """
        Probe for load_balancer config in the helper metadata
        and return it.

        TODO: Replace with a more generic mechanism for filtering
        helper_metadata. See Go issue #659.
        """
        helper_metadata = payload.get('helper_metadata', {})
        load_balancer = helper_metadata.get('load_balancer')
        if load_balancer is not None:
            return {'load_balancer': copy.deepcopy(load_balancer)}
        return {}

    def get_conversation_tag(self, conversation):
        return (conversation.delivery_tag_pool, conversation.delivery_tag)

    @inlineCallbacks
    def handle_PUT(self, request):
        try:
            content=request.content.read()
            payload = json.loads(content)
        except ValueError:
            self.client_error_response(request, 'Invalid Message for Vumi')
            return

        user_account = request.getUser()
        d = self.worker.concurrency_limiter.start(user_account)
        try:
            if payload.get('get_status'):
                yield self.handle_get_status(request,payload)
            elif payload.get('to_addr'):
                yield self.handle_PUT_send_to(request, payload)
            else :
                self.client_error_response(request, 'Invalid Message for Vumi')
                return
        finally:
            self.worker.concurrency_limiter.stop(user_account)
            
    @inlineCallbacks
    def create_http_conversation(self,request):
        """
        Hack on http tokens. Have to be auto-generated in future
        """
        config = {
            'http_api': {
                'api_tokens': [''.join(random.sample(string.letters*5,5)),''.join(random.sample(string.letters*5,5))],
                'transport_name':'testing config',
            }
        }
        user_account = request.getUser()
        conv_name='Conversation_'+strftime("%Y-%m-%d %H:%M:%S", gmtime())
        new_conv_data = {
            'conversation_type':u'http_api',
            'description':u'None',
            'name':unicode(conv_name),
            'config':config,
        }
        
        user_api=yield self.worker.vumi_api.get_user_api(user_account)
        conv = yield user_api.new_conversation(**new_conv_data)
        conv.starting()
        returnValue({"convkey":conv.key,"accesstoken":config['http_api']['api_tokens'][0]})

    @inlineCallbacks
    def handle_send_message(self,**kwargs):
        window_id = yield kwargs["convkey"]
        kwargs["window_id"]=window_id
        yield self.worker.send_message_via_window(**kwargs)
       
        


    @inlineCallbacks
    def handle_PUT_send_to(self, request, payload):
        msg_options = SendToOptions(payload)
        if not msg_options.is_valid:
            self.client_error_response(request, msg_options.error_msg)
            return
        conv_details=yield self.create_http_conversation(request)
        numbers=payload.get('to_addr')
        numbers=numbers.split(",") 
        message=payload.get('content')
        usertoken = request.getUser()
        create_voucher= False
        if "create_voucher" in payload:
            create_voucher= payload.get('create_voucher')

        new_send_message={
        "message":message,
        "numbers":numbers,
        "usertoken":usertoken,
        "create_voucher": create_voucher

        }
        new_send_message.update(conv_details)
        yield self.handle_send_message(**new_send_message)
        conv_details["create_voucher"]=create_voucher
        response= json.dumps(conv_details) 
        self.successful_send_response(request, response)


    @inlineCallbacks
    def handle_get_status(self,request,payload):
        msg_options=GetStatusOptions(payload)
        if not msg_options.is_valid:
            self.client_error_response(request,msg_options.error_msg)
            return
        user_account = request.getUser()
        conv_key=payload.get('get_status')
        conv=yield self.get_conversation(user_account,conv_key)
        status=yield conv.get_progress_status()
        response=json.dumps(status)
        self.successful_send_response(request,response)



class ApiResource(resource.Resource):
 
    def __init__(self,worker):
        resource.Resource.__init__(self)
        self.worker = worker
        self.redis = worker.redis

    def key(self, *args):
        return ':'.join(['concurrency'] + map(unicode, args))
        
    def get_worker_config(self, user_account_key):
        ctxt = ConfigContext(user_account=user_account_key)
        return self.worker.get_config(msg=None, ctxt=ctxt)

    @inlineCallbacks
    def is_allowed(self, config, user_id):
        if config.concurrency_limit < 0:
            returnValue(True)
        count = int((yield self.redis.get(self.key(user_id))) or 0)
        returnValue(count < config.concurrency_limit)

    def track_request(self, user_id):
        return self.redis.incr(self.key(user_id))

    def release_request(self, err, user_id):
        return self.redis.decr(self.key(user_id))

    def render(self, request):
        return resource.NoResource().render(request)
 
    def getChild(self, path, request):
        return util.DeferredResource(self.getDeferredChild(path, request))

    @inlineCallbacks
    def getDeferredChild(self, path, request):
        resource_class = self.get_child_resource(path)

        if resource_class is None:
            returnValue( resource.NoResource())

        user_id = request.getUser()
        config = yield self.get_worker_config(user_id)
        if (yield self.is_allowed(config, user_id)):

            # remove track when request is closed
            finished = request.notifyFinish()
            finished.addBoth(self.release_request, user_id)

            yield self.track_request(user_id)
            returnValue(resource_class(self.worker))
        returnValue(resource.ErrorPage(http.FORBIDDEN, 'Forbidden',
                                       'Too many concurrent connections'))
        
        

    def get_child_resource(self, path):
        return {
            'messages.json': MessageResource,
        }.get(path)