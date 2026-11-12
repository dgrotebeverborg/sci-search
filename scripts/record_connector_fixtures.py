# scripts/record_connector_fixtures.py
"""Record real statistical API responses as offline test fixtures. Needs network access."""

import json
import re
from pathlib import Path

from sci_search.data_research.retrieval import fetch_public

ROOT = Path(__file__).resolve().parents[1] / "tests/fixtures/data_research/connectors"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1"
RECORDINGS = {
    "eurostat/demo_mlexpec-structure.xml": EUROSTAT
    + "/dataflow/ESTAT/demo_mlexpec?references=descendants&detail=referencepartial",
    "eurostat/demo_mlexpec-keys.tsv": EUROSTAT
    + "/data/demo_mlexpec/A.YR..Y_LT1./?format=TSV&detail=serieskeysonly&startPeriod=2000",
    "eurostat/demo_mlexpec-slice.tsv.gz": EUROSTAT
    + "/data/demo_mlexpec/A.YR.F+M.Y_LT1.NL+DE+EL/?format=TSV&compressed=true&startPeriod=2000&endPeriod=2024",
    "cbs/82610NED.zip": "https://datasets.cbs.nl/CSV/CBS/nl/82610NED",
    "pxweb/scb-search.json": "https://statistikdatabasen.scb.se/api/v2/tables?query=electricity&lang=en&pageSize=10",
    "pxweb/scb-TAB4311-metadata.json": "https://statistikdatabasen.scb.se/api/v2/tables/TAB4311/metadata?lang=en&outputFormat=json-stat2",
    "pxweb/scb-TAB4311-data.json": "https://statistikdatabasen.scb.se/api/v2/tables/TAB4311/data?lang=en&outputFormat=json-stat2",
    "pxweb/ssb-search.json": "https://data.ssb.no/api/v0/en/table/?query=electricity",
    "owid/search.json": "https://ourworldindata.org/api/search?q=life%20expectancy",
    "owid/life-expectancy.csv": "https://ourworldindata.org/grapher/life-expectancy.csv?v=1&csvType=full&useColumnShortNames=true",
    "owid/life-expectancy.metadata.json": "https://ourworldindata.org/grapher/life-expectancy.metadata.json?v=1",
}


def trim_dataflows(xml):
    flows = re.findall(r"<s:Dataflow .*?</s:Dataflow>", xml, re.S)
    keep = flows[:200] + [f for f in flows if 'id="DEMO_MLEXPEC"' in f or 'id="NRG_IND_REN"' in f]
    start = xml.index("<s:Dataflows>") + len("<s:Dataflows>")
    end = xml.index("</s:Dataflows>")
    return xml[:start] + "".join(dict.fromkeys(keep)) + xml[end:]


def main():
    for name, url in RECORDINGS.items():
        body, _, _ = fetch_public(url)
        target = ROOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        print(name, len(body))
    flows, _, _ = fetch_public(EUROSTAT + "/dataflow/ESTAT/all?detail=allstubs")
    (ROOT / "eurostat/dataflows.xml").write_text(trim_dataflows(flows.decode()))
    catalogue, _, _ = fetch_public(
        "https://opendata.cbs.nl/ODataCatalog/Tables?$format=json&$select=Identifier,Title,Frequency,Language,Period,ShortDescription"
    )
    tables = json.loads(catalogue)["value"]
    keep = tables[:200] + [t for t in tables if t["Identifier"] in {"82610NED", "85929NED"}]
    (ROOT / "cbs/catalogue.json").write_text(
        json.dumps({"value": list({t["Identifier"]: t for t in keep}.values())}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
