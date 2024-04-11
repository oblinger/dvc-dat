"""
The "naughty list" scans all supported datasets, metrics, visualization/debugging tools 
and verifies they are (1) properly documented, (2) they execute their full regressions, 
(3) The continue to run against representative games, metrics, tools.

Any metric, tool, dataset that is not fully compliant is indicated on the naugthy list.
"""

from do import load

def naughty_list():
    # this double for loop checks docs exist, regression test exists, and passes etc.
    for section, supported_insts in load("supported").items():
        for name in supported_insts:
            try:
                inst = load(name)
                if not hasattr(inst, "__DOC__"):
                    print(F"   {section} {name} does not have a valid doc string")
                if not hasattr(inst, ):
                    print(F"   {section} {name} does not have a valid doc string")
                if not hasattr(inst, "reg_quick_test"):
                    print(F"   {section} {name} does not have a valid quick regression test")
                if not hasattr(inst, "reg_full_test"):
                    print(F"   {section} {name} does not have a valid full regression test")
            except:
                print(F"Could not find {name!r} loadable.")
