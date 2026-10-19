"""Stemmer italiano: l'algoritmo Snowball (https://snowballstem.org/algorithms/italian/stemmer.html) in Python puro.

Serve a far incontrare le forme derivate di una parola, che togliere le vocali finali non riesce a unire:

    rilasciare  rilascio  rilasciato      → rilasc        collaudare  collaudo  collaudato → collaud
    approva     approvazione  approvare   → approv        caricamento  caricamenti  caricare → caric
    chiave  chiavi                        → chiav         lunghe  lungo                  → lung

Adattamenti rispetto a Snowball, che lavora sul testo con gli accenti:
  - `stem()` riceve parole già passate da build_graph.norm (minuscole, a-z0-9, SENZA accenti). Gli accenti che
    Snowball cita nei suffissi (-ità, -istà, -erà, -irò ...) qui sono già caduti: «ità» diventa «ita», e basta (è
    già nell'elenco del passo 1, con la stessa regola R2). I suffissi verbali solo accentati (erà, erò, irà, irò)
    NON si aggiungono senza accento: «era», «ero» sono vocali finali comuni («numero» → «num» ma «numeri» →
    «numer») e le toglie comunque il passo 3a quando serve.
  - le vocali sono a e i o u; le regioni RV, R1, R2 si calcolano come in Snowball;
  - il passo 2 (suffissi verbali) lascia almeno MIN_RADICE_VERBO lettere: lo Snowball originale riduce «chiavi» a
    «chi» (-avi come imperfetto) ma «chiave» a «chiav»; così chiave e chiavi si incontrano;
  - una parola con cifre (acme0, db2, 2026) non si tocca: è un identificatore, non una parola italiana;
  - una parola di meno di 3 lettere non si tocca.
Il risultato non è una parola: è una chiave di confronto. Due parole con la stessa radice «parlano della stessa cosa»
(con qualche falso amico, come in ogni stemmer: «caricare» e «carico» sì, ma anche «carica» come ruolo).
"""

from functools import lru_cache

VOCALI = "aeiou"
MIN_RADICE_VERBO = 4  # lunghezza minima di ciò che resta dopo un suffisso verbale (passo 2)

# Passo 0: pronomi attaccati (dammelo, caricarlo, facendola), solo dopo gerundio o infinito
PRONOMI = sorted("ci gli la le li lo mi ne si ti vi sene gliela gliele glieli glielo gliene mela mele meli melo mene "
                 "tela tele teli telo tene cela cele celi celo cene vela vele veli velo vene".split(), key=len, reverse=True)

# Passo 1: suffissi derivativi → (azione, regione). Tutti insieme: vince il suffisso più lungo.
_CANCELLA_R2 = ("anza anze ico ici ica ice iche ichi ismo ismi abile abili ibile ibili ista iste isti oso osi osa ose "
                "mente atrice atrici ante anti").split()
PASSO1 = {s: "r2" for s in _CANCELLA_R2}
PASSO1.update({s: "r2+ic" for s in "azione azioni atore atori".split()})
PASSO1.update({s: "log" for s in "logia logie".split()})
PASSO1.update({s: "u" for s in "uzione uzioni usione usioni".split()})
PASSO1.update({s: "ente" for s in "enza enze".split()})
PASSO1.update({s: "rv" for s in "amento amenti imento imenti".split()})
PASSO1["amente"] = "amente"
PASSO1["ita"] = "ita"
PASSO1.update({s: "ivo" for s in "ivo ivi iva ive".split()})

# Passo 2: suffissi verbali, in RV (solo se il passo 1 non ha tolto nulla)
VERBALI = sorted((
    "ammo ando ano are arono asse assero assi assimo ata ate ati ato ava avamo avano avate avi avo emmo enda ende endi "
    "endo ere erebbe erebbero erei eremmo eremo ereste eresti erete erono essero ete eva evamo evano evate evi evo "
    "iamo immo ire irebbe irebbero irei iremmo iremo ireste iresti irete irono isca iscano isce isci isco iscono "
    "issero ita ite iti ito iva ivamo ivano ivate ivi ivo ono uta ute uti uto ar ir").split(), key=len, reverse=True)


def _maiuscole_semivocali(p):
    """Snowball: «u» dopo «q» e «u»/«i» fra due vocali sono consonanti (qUi, aIuto): si segnano in maiuscolo."""
    out = list(p)
    for i, c in enumerate(p):
        if c == "u" and i > 0 and p[i - 1] == "q":
            out[i] = "U"
        elif c in "iu" and 0 < i < len(p) - 1 and p[i - 1] in VOCALI and p[i + 1] in VOCALI:
            out[i] = c.upper()
    return "".join(out)


def _regioni(p):
    """(inizio di RV, di R1, di R2) in p."""
    n = len(p)
    v = lambda i: p[i] in VOCALI

    def dopo_non_vocale(da):  # posizione dopo la prima consonante che segue una vocale, a partire da `da`
        for i in range(max(da, 1), n):
            if not v(i) and v(i - 1):
                return i + 1
        return n

    r1 = dopo_non_vocale(0)
    r2 = dopo_non_vocale(r1)
    rv = n
    if n >= 2:
        if not v(1):  # seconda lettera consonante: dopo la vocale successiva
            rv = next((i + 1 for i in range(2, n) if v(i)), n)
        elif v(0) and v(1):  # prime due vocali: dopo la consonante successiva
            rv = next((i + 1 for i in range(2, n) if not v(i)), n)
        else:  # consonante-vocale: dopo la terza lettera
            rv = 3 if n >= 3 else n
    return rv, r1, r2


def _suffisso(p, elenco):
    return next((s for s in elenco if p.endswith(s)), None)


@lru_cache(maxsize=65536)  # per_titolo riduce i titoli di tutte le pagine a ogni domanda: le stesse parole tornano
def stem(parola):
    """Radice di una parola italiana già normalizzata (norm: minuscole, a-z0-9, senza accenti)."""
    if len(parola) < 3 or any(c.isdigit() for c in parola) or not parola.isalpha():
        return parola
    p = _maiuscole_semivocali(parola)

    # Passo 0: «caricarlo» → caricare, «facendola» → facendo
    rv = _regioni(p)[0]
    s = _suffisso(p, PRONOMI)
    if s:
        resto = p[:-len(s)]
        if resto.endswith(("ando", "endo")) and len(resto) - 4 >= rv:
            p = resto
        elif resto.endswith(("ar", "er", "ir")) and len(resto) - 2 >= rv:
            p = resto[:-2] + "e"

    # Passo 1: suffissi derivativi
    rv, r1, r2 = _regioni(p)
    tolto = False
    s = _suffisso(p, sorted(PASSO1, key=len, reverse=True))
    if s:
        base = p[:-len(s)]
        i = len(base)  # inizio del suffisso: sta nella regione R se i >= R
        azione = PASSO1[s]

        def in_r2_prima(sfx):  # base finisce per sfx, che sta in R2
            return base.endswith(sfx) and len(base) - len(sfx) >= r2

        if azione == "r2" and i >= r2:
            p, tolto = base, True
        elif azione == "r2+ic" and i >= r2:
            p, tolto = base, True
            if p.endswith("ic") and len(p) - 2 >= r2:
                p = p[:-2]
        elif azione == "log" and i >= r2:
            p, tolto = base + "log", True
        elif azione == "u" and i >= r2:
            p, tolto = base + "u", True
        elif azione == "ente" and i >= r2:
            p, tolto = base + "ente", True
        elif azione == "rv" and i >= rv:
            p, tolto = base, True
        elif azione == "amente" and i >= r1:
            p, tolto = base, True
            if base.endswith("iv") and len(base) - 2 >= r2:
                p = base[:-2]
                if p.endswith("at") and len(p) - 2 >= r2:
                    p = p[:-2]
            else:
                for sfx in ("os", "ic", "abil"):
                    if in_r2_prima(sfx):
                        p = base[:-len(sfx)]
                        break
        elif azione == "ita" and i >= r2:
            p, tolto = base, True
            for sfx in ("abil", "ic", "iv"):
                if in_r2_prima(sfx):
                    p = base[:-len(sfx)]
                    break
        elif azione == "ivo" and i >= r2:
            p, tolto = base, True
            if p.endswith("at") and len(p) - 2 >= r2:
                p = p[:-2]
                if p.endswith("ic") and len(p) - 2 >= r2:
                    p = p[:-2]

    # Passo 2: suffissi verbali (solo se il passo 1 non ha tolto nulla)
    if not tolto:
        rv = _regioni(p)[0]
        s = _suffisso(p, VERBALI)
        # almeno 4 lettere di radice: senza, «chiavi» (avi) diventava «chi» e non incontrava più «chiave» (chiav)
        if s and len(p) - len(s) >= rv and len(p) - len(s) >= MIN_RADICE_VERBO:
            p = p[:-len(s)]

    # Passo 3a: vocale finale (e la «i» prima di lei: rilascio → rilasc); 3b: ch/gh finali → c/g (lunghe → lung)
    rv = _regioni(p)[0]
    if p and p[-1] in VOCALI and len(p) - 1 >= rv:
        p = p[:-1]
        if p.endswith("i") and len(p) - 1 >= rv:
            p = p[:-1]
    if p.endswith(("ch", "gh")) and len(p) - 2 >= rv:
        p = p[:-1]
    return p.lower()
