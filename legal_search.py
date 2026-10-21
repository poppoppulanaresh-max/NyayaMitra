"""Act, section, keyword, and category search over indexed chunks."""
from __future__ import annotations

from typing import Any

from database import Database


class LegalSearch:
    def __init__(self, db: Database):
        self.db = db

    def search(
        self,
        query: str = "",
        category: str = "All Categories",
        act_name: str = "",
        section_number: str = "",
        section_title: str = "",
        document_id: str = "",
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        category = category or "All Categories"
        keyword = query
        extra_act = act_name
        extra_section = section_number
        extra_title = section_title

        if category == "Acts" and query and not extra_act:
            extra_act = query
            keyword = ""
        elif category == "Sections" and query and not extra_section:
            extra_section = query
            keyword = ""

        results = self.db.search_chunks(
            act_name=extra_act,
            section_number=extra_section,
            section_title=extra_title,
            keyword=keyword,
            document_id=document_id,
            category=category if category in {"Acts", "Sections", "Keywords"} else "",
        )
        return results

    def acts(self) -> list[str]:
        return self.db.available_acts()
