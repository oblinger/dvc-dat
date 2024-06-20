def __main__():
    print("   Hello World again!")


def hella():
    print("   HELLA Hello World!!!  Hello world again.")


def salutation(name="Hello", *, emphasis=False, lucky_number=999):
    line = F"{name}, My lucky number is {lucky_number}"
    print(F"   {line.upper()}!" if emphasis else line)
    return lucky_number, line
