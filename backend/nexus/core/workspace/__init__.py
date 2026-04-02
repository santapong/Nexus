"""Workspace storage — persistent, versioned, shared file storage for agents.

Three-layer hybrid architecture:
  1. Git bare repos on persistent Docker volume — versioning & file content
  2. PostgreSQL — metadata, embeddings, version history, audit trail
  3. Smart context — LLM-generated summaries embedded via pgvector, auto-loaded
     into agent context based on task similarity
"""

from __future__ import annotations
