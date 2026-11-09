"""
Vertex AI provider for the LLM planner: Gemini via the google-genai SDK.

Optional. Install with `pip install -r requirements-llm.txt`. The base repo
never imports this module unless you ask for the vertex planner.

Configuration (environment):
  GOOGLE_CLOUD_PROJECT   your GCP project id (required)
  GOOGLE_CLOUD_LOCATION  Vertex region (default us-central1)
  RFL_VERTEX_MODEL       model id (default gemini-2.5-flash)

Auth: Application Default Credentials (`gcloud auth application-default
login`, or a service account on the runtime). A caller can also pass a
google.auth credentials object explicitly.
"""

from __future__ import annotations

import os

DEFAULT_LOCATION = "us-central1"
DEFAULT_MODEL = "gemini-2.5-flash"


class ProviderConfigError(Exception):
    """The provider is missing a dependency or a setting."""


class VertexGeminiClient:
    """ModelClient backed by Gemini on Vertex AI, with JSON-schema output."""

    def __init__(self, project: str | None = None, location: str | None = None,
                 model: str | None = None, credentials=None):
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise ProviderConfigError(
                "the vertex planner needs google-genai: pip install -r requirements-llm.txt") from e

        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not self.project:
            raise ProviderConfigError("set GOOGLE_CLOUD_PROJECT to your GCP project id")
        self.location = location or os.environ.get("GOOGLE_CLOUD_LOCATION") or DEFAULT_LOCATION
        self.model = model or os.environ.get("RFL_VERTEX_MODEL") or DEFAULT_MODEL
        self.name = f"vertex/{self.model}"
        self._types = types
        self._client = genai.Client(vertexai=True, project=self.project,
                                    location=self.location, credentials=credentials)

    def generate_json(self, system: str, prompt: str, schema: dict) -> str:
        config = self._types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0,
        )
        resp = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
        return resp.text or ""
