"""Dataset loading and processing"""
import os
import pandas as pd
from typing import Tuple, Optional

from .session import DatasetInfo

ALLOWED_EXTENSIONS = ['.csv']


def validate_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def load_dataframe(file_path: str) -> pd.DataFrame:
    """Load DataFrame from CSV file"""
    for encoding in ['utf-8', 'latin-1', 'cp1252']:
        try:
            return pd.read_csv(file_path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode CSV file")


def _dtype_name(dtype) -> str:
    """Convert dtype to readable name"""
    s = str(dtype)
    if 'int' in s: return 'integer'
    if 'float' in s: return 'decimal'
    if 'datetime' in s: return 'datetime'
    if 'bool' in s: return 'boolean'
    if 'object' in s: return 'text'
    return s


def process_dataset(file_path: str, filename: str) -> Tuple[Optional[DatasetInfo], Optional[str]]:
    """
    Process uploaded file into DatasetInfo.
    Returns (DatasetInfo, None) or (None, error_message)
    """
    try:
        if not validate_file(filename):
            return None, f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        
        df = load_dataframe(file_path)
        if df.empty:
            return None, "Dataset is empty"
        
        name = os.path.splitext(filename)[0]
        rows, cols = df.shape
        
        info = DatasetInfo(
            name=name,
            file_path=file_path,
            columns=df.columns.tolist(),
            dtypes={c: _dtype_name(df[c].dtype) for c in df.columns},
            sample_data=df.head(3).to_string(index=False),
            row_count=rows,
            col_count=cols
        )
        
        return info, None
        
    except Exception as e:
        return None, str(e)
