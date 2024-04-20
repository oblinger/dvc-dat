
from ml_dat import do

my_data = [111, 222, 333]

message = "Hello from my_data!"


def my_function():
    print("Hello from my_function!")
    return 123


a_tree = {
    "a": do.load("my_yaml_data"),
    "b": 2,
    "c": {
        "d": my_function,
        "e": 4,
        "f": {
            "g": 5,
            "h": 6,
            "i": 7
        }
    }
}

