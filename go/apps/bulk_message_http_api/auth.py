from zope.interface import implements

from twisted.cred import portal, checkers, credentials, error
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.guard import HTTPAuthSessionWrapper, BasicCredentialFactory
from vumi import log

from twisted.cred import portal, checkers, credentials, error as credError
from twisted.internet import defer, reactor
from twisted.web import static, resource
from twisted.web.resource import IResource



 
class PasswordChecker:
    implements(checkers.ICredentialsChecker)
    credentialInterfaces = (credentials.IUsernamePassword,)
 
    def __init__(self, worker,conversation_key):
      self.worker=worker
      self.conversation_key = conversation_key
        

    @inlineCallbacks
    def requestAvatarId(self, credentials):
        username = credentials.username
        token = credentials.password
        user_exists = yield self.worker.vumi_api.user_exists(username)
        if user_exists:
            user_api = self.worker.vumi_api.get_user_api(username)
            conversation = yield user_api.get_wrapped_conversation(
                self.conversation_key)
            if conversation is not None:
                tokens = self.worker.get_api_config(
                    conversation, 'api_tokens', [])
                if token in tokens:
                  returnValue(username)
            raise credError.UnauthorizedLogin("Bad password")
        else:
            raise credError.UnauthorizedLogin("No such user")
 
class HttpPasswordRealm(object):
    implements(portal.IRealm)
 
    def __init__(self, myresource):
        self.myresource = myresource
    
    def requestAvatar(self, user, mind, *interfaces):
        if IResource in interfaces:
            # myresource is passed on regardless of user
            return (IResource, self.myresource, lambda: None)
        raise NotImplementedError()
class AuthorizedResource(resource.Resource):

    def __init__(self, worker,resource_class):
        resource.Resource.__init__(self)
        self.worker = worker
        self.resource_class = resource_class

    def render(self, request):
        return resource.NoResource().render(request)

    def getChild(self,conversation_key,request):
       myresource = self.resource_class(self.worker)
       checker = PasswordChecker(self.worker,conversation_key)
       realm = HttpPasswordRealm(myresource)
       p = portal.Portal(realm, [checker])
       credentialFactory = BasicCredentialFactory("AccessMobile Messaging Api")
       protected_resource = HTTPAuthSessionWrapper(p, [credentialFactory])
       return protected_resource
       
