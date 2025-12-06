# Tests

To run tests with local changes, run from project root directory:

```
docker build -t kicad-kbplacer-tests:local -f docker/tests.Dockerfile .
docker run --rm -v $(pwd):$(pwd) -w $(pwd) kicad-kbplacer-tests:local /bin/bash -c "hatch run test:test"
```

