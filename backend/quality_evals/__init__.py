"""Deterministic contract-quality evaluation harness."""

import os

# LiteLLM fetches a mutable remote price map at import time by default. The
# evaluator never calls an LLM and must remain network-independent, so force
# its bundled map before any application route imports `app.llm`.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
