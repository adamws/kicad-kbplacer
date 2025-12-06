import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

with open("pyproject.toml", "rb") as f:
    cfg = tomllib.load(f)

for dep in cfg["tool"]["hatch"]["envs"]["test"]["dependencies"]:
    print(dep)

for dep in cfg["project"]["optional-dependencies"]["schematic"]:
    print(dep)
