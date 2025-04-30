__main__ = {
  "dat": {"base": "letterator"},
  "start": 97,
  "rules": [
    (7, "my_letters.jackpot"),
    (3, "my_letters.triple_it"),
    (5, "my_letters.all_caps_it")]
}


def triple_it(_idx, text):
    return F"{text}{text}{text}"


def all_caps_it(_idx, text):
    return text.upper()


def jackpot(_idx, _text):
    return "jackpot "
