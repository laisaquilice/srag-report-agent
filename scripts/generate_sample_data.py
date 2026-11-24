"""Gera um CSV SINTÉTICO no formato do Open DATASUS (SRAG) para demonstração e testes.

Os registros são aleatórios (nenhum dado real). Inclui ruídos típicos da base real:
datas inválidas, códigos 9 (ignorado), campos vazios e linhas duplicadas.

    python scripts/generate_sample_data.py --out data/raw/INFLUD_SINTETICO.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

COLUMNS = [
    "DT_NOTIFIC",
    "SEM_NOT",
    "DT_SIN_PRI",
    "SG_UF_NOT",
    "ID_MUNICIP",
    "CS_SEXO",
    "DT_NASC",
    "NU_IDADE_N",
    "TP_IDADE",
    "HOSPITAL",
    "UTI",
    "VACINA",
    "VACINA_COV",
    "CLASSI_FIN",
    "EVOLUCAO",
]
UFS = ["SP", "RJ", "MG", "PR", "RS", "BA", "PE", "CE", "GO", "DF", "SC", "PA", "AM"]
UF_WEIGHTS = [30, 10, 12, 8, 7, 6, 5, 4, 4, 3, 4, 3, 2]


def _seasonal_rate(day: date) -> float:
    """Casos esperados por dia, com pico no outono/inverno."""
    return 140 + 110 * math.cos(2 * math.pi * (day.timetuple().tm_yday - 150) / 365)


def _poisson(rng: random.Random, lam: float) -> int:
    return max(0, int(rng.gauss(lam, math.sqrt(lam))))


def _pick(rng: random.Random, options: dict[str, float]) -> str:
    return rng.choices(list(options), weights=list(options.values()))[0]


def _row(rng: random.Random, onset: date, end: date) -> dict[str, str]:
    notif = min(onset + timedelta(days=rng.randint(0, 10)), end)
    age = int(min(100, abs(rng.gauss(55, 28))))
    icu = _pick(rng, {"1": 0.28, "2": 0.6, "9": 0.07, "": 0.05})
    death_p = 0.35 if icu == "1" else 0.12
    pending = (end - onset).days < 20 and rng.random() < 0.5
    outcome = (
        "" if pending else _pick(rng, {"1": 1 - death_p - 0.05, "2": death_p, "3": 0.02, "9": 0.03})
    )
    return {
        "DT_NOTIFIC": notif.strftime("%d/%m/%Y"),
        "SEM_NOT": str(notif.isocalendar().week),
        "DT_SIN_PRI": onset.strftime("%d/%m/%Y"),
        "SG_UF_NOT": rng.choices(UFS, UF_WEIGHTS)[0],
        "ID_MUNICIP": "MUNICIPIO FICTICIO",
        "CS_SEXO": _pick(rng, {"M": 0.49, "F": 0.49, "I": 0.02}),
        "DT_NASC": (onset - timedelta(days=365 * age + rng.randint(0, 364))).strftime("%d/%m/%Y"),
        "NU_IDADE_N": str(age),
        "TP_IDADE": "3",
        "HOSPITAL": _pick(rng, {"1": 0.95, "2": 0.03, "9": 0.02}),
        "UTI": icu,
        "VACINA": _pick(rng, {"1": 0.35, "2": 0.45, "9": 0.2}),
        "VACINA_COV": _pick(rng, {"1": 0.55, "2": 0.25, "9": 0.15, "": 0.05}),
        "CLASSI_FIN": _pick(rng, {"1": 0.2, "2": 0.15, "4": 0.4, "5": 0.15, "": 0.1}),
        "EVOLUCAO": outcome,
    }


def generate(out: Path, end: date, months: int = 15, seed: int = 42) -> int:
    rng = random.Random(seed)
    start = end - timedelta(days=30 * months)
    rows: list[dict[str, str]] = []
    day = start
    while day <= end:
        rows += [_row(rng, day, end) for _ in range(_poisson(rng, _seasonal_rate(day)))]
        day += timedelta(days=1)

    # Ruídos típicos da base real
    for _ in range(len(rows) // 200):
        bad = dict(rng.choice(rows))
        bad["DT_SIN_PRI"] = rng.choice(["31/02/2024", "01/01/1900", "", "99/99/9999"])
        rows.append(bad)
    rows += rng.sample(rows, len(rows) // 100)  # duplicatas exatas
    rng.shuffle(rows)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="latin-1") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/raw/INFLUD_SINTETICO.csv"))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 6, 30))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    n = generate(args.out, args.end, seed=args.seed)
    print(f"{n} linhas sintéticas gravadas em {args.out}")


if __name__ == "__main__":
    main()
