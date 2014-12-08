from zope.interface import implements

from twisted.cred import portal, checkers, credentials, error
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web import resource
from twisted.web.guard import HTTPAuthSessionWrapper, BasicCredentialFactory
from vumi import log
class AuthorizedResource(resource.Resource):

    def __init__(self, worker):
        resource.Resource.__init__(self)
        self.worker = worker
        #self.resource_class = resource_class

    def render(self, request):
        return resource.NoResource().render(request)

    def getChild(self, conversation_key, request):
       log.warning("in api")
       log.warning(conversation_key)
       log.warning(request)
       pass