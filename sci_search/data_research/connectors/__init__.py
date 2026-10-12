# sci_search/data_research/connectors/__init__.py
"""Statistical API connectors. Network side only; readers are flat sandbox engines."""

import os

CONNECTORS = {}


def enabled():
    return os.environ.get("SCI_SEARCH_DATA_CONNECTORS", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def dataset_from_url(url):
    for name, connector in CONNECTORS.items():
        dataset = connector.dataset_from_url(url)
        if dataset:
            return name, dataset
    return None


def _register():
    from sci_search.data_research.connectors import cbs, eurostat, owid, pxweb

    CONNECTORS.update({eurostat.NAME: eurostat, cbs.NAME: cbs, pxweb.NAME: pxweb, owid.NAME: owid})


_register()
