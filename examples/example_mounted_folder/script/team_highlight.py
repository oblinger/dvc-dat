"""
Team highlight money is the F1 where correctness is tied to correctly assessing shot 
attempt and make-miss, without consideration of player-ID nor number of points scored.

This is the Jason approved metric associated with our team highlights product, and we
have agreed 80% is the minimum approved threshold required for product ship.
"""

from dvc_dat import do, Dat


def reg_quick_test():
    run_result = Dat.load("reg1_latest")   # Reg1 pickle for a special 5-min snipit
    assert do("team_highlight_money", run_result) > .65


reg_full_test = "std_full1"  # indicates full regression testing is part of 'std_full1'


def money(_run_result: Dat) -> float:
    return -1  # implementation goes here

    
def precision(_run_result: Dat) -> float:
    return -1  # implementation goes here
