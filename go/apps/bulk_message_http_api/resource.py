from twisted.web import static, resource
class ApiResource(resource.Resource):
 
    def __init__(self):
        resource.Resource.__init__(self)
 
    def getChild(self, path, request):
        text = "You're in.  The path is /%s." % path
        return static.Data(text, "text/plain")