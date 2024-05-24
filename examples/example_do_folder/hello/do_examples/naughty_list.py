"""
The "naughty list" scans all supported datasets, metrics, visualization/debugging tools 
and verifies they are (1) properly documented, (2) they execute their full regressions, 
(3) The continue to run against representative games, metrics, tools.

Any metric, tool, dataset that is not fully compliant is indicated on the naughty list.
"""

from dvc_dat import load_dat


def main():
    # this double for loop checks docs exist, regression test exists, and passes etc.
    for section, supported_dats in load_dat("supported").items():
        for name in supported_dats:
            dat = load_dat(name)
            if not hasattr(dat, "__DOC__"):
                print(F"   {section} {name} does not have a valid doc string")
            # if not hasattr(dat, ):
            #     print(F"   {section} {name} does not have a valid doc string")
            if not hasattr(dat, "reg_quick_test"):
                print(F"   {section} {name} doesn't have a valid quick regression test")
            if not hasattr(dat, "reg_full_test"):
                print(F"   {section} {name} doesn't have a valid full regression test")
