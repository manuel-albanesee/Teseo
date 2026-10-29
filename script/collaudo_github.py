"""Collaudo con un repository GitHub reale: due persone (Alice e Bob), due cloni, gli scenari del flusso collaborativo.

Prepara tutto in una cartella nuova, usa gli stessi comandi che usano le persone (`installa.py --collabora`, `teseo_git.py pre|post|
avvisi|riprendi`, la dashboard in locale) e stampa un rapporto JSON. Non legge né salva credenziali: l'autenticazione è quella di Git
nella HOME di ciascuna persona (credential helper, gh, chiavi SSH).

Uso:
  python script/collaudo_github.py --url https://github.com/<org>/<repo>.git --branch collaudo-dati --lavoro <cartella-nuova> \\
         --home-a <HOME di Alice> --home-b <HOME di Bob> [--tieni]

Le HOME contengono almeno un `.gitconfig` con user.name e user.email (Alice e Bob devono essere persone diverse) e la
configurazione di autenticazione. Il branch deve essere nuovo: a fine collaudo si cancella (salvo --tieni). Il repository di
prova non si tocca altrimenti; cancellarlo spetta a chi lo ha creato.
"""
import argparse
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

RADICE = Path(__file__).resolve().parents[1]
NL = chr(10)


class Collaudo:
    def __init__(self, url, branch, lavoro, home_a, home_b):
        self.url, self.branch, self.lavoro = url, branch, Path(lavoro).resolve()
        self.home = {"A": str(Path(home_a).resolve()), "B": str(Path(home_b).resolve())}
        self.vault = {}
        self.risultati = []

    # -- esecuzione -----------------------------------------------------------------------------
    def esegui(self, chi, args, cwd=None, extra_env=None, timeout=900):
        env = {**os.environ, "HOME": self.home[chi], "USERPROFILE": self.home[chi], "PYTHONIOENCODING": "utf-8", **(extra_env or {})}
        done = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=timeout, check=False)
        return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")

    def git(self, chi, cwd, *args):
        code, out, err = self.esegui(chi, ["git", "-c", "core.autocrlf=false", *args], cwd=cwd)
        if code:
            raise RuntimeError("git %s: %s" % (" ".join(args[:3]), err.strip()[:300]))
        return out.strip()

    def installa(self, chi, nome, *extra):
        cartella = self.lavoro / nome
        code, out, err = self.esegui(chi, [sys.executable, str(RADICE / "installa.py"), str(cartella), "--client", "claude", "--skill", "no",
                                           "--collabora", self.url, "--branch", self.branch, "--si", *extra])
        self.vault[nome] = cartella
        return code, (out + err)[-400:]

    def tg(self, chi, nome, comando, *extra, extra_env=None):
        """teseo_git.py dal vault: (codice, JSON se c'è)."""
        code, out, err = self.esegui(chi, [sys.executable, str(self.vault[nome] / ".graph/teseo_git.py"), comando, "--vault",
                                           str(self.vault[nome]), *extra], extra_env=extra_env)
        try:
            dati = json.loads(out)
        except ValueError:
            dati = {"stdout": out[-300:], "stderr": err[-300:]}
        return code, dati

    def remoto(self, percorso):
        """Contenuto di un file sul branch remoto (clone superficiale di sola lettura)."""
        with tempfile.TemporaryDirectory(prefix="collaudo-lettore-") as cartella:
            self.git("A", cartella, "clone", "-q", "--depth", "30", "--branch", self.branch, self.url, "r")
            radice = Path(cartella) / "r"
            return self.git("A", radice, "show", "HEAD:" + percorso) if percorso else self.git("A", radice, "log", "-5", "--format=%an|%B|--fine--")

    def testa_remota(self):
        code, out, err = self.esegui("A", ["git", "ls-remote", self.url, "refs/heads/" + self.branch])
        return out.split()[0] if out.strip() else None

    @staticmethod
    def appendi(vault, relativo, testo):
        with (vault / relativo).open("a", encoding="utf-8", newline=NL) as flusso:
            flusso.write(testo)

    def nota(self, nome_vault, nome, testo):
        (self.vault[nome_vault] / "wiki" / (nome + ".md")).write_text("---\ntipo: concetto\n---\n\n# %s\n\n%s\n" % (nome, testo), encoding="utf-8", newline=NL)

    # -- scenari --------------------------------------------------------------------------------
    def scenario(self, nome, funzione):
        inizio = time.monotonic()
        try:
            dettaglio = funzione()
            esito = True
        except AssertionError as errore:
            dettaglio, esito = "ATTESO: " + str(errore), False
        except Exception as errore:  # un guasto dello scenario non ferma gli altri
            dettaglio, esito = "%s: %s" % (type(errore).__name__, str(errore)[:400]), False
        self.risultati.append({"scenario": nome, "ok": esito, "dettaglio": dettaglio if dettaglio is not None else "", "secondi": round(time.monotonic() - inizio, 1)})
        print(("OK   " if esito else "FALLITO ") + nome, flush=True)

    def s01_installazione(self):
        self.lavoro.mkdir(parents=True)
        code, tail = self.installa("A", "A", "--esempio")
        assert code == 0, "installa.py uscito con %s: %s" % (code, tail)
        assert self.testa_remota(), "il branch non esiste sul remoto"
        elenco = self.git("A", self.vault["A"], "ls-tree", "-r", "--name-only", "HEAD").splitlines()
        assert ".teseo/project.json" in elenco and any(p.startswith("wiki/") for p in elenco), "mancano manifest o note"
        assert not any(p.startswith((".graph/", ".claude/", ".obsidian/")) for p in elenco), "file locali nel repository condiviso"
        code, dati = self.tg("A", "A", "stato")
        assert dati.get("state") == "enabled", "autosync non attivo: %s" % dati
        return "%d file condivisi, autosync attivo" % len(elenco)

    def s02_clone_di_bob(self):
        code, tail = self.installa("B", "B")
        assert code == 0, "installa.py di Bob uscito con %s: %s" % (code, tail)
        assert self.git("B", self.vault["B"], "rev-parse", "HEAD") == self.testa_remota(), "Bob non è allineato al remoto"
        assert (self.vault["B"] / ".graph/teseo_git.py").is_file(), "kit non installato nel clone di Bob"
        code, dati = self.tg("B", "B", "stato")
        assert dati.get("state") == "enabled", "autosync di Bob non attivo: %s" % dati
        return "Bob allineato e con autosync attivo"

    def s03_post_attribuito(self):
        code, dati = self.tg("A", "A", "pre", "--skill", "ingest", "--agente", "claude")
        assert code == 0 and dati.get("state") == "ready", "pre: %s" % dati
        self.appendi(self.vault["A"], "wiki/Gestionale.md", NL + "Nota di Alice sul collaudo." + NL)
        code, dati = self.tg("A", "A", "post", "--skill", "ingest", "--agente", "claude")
        assert code == 0 and dati.get("state") == "published", "post: %s" % dati
        registro = self.remoto(None)
        assert registro.startswith("Alice|") and "Teseo-Skill: ingest" in registro and "Teseo-Agent: claude" in registro, "attribuzione: %s" % registro[:200]
        assert "Nota di Alice sul collaudo." in self.remoto("wiki/Gestionale.md"), "la nota non è sul remoto"
        return "pubblicato da Alice con i trailer Teseo-Skill/Agent"

    def s04_avviso_e_pull(self):
        code, dati = self.tg("B", "B", "avvisi")
        assert code == 0 and dati.get("state") == "behind" and dati.get("count") == 1, "avvisi: %s" % dati
        antes = self.git("B", self.vault["B"], "rev-parse", "HEAD")
        assert self.git("B", self.vault["B"], "rev-parse", "HEAD") == antes
        code, dati = self.tg("B", "B", "pre", "--skill", "lint", "--agente", "codex")
        assert code == 0 and dati.get("received") == 1, "pre: %s" % dati
        assert "Nota di Alice sul collaudo." in (self.vault["B"] / "wiki/Gestionale.md").read_text(encoding="utf-8"), "contenuto non ricevuto"
        code, dati = self.tg("B", "B", "avvisi")
        assert dati.get("state") == "current", "dopo il pull: %s" % dati
        code, dati = self.tg("B", "B", "post", "--skill", "lint", "--agente", "codex")
        assert dati.get("state") in ("noop", "published"), "chiusura sessione: %s" % dati
        return "avviso 'behind', pull di 1 commit, poi 'current'"

    def s05_integrazione_senza_decisione(self):
        for chi, nome in (("A", "A"), ("B", "B")):
            code, dati = self.tg(chi, nome, "pre", "--skill", "ingest", "--agente", "claude" if chi == "A" else "codex")
            assert code == 0, "pre di %s: %s" % (chi, dati)
        self.nota("A", "Nota di Alice", "Testo di Alice.")
        self.appendi(self.vault["A"], "log.md", NL + "## [2026-10-29] ingest | voce di alice" + NL)
        self.nota("B", "Nota di Bob", "Testo di Bob.")
        self.appendi(self.vault["B"], "log.md", NL + "## [2026-10-29] ingest | voce di bob" + NL)
        code, dati = self.tg("A", "A", "post", "--skill", "ingest", "--agente", "claude")
        assert dati.get("state") == "published", "post di Alice: %s" % dati
        code, dati = self.tg("B", "B", "post", "--skill", "ingest", "--agente", "codex")
        assert code == 0 and dati.get("state") == "published", "post di Bob (integrazione): %s" % dati
        log = self.remoto("log.md")
        assert "voce di alice" in log and "voce di bob" in log and "<<<<<<<" not in log, "log non unito"
        assert "Testo di Alice." in self.remoto("wiki/Nota di Alice.md") and "Testo di Bob." in self.remoto("wiki/Nota di Bob.md")
        return "note distinte e log concorrenti uniti senza decisione"

    def s06_autori_e_dashboard(self):
        code, dati = self.tg("A", "A", "pre", "--skill", "lacune", "--agente", "umano")
        assert code == 0 and dati.get("received", 0) >= 1, "pre di Alice dopo Bob: %s" % dati
        self.tg("A", "A", "post", "--skill", "lacune", "--agente", "umano")
        server = subprocess.Popen([sys.executable, str(self.vault["A"] / ".graph/teseo_dashboard.py"), "--vault", str(self.vault["A"]), "--no-browser"],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, "HOME": self.home["A"], "PYTHONIOENCODING": "utf-8"})
        try:
            riga = server.stdout.readline().decode("utf-8", "replace")
            trovato = re.search(r"(http://127\.0\.0\.1:\d+)/#session=(\S+)", riga)
            assert trovato, "il servizio non ha stampato l'URL: %s" % riga[:200]
            origine, sessione = trovato.group(1), trovato.group(2)
            host = urlsplit(origine).netloc
            sessione_http = {"X-Teseo-Session": sessione}

            def chiama(metodo, percorso, corpo=None, intestazioni=None):
                connessione = http.client.HTTPConnection(host, timeout=60)
                testa = {**sessione_http, **(intestazioni or {})}
                if metodo == "POST":
                    testa.update({"Origin": origine, "Content-Type": "application/json", "X-Teseo-CSRF": self.csrf})
                connessione.request(metodo, percorso, body=json.dumps(corpo).encode("utf-8") if corpo is not None else None, headers=testa)
                risposta = connessione.getresponse()
                dati_ = risposta.read()
                connessione.close()
                return risposta.status, json.loads(dati_) if dati_ else None
            self.csrf = ""
            self.csrf = chiama("POST", "/api/v1/session", {})[1]["csrf_token"]
            elenco = chiama("GET", "/api/v1/vaults")[1]["vaults"]
            assert elenco, "nessun vault collegato"
            base = "/api/v1/vaults/%s/" % elenco[0]["vault_id"]
            stato = chiama("GET", base + "status")[1]
            assert stato["capabilities"]["graph"], "grafo non disponibile: %s" % stato.get("issues")
            nodo = chiama("GET", base + "nodes/Nota%20di%20Bob")[1]
            assert (nodo.get("authors") or {}).get("created_by") == "Bob", "autore della nota di Bob: %s" % nodo.get("authors")
            anteprima = chiama("POST", base + "nodes/Gestionale/edit/preview", {"base_content_digest": stato["live_content_revision"],
                                "idempotency_key": "collaudo-anteprima-1", "operations": [{"op": "set_tags", "tags": ["collaudo"]}]})
            assert anteprima[0] == 200 and anteprima[1]["valid"], "anteprima: %s" % anteprima[1]
            p = anteprima[1]
            applica = chiama("POST", base + "nodes/Gestionale/edit/apply", {"preview_id": p["preview_id"], "proposal_hash": p["proposal_hash"],
                             "idempotency_key": "collaudo-applica-1", "mode": "manual_paused", "external_writers_paused": True, "semantic_reviewed": True},
                             {"If-Match": '"%s"' % p["base_content_digest"]})
            assert applica[0] == 202, "apply: %s" % applica[1]
            identificativo = applica[1]["operation_id"]
            for _ in range(600):
                stato_op = chiama("GET", base + "operations/" + identificativo)[1]
                if stato_op.get("state") in ("recovery_required", "failed"):
                    raise AssertionError("operazione %s: %s" % (stato_op["state"], stato_op.get("error")))
                if stato_op.get("state") == "succeeded" and (stato_op.get("publication") or {}).get("state") not in (None, "pending"):
                    break
                time.sleep(0.5)
            pubblicazione = stato_op.get("publication") or {}
            assert pubblicazione.get("state") == "published", "pubblicazione: %s" % pubblicazione
            assert "collaudo" in self.remoto("wiki/Gestionale.md"), "la modifica non è sul remoto"
            assert "Teseo-Skill: dashboard" in self.remoto(None), "trailer dashboard assenti"
            chiama("POST", "/api/v1/shutdown", {})
        finally:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()
        return "autori reali (Bob) nel grafo; modifica dalla dashboard pubblicata con trailer dashboard"

    def s07_offline_e_ripresa(self):
        code, dati = self.tg("B", "B", "pre", "--skill", "ingest", "--agente", "codex")
        assert code == 0, "pre: %s" % dati
        self.appendi(self.vault["B"], "wiki/Gestionale.md", NL + "Nota scritta offline." + NL)
        offline = {"HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9", "NO_PROXY": "", "no_proxy": ""}
        code, dati = self.tg("B", "B", "post", "--skill", "ingest", "--agente", "codex", extra_env=offline)
        assert code == 3 and dati.get("state") == "waiting", "offline atteso exit 3/waiting: %s %s" % (code, dati)
        assert "Nota scritta offline." not in self.remoto("wiki/Gestionale.md"), "la nota offline non doveva essere sul remoto"
        code, dati = self.tg("B", "B", "riprendi")
        assert code == 0 and dati.get("state") == "published", "ripresa: %s" % dati
        assert "Nota scritta offline." in self.remoto("wiki/Gestionale.md"), "la nota non è arrivata dopo la ripresa"
        return "offline: commit conservato (exit 3), poi pubblicato con riprendi"

    def s08_stessa_nota(self):
        code, tail = self.installa("A", "C")  # terzo clone: parte allineato
        assert code == 0, "clone C: %s" % tail
        for chi, nome, agente in (("A", "A", "claude"), ("B", "B", "codex")):
            code, dati = self.tg(chi, nome, "pre", "--skill", "ingest", "--agente", agente)
            assert code == 0, "pre %s: %s" % (nome, dati)
        self.appendi(self.vault["A"], "wiki/Gestionale.md", NL + "Versione di Alice." + NL)
        self.appendi(self.vault["B"], "wiki/Gestionale.md", NL + "Versione di Bob." + NL)
        code, dati = self.tg("A", "A", "post", "--skill", "ingest", "--agente", "claude")
        assert dati.get("state") == "published", "post di Alice: %s" % dati
        code, dati = self.tg("B", "B", "post", "--skill", "ingest", "--agente", "codex")
        assert code == 2 and dati.get("state") == "blocked" and (dati.get("error") or {}).get("code") == "git_conflict", "conflitto atteso: %s %s" % (code, dati)
        vivo = (self.vault["B"] / "wiki/Gestionale.md").read_text(encoding="utf-8")
        assert "Versione di Bob." in vivo and "<<<<<<<" not in vivo and "Versione di Alice." not in vivo, "il vault vivo di Bob è stato toccato"
        assert "Versione di Bob." not in self.remoto("wiki/Gestionale.md"), "la versione di Bob non doveva arrivare sul remoto"
        return "stessa nota: Bob bloccato (git_conflict), vault vivo e remoto intatti"

    def s09_note_collegate(self):
        # C parte dal commit precedente ad Alice: Alice pubblica una nota che linka Gestionale, C modifica Gestionale.
        code, dati = self.tg("A", "C", "pre", "--skill", "ingest", "--agente", "claude")
        assert code == 0, "pre di C: %s" % dati
        code, dati = self.tg("A", "A", "pre", "--skill", "ingest", "--agente", "claude")
        assert code == 0, "pre di A: %s" % dati
        self.nota("A", "Nota collegata", "Vedi [[Gestionale]].")
        code, dati = self.tg("A", "A", "post", "--skill", "ingest", "--agente", "claude")
        assert dati.get("state") == "published", "post di Alice: %s" % dati
        self.appendi(self.vault["C"], "wiki/Gestionale.md", NL + "Aggiunta concorrente di C." + NL)
        code, dati = self.tg("A", "C", "post", "--skill", "ingest", "--agente", "claude")
        assert code == 2 and dati.get("state") == "blocked" and dati.get("job_state") == "needs_decision", "decisione attesa: %s %s" % (code, dati)
        assert "Aggiunta concorrente di C." in (self.vault["C"] / "wiki/Gestionale.md").read_text(encoding="utf-8"), "vault vivo di C toccato"
        return "note correlate concorrenti: pubblicazione ferma in needs_decision, vault vivo intatto"

    # -- chiusura -------------------------------------------------------------------------------
    def pulisci(self):
        """Cancella il branch di prova dal remoto (mai il repository)."""
        with tempfile.TemporaryDirectory(prefix="collaudo-pulizia-") as cartella:
            self.git("A", cartella, "clone", "-q", "--depth", "1", "--branch", self.branch, self.url, "r")
            self.git("A", Path(cartella) / "r", "push", "origin", "--delete", self.branch)

    def tutto(self, tieni):
        for nome, funzione in (("S01 installazione e primo push", self.s01_installazione), ("S02 clone di Bob", self.s02_clone_di_bob),
                               ("S03 pre/post con attribuzione", self.s03_post_attribuito), ("S04 avviso e pull", self.s04_avviso_e_pull),
                               ("S05 integrazione senza decisione", self.s05_integrazione_senza_decisione),
                               ("S06 autori e modifica dalla dashboard", self.s06_autori_e_dashboard),
                               ("S07 offline e ripresa", self.s07_offline_e_ripresa), ("S08 stessa nota", self.s08_stessa_nota),
                               ("S09 note collegate", self.s09_note_collegate)):
            self.scenario(nome, funzione)
        if not tieni:
            try:
                self.pulisci()
                print("branch %s cancellato dal remoto" % self.branch)
            except Exception as errore:
                print("branch NON cancellato: %s" % errore)
        riuscite = sum(1 for r in self.risultati if r["ok"])
        print(json.dumps({"url": self.url, "branch": self.branch, "scenari": self.risultati, "riuscite": riuscite, "totale": len(self.risultati)},
                         ensure_ascii=False, indent=1))
        return 0 if riuscite == len(self.risultati) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--lavoro", required=True, help="cartella nuova per i cloni")
    ap.add_argument("--home-a", required=True)
    ap.add_argument("--home-b", required=True)
    ap.add_argument("--tieni", action="store_true", help="non cancellare il branch di prova a fine collaudo")
    argomenti = ap.parse_args()
    if Path(argomenti.lavoro).exists():
        ap.error("la cartella di lavoro deve essere nuova")
    sys.exit(Collaudo(argomenti.url, argomenti.branch, argomenti.lavoro, argomenti.home_a, argomenti.home_b).tutto(argomenti.tieni))
