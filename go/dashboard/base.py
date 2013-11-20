import json
from urlparse import urljoin
from functools import wraps

import requests
from django.conf import settings


def is_collection(obj):
    return (
        isinstance(obj, dict)
        or isinstance(obj, list)
        or isinstance(obj, set)
        or isinstance(obj, tuple))


def is_mutable_collection(obj):
    return (
        isinstance(obj, dict)
        or isinstance(obj, list)
        or isinstance(obj, set))


def collection_items(collection):
    if isinstance(collection, dict):
        items = collection.iteritems()
    else:
        items = enumerate(collection)
    return items


def visit_dicts(collection, fn):
    is_mutable = is_mutable_collection(collection)

    for key, value in collection_items(collection):
        if is_collection(value):
            visit_dicts(value, fn)

            if is_mutable and isinstance(value, dict):
                collection[key] = fn(value)


def ensure_handler_fields(*fields):
    def decorator(fn):
        @wraps(fn)
        def wrapper(self, target):
            missing_fields = [f for f in fields if f not in target]
            if missing_fields:
                raise DashboardParseError(
                    "Dashboard layout handler '%s' is missing fields: %s" %
                    (fn.__name__, missing_fields))
            return fn(self, target)
        return wrapper
    return decorator


class DashboardSyncError(Exception):
    """
    Raised when we fail to sync the dashboard with diamondash.
    """


class DashboardParseError(Exception):
    """
    Raised when dashboard data cannot be parsed into something that can be
    given to diamondash.
    """


class DiamondashApiClient(object):
    def request(self, method, url, data=None):
        url = urljoin(settings.DIAMONDASH_API_URL, url)
        resp = requests.request(method, url, data=json.dumps(data))
        resp.raise_for_status()
        return resp.json['data']

    def replace_dashboard(self, config):
        return self.request('put', '/dashboards', config)


class Dashboard(object):
    def __init__(self, name, title, layout):
        self.api = DiamondashApiClient()
        self.name = name
        self.title = title
        self.layout = layout
        self.config = None

    def _raw_serialize(self):
        return {
            'name': self.name,
            'title': self.title,
            'widgets': self.layout.serialize()
        }

    def sync(self):
        """
        Ensures the dashboard exists on diamondash's side
        """
        try:
            self.config = self.api.replace_dashboard(self._raw_serialize())
        except Exception, e:
            raise DashboardSyncError("Dashboard sync failed: %s" % e)

    def serialize(self):
        return self.config


class DashboardLayout(object):
    def __init__(self, entities=None):
        self.entities = []

        for entity in (entities or []):
            self.add_entity(entity)

    def handle_metric(self, target):
        handler_name = "handle_%s_metric" % target['metric_type']
        handler = getattr(self, handler_name, None)

        if handler is None:
            raise DashboardParseError(
                "No dashboard metric handler found for metric_type '%s'"
                % target['metric_type'])

        return handler(target)

    def parse_widget_metrics(self, widget):
        def traverse(collection):
            if 'metric_type' in collection:
                collection = self.handle_metric(collection)
            return collection

        visit_dicts(widget, traverse)

    def add_widget(self, widget):
        self.parse_widget_metrics(widget)
        self.entities.append(widget)

    def new_row(self):
        self.entities.append('new_row')

    def add_entity(self, entity):
        if entity == 'new_row':
            self.new_row()
        else:
            self.add_widget(entity)

    def serialize(self):
        return self.entities
