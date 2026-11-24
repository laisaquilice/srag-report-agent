"""Gera docs/arquitetura.pdf (diagrama conceitual da solução).

python docs/build_diagram.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

COLORS = {
    "agent": ("#e7f0f7", "#0b3c5d"),
    "node": ("#ffffff", "#2a6f97"),
    "tool": ("#e9f5ec", "#2d6a3e"),
    "llm": ("#f3e8fb", "#6a3d8f"),
    "data": ("#fff4e0", "#a5641a"),
    "guard": ("#fdecea", "#a32d2d"),
    "audit": ("#eef0f3", "#444c56"),
}
GREEN, RED, PURPLE = COLORS["tool"][1], COLORS["guard"][1], COLORS["llm"][1]


def box(ax, x, y, w, h, text, kind, size=8.5, bold=False):
    face, edge = COLORS[kind]
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.3,rounding_size=0.8",
            facecolor=face,
            edgecolor=edge,
            linewidth=1.4,
        )
    )
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=size,
        color=edge,
        fontweight="bold" if bold else "normal",
    )


def arrow(ax, start, end, text="", color="#444c56", style="-|>", rad=0.0, dashed=False):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            mutation_scale=12,
            color=color,
            linewidth=1.2,
            connectionstyle=f"arc3,rad={rad}",
            linestyle="--" if dashed else "-",
        )
    )
    if text:
        mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        ax.text(
            mx,
            my,
            text,
            fontsize=7.5,
            color=color,
            ha="center",
            va="center",
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 1},
        )


def label(ax, x, y, text, color, bg="white"):
    ax.text(
        x,
        y,
        text,
        fontsize=7.5,
        color=color,
        ha="center",
        va="center",
        bbox={"facecolor": bg, "edgecolor": "none", "pad": 1},
    )


def draw_sources_and_tools(ax):
    box(ax, 1, 66, 14, 7, "Open DATASUS\nSRAG (CSV)\n~100 colunas", "data")
    box(ax, 19, 66, 15, 7, "ETL (DuckDB)\nminimização, limpeza,\nfaixa etária, dedup", "data")
    box(ax, 38, 66, 15, 7, "Base DuckDB\ntabela srag\n(só agregados saem)", "data")
    box(ax, 72, 66, 15, 7, "Fontes de notícias\ngov.br, Fiocruz, OPAS,\nimprensa", "data")
    arrow(ax, (15.4, 69.5), (18.6, 69.5))
    arrow(ax, (34.4, 69.5), (37.6, 69.5))

    ax.text(1, 57.5, "Ferramentas\n(Tools)", fontsize=11, fontweight="bold", color=GREEN)
    box(ax, 38, 54, 15, 7, "Tool Métricas\nSQL parametrizado,\nconexão read-only", "tool")
    box(ax, 55, 54, 15, 7, "Tool Gráficos\nmatplotlib\n(30 dias / 12 meses)", "tool")
    box(
        ax,
        72,
        54,
        15,
        7,
        "Tool Notícias (Tavily)\nallowlist de domínios,\nsanitização + PII",
        "tool",
    )
    arrow(ax, (45.5, 65.6), (45.5, 61.4), "SQL")
    arrow(ax, (50, 65.6), (59, 61.4), "SQL")
    arrow(ax, (79.5, 65.6), (79.5, 61.4), "busca web")


def draw_orchestrator(ax):
    agent_face, agent_edge = COLORS["agent"]
    ax.add_patch(
        FancyBboxPatch(
            (19, 9),
            70,
            41,
            boxstyle="round,pad=0.4,rounding_size=1.2",
            facecolor=agent_face,
            edgecolor=agent_edge,
            linewidth=2,
        )
    )
    ax.text(
        21,
        46,
        "Agente Principal\nOrquestrador (LangGraph)",
        ha="left",
        fontsize=12,
        fontweight="bold",
        color=agent_edge,
    )
    top = [
        (21, "1. validate_input\n(guardrail de entrada)", "guard"),
        (38, "2. compute_metrics", "node"),
        (55, "3. build_charts", "node"),
        (72, "4. research_news\n(LLM decide consultas)", "node"),
    ]
    bottom = [
        (21, "8. render_report\n(Jinja2 → HTML/PDF)", "node"),
        (38, "7. fallback_analysis\n(texto determinístico)", "node"),
        (55, "6. check_output\n(guardrail de saída)", "guard"),
        (72, "5. write_analysis\n(saída estruturada)", "node"),
    ]
    for x, text, kind in top:
        box(ax, x, 36, 15, 7, text, kind)
    for x, text, kind in bottom:
        box(ax, x, 18, 15, 7, text, kind)

    for x in (21, 38, 55):
        arrow(ax, (x + 15.4, 39.5), (x + 16.6, 39.5))
    arrow(ax, (79.5, 35.6), (79.5, 25.4))
    arrow(ax, (71.6, 21.5), (70.4, 21.5))
    arrow(ax, (54.6, 21.5), (53.4, 21.5), color=RED)
    arrow(ax, (37.6, 21.5), (36.4, 21.5))
    label(ax, 54, 16.3, "esgotou", RED, agent_face)

    arrow(ax, (62.5, 25.4), (28.5, 25.4), color=GREEN, rad=0.25)
    label(ax, 45.5, 29.7, "aprovado", GREEN, agent_face)
    arrow(ax, (62.5, 17.6), (79.5, 17.6), color=RED, rad=0.45, dashed=True)
    label(ax, 71, 11.3, "reprovado → reescreve (máx. 2 tentativas)", RED, agent_face)

    arrow(ax, (45.5, 53.6), (45.5, 43.4), style="<|-|>", color=GREEN)
    arrow(ax, (62.5, 53.6), (62.5, 43.4), style="<|-|>", color=GREEN)
    arrow(ax, (79.5, 53.6), (79.5, 43.4), "tool call", style="<|-|>", color=GREEN)


def draw_edges_of_system(ax):
    box(ax, 1, 36, 14, 7, "Usuário / CLI\nsrag report --uf SP", "audit", bold=True)
    box(
        ax,
        1,
        16,
        14,
        11,
        "Relatório\nHTML + PDF\n\n4 métricas, 2 gráficos,\nanálise, fontes,\nmetodologia",
        "audit",
        bold=True,
    )
    arrow(ax, (15.4, 39.5), (20.6, 39.5), "pedido")
    arrow(ax, (20.6, 21.5), (15.4, 21.5))

    box(
        ax,
        93,
        18,
        15,
        25,
        "LLM\nOpenAI GPT\n(temperature 0)\n\n• tool calling\n• saída Pydantic",
        "llm",
        size=9,
        bold=True,
    )
    arrow(ax, (92.6, 39.5), (87.4, 39.5), "decide\nconsultas", color=PURPLE, style="<|-|>")
    arrow(ax, (92.6, 21.5), (87.4, 21.5), "escreve\nanálise", color=PURPLE, style="<|-|>")

    box(
        ax,
        93,
        50,
        15,
        23,
        "Guardrails\n\n• UF/data válidas\n• consultas no escopo\n• domínios confiáveis\n"
        "• anti prompt injection\n• números = métricas\n• fontes recuperadas\n• sem PII\n"
        "• fallback determinístico",
        "guard",
        size=8,
    )
    box(
        ax,
        1,
        1,
        107,
        4.5,
        "Governança e auditoria (transversal): log JSONL por execução com passos, entradas/saídas,"
        " prompts, tokens, latência, decisões e guardrails  •  manifest.json com hash da base"
        "  •  decisões e metodologia no relatório",
        "audit",
        size=8,
    )


OUTPUT = Path(__file__).with_name("arquitetura.pdf")


def main(out: Path = OUTPUT) -> None:
    fig, ax = plt.subplots(figsize=(16.5, 12.5))
    ax.set_xlim(0, 110)
    ax.set_ylim(0, 84)
    ax.axis("off")
    ax.text(
        1,
        81.5,
        "Agente de Relatórios SRAG – Arquitetura conceitual",
        fontsize=17,
        fontweight="bold",
        color=COLORS["agent"][1],
    )
    ax.text(
        1,
        79,
        "Princípio: o LLM nunca calcula números. As métricas vêm de SQL determinístico; "
        "o LLM decide as buscas de notícias e interpreta o cenário.",
        fontsize=10,
        color="#444c56",
    )
    draw_sources_and_tools(ax)
    draw_orchestrator(ax)
    draw_edges_of_system(ax)

    fig.savefig(out, bbox_inches="tight")
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight", dpi=110)
    print(f"Diagrama salvo em {out}")


if __name__ == "__main__":
    main()
