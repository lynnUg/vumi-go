from txpostgres import txpostgres

import psycopg2
import psycopg2.extras
def real_dict_connect(*args, **kwargs):
    kwargs['connection_factory'] = psycopg2.extras.RealDictConnection
    return psycopg2.connect(*args, **kwargs)


class DictRowConnection(txpostgres.Connection):
    """Extend the txpostgres ``Connection`` and override the
    ``cursorFactory``

    """

    connectionFactory = staticmethod(real_dict_connect)

    @property
    def closed(self):
        """Return ``True`` if the underlying connection is closed
        ``False`` otherwise

        """
        if self._connection:
            return self._connection.closed
        return True


class DictRowConnectionPool(txpostgres.ConnectionPool):
    """Extend the txpostgres ``ConnectionPool`` and override the
    ``connectionFactory``

    """

    connectionFactory = DictRowConnection

    @property
    def closed(self):
        """Return ``True`` all the connections are closed
        ``False`` otherwise

        """
        return all(c.closed for c in self.connections)
