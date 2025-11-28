from dvc_dat import do

__main__ = [111, 222, 333]
message = "Hello from my_data!"
def my_function(): # noqa
    print("Hello from my_function!")
    return 123
a_tree = {  # noqa
    "a": do.load("my_yaml_data"),
    "b": 2,
    "c": {
        "d": my_function,
        "e": 4,
        "f": {
            "g": 5,
            "h": 6,
            "i": 7}}}
