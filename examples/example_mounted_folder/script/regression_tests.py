"""
The "naughty list" scans all supported datasets, metrics, visualization/debugging tools 
and verifies they are (1) properly documented, (2) they execute their full regressions, 
(3) The continue to run against representative games, metrics, tools.

Any metric, tool, dataset that is not fully compliant is indicated on the naughty list.
"""

from dvc_dat import do


def __main__():
    # this double for loop checks docs exist, regression test exists, and passes etc.
    for section, supported_dats in do.load("supported").items():
        for name in supported_dats:
            dat = do.load(name, default=None)
            if dat is None:
                print(F"   Error in {section} {name!r} does not exist")
                continue
            if not hasattr(dat, "__DOC__"):
                print(F"   Error in {section} {name!r} doesn't have a valid doc string")
            if not hasattr(dat, "reg_quick_test"):
                print(F"   Error in {section} {name!r} " +
                      "doesn't have a valid quick regression test")
            if not hasattr(dat, "reg_full_test"):
                print(F"   Error in {section} {name!r} " +
                      "doesn't have a valid full regression test")
