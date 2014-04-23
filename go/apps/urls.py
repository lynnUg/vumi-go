from django.conf.urls import patterns, url, include

urlpatterns = patterns('',
    url(r'^survey/',
        include('go.apps.surveys.urls', namespace='survey')),
    url(r'^bulk_message/',
        include('go.apps.bulk_message.urls', namespace='bulk_message')),
    url(r'^opt_out/',
        include('go.apps.opt_out.urls', namespace='opt_out')),
    url(r'^sequential_send/',
        include('go.apps.sequential_send.urls', namespace='sequential_send')),
    url(r'^subscription/',
        include('go.apps.subscription.urls', namespace='subscription')),
    url(r'^wikipedia_ussd/',
        include('go.apps.wikipedia.ussd.urls', namespace='wikipedia_ussd')),
    url(r'^wikipedia_sms/',
        include('go.apps.wikipedia.sms.urls', namespace='wikipedia_sms')),
    url(r'^jsbox/',
        include('go.apps.jsbox.urls', namespace='jsbox')),
    url(r'^http_api/',
        include('go.apps.http_api.urls', namespace='http_api')),
)
