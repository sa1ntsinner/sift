"""Record real Steam store responses for the regional test-suite.

    python tests/record_fixtures.py

Apps: RDR2 (not family-shareable, blocked in RU/BY), Mafia II DE (hidden in Gulf states),
RE4, Portal 2, Witcher 3, Elden Ring, a DLC (Long Dark: Tales), Cyberpunk 2077.
"""
import json
from pathlib import Path

import requests

APPS = [1174180, 1030830, 2050650, 620, 292030, 1245620, 2148100, 1091500]
REGIONS = ["US", "TR", "KZ", "RU", "BR", "IN", "SA", "DE", "JP", "VN", "AZ", "AR"]
OUT = Path(__file__).parent / "fixtures"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    for cc in REGIONS:
        payload = {
            "ids": [{"appid": a} for a in APPS],
            "context": {"language": "english", "country_code": cc, "steam_realm": 1},
            "data_request": {"include_basic_info": True, "include_tag_count": 20, "include_reviews": True,
                             "include_release": True, "include_related_items": True, "include_platforms": True,
                             "include_supported_languages": True, "include_assets": True},
        }
        r = s.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1",
                  params={"input_json": json.dumps(payload)}, timeout=20)
        r.raise_for_status()
        (OUT / f"getitems_{cc}.json").write_text(json.dumps(r.json(), ensure_ascii=False, indent=1), encoding="utf-8")
        print("recorded", cc)
    tags = s.get("https://store.steampowered.com/tagdata/populartags/english", timeout=20).json()
    (OUT / "tags_english.json").write_text(json.dumps(tags, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
