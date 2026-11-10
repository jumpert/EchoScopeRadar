import re
import unicodedata
from functools import lru_cache

POSITIVE = frozenset(
    "excelente excelentes gracias recomendable recomendado recomendada genial bien bueno buena "
    "buenos buenas perfecto perfecta exitoso exitosamente impecable felicidades felicitaciones "
    "agradezco encanto encantado encantada contento contenta satisfecho satisfecha maravilloso".split()
)
NEGATIVE = frozenset(
    "malo mala malos malas pesimo pesima horrible terrible demora demoras decepcion decepcionante "
    "lamentable inaceptable estafa fraude desastroso desastre deficiente indignante vergonzoso "
    "insatisfecho insatisfecha retraso retrasos problema problemas".split()
)
NEGATION = {"no", "nunca", "jamas", "tampoco"}
BOUNDARY = {"pero", "aunque", "sino", "ni", ".", "!", "?", ",", ";", ":"}


def folded(text):
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text.casefold())
        if not unicodedata.combining(char)
    )


@lru_cache(maxsize=512)
def _classify(text):
    signs = set()
    recent = []
    for word in re.findall(r"[^\W\d_]+|[.!?,;:]", folded(text)):
        if word in BOUNDARY:
            recent.clear()
            continue
        if word in POSITIVE or word in NEGATIVE:
            signs.add((word in POSITIVE) != any(term in NEGATION for term in recent))
            recent.clear()
        else:
            recent = [*recent[-1:], word]
    if len(signs) == 2:
        return "mixed"
    if signs:
        return "positive" if True in signs else "negative"
    return "neutral"


def message_tone(text):
    return _classify(text[:4000])
