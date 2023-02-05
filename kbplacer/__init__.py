import sys

if sys.argv[0] != "-m":
    from .kbplacer_plugin_action import KbplacerPluginAction
    KbplacerPluginAction().register()
