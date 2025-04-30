def __main__(dat, name=None, *, emphasis=False, lucky_number=None):
    spec = dat.get_spec()
    name = spec.get("name") if name is None else name
    emphasis = spec.get("emphasis") or emphasis
    lucky_number = spec.get("lucky_number") or lucky_number
    line = F"   {name}, My lucky number is {lucky_number}"
    print(F"{line.upper()}!" if emphasis else line)
    return lucky_number
