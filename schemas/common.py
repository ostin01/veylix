from math import ceil

from pydantic import BaseModel


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


def build_pagination_meta(total_items: int, page: int, page_size: int) -> PaginationMeta:
    return PaginationMeta(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=ceil(total_items / page_size) if total_items else 0,
    )