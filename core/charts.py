"""Chart generation and code execution"""
import json
import time
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from typing import Dict, Tuple, Optional

from .datasets import load_dataframe


def execute_code(code: str, datasets: Dict[str, pd.DataFrame]) -> Tuple[bool, str, Optional[go.Figure]]:
    """
    Execute LLM-generated code.
    Code has access to: df, datasets, pd, px, go, np
    Must create: fig (Plotly figure), summary (string)
    Returns: (success, message, figure)
    """
    if not datasets:
        return False, "No datasets available for visualization", None
    
    primary_df = list(datasets.values())[0]
    
    env = {
        'pd': pd, 'px': px, 'go': go, 'np': np,
        'df': primary_df.copy(),
        'datasets': {n: d.copy() for n, d in datasets.items()}
    }
    local = {}
    
    try:
        exec(code, env, local)
        
        fig = local.get('fig') or env.get('fig')
        summary = local.get('summary') or env.get('summary', 'Visualization generated.')
        
        if fig is None:
            return False, "Code did not create 'fig' variable", None
        if not isinstance(fig, go.Figure):
            return False, f"'fig' is not a Plotly figure (got {type(fig).__name__})", None
        
        fig.update_layout(template='plotly_white', margin={'t': 60, 'b': 60, 'l': 60, 'r': 40})
        return True, str(summary), fig
        
    except SyntaxError as e:
        return False, f"Syntax error: {e}", None
    except KeyError as e:
        return False, f"Column not found: {e}", None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", None


def figure_to_png(fig: go.Figure, width: int = 1200, height: int = 800) -> bytes:
    """Convert figure to PNG bytes"""
    return fig.to_image(format="png", width=width, height=height, engine="kaleido")


def figure_to_json(fig: go.Figure) -> str:
    """Convert figure to JSON for browser Plotly.js"""
    return fig.to_json()


def generate_chart(code: str, file_paths: Dict[str, str]) -> Tuple[bool, str, Optional[bytes], Optional[str], Optional[str]]:
    """
    Generate chart from code.
    Returns: (success, message, png_bytes, figure_json, chart_id)
    """
    if not file_paths:
        return False, "No datasets available", None, None, None
    
    # Load datasets
    datasets = {}
    for name, path in file_paths.items():
        try:
            datasets[name] = load_dataframe(path)
        except Exception as e:
            return False, f"Error loading '{name}': {e}", None, None, None
    
    # Execute code
    success, message, fig = execute_code(code, datasets)
    if not success or fig is None:
        return False, message, None, None, None
    
    try:
        png = figure_to_png(fig)
        fig_json = figure_to_json(fig)
        chart_id = f"chart_{int(time.time() * 1000)}"
        return True, message, png, fig_json, chart_id
    except Exception as e:
        return False, f"Error generating outputs: {e}", None, None, None
