"""LLM integration - Gemini API"""
import google.generativeai as genai
import json
from typing import List, Dict, Any, Tuple, Optional

from prompts import SYSTEM_PROMPT, INSIGHTS_PROMPT


def generate_code(
    prompt: str,
    datasets: List[Dict[str, Any]],
    history: List[Dict[str, str]],
    api_key: str,
    model: str = "gemini-3-flash-preview"
) -> Tuple[Optional[str], Optional[str]]:
    """Generate visualization code using Gemini."""
    try:
        genai.configure(api_key=api_key)
        llm = genai.GenerativeModel(model_name=model, system_instruction=SYSTEM_PROMPT)
        
        # Build comprehensive prompt with all context
        user_prompt = _build_prompt(prompt, datasets, history)
        
        response = llm.generate_content(user_prompt)
        text = response.text.strip()
        
        # Check for rejection FIRST (before code extraction)
        if text.startswith("REJECT:"):
            return (text, None)  # Return the rejection as "code" to be handled by caller
        
        code = _extract_code(text)
        
        return (code, None) if code else (None, "Could not extract code")
        
    except Exception as e:
        return None, str(e)


def generate_insights(
    insights_payload: Dict[str, Any],
    api_key: str,
    model: str = "gemini-3-flash-preview"
) -> Tuple[Optional[str], Optional[str]]:
    """Generate actionable business insights from chart datapoints + dataset stats."""
    try:
        genai.configure(api_key=api_key)
        llm = genai.GenerativeModel(model_name=model, system_instruction=INSIGHTS_PROMPT)

        # Keep the input deterministic and reasonably compact.
        payload_text = json.dumps(insights_payload, ensure_ascii=False, separators=(',', ':'), default=str)

        user_prompt = (
            "You are given a JSON payload with chart datapoints and dataset statistics. "
            "Generate actionable business insights following your rules.\n\n"
            "PAYLOAD:\n"
            f"{payload_text}"
        )

        response = llm.generate_content(user_prompt)
        text = (response.text or "").strip()
        if not text:
            return None, "Empty insights response"
        return text, None
    except Exception as e:
        return None, str(e)


def _build_prompt(prompt: str, datasets: List[Dict[str, Any]], history: List[Dict[str, str]]) -> str:
    """Build comprehensive prompt with datasets and history."""
    sections = []
    
    # Section 1: Datasets
    sections.append("=" * 50)
    sections.append("AVAILABLE DATASETS")
    sections.append("=" * 50)
    
    if datasets:
        for ds in datasets:
            sections.append(f"\n📊 Dataset: '{ds['name']}'")
            sections.append("-" * 40)
            sections.append(f"  Dimensions: {ds['rows']} rows × {ds['cols']} columns")
            sections.append(f"  Columns: {', '.join(ds['columns'])}")
            sections.append(f"  Data Types:")
            for col, dtype in ds['dtypes'].items():
                sections.append(f"    - {col}: {dtype}")
            sections.append(f"\n  Sample Data (first 3 rows):")
            sections.append(ds['sample_data'])
    else:
        sections.append("No datasets available.")
    
    # Section 2: Conversation History
    sections.append("\n" + "=" * 50)
    sections.append("CONVERSATION HISTORY")
    sections.append("=" * 50)
    
    if history:
        for i, msg in enumerate(history, 1):
            role = "User" if msg['role'] == 'user' else "Assistant"
            content = msg['content'][:500] + "..." if len(msg['content']) > 500 else msg['content']
            sections.append(f"\n[{i}] {role}:")
            sections.append(f"    {content}")
    else:
        sections.append("No previous conversation.")
    
    # Section 3: Current Request
    sections.append("\n" + "=" * 50)
    sections.append("CURRENT REQUEST")
    sections.append("=" * 50)
    sections.append(f"\n{prompt}")
    
    # Final instruction
    sections.append("\n" + "=" * 50)
    sections.append("Generate the Python code now.")
    
    return "\n".join(sections)


def _extract_code(text: str) -> Optional[str]:
    """Extract Python code from LLM response."""
    # Try ```python block
    if "```python" in text:
        start = text.find("```python") + 9
        end = text.find("```", start)
        if end != -1:
            return text[start:end].strip()
    
    # Try generic ``` block
    if "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end != -1:
            code = text[start:end].strip()
            if code.startswith(('python', 'py')):
                code = '\n'.join(code.split('\n')[1:])
            return code.strip()
    
    # Raw code (has fig or px/df usage)
    if 'fig' in text or 'px.' in text:
        return text
    
    return None
