from django.conf import settings
ENDPOINT_DESCRIPTION_STRING = getattr(
    settings, 'BILLING_ENDPOINT_DESCRIPTION_STRING',
    "tcp:9090:interface=127.0.0.1")
API_MIN_CONNECTIONS = getattr(settings, 'BILLING_API_MIN_CONNECTIONS', 10)
def get_connection_string():
    """Return the database connection string"""
    db = settings.DATABASES['default']
    if 'postgres' not in db['ENGINE']:
        raise ValueError("voucher API only supports PostGreSQL.")
    return "host='%s' dbname='%s' user='%s' password='%s'" \
        % (db.get('HOST', 'localhost'), db.get('NAME'), db.get('USER'),
           db.get('PASSWORD'))