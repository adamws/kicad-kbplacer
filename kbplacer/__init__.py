import sys

if sys.argv[0] != "-m" and not sys.argv[0].endswith("pytest"):
    from .kbplacer_plugin_action import KbplacerPluginAction

    KbplacerPluginAction().register()
