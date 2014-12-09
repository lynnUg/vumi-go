from zope.interface import implements

from twisted.cred import portal, checkers, credentials, error
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.guard import HTTPAuthSessionWrapper, BasicCredentialFactory
from vumi import log

from twisted.cred import portal, checkers, credentials, error as credError
from twisted.internet import defer, reactor
from twisted.web import static, resource
from twisted.web.resource import IResource



 
class PasswordDictChecker:
    implements(checkers.ICredentialsChecker)
    credentialInterfaces = (credentials.IUsernamePassword,)
 
    def __init__(self, passwords):
        "passwords: a dict-like object mapping usernames to passwords"
        self.passwords = passwords
 
    def requestAvatarId(self, credentials):
        username = credentials.username
        if self.passwords.has_key(username):
            if credentials.password == self.passwords[username]:
                return defer.succeed(username)
            else:
                return defer.fail(
                    credError.UnauthorizedLogin("Bad password"))
        else:
            return defer.fail(
                credError.UnauthorizedLogin("No such user"))
 
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

    def getChild(self, conversation_key, request):
       log.warning("in api")
       log.warning(conversation_key)
       log.warning(request)
       myresource = self.resource_class()
       checker = PasswordDictChecker(passwords)
       realm = HttpPasswordRealm(myresource)
       p = portal.Portal(realm, [checker])
       credentialFactory = BasicCredentialFactory("AccessMobile Messaging Api")
       protected_resource = HTTPAuthSessionWrapper(p, [credentialFactory])
       return protected_resource
       
passwords = {
    'admin': 'aaa',
    'user1': 'bbb',
    'user2': 'ccc'
    }