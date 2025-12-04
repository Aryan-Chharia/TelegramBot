"""Web server for interactive charts (Flask + ngrok)"""
import os
import threading
import time
import logging
from flask import Flask, Response, abort

# Suppress Flask/Werkzeug logs
logging.getLogger('werkzeug').setLevel(logging.CRITICAL)

app = Flask(__name__)
_public_url = None
_session = None

# Load HTML templates from files
_templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')

with open(os.path.join(_templates_dir, 'chart.html'), 'r', encoding='utf-8') as f:
    CHART_TEMPLATE = f.read()

with open(os.path.join(_templates_dir, 'preview.html'), 'r', encoding='utf-8') as f:
    PREVIEW_TEMPLATE = f.read()


@app.after_request
def headers(response):
    response.headers['ngrok-skip-browser-warning'] = 'true'
    return response


@app.route('/chart/<chart_id>')
def serve_chart(chart_id: str):
    if _session is None:
        abort(500)
    
    fig_json = _session.get_chart(chart_id)
    if fig_json is None:
        abort(404)
    
    html = CHART_TEMPLATE.replace('{{figure_json}}', fig_json)
    return Response(html, mimetype='text/html')


@app.route('/preview/<dataset_name>')
def serve_preview(dataset_name: str):
    """Serve interactive dataset preview"""
    import pandas as pd
    import html as html_escape
    import urllib.parse
    
    # URL decode the dataset name
    dataset_name = urllib.parse.unquote(dataset_name)
    
    if _session is None:
        abort(500)
    
    datasets = _session.get_all_datasets()
    
    # Find dataset (case-insensitive)
    matched_name = None
    for ds_name in datasets.keys():
        if ds_name.lower() == dataset_name.lower():
            matched_name = ds_name
            break
    
    if not matched_name:
        abort(404)
    
    info = datasets[matched_name]
    
    try:
        df = pd.read_csv(info.file_path)
    except:
        abort(500)
    
    preview_count = min(10, len(df))
    preview_df = df.head(preview_count)
    
    # Build table headers
    headers = []
    col_types = {}
    for col in df.columns:
        dtype = str(df[col].dtype)
        if dtype == 'object':
            dtype_label = 'text'
        elif dtype.startswith('int'):
            dtype_label = 'int'
        elif dtype.startswith('float'):
            dtype_label = 'float'
        elif dtype.startswith('datetime'):
            dtype_label = 'date'
        elif dtype == 'bool':
            dtype_label = 'bool'
        else:
            dtype_label = dtype
        col_types[col] = dtype_label
        headers.append(f'<th>{html_escape.escape(str(col))}<span class="dtype">{dtype_label}</span></th>')
    
    # Build table rows
    rows = []
    for _, row in preview_df.iterrows():
        cells = []
        for col in df.columns:
            val = row[col]
            dtype = col_types[col]
            
            if pd.isna(val):
                cells.append('<td class="null">null</td>')
            elif dtype in ('int', 'float'):
                cells.append(f'<td class="number">{html_escape.escape(str(val))}</td>')
            else:
                val_str = str(val)
                if len(val_str) > 100:
                    val_str = val_str[:97] + '...'
                cells.append(f'<td class="text">{html_escape.escape(val_str)}</td>')
        rows.append(f'<tr>{"".join(cells)}</tr>')
    
    # Build column tags
    tags = []
    for col, dtype in col_types.items():
        tags.append(f'<span class="col-tag"><span class="name">{html_escape.escape(str(col))}</span><span class="type">({dtype})</span></span>')
    
    # Build HTML
    html = PREVIEW_TEMPLATE
    html = html.replace('{{dataset_name}}', html_escape.escape(matched_name))
    html = html.replace('{{row_count}}', str(info.row_count))
    html = html.replace('{{col_count}}', str(info.col_count))
    html = html.replace('{{preview_count}}', str(preview_count))
    html = html.replace('{{table_headers}}', ''.join(headers))
    html = html.replace('{{table_rows}}', ''.join(rows))
    html = html.replace('{{column_tags}}', ''.join(tags))
    
    return Response(html, mimetype='text/html')


@app.route('/health')
def health():
    return {"status": "ok", "url": _public_url}


def start_server(session_manager, port: int = 5000, ngrok_token: str = None, railway_url: str = None) -> bool:
    """Start Flask + ngrok/Railway. Returns True if successful."""
    global _public_url, _session
    _session = session_manager
    
    # Start Flask server using werkzeug directly
    from werkzeug.serving import make_server
    import socket
    
    # On Railway, bind to 0.0.0.0 (all interfaces)
    host = '0.0.0.0' if railway_url else '127.0.0.1'
    
    # Check if port is available (only for local)
    if not railway_url:
        def is_port_available(p):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('127.0.0.1', p))
                    return True
                except:
                    return False
        
        if not is_port_available(port):
            print(f"  ✗ Port {port} is in use")
            return False
    
    try:
        server = make_server(host, port, app, threaded=True)
    except Exception as e:
        print(f"  ✗ Flask error: {e}")
        return False
    
    def run():
        server.serve_forever()
    
    server_thread = threading.Thread(target=run, daemon=True)
    server_thread.start()
    
    # Verify Flask is running
    time.sleep(0.5)
    try:
        import urllib.request
        urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2)
        print(f"  ✓ Flask running on port {port}")
    except Exception as e:
        print(f"  ✗ Flask not responding: {e}")
        return False
    
    # If Railway URL is provided, use it directly (no ngrok needed)
    if railway_url:
        _public_url = f"https://{railway_url}"
        print(f"  ✓ Using Railway URL")
        return True
    
    # Otherwise, use ngrok for local development
    try:
        from pyngrok import ngrok, conf
        
        if ngrok_token:
            conf.get_default().auth_token = ngrok_token
        
        try:
            ngrok.kill()
            time.sleep(1)  # Wait for ngrok to fully stop
        except:
            pass
        
        # Connect with bind_tls=True for proper HTTPS
        tunnel = ngrok.connect(str(port), "http", bind_tls=True)
        _public_url = str(tunnel.public_url)
        
        # Ensure HTTPS
        if _public_url.startswith("http://"):
            _public_url = _public_url.replace("http://", "https://")
        
        print(f"  ✓ ngrok tunnel created")
        
    except Exception as e:
        print(f"  ✗ ngrok error: {e}")
        return False
    
    return True


def get_public_url() -> str:
    return _public_url


def get_chart_url(chart_id: str) -> str:
    if _public_url is None:
        return None
    return f"{_public_url}/chart/{chart_id}"


def get_preview_url(dataset_name: str) -> str:
    """Get public URL for dataset preview"""
    if _public_url is None:
        return None
    import urllib.parse
    encoded_name = urllib.parse.quote(dataset_name, safe='')
    return f"{_public_url}/preview/{encoded_name}"
