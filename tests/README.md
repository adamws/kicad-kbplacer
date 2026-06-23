# Tests

To run tests with local changes, run from project root directory:

```
docker run --rm -v $(pwd):$(pwd) -w $(pwd) admwscki/kicad-kbplacer-primary:10.0.4-noble \
  /bin/bash -c "pip3 install --no-cache-dir hatch && hatch run test:test"
```

or use [just](https://github.com/casey/just) `test` recipe.
