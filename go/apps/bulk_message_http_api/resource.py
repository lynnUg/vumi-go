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


class MessageResource(BaseResource):

    #routing_key = '%(transport_name)s.stream.message.%(conversation_key)s'

    def render_PUT(self, request):
        d = Deferred()
        d.addCallback(self.handle_PUT)
        d.callback(request)
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
            payload = json.loads(request.content.read())
        except ValueError:
            self.client_error_response(request, 'Invalid Message for Vumi')
            return

     
        user_account = request.getUser()
        d = self.worker.concurrency_limiter.start(user_account)
        try:
             yield self.handle_PUT_send_to(request, payload)
        finally:
            self.worker.concurrency_limiter.stop(user_account)
            

   

   
    def handle_PUT_send_to(self, request, payload):
        user_account = request.getUser()
        msg_options = SendToOptions(payload)
        if not msg_options.is_valid:
            self.client_error_response(request, msg_options.error_msg)
            return
        m = payload  
        n = json.dumps(m) 
        self.successful_send_response(request, n)



class ApiResource(resource.Resource):
 
    def __init__(self,worker):
        resource.Resource.__init__(self)
        self.worker = worker
        self.redis = worker.redis

    def key(self, *args):
        return ':'.join(['concurrency'] + map(unicode, args))

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
        return self.getDeferredChild(path, request)
   
    def getDeferredChild(self, path, request):
        resource_class = self.get_child_resource(path)

        if resource_class is None:
            return resource.NoResource()

        user_id=request.getUser()
        config= yield self.get_wo

        return resource_class(self.worker)
        

    def get_child_resource(self, path):
        return {
            'messages.json': MessageResource,
        }.get(path)