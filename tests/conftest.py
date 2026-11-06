"""Tests run against a fixed QA profile (tests/fixtures/my) and a throwaway data dir, never the owner's my/ and data/."""
import os
import tempfile
from pathlib import Path

os.environ["JOBSEARCH_MY"] = str(Path(__file__).parent / "fixtures" / "my")
os.environ["JOBSEARCH_DATA"] = tempfile.mkdtemp(prefix="jobsearch-test-")
