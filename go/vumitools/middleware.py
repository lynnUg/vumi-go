# -*- test-case-name: go.vumitools.tests.test_middleware -*-
import math
import re
import time

from twisted.internet.defer import inlineCallbacks, returnValue

from vumi.middleware.base import TransportMiddleware, BaseMiddleware
from vumi.middleware.message_storing import StoringMiddleware
from vumi.middleware.tagger import TaggingMiddleware
from vumi.utils import normalize_msisdn
from vumi.blinkenlights.metrics import (
    MetricPublisher, Count, Metric, MetricManager, AVG, SUM)
from vumi.errors import ConfigError
from vumi.persist.txredis_manager import TxRedisManager

from go.vumitools.api import VumiApi
from go.vumitools.utils import MessageMetadataHelper
from vumi import log

class NormalizeMsisdnMiddleware(TransportMiddleware):

    def setup_middleware(self):
        self.country_code = self.config['country_code']
        self.strip_plus = self.config.get('strip_plus', False)

    def handle_inbound(self, message, endpoint):
        from_addr = normalize_msisdn(message.get('from_addr'),
                                     country_code=self.country_code)
        message['from_addr'] = from_addr
        return message

    def handle_outbound(self, message, endpoint):
        to_addr = normalize_msisdn(message.get('to_addr'),
                                   country_code=self.country_code)
        if self.strip_plus:
            to_addr = to_addr.lstrip('+')
        message['to_addr'] = to_addr
        return message


class OptOutMiddleware(BaseMiddleware):

    @inlineCallbacks
    def setup_middleware(self):
        self.vumi_api = yield VumiApi.from_config_async(self.config)

        self.case_sensitive = self.config.get('case_sensitive', False)
        keywords = self.config.get('optout_keywords', [])
        self.optout_keywords = set([self.casing(word) for word in keywords])

    def casing(self, word):
        if not self.case_sensitive:
            return word.lower()
        return word

    @inlineCallbacks
    def handle_inbound(self, message, endpoint):
        optout_disabled = False
        msg_mdh = MessageMetadataHelper(self.vumi_api, message)
        if msg_mdh.tag is not None:
            tagpool_metadata = yield msg_mdh.get_tagpool_metadata()
            optout_disabled = tagpool_metadata.get(
                'disable_global_opt_out', False)
        keyword = (message['content'] or '').strip()
        helper_metadata = message['helper_metadata']
        optout_metadata = helper_metadata.setdefault(
            'optout', {'optout': False})

        if (not optout_disabled
                and self.casing(keyword) in self.optout_keywords):
            optout_metadata['optout'] = True
            optout_metadata['optout_keyword'] = self.casing(keyword)
        returnValue(message)

    @staticmethod
    def is_optout_message(message):
        return message['helper_metadata'].get('optout', {}).get('optout')


class TimeMetric(Metric):
    """
    A time-based metric that fires both sums and averages.
    """
    DEFAULT_AGGREGATORS = [AVG, SUM]


class MetricsMiddleware(BaseMiddleware):
    """
    Middleware that publishes metrics on messages flowing through.

    For each transport it tracks:

    * The number of messages sent and received.
    * The time taken to respond to each reply.
    * The number of sessions started.
    * The length of each session.

    For each network operator it tracks:

    * The number of messages sent and received.
    * The number of sessions started.
    * The length of each session.

    The network operator is determined by examining each message. If the
    network operator is not detected by the transport, consider using network
    operator detecting middleware to provide it.

    Network operator metrics must be enabled by setting ``provider_metrics`` to
    ``true``.

    For each selected tag or tag pool it tracks:

    * The number of messages sent and received.
    * The number of sessions started.
    * The length of each session.

    Tags and pools to track are defined in the `tagpools` configuration option.

    :param str manager_name:
        The name of the metrics publisher, this is used for the MetricManager
        publisher and all metric names will be prefixed with it.
    :param dict redis_manager:
        Connection configuration details for Redis.
    :param str count_suffix:
        Defaults to 'count'. This is the suffix appended to all
        counters. If a message is received on endpoint
        'foo', counters are published on
        '<manager_name>.foo.inbound.<count_suffix>'
    :param str response_time_suffix:
        Defaults to 'response_time'. This is the suffix appended to all
        average response time metrics. If a message is
        received its `message_id` is stored and when a reply for the given
        `message_id` is sent out, the timestamps are compared and a averaged
        metric is published.
    :param str session_time_suffix:
        Defaults to 'session_time'. This is the suffix appended to all session
        timer metrics. When a session starts the current time is stored under
        the `from_addr` and when the session ends, the duration of the session
        is published.
    :param str session_billing_unit:
        Defaults to ``null``. Some networks charge for sessions per unit of
        time or part there of. This means it might be useful, for example, to
        record the session duration rounded to the nearest 20 seconds. Setting
        `session_billing_unit` to a number fires an additional metric whenever
        the session duration metric is fired. The new metric records the
        duration rounded up to the next `session_billing_unit`.
    :param bool provider_metrics:
        Defaults to ``false``. Set to ``true`` to fire per-operator metrics.
    :param dict tagpools:
        A dictionary defining which tag pools and tags should be tracked.
        E.g.::

            tagpools:
                pool1:
                    track_pool: true
                    track_all_tags: true
                pool2:
                    track_tags: ["tagA"]

        This tracks `pool1` but not `pool2` and tracks all tags from `pool`
        and the tag `tagB` (from `pool2`). If this configuration
        option is missing or empty, no tag or tag pool metrics are produced.
    :param int max_lifetime:
        How long to keep the response time timestamp for. Any response time
        longer than this is not recorded. Defaults to 60 seconds.
    :param int max_session_time:
        How long to keep the session time timestamp for. Any session duration
        longer than this is not recorded. Defaults to 600 seconds.
    :param str op_mode:
        What mode to operate in, options are `passive` or `active`.
        Defaults to passive.
        *passive*:  assumes the middleware endpoints are to be used as the
                    names for metrics publishing.
        *active*:   assumes that the individual messages are to be inspected
                    for their `transport_name` values.

        NOTE:   This does not apply for events or failures, the endpoints
                are always used for those since those message types are not
                guaranteed to have a `transport_name` value.
    """

    KNOWN_MODES = frozenset(['active', 'passive'])
    TAG_STRIP_RE = re.compile(r"(^[^a-zA-Z0-9_-]+)|([^a-zA-Z0-9_-]+$)")
    TAG_DOT_RE = re.compile(r"[^a-zA-Z0-9_-]+")

    def validate_config(self):
        self.manager_name = self.config['manager_name']
        self.count_suffix = self.config.get('count_suffix', 'count')
        self.response_time_suffix = self.config.get(
            'response_time_suffix', 'response_time')
        self.session_time_suffix = self.config.get(
            'session_time_suffix', 'session_time')
        self.session_billing_unit = self.config.get(
            'session_billing_unit')
        if self.session_billing_unit is not None:
            self.session_billing_unit = float(self.session_billing_unit)
        self.provider_metrics = bool(self.config.get(
            'provider_metrics', False))
        self.tagpools = dict(self.config.get('tagpools', {}))
        for pool, cfg in self.tagpools.iteritems():
            cfg['tags'] = set(cfg.get('tags', []))
        self.max_lifetime = int(self.config.get('max_lifetime', 60))
        self.max_session_time = int(self.config.get('max_session_time', 600))
        self.op_mode = self.config.get('op_mode', 'passive')
        if self.op_mode not in self.KNOWN_MODES:
            raise ConfigError('Unknown op_mode: %s' % (
                self.op_mode,))

    @inlineCallbacks
    def setup_middleware(self):
        self.validate_config()
        self.metric_publisher = yield self.worker.start_publisher(
            MetricPublisher)
        # We don't use a VumiApi here because we don't have a Riak config for
        # it.
        self.redis = yield TxRedisManager.from_config(
            self.config['redis_manager'])
        self.metric_manager = MetricManager(
            self.manager_name + '.', publisher=self.metric_publisher)
        self.metric_manager.start_polling()

    def teardown_middleware(self):
        self.metric_manager.stop_polling()
        return self.redis.close_manager()

    def get_or_create_metric(self, name, metric_class, *args, **kwargs):
        """
        Get the metric for `name`, create it with
        `metric_class(*args, **kwargs)` if it doesn't exist yet.
        """
        if name not in self.metric_manager:
            self.metric_manager.register(metric_class(name, *args, **kwargs))
        return self.metric_manager[name]

    def get_counter_metric(self, name):
        metric_name = '%s.%s' % (name, self.count_suffix)
        return self.get_or_create_metric(metric_name, Count)

    def increment_counter(self, prefix, message_type):
        metric = self.get_counter_metric('%s.%s' % (prefix, message_type))
        metric.inc()

    def get_response_time_metric(self, name):
        metric_name = '%s.%s' % (name, self.response_time_suffix)
        return self.get_or_create_metric(metric_name, TimeMetric)

    def set_response_time(self, name, time_delta):
        metric = self.get_response_time_metric(name)
        metric.set(time_delta)

    def get_session_time_metric(self, name):
        metric_name = '%s.%s' % (name, self.session_time_suffix)
        return self.get_or_create_metric(metric_name, TimeMetric)

    def set_session_time(self, name, time_delta):
        metric = self.get_session_time_metric(name)
        metric.set(time_delta)

    def key(self, transport_name, message_id):
        return '%s:%s' % (transport_name, message_id)

    def set_inbound_timestamp(self, transport_name, message):
        key = self.key(transport_name, message['message_id'])
        return self.redis.setex(
            key, self.max_lifetime, repr(time.time()))

    @inlineCallbacks
    def get_inbound_timestamp(self, transport_name, message):
        key = self.key(transport_name, message['in_reply_to'])
        timestamp = yield self.redis.get(key)
        if timestamp:
            returnValue(float(timestamp))

    @inlineCallbacks
    def get_reply_dt(self, transport_name, message):
        timestamp = yield self.get_inbound_timestamp(transport_name, message)
        if timestamp:
            returnValue(time.time() - timestamp)

    def set_session_start_timestamp(self, transport_name, addr):
        key = self.key(transport_name, addr)
        return self.redis.setex(
            key, self.max_session_time, repr(time.time()))

    @inlineCallbacks
    def get_session_start_timestamp(self, transport_name, addr):
        key = self.key(transport_name, addr)
        timestamp = yield self.redis.get(key)
        if timestamp:
            returnValue(float(timestamp))

    @inlineCallbacks
    def get_session_dt(self, transport_name, addr):
        timestamp = yield self.get_session_start_timestamp(
            transport_name, addr)
        if timestamp:
            returnValue(time.time() - timestamp)

    def get_name(self, message, endpoint):
        if self.op_mode == 'active':
            return message['transport_name']
        return endpoint

    def get_provider(self, message):
        provider = message.get('provider') or 'unknown'
        return provider.lower()

    def get_tag(self, message):
        return TaggingMiddleware.map_msg_to_tag(message)

    def slugify_tagname(self, tagname):
        tagname = self.TAG_STRIP_RE.sub("", tagname)
        tagname = self.TAG_DOT_RE.sub(".", tagname)
        return tagname.lower()

    def fire_response_time(self, prefix, reply_dt):
        if reply_dt:
            self.set_response_time(prefix, reply_dt)

    def fire_session_dt(self, prefix, session_dt):
        if not session_dt:
            return
        self.set_session_time(prefix, session_dt)
        unit = self.session_billing_unit
        if unit:
            rounded_dt = math.ceil(session_dt / unit) * unit
            rounded_prefix = '%s.rounded.%ds' % (prefix, unit)
            self.set_session_time(rounded_prefix, rounded_dt)

    def fire_inbound_metrics(self, prefix, msg, session_dt):
        self.increment_counter(prefix, 'inbound')
        if msg['session_event'] == msg.SESSION_NEW:
            self.increment_counter(prefix, 'sessions_started')
        self.fire_session_dt(prefix, session_dt)

    def fire_inbound_transport_metrics(self, name, msg, session_dt):
        self.fire_inbound_metrics(name, msg, session_dt)

    def fire_inbound_provider_metrics(self, name, msg, session_dt):
        provider = self.get_provider(msg)
        self.fire_inbound_metrics(
            '%s.provider.%s' % (name, provider), msg, session_dt)

    def fire_inbound_tagpool_metrics(self, name, msg, session_dt):
        tag = self.get_tag(msg)
        if tag is None:
            return
        pool, tagname = tag
        config = self.tagpools.get(pool)
        if config is None:
            return
        if config.get('track_pool'):
            self.fire_inbound_metrics(
                '%s.tagpool.%s' % (name, pool), msg, session_dt)
        if config.get('track_all_tags') or tagname in config['tags']:
            slugname = self.slugify_tagname(tagname)
            self.fire_inbound_metrics(
                '%s.tag.%s.%s' % (name, pool, slugname), msg, session_dt)

    def fire_outbound_metrics(self, prefix, msg, session_dt):
        self.increment_counter(prefix, 'outbound')
        if msg['session_event'] == msg.SESSION_NEW:
            self.increment_counter(prefix, 'sessions_started')
        if session_dt is not None:
            self.fire_session_dt(prefix, session_dt)

    def fire_outbound_transport_metrics(self, name, msg, session_dt):
        self.fire_outbound_metrics(name, msg, session_dt)

    def fire_outbound_provider_metrics(self, name, msg, session_dt):
        provider = self.get_provider(msg)
        self.fire_outbound_metrics(
            '%s.provider.%s' % (name, provider), msg, session_dt)

    def fire_outbound_tagpool_metrics(self, name, msg, session_dt):
        tag = self.get_tag(msg)
        if tag is None:
            return
        pool, tagname = tag
        config = self.tagpools.get(pool)
        if config is None:
            return
        if config.get('track_pool'):
            self.fire_outbound_metrics(
                '%s.tagpool.%s' % (name, pool), msg, session_dt)
        if config.get('track_all_tags') or tagname in config['tags']:
            slugname = self.slugify_tagname(tagname)
            self.fire_outbound_metrics(
                '%s.tag.%s.%s' % (name, pool, slugname), msg, session_dt)

    @inlineCallbacks
    def handle_inbound(self, message, endpoint):
        name = self.get_name(message, endpoint)

        yield self.set_inbound_timestamp(name, message)
        if message['session_event'] == message.SESSION_NEW:
            yield self.set_session_start_timestamp(name, message['to_addr'])

        session_dt = None
        if message['session_event'] == message.SESSION_CLOSE:
            session_dt = yield self.get_session_dt(name, message['to_addr'])

        self.fire_inbound_transport_metrics(name, message, session_dt)
        if self.provider_metrics:
            self.fire_inbound_provider_metrics(name, message, session_dt)
        if self.tagpools:
            self.fire_inbound_tagpool_metrics(name, message, session_dt)
        returnValue(message)

    @inlineCallbacks
    def handle_outbound(self, message, endpoint):
        name = self.get_name(message, endpoint)

        if message['session_event'] == message.SESSION_NEW:
            yield self.set_session_start_timestamp(name, message['from_addr'])

        reply_dt = yield self.get_reply_dt(name, message)

        session_dt = None
        if message['session_event'] == message.SESSION_CLOSE:
            session_dt = yield self.get_session_dt(name, message['from_addr'])

        self.fire_response_time(name, reply_dt)
        self.fire_outbound_transport_metrics(name, message, session_dt)
        if self.provider_metrics:
            self.fire_outbound_provider_metrics(name, message, session_dt)
        if self.tagpools:
            self.fire_outbound_tagpool_metrics(name, message, session_dt)
        returnValue(message)

    def handle_event(self, event, endpoint):
        'FIX: hack for messages without delivery reports'
        self.increment_counter(endpoint, 'event.%s' % (event['event_type']))
        log.warning("handling event")
        log.warning(event['event_type'])
        if event['event_type'] == 'delivery_report':
            self.increment_counter(endpoint, 'event.%s.%s' % (
                event['event_type'], event['delivery_status']))
        elif event['event_type']=='ack':
            log.warning(event['event_type'])
            self.increment_counter(endpoint, 'event.%s.%s' % (
                'delivery_report', 'delivered'))
        return event

    def handle_failure(self, failure, endpoint):
        self.increment_counter(endpoint, 'failure.%s' % (
            failure['failure_code'] or 'unspecified',))
        return failure


class GoStoringMiddleware(StoringMiddleware):
    @inlineCallbacks
    def setup_middleware(self):
        yield super(GoStoringMiddleware, self).setup_middleware()
        self.vumi_api = yield VumiApi.from_config_async(self.config)

    @inlineCallbacks
    def teardown_middleware(self):
        yield self.vumi_api.redis.close_manager()
        yield super(GoStoringMiddleware, self).teardown_middleware()

    def get_batch_id(self, msg):
        raise NotImplementedError("Sub-classes should implement .get_batch_id")

    @inlineCallbacks
    def handle_inbound(self, message, connector_name):
        try:
            batch_id = yield self.get_batch_id(message)
            yield self.store.add_inbound_message(message, batch_id=batch_id)
        except Exception as e:
            log.warning(e.message)
            log.warning("execption happened inbound")
        returnValue(message)

    @inlineCallbacks
    def handle_outbound(self, message, connector_name):
        batch_id = yield self.get_batch_id(message)
        yield self.store.add_outbound_message(message, batch_id=batch_id)
        returnValue(message)


class ConversationStoringMiddleware(GoStoringMiddleware):
    @inlineCallbacks
    def get_batch_id(self, msg):
        mdh = MessageMetadataHelper(self.vumi_api, msg)
        conversation = yield mdh.get_conversation()
        returnValue(conversation.batch.key)


class RouterStoringMiddleware(GoStoringMiddleware):
    @inlineCallbacks
    def get_batch_id(self, msg):
        mdh = MessageMetadataHelper(self.vumi_api, msg)
        router = yield mdh.get_router()
        returnValue(router.batch.key)
