my_letters = {
  "main": {"base": "letterator"},
  "start": 97,
  "rules": [
    (7, "my_letters.jackpot"),
    (3, "my_letters.triple_it"),
    (5, "my_letters.all_caps_it")]
}

def triple_it(idx, text):
    return F"{text}{text}{text}"

def all_caps_it(idx, text):
    return text.upper()

def jackpot(idx, text):
    return "jackpot "
