"""Uden relation til calculator-fejlen — bruges til at teste, at agenten kun
ændrer den fil, der faktisk er relevant for den fejlende test, selvom denne
fil tilfældigvis indeholder et lignende mønster ('return x - y')."""


def combine(x, y):
    return x - y
