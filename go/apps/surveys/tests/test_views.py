from django.test.client import Client
from django.core.urlresolvers import reverse

from go.vumitools.tests.utils import VumiApiCommand
from go.apps.tests.base import DjangoGoApplicationTestCase
from go.apps.surveys.views import get_poll_config


TEST_GROUP_NAME = u"Test Group"
TEST_CONTACT_NAME = u"Name"
TEST_CONTACT_SURNAME = u"Surname"
TEST_SUBJECT = u"Test Conversation"


class SurveyTestCase(DjangoGoApplicationTestCase):

    fixtures = ['test_user']

    def setUp(self):
        super(SurveyTestCase, self).setUp()
        self.client = Client()
        self.client.login(username='username', password='password')

        self.patch_settings(VXPOLLS_REDIS_CONFIG={'FAKE_REDIS': 'sure'})

        self.setup_riak_fixtures()

    def get_wrapped_conv(self):
        conv = self.conv_store.get_conversation_by_key(self.conv_key)
        return self.user_api.wrap_conversation(conv)

    def run_new_conversation(self, selected_option, pool, tag):
        # render the form
        self.assertEqual(len(self.conv_store.list_conversations()), 1)
        response = self.client.get(reverse('survey:new'))
        self.assertEqual(response.status_code, 200)
        # post the form
        response = self.client.post(reverse('survey:new'), {
            'subject': 'the subject',
            'message': 'the message',
            'delivery_class': 'sms',
            'delivery_tag_pool': selected_option,
        })
        self.assertEqual(len(self.conv_store.list_conversations()), 2)
        conversation = max(self.conv_store.list_conversations(),
                           key=lambda c: c.created_at)
        self.assertEqual(conversation.delivery_class, 'sms')
        self.assertEqual(conversation.delivery_tag_pool, pool)
        self.assertEqual(conversation.delivery_tag, tag)
        self.assertRedirects(response, reverse('survey:contents', kwargs={
            'conversation_key': conversation.key,
        }))

    def test_new_conversation(self):
        """test the creation of a new conversation"""
        self.run_new_conversation('longcode:', 'longcode', None)

    def test_new_conversation_with_user_selected_tags(self):
        tp_meta = self.api.tpm.get_metadata('longcode')
        tp_meta['user_selects_tag'] = True
        self.api.tpm.set_metadata('longcode', tp_meta)
        self.run_new_conversation('longcode:default10001', 'longcode',
                                  'default10001')

    def test_end(self):
        """
        Test ending the conversation
        """
        conversation = self.get_wrapped_conv()
        self.assertFalse(conversation.ended())
        response = self.client.post(reverse('survey:end', kwargs={
            'conversation_key': conversation.key}), follow=True)
        self.assertRedirects(response, reverse('survey:show', kwargs={
            'conversation_key': conversation.key}))
        [msg] = response.context['messages']
        self.assertEqual(str(msg), "Survey ended")
        conversation = self.get_wrapped_conv()
        self.assertTrue(conversation.ended())

    def test_client_or_server_init_distinction(self):
        """A survey should not ask for recipients if the transport
        used only supports client initiated sessions (i.e. USSD)"""

        self.api.set_pool_metadata("pool1", {
            "delivery_class": "sms",
            "server_initiated": True,
            })

        self.api.set_pool_metadata("pool2", {
            "delivery_class": "ussd",
            "client_initiated": True,
            })

        def get_people_page(tag_pool):
            conversation = self.get_wrapped_conv()
            conversation.c.delivery_tag_pool = tag_pool
            conversation.save()
            return self.client.get(reverse('survey:people', kwargs={
                'conversation_key': conversation.key,
                }))

        self.assertContains(get_people_page(u'pool1'), 'Survey Recipients')
        self.assertNotContains(get_people_page(u'pool2'), 'Survey Recipients')

    def test_group_selection(self):
        """Select an existing group and use that as the group for the
        conversation"""
        conversation = self.get_wrapped_conv()
        self.assertFalse(conversation.is_client_initiated())
        response = self.client.post(reverse('survey:people',
            kwargs={'conversation_key': conversation.key}), {'groups': [
                    grp.key for grp in self.contact_store.list_groups()]})
        self.assertRedirects(response, reverse('survey:start', kwargs={
            'conversation_key': conversation.key}))

    def test_start(self):
        """
        Test the start conversation view
        """
        consumer = self.get_cmd_consumer()

        response = self.client.post(reverse('survey:start', kwargs={
            'conversation_key': self.conv_key}))
        self.assertRedirects(response, reverse('survey:show', kwargs={
            'conversation_key': self.conv_key}))

        conversation = self.get_wrapped_conv()
        [cmd] = self.fetch_cmds(consumer)
        [batch] = conversation.get_batches()
        [tag] = list(batch.tags)
        [contact] = self.get_contacts_for_conversation(conversation)
        msg_options = {
            "transport_type": "sms",
            "from_addr": "default10001",
            "helper_metadata": {
                "tag": {"tag": list(tag)},
                "go": {"user_account": conversation.user_account.key},
                },
            }

        self.assertEqual(cmd, VumiApiCommand.command(
            '%s_application' % (conversation.conversation_type,), 'start',
            conversation_type=conversation.conversation_type,
            conversation_key=conversation.key,
            is_client_initiated=conversation.is_client_initiated(),
            batch_id=batch.key,
            msg_options=msg_options
            ))

    def test_send_fails(self):
        """
        Test failure to send messages
        """
        self.acquire_all_longcode_tags()
        consumer = self.get_cmd_consumer()
        response = self.client.post(reverse('survey:start', kwargs={
            'conversation_key': self.conv_key}), follow=True)
        self.assertRedirects(response, reverse('survey:start', kwargs={
            'conversation_key': self.conv_key}))
        [] = self.fetch_cmds(consumer)
        [msg] = response.context['messages']
        self.assertEqual(str(msg), "No spare messaging tags.")

    def test_show(self):
        """
        Test showing the conversation
        """
        response = self.client.get(reverse('survey:show', kwargs={
            'conversation_key': self.conv_key}))
        conversation = response.context[0].get('conversation')
        self.assertEqual(conversation.subject, 'Test Conversation')

    def test_edit(self):
        survey_url = reverse('survey:edit', kwargs={
            'conversation_key': self.conv_key,
            })
        show_url = reverse('survey:show', kwargs={
            'conversation_key': self.conv_key,
            })
        response = self.client.post(survey_url, {
            'questions-TOTAL_FORMS': 1,
            'questions-INITIAL_FORMS': 0,
            'questions-MAX_NUM_FORMS': '',
            'questions-0-copy': 'What is your favorite music?',
            'questions-0-label': 'favorite music',
            'questions-0-valid_responses': 'rock, jazz, techno',
            'completed_response-TOTAL_FORMS': 0,
            'completed_response-INITIAL_FORMS': 0,
            'completed_response-MAX_NUM_FORMS': '',
        })
        self.assertRedirects(response, show_url)
        poll_id = 'poll-%s' % (self.conv_key,)
        pm, config = get_poll_config(poll_id)
        [question] = config['questions']
        self.assertEqual(question['copy'], 'What is your favorite music?')
        self.assertEqual(question['valid_responses'], [
            'rock', 'jazz', 'techno'])
        self.assertEqual(question['label'], 'favorite music')

    def test_edit_continue_editing(self):
        survey_url = reverse('survey:edit', kwargs={
            'conversation_key': self.conv_key,
        })
        response = self.client.post(survey_url, {
            'questions-TOTAL_FORMS': 1,
            'questions-INITIAL_FORMS': 0,
            'questions-MAX_NUM_FORMS': '',
            'questions-0-copy': 'What is your favorite music?',
            'questions-0-label': 'favorite music',
            'questions-0-valid_responses': 'rock, jazz, techno',
            'completed_response-TOTAL_FORMS': 0,
            'completed_response-INITIAL_FORMS': 0,
            'completed_response-MAX_NUM_FORMS': '',
            '_save_contents': 1
        })
        self.assertRedirects(response, survey_url)
        poll_id = 'poll-%s' % (self.conv_key,)
        pm, config = get_poll_config(poll_id)
        [question] = config['questions']
        self.assertEqual(question['copy'], 'What is your favorite music?')
        self.assertEqual(question['valid_responses'], [
            'rock', 'jazz', 'techno'])
        self.assertEqual(question['label'], 'favorite music')
