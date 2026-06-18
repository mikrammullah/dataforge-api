import json, os, re, anthropic
from typing import Any, Optional
from dataclasses import dataclass, field

client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-6"

@dataclass
class PipelineContext:
    raw_data: Any
    target_schema: Optional[dict]
    output_format: str
    inspection: dict = field(default_factory=dict)
    cleaned: Any = None
    validation: dict = field(default_factory=dict)

async def run_inspector(ctx):
    prompt = f"Analyze this data:\n{json.dumps(ctx.raw_data, default=str)}"
    resp = await client.messages.create(model=MODEL, max_tokens=2000,
        system=(
            'Return ONLY raw JSON: {"detected_type":"...","issues":["short string per issue"],'
            '"field_map":{"field":"canonical_name"},"cleaning_plan":["short string per step"]}. '
            'Keep issues and cleaning_plan as SHORT STRINGS, not nested objects. Be concise — '
            'no before/after examples, no extra metadata. No markdown fences.'
        ),
        messages=[{"role":"user","content":prompt}])
    raw_text = resp.content[0].text
    parsed = _parse_json(raw_text, default=None)
    ctx.inspection = parsed if parsed is not None else {"_debug_raw": raw_text}
async def run_cleaner(ctx):
    prompt = (f"Raw data:\n{json.dumps(ctx.raw_data, default=str)}\n\n"
              f"Cleaning plan:\n{json.dumps(ctx.inspection.get('cleaning_plan',[]))}\n\n"
              f"Output format: {ctx.output_format}")
    resp = await client.messages.create(model=MODEL, max_tokens=1500,
        system="Apply the cleaning plan. Return cleaned data only — no prose, no fences.",
        messages=[{"role":"user","content":prompt}])
    text = resp.content[0].text.strip()
    ctx.cleaned = _parse_json(text, default=text) if ctx.output_format == "json" else text

async def run_validator(ctx):
    prompt = (f"Issues:\n{json.dumps(ctx.inspection.get('issues',[]))}\n\n"
              f"Cleaned:\n{json.dumps(ctx.cleaned, default=str)}")
    resp = await client.messages.create(model=MODEL, max_tokens=600,
        system='Return ONLY raw JSON: {"passed":true,"score":0-100,"issues_resolved":[...],"issues_remaining":[...],"warnings":[...]}',
        messages=[{"role":"user","content":prompt}])
    ctx.validation = _parse_json(resp.content[0].text, default={})

async def run_pipeline(raw_data, target_schema, output_format):
    ctx = PipelineContext(raw_data=raw_data, target_schema=target_schema,
                         output_format=output_format or "json")
    await run_inspector(ctx)
    await run_cleaner(ctx)
    await run_validator(ctx)
    return {"output": ctx.cleaned, "output_format": ctx.output_format,
            "pipeline": {"inspection": ctx.inspection, "validation": ctx.validation}}

def _parse_json(text, default=None):
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fallback: extract the first balanced {...} or [...] block
    match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return default
