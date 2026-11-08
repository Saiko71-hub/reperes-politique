#!/usr/bin/env python3
"""Repères : met à jour data.json à partir de sources officielles et ouvertes.

Sources (données brutes, sans interprétation) :
- Assemblée nationale, open data : composition des groupes (députés en exercice)
- Eurostat : inflation (IPCH), chômage (BIT), croissance du PIB, déficit, dette, coefficient de Gini
- Banque centrale européenne : taux directeurs
- vie-publique.fr (DILA, service du Premier ministre) : actualités et textes de loi

Bibliothèque standard Python uniquement. Si une source échoue, la valeur
précédente de data.json est conservée.
"""
import csv
import datetime as dt
import email.utils
import gzip
import io
import json
import pathlib
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "data.json"
UA = {"User-Agent": "Reperes/1.0 (application pedagogique; github.com/Saiko71-hub/reperes-politique)"}


def get(url, timeout=90, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def today():
    return dt.date.today().isoformat()


# ---------- Assemblée nationale ----------
AN_PAGE = "https://data.assemblee-nationale.fr/acteurs/deputes-en-exercice"
AN_CSV = ("https://data.assemblee-nationale.fr/static/openData/repository/17/amo/"
          "deputes_actifs_csv_opendata/liste_deputes_libre_office.csv")


def assemblee():
    text = get(AN_CSV).decode("utf-8-sig")
    groups = {}
    total = 0
    for row in csv.DictReader(io.StringIO(text)):
        abrev = (row.get("Groupe politique (abrégé)") or "NI").strip() or "NI"
        nom = (row.get("Groupe politique (complet)") or "Non inscrit").strip()
        g = groups.setdefault(abrev, {"abrev": abrev, "nom": nom, "sieges": 0})
        g["sieges"] += 1
        total += 1
    if total < 400:
        raise ValueError(f"seulement {total} députés lus, données suspectes")
    return {
        "source": "Assemblée nationale – open data (députés en exercice)",
        "url": AN_PAGE,
        "date": today(),
        "total": total,
        "groupes": sorted(groups.values(), key=lambda g: -g["sieges"]),
    }


# ---------- Eurostat ----------
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"


def eurostat(dataset, params, n):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    j = json.loads(get(f"{EUROSTAT}{dataset}?{q}&lastTimePeriod={n}&format=JSON&lang=fr"))
    for dim, size in zip(j["id"], j["size"]):
        if dim != "time" and size != 1:
            raise ValueError(f"{dataset} : la dimension {dim} n'est pas filtrée ({size})")
    times = sorted(j["dimension"]["time"]["category"]["index"].items(), key=lambda kv: kv[1])
    values, status = j.get("value", {}), j.get("status", {})
    serie = [[t, values[str(i)]] for t, i in times if str(i) in values]
    if not serie:
        raise ValueError(f"{dataset} : aucune valeur")
    last_idx = max(i for t, i in times if str(i) in values)
    return serie, status.get(str(last_idx))


EUROSTAT_SERIES = {
    "inflation": dict(
        dataset="prc_hicp_minr", params={"geo": "FR", "unit": "RCH_A", "coicop18": "TOTAL"}, n=13,
        label="Inflation sur un an", unite="%",
        explication="Hausse des prix à la consommation par rapport au même mois de l’année précédente (indice harmonisé européen, IPCH)."),
    "chomage": dict(
        dataset="une_rt_m", params={"geo": "FR", "s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"}, n=13,
        label="Taux de chômage", unite="%",
        explication="Part des personnes actives sans emploi qui en cherchent un (définition du BIT, corrigé des variations saisonnières)."),
    "croissance": dict(
        dataset="namq_10_gdp", params={"geo": "FR", "unit": "CLV_PCH_PRE", "s_adj": "SCA", "na_item": "B1GQ"}, n=8,
        label="Croissance du PIB", unite="%",
        explication="Évolution du PIB en volume par rapport au trimestre précédent."),
    "deficit": dict(
        dataset="gov_10dd_edpt1", params={"geo": "FR", "na_item": "B9", "sector": "S13", "unit": "PC_GDP"}, n=6,
        label="Solde public", unite="% du PIB",
        explication="Recettes moins dépenses de toutes les administrations publiques. Un chiffre négatif est un déficit."),
    "dette": dict(
        dataset="gov_10dd_edpt1", params={"geo": "FR", "na_item": "GD", "sector": "S13", "unit": "PC_GDP"}, n=6,
        label="Dette publique", unite="% du PIB",
        explication="Dette des administrations publiques au sens du traité de Maastricht."),
    "gini": dict(
        dataset="ilc_di12", params={"geo": "FR", "age": "TOTAL"}, n=5,
        label="Coefficient de Gini", unite="/ 100",
        explication="Inégalités de revenu disponible : 0 = égalité parfaite, 100 = inégalité maximale."),
}

# ---------- BCE ----------
ECB = "https://data-api.ecb.europa.eu/service/data/"
ECB_SERIES = {
    "bce_depot": dict(key="FM/D.U2.EUR.4F.KR.DFR.LEV", label="Taux de dépôt de la BCE", unite="%",
                      explication="Rémunération des dépôts des banques auprès de la BCE ; c’est le principal taux directeur de la zone euro."),
    "bce_refi": dict(key="FM/D.U2.EUR.4F.KR.MRR_FR.LEV", label="Taux de refinancement de la BCE", unite="%",
                     explication="Taux auquel les banques empruntent à la BCE pour une semaine."),
}


def ecb(key):
    j = json.loads(get(f"{ECB}{key}?lastNObservations=1&format=jsondata"))
    series = j["dataSets"][0]["series"]
    obs = series[next(iter(series))]["observations"]
    idx = max(obs, key=int)
    t = j["structure"]["dimensions"]["observation"][0]["values"][int(idx)]["id"]
    return [[t, obs[idx][0]]]


# ---------- vie-publique.fr ----------
VP = {"actus": "https://www.vie-publique.fr/actualites-feeds.xml",
      "lois": "https://www.vie-publique.fr/lois-feeds.xml"}


def rss(url, n):
    raw = get(url, headers={"Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
                            "Accept-Language": "fr-FR,fr;q=0.9"}).lstrip(b"\xef\xbb\xbf \r\n\t")
    if not raw.startswith(b"<"):
        raise ValueError("réponse non XML : " + raw[:80].decode("utf-8", "replace"))
    root = ET.fromstring(raw)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        date = it.findtext("pubDate")
        try:
            date = email.utils.parsedate_to_datetime(date).date().isoformat()
        except Exception:
            date = None
        if title and link.startswith("https://www.vie-publique.fr/"):
            items.append({"titre": title, "lien": link, "date": date})
        if len(items) >= n:
            break
    if not items:
        raise ValueError("flux vide")
    return items


def main():
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    data = {"maj": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
            "indicateurs": dict(old.get("indicateurs", {}))}
    errors = []

    try:
        data["assemblee"] = assemblee()
    except Exception as e:
        errors.append(f"assemblee: {e}")
        data["assemblee"] = old.get("assemblee")

    for key, cfg in EUROSTAT_SERIES.items():
        try:
            serie, statut = eurostat(cfg["dataset"], cfg["params"], cfg["n"])
            data["indicateurs"][key] = {
                "label": cfg["label"], "unite": cfg["unite"], "explication": cfg["explication"],
                "valeur": serie[-1][1], "periode": serie[-1][0], "serie": serie,
                "provisoire": statut in ("e", "p"),
                "source": "Eurostat", "url": f"https://ec.europa.eu/eurostat/databrowser/view/{cfg['dataset']}/default/table",
            }
        except Exception as e:
            errors.append(f"{key}: {e}")

    for key, cfg in ECB_SERIES.items():
        try:
            serie = ecb(cfg["key"])
            data["indicateurs"][key] = {
                "label": cfg["label"], "unite": cfg["unite"], "explication": cfg["explication"],
                "valeur": serie[-1][1], "periode": serie[-1][0], "serie": serie, "provisoire": False,
                "source": "Banque centrale européenne", "url": "https://data.ecb.europa.eu/",
            }
        except Exception as e:
            errors.append(f"{key}: {e}")

    for key, url in VP.items():
        try:
            data[key] = {"source": "vie-publique.fr (DILA)", "url": url, "date": today(), "items": rss(url, 12)}
        except Exception as e:
            errors.append(f"{key}: {e}")
            data[key] = old.get(key)

    data["erreurs"] = errors
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("data.json écrit.")
    for e in errors:
        print("AVERTISSEMENT", e)


if __name__ == "__main__":
    main()
