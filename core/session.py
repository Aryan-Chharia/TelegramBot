"""Session management - datasets, messages, chart cache"""
import os
import json
from dataclasses import dataclass
from typing import Dict, List, Optional

MAX_MESSAGES = 10
MAX_DATASETS = 5


@dataclass
class DatasetInfo:
    """Dataset metadata"""
    name: str
    file_path: str
    columns: List[str]
    dtypes: Dict[str, str]
    sample_data: str
    row_count: int
    col_count: int


class SessionManager:
    """Single shared session with datasets, messages, and chart cache"""
    
    def __init__(self, storage_dir: str = "uploads"):
        self.datasets: Dict[str, DatasetInfo] = {}
        self.messages: List[dict] = []
        self._charts: Dict[str, str] = {}
        self._insights_payloads: Dict[str, dict] = {}
        self._insights_text: Dict[str, str] = {}
        self._storage_dir = storage_dir
        self._path = os.path.join(storage_dir, 'session.json')
        self._charts_dir = os.path.join(storage_dir, 'charts')
        os.makedirs(storage_dir, exist_ok=True)
        os.makedirs(self._charts_dir, exist_ok=True)
        self._load()
    
    def _load(self):
        """Load session from disk"""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, 'r') as f:
                data = json.load(f)
            for ds in data.get('datasets', []):
                self.datasets[ds['name']] = DatasetInfo(**ds)
            self.messages = data.get('messages', [])
        except Exception as e:
            pass  # Silent fail on load
    
    def _save(self):
        """Save session to disk"""
        try:
            data = {
                'datasets': [
                    {'name': d.name, 'file_path': d.file_path, 'columns': d.columns,
                     'dtypes': d.dtypes, 'sample_data': d.sample_data,
                     'row_count': d.row_count, 'col_count': d.col_count}
                    for d in self.datasets.values()
                ],
                'messages': self.messages[-MAX_MESSAGES:]
            }
            with open(self._path, 'w') as f:
                json.dump(data, f, separators=(',', ':'))
        except:
            pass  # Silent fail on save
    
    # Dataset methods
    def add_dataset(self, info: DatasetInfo) -> Optional[str]:
        """Add dataset, returns removed name if limit exceeded"""
        removed = None
        if len(self.datasets) >= MAX_DATASETS:
            oldest = next(iter(self.datasets))
            old = self.datasets.pop(oldest)
            removed = old.name
            try:
                os.remove(old.file_path)
            except:
                pass
        self.datasets[info.name] = info
        self._save()
        return removed
    
    def get_all_datasets(self) -> Dict[str, DatasetInfo]:
        return self.datasets
    
    def get_dataset_paths(self) -> Dict[str, str]:
        return {n: d.file_path for n, d in self.datasets.items()}
    
    def get_datasets_for_llm(self) -> List[dict]:
        """Get dataset info formatted for LLM"""
        return [
            {'name': d.name, 'rows': d.row_count, 'cols': d.col_count,
             'columns': d.columns, 'dtypes': d.dtypes, 'sample_data': d.sample_data}
            for d in self.datasets.values()
        ]
    
    # Message methods
    def add_message(self, role: str, content: str):
        """Add message, keep last MAX_MESSAGES"""
        self.messages.append({'role': role, 'content': content})
        if len(self.messages) > MAX_MESSAGES:
            self.messages = self.messages[-MAX_MESSAGES:]
        self._save()
    
    def get_history(self) -> List[dict]:
        """Get message history for LLM"""
        return [{'role': 'user' if m['role'] == 'user' else 'assistant', 
                 'content': m['content']} for m in self.messages]
    
    # Chart methods
    def store_chart(self, chart_id: str, json_data: str):
        """Store chart JSON to memory and disk"""
        self._charts[chart_id] = json_data
        # Also persist to disk
        try:
            chart_path = os.path.join(self._charts_dir, f"{chart_id}.json")
            with open(chart_path, 'w') as f:
                f.write(json_data)
        except:
            pass
    
    def get_chart(self, chart_id: str) -> Optional[str]:
        """Get chart JSON from memory or disk"""
        # Try memory first
        if chart_id in self._charts:
            return self._charts[chart_id]
        # Try disk
        try:
            chart_path = os.path.join(self._charts_dir, f"{chart_id}.json")
            if os.path.exists(chart_path):
                with open(chart_path, 'r') as f:
                    json_data = f.read()
                self._charts[chart_id] = json_data  # Cache in memory
                return json_data
        except:
            pass
        return None

    # Insights methods
    def store_insights_payload(self, chart_id: str, payload: dict):
        """Store insights payload to memory and disk for on-demand insights generation."""
        self._insights_payloads[chart_id] = payload
        try:
            payload_path = os.path.join(self._charts_dir, f"{chart_id}_insights_payload.json")
            with open(payload_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, separators=(',', ':'), ensure_ascii=False, default=str)
        except:
            pass

    def get_insights_payload(self, chart_id: str) -> Optional[dict]:
        """Get insights payload from memory or disk."""
        if chart_id in self._insights_payloads:
            return self._insights_payloads[chart_id]
        try:
            payload_path = os.path.join(self._charts_dir, f"{chart_id}_insights_payload.json")
            if os.path.exists(payload_path):
                with open(payload_path, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                self._insights_payloads[chart_id] = payload
                return payload
        except:
            pass
        return None

    def set_insights_text(self, chart_id: str, text: str):
        self._insights_text[chart_id] = text
        try:
            path = os.path.join(self._charts_dir, f"{chart_id}_insights.txt")
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
        except:
            pass

    def get_insights_text(self, chart_id: str) -> Optional[str]:
        if chart_id in self._insights_text:
            return self._insights_text.get(chart_id)
        try:
            path = os.path.join(self._charts_dir, f"{chart_id}_insights.txt")
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    text = f.read()
                if text:
                    self._insights_text[chart_id] = text
                    return text
        except:
            pass
        return None
    
    # Clear
    def clear(self):
        """Clear all data"""
        # Best-effort remove dataset files we know about
        for d in self.datasets.values():
            try:
                os.remove(d.file_path)
            except:
                pass
        self.datasets.clear()
        self.messages.clear()
        self._charts.clear()
        self._insights_payloads.clear()
        self._insights_text.clear()

        # Clear ALL persisted files under uploads/ (handles orphaned CSVs, old payloads, etc.)
        try:
            import shutil
            if os.path.exists(self._storage_dir):
                for name in os.listdir(self._storage_dir):
                    p = os.path.join(self._storage_dir, name)
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p)
                        else:
                            os.remove(p)
                    except:
                        pass
        except:
            pass

        # Recreate required folders
        try:
            os.makedirs(self._storage_dir, exist_ok=True)
            os.makedirs(self._charts_dir, exist_ok=True)
        except:
            pass


# Global instance
session_manager = SessionManager()
