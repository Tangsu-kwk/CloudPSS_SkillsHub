"""Modeling toolbox; scenario methods are migrated separately."""

from .CaseEditToolbox import CaseEditToolbox


class PSAToolbox(CaseEditToolbox):
    """Retain the reference inheritance for callers and later scenario methods."""
