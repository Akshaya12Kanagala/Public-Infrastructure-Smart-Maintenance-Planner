"""Plotly figure builders (no Streamlit import)."""
from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from . import config
from .ui_colors import COLORS


def timeseries(s: pd.Series, title: str, unit: str, zthr: float = 3.5, baseline_n: int = 60, window_n: int = 5,
               floor: float = 1e-6, pct: bool = False, height: int = 270) -> go.Figure:
    """Line chart with the 'normal' band (median +/- z*scale of the baseline) and anomaly markers."""
    s = s.dropna()
    fig = go.Figure()
    mult = 100.0 if pct else 1.0
    fig.add_trace(go.Scatter(x=s.index, y=s.values * mult, mode="lines", name=title, line=dict(width=2)))
    if len(s) > window_n + 8:
        hist = s.iloc[-(window_n + baseline_n):-window_n]
        med = float(np.median(hist))
        mad = float(np.median(np.abs(hist - med)))
        scale = max(1.4826 * mad, 0.05 * abs(med), floor)
        fig.add_hrect(y0=(med - zthr * scale) * mult, y1=(med + zthr * scale) * mult, fillcolor="green",
                      opacity=0.10, line_width=0, annotation_text="normal range", annotation_position="top left")
        z = (s - med) / scale
        bad = s[z > zthr]
        if not bad.empty:
            fig.add_trace(go.Scatter(x=bad.index, y=bad.values * mult, mode="markers", name="anomaly",
                                     marker=dict(color="#C62828", size=8, symbol="circle")))
    fig.update_layout(title=dict(text=title, font=dict(size=14)), height=height, margin=dict(l=10, r=10, t=40, b=10),
                      yaxis_title=("%" if pct else unit), showlegend=False, hovermode="x unified")
    return fig


def dependency_graph(status: dict[str, str], highlight: str | None = None) -> tuple[go.Figure, set[str]]:
    reg = config.services()
    g = nx.DiGraph()
    g.add_nodes_from(reg)
    for s, meta in reg.items():
        for d in meta.get("depends_on", []):
            if d in reg:
                g.add_edge(s, d)  # s depends on d
    layers = list(nx.topological_generations(g))
    pos = {}
    for x, gen in enumerate(layers):
        gen = sorted(gen)
        for i, n in enumerate(gen):
            pos[n] = (x, (i - (len(gen) - 1) / 2.0) * 1.0)
    affected = set(nx.ancestors(g, highlight)) if highlight in g else set()
    fig = go.Figure()
    for a, b in g.edges():
        hot = highlight in (a, b) or (a in affected and (b == highlight or b in affected))
        fig.add_annotation(x=pos[b][0], y=pos[b][1], ax=pos[a][0], ay=pos[a][1], xref="x", yref="y", axref="x",
                           ayref="y", showarrow=True, arrowhead=3, arrowsize=1.1, arrowwidth=1.6 if hot else 1,
                           arrowcolor="#C62828" if hot else "rgba(128,128,128,.55)", standoff=14, startstandoff=14)
    names = list(g.nodes())
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in names], y=[pos[n][1] for n in names], mode="markers+text", text=names,
        textposition="bottom center", textfont=dict(size=11),
        marker=dict(size=[30 if n == highlight else 22 for n in names],
                    color=[COLORS.get(status.get(n, "no data"), "#757575") for n in names],
                    line=dict(width=[4 if n in affected or n == highlight else 1 for n in names],
                              color=["#000000" if n == highlight else ("#C62828" if n in affected else "#FFFFFF")
                                     for n in names])),
        hovertext=[f"{n}: {status.get(n, 'no data')}" for n in names], hoverinfo="text"))
    fig.update_layout(height=560, margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig, affected
