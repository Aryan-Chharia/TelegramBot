"""Chart generation and code execution"""
import json
import time
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from typing import Dict, Tuple, Optional, Any, List, Iterable

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


def _safe_list(v: Any, limit: int) -> List[Any]:
    """Best-effort conversion of plotly array-like to a JSON-serializable list."""
    if v is None:
        return []
    if isinstance(v, (str, bytes, int, float, bool)):
        return [v]
    try:
        if isinstance(v, (list, tuple)):
            out = list(v)
        elif hasattr(v, 'tolist'):
            out = v.tolist()
        else:
            out = list(v)  # may raise
    except Exception:
        return []
    if limit and len(out) > limit:
        return out[:limit]
    return out


def _flatten(values: Any, limit: int) -> List[Any]:
    """Flatten nested list/tuple/ndarray into a 1D list (best-effort, capped)."""
    if values is None:
        return []
    # Fast path: not nested
    if isinstance(values, (str, bytes, int, float, bool)):
        return [values]

    # Convert numpy arrays to lists
    if hasattr(values, 'tolist'):
        try:
            values = values.tolist()
        except Exception:
            pass

    out: List[Any] = []

    def walk(v: Any):
        nonlocal out
        if limit and len(out) >= limit:
            return
        if v is None or isinstance(v, (str, bytes, int, float, bool)):
            out.append(v)
            return
        if hasattr(v, 'tolist'):
            try:
                walk(v.tolist())
                return
            except Exception:
                pass
        if isinstance(v, dict):
            # Dicts aren't useful for datapoints here
            return
        if isinstance(v, (list, tuple)):
            for item in v:
                if limit and len(out) >= limit:
                    break
                walk(item)
            return
        # Fallback: try iterating
        try:
            for item in v:  # type: ignore[assignment]
                if limit and len(out) >= limit:
                    break
                walk(item)
        except Exception:
            return

    walk(values)
    if limit and len(out) > limit:
        return out[:limit]
    return out


def _get_attr_path(obj: Any, path: str) -> Any:
    """Get attribute by dotted path (e.g., 'marker.color'); returns None if missing."""
    cur = obj
    for part in path.split('.'):
        if cur is None:
            return None
        try:
            cur = getattr(cur, part)
        except Exception:
            return None
    return cur


def _is_primitive(v: Any) -> bool:
    return v is None or isinstance(v, (str, bytes, int, float, bool))


def _truncate_string(s: str, max_len: int = 200) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + '...'


def _auto_extract_trace_fields(
    tr: Any,
    limit: int,
    max_fields: int = 14,
) -> Tuple[Dict[str, List[Any]], Dict[str, dict]]:
    """Best-effort extraction for any Plotly trace type.

    Walks trace.to_plotly_json() and collects list-like/scalar datapoint fields.
    Prioritizes numeric signals, but keeps a few label-like fields when present.
    """
    try:
        raw = tr.to_plotly_json()
    except Exception:
        return {}, {}

    deny_keys = {
        'uid', 'hovertemplate', 'hoverlabel', 'hoverinfo', 'meta', 'transforms',
        'legendgroup', 'legendrank', 'name', 'type', 'xaxis', 'yaxis', 'scene',
        'texttemplate', 'textfont', 'marker', 'line', 'fillcolor', 'opacity',
        'showlegend', 'visible', 'mode'
    }

    label_hints = {'label', 'labels', 'text', 'locations', 'parents', 'ids', 'theta'}
    numeric_hints = {
        'x', 'y', 'z', 'r', 'value', 'values', 'open', 'high', 'low', 'close',
        'lat', 'lon', 'size', 'width', 'height', 'count', 'probability'
    }

    collected: List[Tuple[str, List[Any], Optional[dict], bool, bool]] = []
    # tuple: (path, values, num_summary, is_numeric, is_label)

    def add_candidate(path: str, val: Any):
        if not path:
            return
        leaf = path.split('.')[-1]
        if leaf in deny_keys:
            return
        # Avoid long free-form strings
        if isinstance(val, str):
            val = _truncate_string(val)

        if _is_primitive(val):
            values = [val]
        else:
            # Flatten any nested array-ish values
            values = _flatten(val, limit)
            if not values:
                return

        num_summary = _numeric_summary(values)
        is_numeric = num_summary is not None
        is_label = (leaf in label_hints) or (any(h in path for h in label_hints))

        # Keep numeric always; keep label fields sparingly
        if not is_numeric and not is_label:
            # also keep if looks like categorical axis values
            if leaf in {'x', 'y'}:
                is_label = True
            else:
                return

        collected.append((path, values, num_summary, is_numeric, is_label))

    def walk(obj: Any, path: str = '', depth: int = 0):
        if depth > 6:
            return
        if obj is None:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in deny_keys:
                    continue
                next_path = f"{path}.{k}" if path else str(k)
                walk(v, next_path, depth + 1)
            return
        if isinstance(obj, (list, tuple)):
            # treat whole list as a candidate if primitive-ish
            if obj and all(_is_primitive(x) for x in obj[:10]):
                add_candidate(path, list(obj))
                return
            # If list contains dicts (common in dimensions/spec objects), descend.
            any_descended = False
            for item in obj[:50]:
                if isinstance(item, dict):
                    any_descended = True
                    walk(item, path, depth + 1)
            if any_descended:
                return
            # else flatten whole structure as candidate
            add_candidate(path, obj)
            return
        if hasattr(obj, 'tolist'):
            try:
                walk(obj.tolist(), path, depth + 1)
                return
            except Exception:
                pass
        if _is_primitive(obj):
            add_candidate(path, obj)
            return

    walk(raw)

    # Rank: numeric first, then label, then hints
    def score(item: Tuple[str, List[Any], Optional[dict], bool, bool]) -> int:
        path, values, num_summary, is_numeric, is_label = item
        leaf = path.split('.')[-1]
        s = 0
        if is_numeric:
            s += 100
        if is_label:
            s += 30
        if leaf in numeric_hints:
            s += 20
        if leaf in label_hints:
            s += 10
        # prefer more datapoints
        s += min(len(values), limit) // 10
        return s

    collected.sort(key=score, reverse=True)

    fields: Dict[str, List[Any]] = {}
    summaries: Dict[str, dict] = {}
    for path, values, num_summary, is_numeric, is_label in collected:
        if path in fields:
            continue
        fields[path] = values[:limit]
        if num_summary is not None:
            summaries[path] = num_summary
        if len(fields) >= max_fields:
            break

    return fields, summaries


def _numeric_summary(values: List[Any]) -> Optional[dict]:
    """Compute numeric summary for a mixed list; returns None if not numeric."""
    if not values:
        return None
    nums: List[float] = []
    for val in values:
        try:
            if val is None or (isinstance(val, float) and np.isnan(val)):
                continue
            nums.append(float(val))
        except Exception:
            continue
    if not nums:
        return None
    arr = np.array(nums, dtype=float)
    return {
        'count': int(arr.size),
        'min': float(np.min(arr)),
        'max': float(np.max(arr)),
        'mean': float(np.mean(arr)),
        'median': float(np.median(arr)),
    }


def _trace_field_candidates(trace_type: Optional[str]) -> List[str]:
    """Field candidates to extract from a trace, depending on trace type."""
    t = (trace_type or '').lower()

    # Common defaults (work for many trace types)
    candidates: List[str] = ['x', 'y']

    # z-based charts
    if t in {
        'heatmap', 'contour', 'surface', 'histogram2d', 'histogram2dcontour',
        'densitymapbox', 'choropleth', 'choroplethmapbox'
    }:
        candidates = ['x', 'y', 'z']

    # Categorical part-to-whole
    if t in {'pie', 'sunburst', 'treemap', 'funnelarea'}:
        candidates = ['labels', 'values', 'parents']

    # Financial
    if t in {'candlestick', 'ohlc'}:
        candidates = ['x', 'open', 'high', 'low', 'close']

    # Tables
    if t in {'table'}:
        candidates = ['header.values', 'cells.values']

    # Sankey
    if t in {'sankey'}:
        candidates = ['node.label', 'link.value', 'link.source', 'link.target']

    # Indicator
    if t in {'indicator'}:
        candidates = ['value', 'delta.reference']

    # Polar
    if t in {'scatterpolar', 'barpolar'}:
        candidates = ['theta', 'r']

    # Geo
    if t in {'scattergeo', 'scattermapbox'}:
        candidates = ['lat', 'lon']

    # 3D scatter
    if t in {'scatter3d', 'mesh3d'}:
        candidates = ['x', 'y', 'z']

    # Distributions often only have x or y
    if t in {'histogram'}:
        candidates = ['x', 'y']  # plotly uses x for hist, y for orientation=horizontal
    if t in {'box', 'violin'}:
        candidates = ['y', 'x']

    # Some traces use locations/value
    if t in {'choropleth', 'choroplethmapbox'}:
        candidates = ['locations', 'z', 'text']

    return candidates


def _extra_attr_paths(trace_type: Optional[str]) -> List[str]:
    """Extra nested fields that can add quantitative signal across trace types."""
    t = (trace_type or '').lower()
    common = [
        'value',
        'text',
        'customdata',
        'marker.size',
        'marker.color',
        'marker.line.width',
    ]
    if t in {'sankey'}:
        common.extend(['node.x', 'node.y'])
    if t in {'bar', 'scatter', 'scatter3d', 'scatterpolar', 'scattergeo', 'scattermapbox'}:
        common.extend(['error_y.array', 'error_x.array'])
    return common


def _dataset_stats(df: pd.DataFrame, max_numeric_cols: int = 12) -> dict:
    """Compact stats for LLM insight generation."""
    stats: dict = {
        'rows': int(df.shape[0]),
        'cols': int(df.shape[1]),
        'missing_by_col_top': [],
        'numeric_describe': {},
    }

    try:
        if df.shape[0] > 0:
            missing = (df.isna().mean() * 100).sort_values(ascending=False)
            stats['missing_by_col_top'] = [
                {'column': str(col), 'missing_pct': float(pct)}
                for col, pct in missing.head(10).items()
                if float(pct) > 0.0
            ]
    except Exception:
        pass

    try:
        numeric_cols = df.select_dtypes(include='number').columns.tolist()[:max_numeric_cols]
        if numeric_cols:
            desc = df[numeric_cols].describe().to_dict()
            # Ensure JSON-serializable primitives
            cleaned: dict = {}
            for col, metrics in desc.items():
                cleaned[str(col)] = {k: (float(v) if v is not None and not pd.isna(v) else None) for k, v in metrics.items()}
            stats['numeric_describe'] = cleaned
    except Exception:
        pass

    return stats


def build_insights_payload(fig: go.Figure, datasets: Dict[str, pd.DataFrame], max_points_per_trace: int = 200) -> dict:
    """Extract plotted datapoints + basic dataset stats for business insight generation."""
    payload: dict = {
        'chart': {
            'title': None,
            'type': 'plotly',
            'trace_count': 0,
            'traces': [],
        },
        'datasets': {},
    }

    try:
        title = getattr(getattr(fig, 'layout', None), 'title', None)
        payload['chart']['title'] = getattr(title, 'text', None) if title else None
    except Exception:
        payload['chart']['title'] = None

    # Trace datapoints across many trace types + simple numeric summaries
    try:
        payload['chart']['trace_count'] = len(fig.data)
        for tr in fig.data:
            trace_type = getattr(tr, 'type', None)

            fields: dict = {}
            summaries: dict = {}

            for field in _trace_field_candidates(trace_type):
                raw = _get_attr_path(tr, field)
                # z may be 2D (heatmap/contour). Flatten to 1D.
                if field == 'z':
                    values = _flatten(raw, max_points_per_trace)
                else:
                    # tables often store 2D arrays in cells.values
                    if field.endswith('.values') and isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], (list, tuple)):
                        values = _flatten(raw, max_points_per_trace)
                    else:
                        values = _safe_list(raw, max_points_per_trace)
                if values:
                    fields[field] = values
                    num_summary = _numeric_summary(values)
                    if num_summary is not None:
                        summaries[field] = num_summary

            # Also try some common nested fields for extra signal
            for extra in _extra_attr_paths(trace_type):
                raw = _get_attr_path(tr, extra)
                # customdata can be 2D
                if extra in {'customdata'}:
                    values = _flatten(raw, max_points_per_trace)
                else:
                    values = _safe_list(raw, max_points_per_trace)
                if values:
                    fields[extra] = values
                    num_summary = _numeric_summary(values)
                    if num_summary is not None:
                        summaries[extra] = num_summary

            # Fallback: for unfamiliar trace types, introspect trace JSON.
            # This makes insights resilient across Plotly's full trace library.
            if len(fields) < 2:
                auto_fields, auto_summaries = _auto_extract_trace_fields(tr, max_points_per_trace)
                for k, v in auto_fields.items():
                    if k not in fields and v:
                        fields[k] = v
                for k, v in auto_summaries.items():
                    if k not in summaries and v:
                        summaries[k] = v

            trace_obj = {
                'name': getattr(tr, 'name', None),
                'type': trace_type,
                'fields': fields,
                'summaries': summaries,
            }
            payload['chart']['traces'].append(trace_obj)
    except Exception:
        pass

    # Dataset stats
    for name, df in datasets.items():
        try:
            payload['datasets'][str(name)] = {
                'columns': [str(c) for c in df.columns.tolist()[:60]],
                'stats': _dataset_stats(df),
                'sample_rows': df.head(8).to_dict(orient='records'),
            }
        except Exception:
            payload['datasets'][str(name)] = {'error': 'failed_to_summarize'}

    return payload


def generate_chart(code: str, file_paths: Dict[str, str]) -> Tuple[bool, str, Optional[bytes], Optional[str], Optional[str], Optional[dict]]:
    """
    Generate chart from code.
    Returns: (success, message, png_bytes, figure_json, chart_id, insights_payload)
    """
    if not file_paths:
        return False, "No datasets available", None, None, None, None
    
    # Load datasets
    datasets = {}
    for name, path in file_paths.items():
        try:
            datasets[name] = load_dataframe(path)
        except Exception as e:
            return False, f"Error loading '{name}': {e}", None, None, None, None
    
    # Execute code
    success, message, fig = execute_code(code, datasets)
    if not success or fig is None:
        return False, message, None, None, None, None
    
    try:
        png = figure_to_png(fig)
        fig_json = figure_to_json(fig)
        chart_id = f"chart_{int(time.time() * 1000)}"
        insights_payload = build_insights_payload(fig, datasets)
        return True, message, png, fig_json, chart_id, insights_payload
    except Exception as e:
        return False, f"Error generating outputs: {e}", None, None, None, None
