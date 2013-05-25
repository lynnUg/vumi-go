describe("go.utils", function() {
  describe(".merge", function() {
    var merge = go.utils.merge;

    it("should merge objects together into a single object", function() {
      assert.deepEqual(
        merge({a: 1}, {b: 2, c: 3}, {d: 4}),
        {a: 1, b: 2, c: 3, d: 4});

      assert.deepEqual(
        merge({a: 1}, {}, {d: 4}),
        {a: 1, d: 4});

      assert.deepEqual(
        merge({a: 1}, {b: 2}, {a: 'one'}),
        {a: 'one', b: 2});
    });

    it("should not modify any of the passed in objects", function() {
      var a = {a: 1},
          b = {b: 2},
          c = {c: 3};

      merge(a, b, c);

      assert.deepEqual(a, {a: 1});
      assert.deepEqual(b, {b: 2});
      assert.deepEqual(c, {c: 3});
    });
  });

  describe(".pairId", function() {
    var pairId = go.utils.pairId;

    it("should create a unique id from a pair of ids", function() {
      assert.equal(pairId(1, 2), '1-2');
      assert.equal(pairId(2, 1), '1-2');

      assert.equal(pairId('a', 'b'), 'a-b');
      assert.equal(pairId('b', 'a'), 'a-b');
    });
  });
});
