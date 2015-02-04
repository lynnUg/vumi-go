def get_connection_string():
    """Return the database connection string"""
    db = settings.DATABASES['default']
    if 'postgres' not in db['ENGINE']:
        raise ValueError("voucher API only supports PostGreSQL.")
    return "host='%s' dbname='%s' user='%s' password='%s'" \
        % (db.get('HOST', 'localhost'), db.get('NAME'), db.get('USER'),
           db.get('PASSWORD'))