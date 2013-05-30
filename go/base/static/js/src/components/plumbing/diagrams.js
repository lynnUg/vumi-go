// go.components.plumbing (diagrams)
// =================================
// Components for state diagrams (or 'plumbing views') in Go

(function(exports) {
  var structures = go.components.structures,
      Lookup = structures.Lookup,
      ViewCollectionGroup = structures.ViewCollectionGroup,
      ViewCollection = structures.ViewCollection;
      
  var plumbing = go.components.plumbing,
      StateView = plumbing.StateView,
      ConnectionView = plumbing.ConnectionView;

  // Arguments:
  // - diagram: The state diagram view associated to the endpoints
  var DiagramViewEndpoints = ViewCollectionGroup.extend({
    constructor: function(diagram) {
      ViewCollectionGroup.prototype.constructor.call(this);
      this.diagram = diagram;

      jsPlumb.bind(
        'connection',
        _.bind(this.delegateEvent, this, 'connection'));

      jsPlumb.bind(
        'connectionDetached',
        _.bind(this.delegateEvent, this, 'disconnection'));

      // Add the initial states' endpoints
      var states = this.diagram.states;
      states.eachItem(
        function(id, endpoint) { this.addState(id, endpoint); },
        this);

      states.on('add', this.addState, this);
      states.on('remove', this.addRemove, this);
    },

    addState: function(id, state) { this.subscribe(id, state.endpoints); },

    removeState: function(id) { return this.unsubscribe(id); },

    delegateEvent: function(type, plumbEvent) {
      var source = this.get(plumbEvent.sourceEndpoint.getUuid()),
          target = this.get(plumbEvent.targetEndpoint.getUuid());

      if (source && target) { 
        source.trigger(type, source, target, plumbEvent);
        target.trigger(type, source, target, plumbEvent);
      }
    }
  });

  // Arguments:
  // - diagram: The state diagram view associated to the endpoints
  var DiagramViewConnections = Lookup.extend({
    View: ConnectionView,

    constructor: function(diagram) {
      Lookup.prototype.constructor.call(this);

      this.diagram = diagram;

      var endpoints = this.diagram.endpoints;
      endpoints.each(this.subscribeEndpoint, this);

      endpoints.on('add', this.subscribeEndpoint, this);
      endpoints.on('remove', this.unsubscribeEndpoint, this);

      // Check which endpoint models were connected upon initialisation and add
      // the initial connections accordingly
      endpoints.each(function(e){
        var sourceModel = e.model,
            targetModel = sourceModel.get('target');

        if (targetModel) { this.add(sourceModel.id, targetModel.id); }
      }, this);
    },

    subscribeEndpoint: function(endpoint) {
      endpoint.model.on('change:target', this.onTargetChange, this);
      return this;
    },

    unsubscribeEndpoint: function(endpoint) {
      endpoint.model.off('change:target', this.onTargetChange, this);
      return this;
    },

    onTargetChange: function(sourceModel, targetModel) {
      // If the target has been set, connect.
      // Otherwise, the target has been unset, so disconnect.
      if (targetModel) { this.add(sourceModel.id, targetModel.id); }
      else { this.remove(sourceModel.id); }
    },

    add: function(sourceId, targetId) {
      var endpoints = this.diagram.endpoints,
          source = endpoints.get(sourceId),
          target = endpoints.get(targetId),
          connection = new this.View({source: source, target: target});

      return Lookup.prototype.add.call(this, sourceId, connection);
    },

    render: function() { this.each(function(c) { c.render(); }); }
  });

  // Options:
  // - diagram: The diagram view assocModeliated to the state group
  // - attr: The attr on the state view's model which holds the collection
  // of states
  // - [type]: The view type to instantiate for each new state view. Defaults
  // to StateView.
  var DiagramViewStateCollection = ViewCollection.extend({
    View: StateView,

    constructor: function(options) {
      this.diagram = options.diagram;
      this.attr = options.attr;
      this.type = options.type || this.View;

      ViewCollection
        .prototype
        .constructor
        .call(this, this.diagram.model.get(this.attr));
    },

    create: function(model) {
      return new this.type({diagram: this.diagram, model: model});
    }
  });
  
  // Arguments:
  // - diagram: The diagram view associated to the states
  var DiagramViewStates = ViewCollectionGroup.extend({
    constructor: function(diagram) {
      ViewCollectionGroup.prototype.constructor.call(this);

      this.diagram = diagram;
      this.schema = this.diagram.stateSchema;
      this.schema.forEach(this.subscribe, this);
    },

    subscribe: function(options) {
      _.extend(options, {diagram: this.diagram});
      var endpoints = new this.diagram.StateCollection(options);

      return ViewCollectionGroup
        .prototype
        .subscribe
        .call(this, options.attr, endpoints);
    }
  });

  // The main view for the state diagram. Delegates interactions between
  // the states and their endpoints.
  var DiagramView = Backbone.View.extend({
    StateCollection: DiagramViewStateCollection,

    // A list of configuration objects, where each corresponds to a group of
    // states. Override to change the state schema.
    stateSchema: [{attr: 'states'}],

    initialize: function() {
      this.states = new DiagramViewStates(this);
      this.endpoints = new DiagramViewEndpoints(this);
      this.connections = new DiagramViewConnections(this);
    },

    render: function() {
      this.states.render();
      this.connections.render();
      return this;
    }
  });

  _.extend(exports, {
    // Components intended to be used and extended
    DiagramView: DiagramView,
    DiagramViewConnections: DiagramViewConnections,
    DiagramViewStateCollection: DiagramViewStateCollection,

    // Secondary components exposed for testing purposes
    DiagramViewEndpoints: DiagramViewEndpoints,
    DiagramViewStates: DiagramViewStates
  });
})(go.components.plumbing);