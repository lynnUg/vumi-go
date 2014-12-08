from zope.interface import implements

from twisted.cred import portal, checkers, credentials, error
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web import resource
from twisted.web.guard import HTTPAuthSessionWrapper, BasicCredentialFactory