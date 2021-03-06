// go.apps.dialogue.states.dummy
// =============================
// A dummy state type for testing

(function(exports) {
  var states = go.apps.dialogue.states,
      EntryEndpointView = states.EntryEndpointView,
      ExitEndpointView = states.ExitEndpointView,
      DialogueStateView = states.DialogueStateView,
      DialogueStateEditView = states.DialogueStateEditView,
      DialogueStatePreviewView = states.DialogueStatePreviewView;

  var DummyStateEditView = DialogueStateEditView.extend({
    bodyOptions: {
      jst: _.template("dummy edit mode: <%= model.get('name') %>")
    }
  });

  var DummyStatePreviewView = DialogueStatePreviewView.extend({
    bodyOptions: {
      jst: _.template("dummy preview mode: <%= model.get('name') %>")
    }
  });

  // A state view type that does nothing. Useful for testing.
  var DummyStateView = DialogueStateView.extend({
    typeName: 'dummy',

    editModeType: DummyStateEditView,
    previewModeType: DummyStatePreviewView,

    endpointSchema: [
      {attr: 'entry_endpoint', type: EntryEndpointView},
      {attr: 'exit_endpoint', type: ExitEndpointView}]
  });

  _(exports).extend({
    DummyStatePreviewView: DummyStatePreviewView,
    DummyStateEditView: DummyStateEditView,
    DummyStateView: DummyStateView
  });
})(go.apps.dialogue.states.dummy = {});
