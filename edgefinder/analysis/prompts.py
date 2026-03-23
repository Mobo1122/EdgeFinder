"""Prompt templates for Claude-powered market analysis."""

SYSTEM_PROMPT = """You are an expert superforecaster and prediction market analyst. Your job is to \
estimate the TRUE probability of events, independent of what the market currently says.

You are calibrated, analytical, and evidence-based. You consider:
- Base rates and reference classes
- Recent news and developments
- Potential biases in market pricing (recency bias, narrative bias, etc.)
- Time remaining until resolution
- Resolution criteria specifics

You always output your analysis as valid JSON."""

ANALYSIS_PROMPT = """Analyze this prediction market and estimate the true probability.

## Market Details
- **Question:** {question}
- **Platform:** {platform}
- **Outcomes:** {outcomes}
- **Current market prices:** {prices}
- **Volume traded:** £{volume:,.0f}
- **Resolution date:** {end_date}
- **Description:** {description}

## Recent Context
{news_context}

## Your Task
1. Consider the base rate for this type of event
2. Factor in all available evidence from the context above
3. Identify any biases that might be affecting the market price
4. Estimate the TRUE probability for each outcome

Respond with ONLY valid JSON in this exact format:
{{
    "probability": <float 0-1 for the first/primary outcome>,
    "confidence": <float 0-1, how confident you are in your estimate>,
    "reasoning": "<2-3 sentence explanation of your reasoning>",
    "key_factors": ["<factor 1>", "<factor 2>", "<factor 3>"],
    "bias_detected": "<any market bias you've identified, or 'none'>"
}}"""

MULTI_OUTCOME_PROMPT = """Analyze this prediction market with multiple outcomes.

## Market Details
- **Question:** {question}
- **Platform:** {platform}
- **Outcomes and current prices:**
{outcome_list}
- **Volume traded:** £{volume:,.0f}
- **Resolution date:** {end_date}
- **Description:** {description}

## Recent Context
{news_context}

## Your Task
Estimate the true probability for EACH outcome. Probabilities must sum to ~1.0.

Respond with ONLY valid JSON in this exact format:
{{
    "probabilities": {{
        "<outcome_name>": <float 0-1>,
        ...
    }},
    "confidence": <float 0-1>,
    "reasoning": "<2-3 sentence explanation>",
    "key_factors": ["<factor 1>", "<factor 2>", "<factor 3>"],
    "biggest_mispricing": "<which outcome is most mispriced and why>"
}}"""
